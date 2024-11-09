import sys
import os
import configparser
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl

# ============================================================
#  TunnelFox v0.2  —  Basic browser window
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

config = configparser.ConfigParser()
config.read(CONFIG_PATH)

TARGET_URL   = config.get("BROWSER", "home_url",  fallback="https://google.com")
APP_DISGUISE = config.get("BROWSER", "app_name",  fallback="NotepadHelper")
PROXY_HOST   = "127.0.0.1"
PROXY_PORT   = config.getint("BROWSER", "local_port", fallback=1080)


class TunnelFoxBrowser(QMainWindow):

    def __init__(self):
        super().__init__()
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
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISGUISE)
    window = TunnelFoxBrowser()
    window.show()
    sys.exit(app.exec_())
