import sys
import os
import socket
import configparser
from pathlib import Path
from urllib.parse import quote_plus

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QToolBar, QAction, QMessageBox, QProgressBar, QStatusBar, QLabel
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl, QSize

# ============================================================
#  TunnelFox v0.4  —  Address bar + navigation toolbar
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

config = configparser.ConfigParser()
config.read(CONFIG_PATH)

TARGET_URL    = config.get("BROWSER", "home_url",      fallback="https://google.com")
APP_DISGUISE  = config.get("BROWSER", "app_name",      fallback="NotepadHelper")
PROXY_HOST    = "127.0.0.1"
PROXY_PORT    = config.getint("BROWSER", "local_port", fallback=1080)
SEARCH_ENGINE = config.get("BROWSER", "search_engine", fallback="duckduckgo")

SEARCH_ENGINES = {
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "google":     "https://www.google.com/search?q={}",
}


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


def normalise_url(text: str) -> str:
    text = text.strip()
    if not text:
        return TARGET_URL
    if text.startswith(("http://", "https://")):
        return text
    if "." in text and " " not in text:
        return "https://" + text
    engine = SEARCH_ENGINES.get(SEARCH_ENGINE, SEARCH_ENGINES["duckduckgo"])
    return engine.format(quote_plus(text))


class TunnelFoxBrowser(QMainWindow):

    def __init__(self):
        super().__init__()

        if not is_tunnel_active():
            QMessageBox.critical(None, "Tunnel Not Detected",
                f"Could not reach SOCKS5 proxy on {PROXY_HOST}:{PROXY_PORT}.")
            sys.exit(1)

        self.setWindowTitle(APP_DISGUISE)
        self.resize(1280, 900)

        nav = QToolBar("Navigation")
        nav.setMovable(False)
        self.addToolBar(nav)

        self.btn_back    = QAction("◀", self)
        self.btn_forward = QAction("▶", self)
        self.btn_reload  = QAction("↻", self)
        self.btn_home    = QAction("⌂", self)

        self.btn_back.triggered.connect(lambda: self.view.back())
        self.btn_forward.triggered.connect(lambda: self.view.forward())
        self.btn_reload.triggered.connect(lambda: self.view.reload())
        self.btn_home.triggered.connect(self._go_home)

        nav.addAction(self.btn_back)
        nav.addAction(self.btn_forward)
        nav.addAction(self.btn_reload)
        nav.addAction(self.btn_home)

        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText("Enter URL or search…")
        self.address_bar.returnPressed.connect(self._navigate_from_bar)
        nav.addWidget(self.address_bar)

        self.progress = QProgressBar()
        self.progress.setMaximumHeight(3)
        self.progress.setTextVisible(False)
        self.progress.hide()

        self.view = QWebEngineView()
        self.view.urlChanged.connect(lambda u: self.address_bar.setText(u.toString()))
        self.view.loadStarted.connect(lambda: self.progress.show())
        self.view.loadFinished.connect(lambda: self.progress.hide())
        self.view.loadProgress.connect(self.progress.setValue)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.progress)
        layout.addWidget(self.view)

        self.view.load(QUrl(TARGET_URL))

    def _navigate_from_bar(self):
        self.view.load(QUrl(normalise_url(self.address_bar.text())))

    def _go_home(self):
        self.view.load(QUrl(TARGET_URL))


if __name__ == "__main__":
    configure_proxy_early()
    app = QApplication(sys.argv)
    window = TunnelFoxBrowser()
    window.show()
    sys.exit(app.exec_())
