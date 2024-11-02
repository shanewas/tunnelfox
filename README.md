# TunnelFox

> Hardened, session-isolated browser wrapper that routes all traffic through a local SOCKS5 SSH tunnel.

[![Build & Release](https://github.com/shanewas/tunnelfox/actions/workflows/build-release.yml/badge.svg)](https://github.com/shanewas/tunnelfox/actions/workflows/build-release.yml)

---

## Architecture Overview

TunnelFox is a single-tier Windows desktop application. It wraps Chromium (via PyQtWebEngine) in a controlled session profile and enforces all outbound network traffic through a SOCKS5 dynamic port forward established over SSH to a remote jump host.

```
[Windows Host]
    |
    +-- start_fox.bat
    |     +-- ssh -D 1080 --> [Oracle VM / Jump Host]  <-- encrypted tunnel
    |     +-- NotepadHelper.exe
    |           +-- QWebEngineView (Chromium)
    |                 +-- --proxy-server=socks5://127.0.0.1:1080
    |                       +-- claude.ai
    |
    +-- kill_fox.bat --> terminates ssh.exe + NotepadHelper.exe, flushes DNS
```

**Key properties:**
- No persistent cookies or disk cache (memory-only profile)
- Proxy injected as Chromium `--proxy-server` argv flag before `QApplication()` — the only method that actually routes WebEngine renderer traffic through the tunnel (`QNetworkProxy` does not affect `QtWebEngineProcess.exe`)
- Browser binary disguised as `NotepadHelper.exe` for EDR/policy compatibility
- Chromium sandbox disabled for enterprise AV compatibility (`QTWEBENGINE_DISABLE_SANDBOX=1`)

---

## Repository Structure

```
tunnelfox/
+-- .github/
|   +-- workflows/
|       +-- build.yml        # CI/CD -- auto build + GitHub Release on tag
+-- src/
|   +-- tunnelfox.py         # Application source
+-- assets/
|   +-- file_version_info.txt # Windows PE version metadata
+-- BUILD.bat                # Local build (PyInstaller)
+-- start_fox.bat            # Launch: tunnel -> browser
+-- kill_fox.bat             # Teardown: browser -> tunnel -> DNS flush
+-- requirements.txt         # Python dependencies
+-- .gitignore
+-- README.md
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Windows | 10 / 11 (64-bit) |
| Python | 3.10 - 3.11 |
| OpenSSH client | bundled with Windows 10+ |
| SSH key | Ed25519 or RSA, no passphrase |
| Oracle VM / jump host | Any SOCKS5-capable SSH server |

---

## Configuration

Edit the variables at the top of `start_fox.bat` before first use:

```bat
set "VM_USER=ubuntu"                        :: SSH username on the jump host
set "VM_IP=YOUR_VM_IP"                    :: Jump host IP or hostname
set "KEY_PATH=C:\path\to\your.key"       :: Path to private key (no passphrase)
```

> **Security:** Never commit the private key. It is excluded by `.gitignore`.

---

## Local Build

```bat
pip install -r requirements.txt
BUILD.bat
```

Output: `.\dist\NotepadHelper\NotepadHelper.exe`

> The entire `dist\NotepadHelper\` folder must be kept intact. Do not move the `.exe` out of it -- Qt DLLs and `QtWebEngineProcess.exe` are resolved by relative path.

---

## Usage

| Script | Action |
|---|---|
| `start_fox.bat` | Starts SSH tunnel on port 1080, then launches the browser |
| `kill_fox.bat` | Kills browser and tunnel, flushes Windows DNS cache |
| `BUILD.bat` | Compiles `src/tunnelfox.py` into `dist/NotepadHelper/` |

---

## Known Constraints

- **Single target URL.** `TARGET_URL` in `src/tunnelfox.py` is hardcoded to `https://claude.ai`. Change and rebuild to redirect.
- **No sandbox.** `QTWEBENGINE_DISABLE_SANDBOX=1` is set globally. Do not browse untrusted content.
- **SSH key must have no passphrase.** A passphrase causes `ssh.exe` to block waiting for terminal input, which `start_fox.bat` cannot supply.

---

## License

MIT






























