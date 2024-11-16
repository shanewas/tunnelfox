import sys
import os
import socket
import configparser
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QMessageBox
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl

# ============================================================
#  TunnelFox v0.3  —  SSH tunnel + SOCKS5 proxy
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

config = configparser.ConfigParser()
config.read(CONFIG_PATH)

TARGET_URL   = config.get("BROWSER", "home_url",  fallback="https://google.com")
APP_DISGUISE = config.get("BROWSER", "app_name",  fallback="NotepadHelper")
PROXY_HOST   = "127.0.0.1"
PROXY_PORT   = config.getint("BROWSER", "local_port", fallback=1080)


def configure_proxy_early():
    sys.argv += [
        f"--proxy-server=socks5://{PROXY_HOST}:{PROXY_PORT}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def is_tunnel_active():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            return s.connect_ex((PROXY_HOST, PROXY_PORT)) == 0
    except OSError:
        return False


class TunnelFoxBrowser(QMainWindow):

    def __init__(self):
        super().__init__()

        if not is_tunnel_active():
            QMessageBox.critical(
                None, "Tunnel Not Detected",
                f"Could not reach SOCKS5 proxy on {PROXY_HOST}:{PROXY_PORT}.\n"
                "Please run start_fox.bat and try again."
            )
            sys.exit(1)

        self.setWindowTitle(APP_DISGUISE)
        self.resize(1280, 900)

        self.view = QWebEngineView()
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.view.load(QUrl(TARGET_URL))


if __name__ == "__main__":
    configure_proxy_early()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISGUISE)
    window = TunnelFoxBrowser()
    window.show()
    sys.exit(app.exec_())
