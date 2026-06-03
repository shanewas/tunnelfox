#!/usr/bin/env python3
"""
TunnelFox Tunnel Diagnostics
============================

Run this script (or double-click tunnel-diagnose.bat) to troubleshoot
why start_fox.bat is failing or the browser thinks the tunnel is down.

It performs:
- Config validation
- ssh.exe presence check
- Private key file checks
- Real SOCKS5 protocol test (handshake + CONNECT)
- Egress IP verification through the tunnel (if proxy is working)
- Actionable suggestions

No external dependencies beyond Python 3.8+ (stdlib only).
"""

import os
import sys
import socket
import subprocess
import configparser
from pathlib import Path
from urllib.parse import urlparse

# --------------------------- Config Loading ---------------------------

def load_connection_config(config_path: Path | None = None) -> dict:
    """Parse the same [CONNECTION] + [BROWSER] keys used by the launchers."""
    if config_path is None:
        # Try to find config.ini next to this script or in current dir
        candidates = [
            Path(__file__).parent / "config.ini",
            Path.cwd() / "config.ini",
        ]
        for c in candidates:
            if c.exists():
                config_path = c
                break
        else:
            return {"error": "config.ini not found"}

    if not config_path.exists():
        return {"error": f"config.ini not found at {config_path}"}

    cfg = configparser.ConfigParser()
    try:
        cfg.read(config_path, encoding="utf-8")
    except Exception as e:
        return {"error": f"Failed to read config.ini: {e}"}

    data = {
        "config_path": str(config_path),
        "vm_ip": cfg.get("CONNECTION", "vm_ip", fallback="").strip(),
        "key_path": cfg.get("CONNECTION", "key_path", fallback="").strip(),
        "vm_user": cfg.get("CONNECTION", "vm_user", fallback="").strip(),
        "local_port": cfg.getint("BROWSER", "local_port", fallback=1080),
        "app_name": cfg.get("BROWSER", "app_name", fallback="NotepadHelper"),
    }
    return data


# --------------------------- SOCKS5 Test (standalone copy) ---------------------------

