# TunnelFox

TunnelFox is a Windows desktop application that provides a hardened, session-isolated web browser. All network traffic is routed through an SSH SOCKS5 tunnel to a remote jump host, ensuring no persistent local data and preventing local network observation of browsing activity. The executable is named NotepadHelper.exe to maintain compatibility with enterprise endpoint detection and response (EDR) systems and policy restrictions.

[![Build & Release](https://github.com/shanewas/tunnelfox/actions/workflows/build-release.yml/badge.svg)](https://github.com/shanewas/tunnelfox/actions/workflows/build-release.yml)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Python](https://img.shields.io/badge/python-3.11--3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Getting Started

### Prerequisites

- A computer running Windows 10 or Windows 11 (64-bit).
- A remote server (such as a virtual private server) that supports SSH access and dynamic port forwarding.
- An SSH private key file corresponding to an account on the remote server. The key must not be protected by a passphrase.
- (Optional) Python 3.11 or later, if building from source.

### Quick Evaluation

To set up and test TunnelFox quickly:

1. Navigate to the [Releases](https://github.com/shanewas/tunnelfox/releases) page of this repository and download the most recent Windows archive (for example, `TunnelFox-....-windows.zip`).

2. Extract the archive to a convenient location on your computer.

3. Open the extracted folder and edit the file `config.ini` using a text editor such as Notepad. Update the following values under the `[CONNECTION]` section with details for your remote server:
   - `vm_ip`: The IP address or hostname of your remote server.
   - `key_path`: The full local path to your SSH private key file (for example, `C:\Users\YourName\Downloads\mykey.pem`).
   - `vm_user`: The username for the SSH account on the remote server (commonly `ubuntu` or `root`).

   Save the file after making these changes. Do not commit your private key or modified configuration containing sensitive paths.

4. Double-click the file `start_fox.bat` to launch the application.
   - A command window will appear briefly while the SSH tunnel is established.
   - The TunnelFox browser window will then open. All traffic from this browser instance is directed through the configured tunnel.

5. Use the browser as needed. Features such as tabbed browsing, bookmarks, and a command palette (`Ctrl+Shift+P`) are available.

6. When finished, double-click `kill_fox.bat` to terminate the browser, close the tunnel, and flush the local DNS cache.

If the application does not start as expected, double-click `tunnel-diagnose.bat`. This script performs checks on SSH availability, the private key file, SOCKS5 proxy connectivity, and egress IP address, and provides guidance on common configuration issues.

No additional software is required on the target machine beyond the contents of the archive and a properly configured `config.ini`.

## Configuration

Runtime behavior is controlled by the `config.ini` file located in the application directory. The `[CONNECTION]` section specifies the remote server and authentication details. The `[BROWSER]` section controls application appearance and default behavior, such as the initial home page.

Changes to browser settings (for example, the home URL) may also be made at runtime through the in-application Settings menu without rebuilding the executable.

**Important:** Private key files must never be included in version control. The repository `.gitignore` excludes common key file extensions.

## Building from Source

If a pre-built release is not suitable, TunnelFox may be built from source on a Windows system with Python 3.11 or later installed and added to the system PATH:

1. Clone the repository or download the source archive.
2. Open a command prompt in the repository root directory.
3. Execute the following commands:

   ```
   pip install -r requirements.txt
   BUILD.bat
   ```

The resulting executable and supporting files will be located in the `dist\NotepadHelper` directory. The entire contents of this directory must be kept together; relocating the primary executable will prevent the application from starting.

## Additional Information

### Daily Operation

- `start_fox.bat`: Establishes the SSH tunnel and launches the browser.
- `kill_fox.bat`: Terminates the browser and tunnel processes and clears the local DNS cache.
- `tunnel-diagnose.bat`: Assists with troubleshooting SSH connectivity, key configuration, and tunnel functionality.

The in-application interface provides standard browser controls along with TunnelFox-specific features, including a live tunnel status indicator and egress IP verification.

### Limitations

- The Chromium sandbox is disabled (`QTWEBENGINE_DISABLE_SANDBOX=1`) to support compatibility with certain enterprise security software. TunnelFox is not intended for browsing untrusted content.
- SSH keys used with the application must not require a passphrase, as interactive prompts cannot be handled by the launcher scripts.
- Certain authentication flows (for example, Google OAuth) may be restricted within embedded browser environments. Alternative login methods, such as email magic links, are recommended where applicable.

### Deployment to Additional Systems

The pre-built archive requires no Python installation on the destination machine. Copy the full `dist\NotepadHelper` directory along with `start_fox.bat`, `kill_fox.bat`, `tunnel-diagnose.bat`, and a `config.ini` file configured for the target environment. Update the `key_path` value in `config.ini` to reflect the location of the SSH key on the new system.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
