import sys
import os
import json
import socket
import configparser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QToolBar, QMessageBox,
    QProgressBar, QStatusBar, QLabel, QFileDialog,
    QListWidget, QListWidgetItem, QDialogButtonBox
)
from PyQt6.QtGui import QAction, QShortcut, QKeySequence
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PyQt6.QtCore import QUrl, QSize, QTimer, Qt

# ============================================================
#  TunnelFox v0.8  —  Migrated to PyQt6 (Chrome 120 engine)
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

config = configparser.ConfigParser()
config.read(CONFIG_PATH)

TARGET_URL    = config.get("BROWSER", "home_url",      fallback="https://claude.ai")
APP_DISGUISE  = config.get("BROWSER", "app_name",      fallback="NotepadHelper")
PROXY_HOST    = "127.0.0.1"
PROXY_PORT    = config.getint("BROWSER", "local_port", fallback=1080)
SEARCH_ENGINE = config.get("BROWSER", "search_engine", fallback="duckduckgo")

BOOKMARKS_PATH = Path.home() / ".tunnelfox" / "bookmarks.json"
BOOKMARKS_PATH.parent.mkdir(parents=True, exist_ok=True)

SEARCH_ENGINES = {
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "google":     "https://www.google.com/search?q={}",
    "bing":       "https://www.bing.com/search?q={}",
    "brave":      "https://search.brave.com/search?q={}",
}


