# TunnelFox

> Hardened, session-isolated desktop browser that routes all traffic through an SSH SOCKS5 tunnel.

[![Build & Release](https://github.com/shanewas/tunnelfox/actions/workflows/build-release.yml/badge.svg)](https://github.com/shanewas/tunnelfox/actions/workflows/build-release.yml)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Python](https://img.shields.io/badge/python-3.11--3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Overview

TunnelFox is a Windows desktop application that wraps Chromium (via PyQt6 WebEngine) in a controlled, memory-only session profile. All outbound network traffic is enforced through a SOCKS5 dynamic port forward established over SSH to a remote jump host — no persistent cookies, no disk cache, no DNS leaks.

The browser binary is intentionally named `NotepadHelper.exe` for compatibility with EDR and enterprise policy environments.

---

## How It Works

```
[Windows Host]
    │
    ├── start_fox.bat
    │     ├── ssh -D 1080 ──────────────────► [Oracle VM / Jump Host]
    │     │                                        (encrypted tunnel)
    │     └── NotepadHelper.exe
    │           └── QWebEngineView (Chromium 120)
    │                 └── QTWEBENGINE_CHROMIUM_FLAGS
    │                       └── --proxy-server=socks5://127.0.0.1:1080
    │                             └── All traffic exits via jump host
    │
    └── kill_fox.bat
          └── Terminates browser + tunnel, flushes DNS cache
```

**Security properties:**
- Memory-only HTTP cache — no data written to disk between sessions
- No persistent cookies — session is fully isolated and discarded on close
- Proxy enforced via `QTWEBENGINE_CHROMIUM_FLAGS` before `QApplication()` instantiation — the only method that reliably routes `QtWebEngineProcess.exe` renderer traffic through the tunnel (`QNetworkProxy` does not affect the renderer subprocess)
- WebRTC restricted to public interfaces only, preventing local IP leakage
- Browser binary disguised as `NotepadHelper.exe` for EDR and policy compatibility
- Chromium sandbox disabled via `QTWEBENGINE_DISABLE_SANDBOX=1` for enterprise AV compatibility

---

## Repository Structure

```
tunnelfox/
├── .github/
│   └── workflows/
│       └── build-release.yml   # CI/CD — auto build + GitHub Release on tag push
├── src/
│   └── tunnelfox.py            # Application source (PyQt6)
├── BUILD.bat                   # Local build script (PyInstaller)
├── start_fox.bat               # Launch: SSH tunnel → browser
├── kill_fox.bat                # Teardown: browser → tunnel → DNS flush
├── config.ini                  # Runtime configuration (URL, port, app name)
├── requirements.txt            # Python dependencies
└── .gitignore
```

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Windows 10 / 11 (64-bit) | Required |
| Python 3.11 – 3.13 | Must be added to PATH |
| OpenSSH client | Bundled with Windows 10+ |
| SSH private key | Ed25519 or RSA — **no passphrase** |
| Remote jump host | Any SSH server supporting dynamic port forwarding |

---

## Configuration

All runtime settings are controlled via `config.ini`:

```ini
[CONNECTION]
vm_ip=YOUR_SERVER_IP          ; Jump host IP or hostname
key_path=C:\path\to\key.pem   ; Absolute path to private key (no passphrase)
vm_user=ubuntu                ; SSH username on the jump host

[BROWSER]
app_name=NotepadHelper        ; Process and window name (disguise)
home_url=https://claude.ai    ; Default home page
local_port=1080               ; Local SOCKS5 proxy port
```

> **Security:** Never commit `key.pem` or any private key file. Both are excluded by `.gitignore` via `*.pem` and `*.key` patterns.

The target URL and other browser settings can also be changed at runtime via the in-app **Settings** dialog (☰) without requiring a rebuild.

---

## Local Build

```bat
pip install -r requirements.txt
BUILD.bat
```

Output: `.\dist\NotepadHelper\NotepadHelper.exe`

> **Important:** The entire `dist\NotepadHelper\` folder must be kept intact. `QtWebEngineProcess.exe` and all Qt DLLs resolve paths relative to the executable's directory. Moving `NotepadHelper.exe` out of the folder will cause it to fail at launch.

---

## Automated Build (CI/CD)

The included GitHub Actions workflow (`.github/workflows/build-release.yml`) automatically:

1. Builds the executable on `windows-latest` using PyInstaller
2. Packages the output with `start_fox.bat`, `kill_fox.bat`, and `config.ini`
3. Uploads a build artifact on every push to `master`
4. Creates a versioned GitHub Release when a `v*.*.*` tag is pushed

To cut a release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The release archive will be published as `TunnelFox-v1.0.0-windows.zip`.

---

## Usage

| Script | Action |
|--------|--------|
| `start_fox.bat` | Starts the SSH tunnel on port 1080, then launches the browser |
| `kill_fox.bat` | Kills browser and tunnel processes, flushes Windows DNS cache |
| `BUILD.bat` | Compiles `src/tunnelfox.py` into `dist/NotepadHelper/` via PyInstaller |

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+L` | Focus address bar |
| `Ctrl+F` | Find in page |
| `Ctrl+D` | Bookmark current page |
| `Ctrl+Shift+B` | Show bookmarks |
| `Ctrl+Shift+H` | Show history |
| `Ctrl++ / Ctrl+-` | Zoom in / out |
| `Ctrl+0` | Reset zoom |
| `Ctrl+P` | Save page as PDF |
| `F5 / Ctrl+R` | Reload |
| `F11` | Toggle fullscreen |
| `F12` | Developer tools |
| `Alt+← / Alt+→` | Navigate back / forward |
| `Ctrl+Shift+Del` | Clear session data |

---

## Deploying to Another Machine

No Python installation is required on target machines. Copy the following:

```
dist/NotepadHelper/     ← entire folder (do not flatten)
start_fox.bat
kill_fox.bat
config.ini              ← update key_path for the new machine
key.pem                 ← copy SSH key securely, never commit
```

Update `key_path` in `config.ini` to match the key location on the target machine. All other settings remain the same.

---

## Known Constraints

**No sandbox**
`QTWEBENGINE_DISABLE_SANDBOX=1` is set globally for enterprise AV compatibility. Do not use TunnelFox to browse untrusted or arbitrary web content.

**SSH key must have no passphrase**
A passphrase causes `ssh.exe` to block on a terminal prompt that `start_fox.bat` cannot supply. Generate keys without a passphrase or strip the passphrase before use.

**Google OAuth blocked in embedded browsers**
Google detects and blocks OAuth flows initiated from embedded Chromium instances. Use email magic link login (available on claude.ai and other services) as an alternative.

**Tunnel must be active before launch**
TunnelFox checks for an active SOCKS5 listener on startup and will exit with an error if the tunnel is not running. Always use `start_fox.bat` rather than launching the executable directly.

**Folder structure must remain intact**
Moving `NotepadHelper.exe` out of its distribution folder will break the Qt runtime. The entire `dist\NotepadHelper\` directory must be distributed together.

---

## License

MIT — see [LICENSE](LICENSE) for details.