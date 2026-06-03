# TunnelFox

A simple secret browser for Windows.  
Everything you do online goes through **your own server** so nobody else can see it.  
It looks like a normal Notepad program.

[![Build & Release](https://github.com/shanewas/tunnelfox/actions/workflows/build-release.yml/badge.svg)](https://github.com/shanewas/tunnelfox/actions/workflows/build-release.yml)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Python](https://img.shields.io/badge/python-3.11--3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Try It Right Now (Takes 2 Minutes)

### What you need
- Windows 10 or 11
- A server you control (cheap VPS from DigitalOcean, Hetzner, Oracle free tier, etc.)
- An SSH key file for that server **with no password**

### Steps
1. Go to the **Releases** page on GitHub and download the latest zip file.
2. Unzip it anywhere.
3. Open the folder and edit the file called `config.ini` using Notepad:
   - `vm_ip` → put your server's IP address or name (example: 123.45.67.89)
   - `key_path` → put the full path to your SSH key file (example: `C:\Users\You\Downloads\mykey.pem`)
   - `vm_user` → your username on the server (usually `ubuntu` or `root`)
4. Save the file.
5. Double-click `start_fox.bat`
   - A small black window appears (this is the secret tunnel)
   - A normal-looking browser opens
6. Browse anything you want. All traffic goes through your server.

**Finished?** Double-click `kill_fox.bat` to close everything and clean up.

**Something wrong?** Double-click `tunnel-diagnose.bat` — it will tell you exactly what to fix.

That's all. No installation. No extra programs needed after the first run.

---

## What This Actually Does (Super Simple)

- Hides your real location and what sites you visit.
- Nothing is saved on your computer (no history, no cookies, no cache).
- The program is named `NotepadHelper.exe` so work computers and security tools usually ignore it.
- Uses a real encrypted SSH tunnel.

---

## Daily Use

- `start_fox.bat` → start the secret browser
- `kill_fox.bat` → shut everything down cleanly
- Inside the browser you get normal tabs, bookmarks, downloads, etc.
- Press `Ctrl+I` anytime to check "Is the tunnel actually working right now?"

---

## If You Want to Change the Starting Page

Edit `config.ini` and change the `home_url` line.  
Or just use the Settings button (☰) inside the browser.

---

## Building It Yourself (Only If You Want To)

1. Install Python 3.11, 3.12 or 3.13 and add it to PATH.
2. Run these two commands in the folder:
   ```
   pip install -r requirements.txt
   BUILD.bat
   ```
3. The finished program appears in the `dist\NotepadHelper` folder.

**Important:** Never move the .exe out of that folder or it will break.

---

## Common Problems

- "Tunnel not detected" → Run `tunnel-diagnose.bat`
- Key has a password → Remove the password from your SSH key (or load it in Pageant)
- Nothing happens when you double-click the .bat files → Make sure you edited `config.ini` correctly

---

## License

MIT. See the LICENSE file.

Just edit `config.ini` with your own server details and run `start_fox.bat`. Done.