def _test_socks5_proxy(host: str, port: int, timeout: float = 3.5) -> tuple[bool, str]:
    """Return (success, reason). Performs full SOCKS5 greeting + CONNECT test."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            # Greeting
            sock.sendall(b"\x05\x01\x00")
            greeting = sock.recv(2)
            if len(greeting) != 2 or greeting[0] != 0x05 or greeting[1] != 0x00:
                return False, f"Bad SOCKS5 greeting reply: {greeting!r}"

            # CONNECT to 1.1.1.1:53 (reliable public IP, TCP DNS port)
            test_ip = "1.1.1.1"
            test_port = 53
            addr = socket.inet_aton(test_ip)
            req = b"\x05\x01\x00\x01" + addr + test_port.to_bytes(2, "big")
            sock.sendall(req)

            reply = sock.recv(10)
            if len(reply) < 2 or reply[0] != 0x05 or reply[1] != 0x00:
                rep = reply[1] if len(reply) > 1 else -1
                return False, f"SOCKS5 CONNECT failed (REP=0x{rep:02x})"

            return True, "SOCKS5 handshake + CONNECT successful"

    except socket.timeout:
        return False, "Connection timed out (tunnel slow or dead)"
    except ConnectionRefusedError:
        return False, "Connection refused (nothing listening on the port)"
    except OSError as e:
        return False, f"Network error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"


# --------------------------- Egress IP Test ---------------------------

def get_egress_ip_via_socks(socks_host: str, socks_port: int, timeout: float = 6.0) -> tuple[str | None, str]:
    """
    Attempt to fetch our public IP through the SOCKS5 proxy using a minimal
    HTTP/1.0 request over a manually proxied connection.
    Returns (ip_or_None, message).
    """
    target_host = "ifconfig.me"
    target_port = 80

    try:
        with socket.create_connection((socks_host, socks_port), timeout=timeout) as sock:
            # SOCKS5 greeting
            sock.sendall(b"\x05\x01\x00")
            if sock.recv(2) != b"\x05\x00":
                return None, "SOCKS5 greeting failed during IP test"

            # CONNECT
            addr = socket.inet_aton(socket.gethostbyname(target_host))  # resolve locally
            req = b"\x05\x01\x00\x01" + addr + target_port.to_bytes(2, "big")
            sock.sendall(req)
            if sock.recv(10)[1] != 0x00:
                return None, "SOCKS5 CONNECT to ifconfig.me failed"

            # Now send a plain HTTP request
            http_req = (
                f"GET / HTTP/1.0\r\n"
                f"Host: {target_host}\r\n"
                f"User-Agent: TunnelFox-Diagnostics/1.0\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("ascii")
            sock.sendall(http_req)

            # Read response
            sock.settimeout(timeout)
            chunks = []
            while True:
                try:
                    data = sock.recv(4096)
                    if not data:
                        break
                    chunks.append(data)
                except socket.timeout:
                    break

            body = b"".join(chunks).decode("utf-8", errors="replace")
            # Very crude parse: ifconfig.me returns just the IP as body for this request
            lines = [l.strip() for l in body.splitlines() if l.strip()]
            # Look for a plausible IP in the last lines
            for line in reversed(lines[-5:]):
                if any(c.isdigit() for c in line) and "." in line and len(line) < 50:
                    # Basic sanity
                    if line.replace(".", "").isdigit():
                        return line, "Egress IP retrieved successfully through tunnel"

            return None, f"Got response but could not parse IP. Raw tail:\n{body[-300:]}"

    except Exception as e:
        return None, f"Failed to fetch egress IP: {e}"


# --------------------------- Main Diagnostics ---------------------------

def main():
    print("TunnelFox Diagnostics")
    print("=" * 50)
    print()

    config = load_connection_config()
    if "error" in config:
        print(f"[FAIL] {config['error']}")
        print("\nMake sure config.ini exists next to this script or in the current directory.")
        input("\nPress Enter to exit...")
        sys.exit(1)

    print(f"[OK]   Loaded config from: {config['config_path']}")
    print(f"       Jump host : {config['vm_user']}@{config['vm_ip']}")
    print(f"       Local port: {config['local_port']}")
    print(f"       Key path  : {config['key_path']}")
    print()

    # 1. ssh.exe availability
    ssh_path = None
    try:
        result = subprocess.run(
            ["where", "ssh.exe"],
            capture_output=True,
            text=True,
            shell=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            ssh_path = result.stdout.strip().splitlines()[0]
            print(f"[OK]   ssh.exe found: {ssh_path}")
        else:
            print("[FAIL] ssh.exe not found in PATH")
            print("       Windows 10+ should include OpenSSH. Enable it in Optional Features.")
    except Exception as e:
        print(f"[WARN] Could not check for ssh.exe: {e}")

    print()

    # 2. Key file checks
    key_path = Path(config["key_path"])
    if not key_path.exists():
        print(f"[FAIL] Private key not found: {key_path}")
        print("       Update key_path in config.ini")
    else:
        print(f"[OK]   Private key exists: {key_path}")
        try:
            size = key_path.stat().st_size
            print(f"       Size: {size} bytes")
            # Very rough check for PEM header
            with key_path.open("rb") as f:
                head = f.read(100)
            if b"BEGIN" in head and (b"PRIVATE KEY" in head or b"OPENSSH PRIVATE KEY" in head):
                print("       Looks like a valid private key file (PEM/OpenSSH format)")
            else:
                print("[WARN] Key file does not look like a standard private key")
        except Exception as e:
            print(f"[WARN] Could not inspect key file: {e}")

    print()

    # 3. SOCKS5 proxy test (the important one)
    port = config["local_port"]
    print(f"--- Testing SOCKS5 proxy on 127.0.0.1:{port} ---")
    ok, reason = _test_socks5_proxy("127.0.0.1", port)
    if ok:
        print(f"[OK]   {reason}")
    else:
        print(f"[FAIL] {reason}")
        print()
        print("Suggestions:")
        print("  • Run start_fox.bat (or start_tunnel.bat) first")
        print("  • Check that the remote VM is reachable and the SSH key has no passphrase")
        print("  • Increase local_port in config if something else is using 1080")
        print("  • Run with verbose: start_tunnel.bat (it uses ssh -v)")
        print()

    # 4. Egress IP test (only if proxy test passed)
    if ok:
        print("--- Verifying traffic is actually exiting through the tunnel ---")
        ip, msg = get_egress_ip_via_socks("127.0.0.1", port)
        if ip:
            print(f"[OK]   Your public IP appears to be: {ip}")
            print("       (This IP should be the one of your jump host / Oracle VM, not your local machine)")
        else:
            print(f"[FAIL] {msg}")
            print("       The proxy accepted connections but could not fetch an IP.")
            print("       This can happen with very restrictive firewalls on the jump host.")

    print()
    print("=" * 50)
    print("Diagnostics finished.")
    print()
    print("If everything above is green but the browser still complains,")
    print("try killing any old ssh.exe / NotepadHelper.exe processes and run start_fox.bat again.")
    print()

    input("Press Enter to exit...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nUnexpected error during diagnostics: {e}")
        input("Press Enter to exit...")
        sys.exit(1)