def configure_proxy_early():
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        f"--proxy-server=socks5://{PROXY_HOST}:{PROXY_PORT} "
        "--no-first-run --no-default-browser-check "
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )


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
        self._tunnel_warned = False

        nav = QToolBar("Navigation")
        nav.setMovable(False)
        self.addToolBar(nav)

        self.btn_back     = QAction("◀", self)
        self.btn_forward  = QAction("▶", self)
        self.btn_reload   = QAction("↻", self)
        self.btn_home     = QAction("⌂", self)
        self.btn_stop     = QAction("✕", self)
        self.btn_bookmark = QAction("☆", self)
        self.btn_mute     = QAction("🔊", self)

        self.btn_back.triggered.connect(lambda: self.view.back())
        self.btn_forward.triggered.connect(lambda: self.view.forward())
        self.btn_reload.triggered.connect(lambda: self.view.reload())
        self.btn_home.triggered.connect(self._go_home)
        self.btn_stop.triggered.connect(lambda: self.view.stop())
        self.btn_bookmark.triggered.connect(self._toggle_bookmark)
        self.btn_mute.triggered.connect(self._toggle_mute)

        for btn in [self.btn_back, self.btn_forward, self.btn_reload,
                    self.btn_stop, self.btn_home, self.btn_bookmark]:
            nav.addAction(btn)

        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText("Enter URL or search…")
        self.address_bar.returnPressed.connect(self._navigate_from_bar)
        nav.addWidget(self.address_bar)

        self.zoom_label = QLabel("100%")
        nav.addWidget(self.zoom_label)
        nav.addAction(self.btn_mute)

        self.progress = QProgressBar()
        self.progress.setMaximumHeight(3)
        self.progress.setTextVisible(False)
        self.progress.hide()

        self.find_bar = QWidget()
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(8, 4, 8, 4)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find in page…")
        self.find_input.setFixedWidth(220)
        self.find_input.textChanged.connect(lambda t: self._find_text(True))
        btn_next  = QPushButton("▼")
        btn_prev  = QPushButton("▲")
        btn_close = QPushButton("✕")
        btn_next.clicked.connect(lambda: self._find_text(True))
        btn_prev.clicked.connect(lambda: self._find_text(False))
        btn_close.clicked.connect(self._hide_find_bar)
        find_layout.addWidget(QLabel("Find:"))
        find_layout.addWidget(self.find_input)
        find_layout.addWidget(btn_next)
        find_layout.addWidget(btn_prev)
        find_layout.addStretch()
        find_layout.addWidget(btn_close)
        self.find_bar.hide()

        self.profile = QWebEngineProfile("TunnelFoxSession", self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.page = QWebEnginePage(self.profile)
        self.view = QWebEngineView()
        self.view.setPage(self.page)
        self.view.urlChanged.connect(self._on_url_changed)
        self.view.loadStarted.connect(lambda: self.progress.show())
        self.view.loadFinished.connect(lambda ok: self.progress.hide())
        self.view.loadProgress.connect(self.progress.setValue)
        self.profile.downloadRequested.connect(self._on_download_requested)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.tunnel_indicator = QLabel("● Tunnel")
        self.tunnel_indicator.setStyleSheet("color:green;")
        self.status.addPermanentWidget(self.tunnel_indicator)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.progress)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.view)

        self._tunnel_timer = QTimer(self)
        self._tunnel_timer.timeout.connect(self._check_tunnel_health)
        self._tunnel_timer.start(15000)

        QShortcut(QKeySequence("Ctrl+F"), self, self._show_find_bar)
        QShortcut(QKeySequence("Ctrl++"), self, self._zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, self._zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, self._zoom_reset)
        QShortcut(QKeySequence("F5"),     self, self.view.reload)
        QShortcut(QKeySequence("Escape"), self, self._on_escape)

        self.view.load(QUrl(TARGET_URL))

    def _on_url_changed(self, qurl):
        url = qurl.toString()
        self.address_bar.setText(url)
        bookmarks = self._load_bookmarks()
        self.btn_bookmark.setText("★" if any(b["url"] == url for b in bookmarks) else "☆")

    def _navigate_from_bar(self):
        self.view.load(QUrl(normalise_url(self.address_bar.text())))

    def _go_home(self):
        self.view.load(QUrl(TARGET_URL))

    def _on_escape(self):
        if self.find_bar.isVisible():
            self._hide_find_bar()
        else:
            self.view.stop()

    def _show_find_bar(self):
        self.find_bar.show()
        self.find_input.setFocus()

    def _hide_find_bar(self):
        self.find_bar.hide()
        self.page.findText("")
        self.view.setFocus()

    def _find_text(self, forward=True):
        text = self.find_input.text()
        if forward:
            self.page.findText(text)
        else:
            self.page.findText(text, QWebEnginePage.FindFlag.FindBackward)

    def _zoom_in(self):
        f = min(5.0, self.view.zoomFactor() + 0.1)
        self.view.setZoomFactor(f)
        self.zoom_label.setText(f"{int(f*100)}%")

    def _zoom_out(self):
        f = max(0.25, self.view.zoomFactor() - 0.1)
        self.view.setZoomFactor(f)
        self.zoom_label.setText(f"{int(f*100)}%")

    def _zoom_reset(self):
        self.view.setZoomFactor(1.0)
        self.zoom_label.setText("100%")

    def _toggle_mute(self):
        muted = self.page.isAudioMuted()
        self.page.setAudioMuted(not muted)
        self.btn_mute.setText("🔊" if muted else "🔇")

    def _load_bookmarks(self):
        try:
            return json.loads(BOOKMARKS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_bookmarks(self, bookmarks):
        BOOKMARKS_PATH.write_text(
            json.dumps(bookmarks, indent=2, ensure_ascii=False), encoding="utf-8")

    def _toggle_bookmark(self):
        url = self.view.url().toString()
        if not url or url.startswith("about:"):
            return
        bookmarks = self._load_bookmarks()
        if any(b["url"] == url for b in bookmarks):
            bookmarks = [b for b in bookmarks if b["url"] != url]
            self.btn_bookmark.setText("☆")
        else:
            bookmarks.append({"url": url, "title": self.view.title() or url,
                               "added": datetime.now().isoformat()})
            self.btn_bookmark.setText("★")
        self._save_bookmarks(bookmarks)

    def _on_download_requested(self, item):
        path, _ = QFileDialog.getSaveFileName(self, "Save", item.suggestedFileName())
        if path:
            item.setDownloadDirectory(os.path.dirname(path))
            item.setDownloadFileName(os.path.basename(path))
            item.accept()

    def _check_tunnel_health(self):
        if is_tunnel_active():
            self.tunnel_indicator.setText("● Tunnel")
            self.tunnel_indicator.setStyleSheet("color:green;")
            self._tunnel_warned = False
        else:
            self.tunnel_indicator.setText("● Tunnel ✗")
            self.tunnel_indicator.setStyleSheet("color:red;")
            if not self._tunnel_warned:
                self._tunnel_warned = True
                QMessageBox.warning(self, "Tunnel Disconnected",
                    "The SOCKS5 tunnel is down.")


if __name__ == "__main__":
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    configure_proxy_early()
    app = QApplication(sys.argv)
    window = TunnelFoxBrowser()
    window.show()
    sys.exit(app.exec())
