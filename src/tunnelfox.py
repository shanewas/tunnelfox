import sys
import os
import json
import socket
import shutil
import tempfile
import configparser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QToolBar, QMessageBox,
    QProgressBar, QStatusBar, QLabel, QFileDialog,
    QDialog, QFormLayout, QComboBox, QSpinBox, QDialogButtonBox
)
from PyQt6.QtGui import QAction, QShortcut, QKeySequence, QColor, QPalette
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PyQt6.QtCore import QUrl, QSize, QTimer, Qt

# ============================================================
#  TunnelFox v0.9  —  Dark theme + settings dialog
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
TEMP_DIR      = tempfile.mkdtemp(prefix="tfox_")

BOOKMARKS_PATH = Path.home() / ".tunnelfox" / "bookmarks.json"
BOOKMARKS_PATH.parent.mkdir(parents=True, exist_ok=True)

SEARCH_ENGINES = {
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "google":     "https://www.google.com/search?q={}",
    "bing":       "https://www.bing.com/search?q={}",
    "brave":      "https://search.brave.com/search?q={}",
}

ERROR_PAGE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{margin:0;background:#0f0f1e;color:#e0e0e0;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;}}
.box{{text-align:center;max-width:500px;padding:40px;}}
h1{{color:#cc4444;}}p{{color:#909090;}}</style></head>
<body><div class="box"><div style="font-size:60px">⚠️</div>
<h1>Page Failed to Load</h1><p>Check your tunnel connection.</p>
<p style="color:#606090;font-size:12px">{url}</p>
<button onclick="window.location.reload()" style="background:#2a2a4a;color:#e0e0e0;
border:none;border-radius:6px;padding:8px 20px;cursor:pointer">Retry</button>
</div></body></html>"""


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
        self._apply_dark_palette()

        nav = QToolBar("Navigation")
        nav.setMovable(False)
        nav.setStyleSheet("""
            QToolBar { background:#1a1a2e; border-bottom:1px solid #2a2a4a; padding:4px 6px; }
            QToolButton { background:transparent; color:#c0c0d0; border:none;
                          border-radius:4px; font-size:15px; padding:3px 7px; }
            QToolButton:hover { background:#2a2a4a; }
        """)
        self.addToolBar(nav)

        self.btn_back     = QAction("◀", self)
        self.btn_forward  = QAction("▶", self)
        self.btn_reload   = QAction("↻", self)
        self.btn_home     = QAction("⌂", self)
        self.btn_stop     = QAction("✕", self)
        self.btn_bookmark = QAction("☆", self)
        self.btn_mute     = QAction("🔊", self)
        self.btn_settings = QAction("☰", self)

        self.btn_back.triggered.connect(lambda: self.view.back())
        self.btn_forward.triggered.connect(lambda: self.view.forward())
        self.btn_reload.triggered.connect(lambda: self.view.reload())
        self.btn_home.triggered.connect(self._go_home)
        self.btn_stop.triggered.connect(lambda: self.view.stop())
        self.btn_bookmark.triggered.connect(self._toggle_bookmark)
        self.btn_mute.triggered.connect(self._toggle_mute)
        self.btn_settings.triggered.connect(self._show_settings)

        for btn in [self.btn_back, self.btn_forward, self.btn_reload,
                    self.btn_stop, self.btn_home, self.btn_bookmark]:
            nav.addAction(btn)

        self.lock_label = QLabel("🔒")
        self.lock_label.setStyleSheet("color:#00cc44; font-size:13px; padding:0 4px;")
        nav.addWidget(self.lock_label)

        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText("Enter URL or search…")
        self.address_bar.returnPressed.connect(self._navigate_from_bar)
        self.address_bar.setStyleSheet("""
            QLineEdit { background:#0f0f1e; color:#e0e0e0;
                        border:1px solid #3a3a5e; border-radius:5px; padding:4px 10px; }
            QLineEdit:focus { border-color:#7070c0; }
        """)
        nav.addWidget(self.address_bar)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet("color:#808090; font-size:11px; padding:0 6px;")
        nav.addWidget(self.zoom_label)
        nav.addAction(self.btn_mute)
        nav.addAction(self.btn_settings)

        self.progress = QProgressBar()
        self.progress.setMaximumHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar{background:#0f0f1e;border:none;}"
            "QProgressBar::chunk{background:#7070f0;}")
        self.progress.hide()

        self.find_bar = QWidget()
        self.find_bar.setStyleSheet("background:#1a1a2e; border-top:1px solid #2a2a4a;")
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(8, 4, 8, 4)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find in page…")
        self.find_input.setFixedWidth(220)
        self.find_input.textChanged.connect(lambda t: self._find_text(True))
        btn_next  = QPushButton("▼ Next")
        btn_prev  = QPushButton("▲ Prev")
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
        self.view.titleChanged.connect(
            lambda t: self.setWindowTitle(f"{t}  —  {APP_DISGUISE}" if t else APP_DISGUISE))
        self.view.loadStarted.connect(lambda: (self.progress.show(), self.progress.setValue(0)))
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.loadProgress.connect(self.progress.setValue)
        self.profile.downloadRequested.connect(self._on_download_requested)

        self.status = QStatusBar()
        self.status.setStyleSheet("background:#1a1a2e; color:#808090; font-size:11px;")
        self.setStatusBar(self.status)
        self.tunnel_indicator = QLabel("● Tunnel")
        self.tunnel_indicator.setStyleSheet("color:#00cc44; font-size:11px; padding:0 8px;")
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
        QShortcut(QKeySequence("Alt+Left"),  self, self.view.back)
        QShortcut(QKeySequence("Alt+Right"), self, self.view.forward)

        self.view.load(QUrl(TARGET_URL))

    def _apply_dark_palette(self):
        p = QPalette()
        p.setColor(QPalette.ColorRole.Window,        QColor("#0f0f1e"))
        p.setColor(QPalette.ColorRole.WindowText,    QColor("#e0e0e0"))
        p.setColor(QPalette.ColorRole.Base,          QColor("#0f0f1e"))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor("#1a1a2e"))
        p.setColor(QPalette.ColorRole.Text,          QColor("#e0e0e0"))
        p.setColor(QPalette.ColorRole.Button,        QColor("#1a1a2e"))
        p.setColor(QPalette.ColorRole.ButtonText,    QColor("#e0e0e0"))
        self.setPalette(p)

    def _on_url_changed(self, qurl):
        url = qurl.toString()
        self.address_bar.setText(url)
        scheme = qurl.scheme()
        if scheme == "https":
            self.lock_label.setText("🔒")
            self.lock_label.setStyleSheet("color:#00cc44; font-size:13px; padding:0 4px;")
        elif scheme == "http":
            self.lock_label.setText("⚠")
            self.lock_label.setStyleSheet("color:#cc4444; font-size:13px; padding:0 4px;")
        bookmarks = self._load_bookmarks()
        self.btn_bookmark.setText("★" if any(b["url"] == url for b in bookmarks) else "☆")

    def _on_load_finished(self, ok):
        self.progress.hide()
        if not ok:
            self.view.setHtml(ERROR_PAGE_HTML.format(url=self.view.url().toString()))

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
            self.status.showMessage("Bookmark removed.", 2000)
        else:
            bookmarks.append({"url": url, "title": self.view.title() or url,
                               "added": datetime.now().isoformat()})
            self.btn_bookmark.setText("★")
            self.status.showMessage("Bookmark saved.", 2000)
        self._save_bookmarks(bookmarks)

    def _on_download_requested(self, item):
        path, _ = QFileDialog.getSaveFileName(self, "Save", item.suggestedFileName())
        if path:
            item.setDownloadDirectory(os.path.dirname(path))
            item.setDownloadFileName(os.path.basename(path))
            item.accept()

    def _show_settings(self):
        global TARGET_URL, APP_DISGUISE, SEARCH_ENGINE
        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setFixedWidth(420)
        dlg.setStyleSheet("QDialog{background:#0f0f1e;color:#e0e0e0;}"
                          "QLabel{color:#c0c0d0;}"
                          "QLineEdit,QSpinBox,QComboBox{background:#1a1a2e;color:#e0e0e0;"
                          "border:1px solid #3a3a5e;border-radius:4px;padding:4px 8px;}")
        form = QFormLayout(dlg)
        form.setContentsMargins(16, 16, 16, 16)
        url_edit    = QLineEdit(TARGET_URL)
        name_edit   = QLineEdit(APP_DISGUISE)
        port_spin   = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(PROXY_PORT)
        eng_combo   = QComboBox()
        eng_combo.addItems(["duckduckgo", "google", "bing", "brave"])
        eng_combo.setCurrentText(SEARCH_ENGINE)
        form.addRow("Home URL:", url_edit)
        form.addRow("App Name:", name_edit)
        form.addRow("Local Port:", port_spin)
        form.addRow("Search Engine:", eng_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            TARGET_URL    = url_edit.text().strip() or TARGET_URL
            APP_DISGUISE  = name_edit.text().strip() or APP_DISGUISE
            SEARCH_ENGINE = eng_combo.currentText()
            config["BROWSER"]["home_url"]      = TARGET_URL
            config["BROWSER"]["app_name"]      = APP_DISGUISE
            config["BROWSER"]["local_port"]    = str(port_spin.value())
            config["BROWSER"]["search_engine"] = SEARCH_ENGINE
            with open(CONFIG_PATH, "w") as f:
                config.write(f)
            self.status.showMessage("Settings saved.", 4000)

    def _check_tunnel_health(self):
        if is_tunnel_active():
            self.tunnel_indicator.setText("● Tunnel")
            self.tunnel_indicator.setStyleSheet("color:#00cc44; font-size:11px; padding:0 8px;")
            self._tunnel_warned = False
        else:
            self.tunnel_indicator.setText("● Tunnel ✗")
            self.tunnel_indicator.setStyleSheet("color:#cc2200; font-size:11px; padding:0 8px;")
            if not self._tunnel_warned:
                self._tunnel_warned = True
                QMessageBox.warning(self, "Tunnel Disconnected",
                    "The SOCKS5 tunnel is down. Restart the tunnel.")

    def closeEvent(self, event):
        try:
            if os.path.exists(TEMP_DIR):
                shutil.rmtree(TEMP_DIR, ignore_errors=True)
        except Exception:
            pass
        event.accept()


if __name__ == "__main__":
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    configure_proxy_early()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISGUISE)
    window = TunnelFoxBrowser()
    window.show()
    sys.exit(app.exec())
