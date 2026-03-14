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
    QLineEdit, QPushButton, QMessageBox, QToolBar, QProgressBar,
    QStatusBar, QLabel, QDialog, QFormLayout, QComboBox,
    QSpinBox, QListWidget, QListWidgetItem, QDialogButtonBox, QFileDialog,
    QSizePolicy
)
from PyQt6.QtGui import QColor, QPalette, QIcon, QKeySequence, QAction, QShortcut
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEngineProfile, QWebEnginePage, QWebEngineSettings
)
from PyQt6.QtCore import QUrl, Qt, QSize, QTimer
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog

# ============================================================
#  TunnelFox v3.0  —  Load config.ini
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

config = configparser.ConfigParser()
config.read(CONFIG_PATH)

TARGET_URL    = config.get("BROWSER", "home_url",       fallback="https://claude.ai")
APP_DISGUISE  = config.get("BROWSER", "app_name",       fallback="NotepadHelper")
PROXY_HOST    = "127.0.0.1"
PROXY_PORT    = config.getint("BROWSER", "local_port",  fallback=1080)
SEARCH_ENGINE = config.get("BROWSER", "search_engine",  fallback="duckduckgo")
TEMP_DIR      = tempfile.mkdtemp(prefix="tfox_")

BOOKMARKS_PATH = Path.home() / ".tunnelfox" / "bookmarks.json"
BOOKMARKS_PATH.parent.mkdir(parents=True, exist_ok=True)

SEARCH_ENGINES = {
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "google":     "https://www.google.com/search?q={}",
    "bing":       "https://www.bing.com/search?q={}",
    "brave":      "https://search.brave.com/search?q={}",
}

ERROR_PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ margin:0; background:#0f0f1e; color:#e0e0e0;
          font-family:system-ui,sans-serif; display:flex;
          align-items:center; justify-content:center; height:100vh; }}
  .box {{ text-align:center; max-width:500px; padding:40px; }}
  .icon {{ font-size:60px; margin-bottom:16px; }}
  h1 {{ font-size:22px; color:#cc4444; margin:0 0 10px; }}
  p  {{ color:#909090; font-size:14px; margin:0 0 24px; }}
  .url {{ color:#606090; font-size:12px; word-break:break-all; margin-bottom:28px; }}
  button {{ background:#2a2a4a; color:#e0e0e0; border:1px solid #3a3a5e;
            border-radius:6px; padding:8px 20px; font-size:13px;
            cursor:pointer; margin:0 6px; }}
  button:hover {{ background:#3a3a5e; }}
</style>
</head>
<body>
<div class="box">
  <div class="icon">⚠️</div>
  <h1>Page Failed to Load</h1>
  <p>TunnelFox could not reach this address. Check your tunnel connection or try again.</p>
  <div class="url">{url}</div>
  <button onclick="window.location.reload()">Retry</button>
  <button onclick="window.location.href='{home}'">Go Home</button>
</div>
</body>
</html>"""


def configure_proxy_early():
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        f"--proxy-server=socks5://{PROXY_HOST}:{PROXY_PORT} "
        "--no-first-run "
        "--no-default-browser-check "
        f"--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
    if text.startswith(("http://", "https://", "file://")):
        return text
    if "." in text and " " not in text:
        return "https://" + text
    engine = SEARCH_ENGINES.get(SEARCH_ENGINE, SEARCH_ENGINES["duckduckgo"])
    return engine.format(quote_plus(text))


class CustomWebEnginePage(QWebEnginePage):

    def createWindow(self, _type):
        return self

    def javaScriptConsoleMessage(self, level, message, line, source):
        pass

    def certificateError(self, error):
        url = error.url().toString()
        reply = QMessageBox.warning(
            None,
            "Certificate Error",
            f"The certificate for <b>{url}</b> is not trusted.\n\n"
            f"{error.description()}\n\nProceed anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            error.acceptCertificate()
            return True
        error.rejectCertificate()
        return False


class TunnelFoxBrowser(QMainWindow):

    def __init__(self):
        super().__init__()

        if not is_tunnel_active():
            QMessageBox.critical(
                None, "Tunnel Not Detected",
                f"TunnelFox could not reach the local SOCKS5 proxy "
                f"on {PROXY_HOST}:{PROXY_PORT}.\n\n"
                "Please run start_fox.bat and try again."
            )
            sys.exit(1)

        self.setWindowTitle(APP_DISGUISE)
        self.resize(1280, 900)
        self._apply_dark_palette()

        self._devtools_dialog = None
        self._tunnel_warned = False

        # ── Session-scoped profile ──────────────────────────────────────
        self.profile = QWebEngineProfile("TunnelFoxSession", self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )
        s = self.profile.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled,        True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled,          True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,   True)
        s.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled,           False)
        s.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,      True)
        s.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,   True)
        s.setAttribute(QWebEngineSettings.WebAttribute.WebRTCPublicInterfacesOnly, True)

        # ── Web view ────────────────────────────────────────────────────
        self.view = QWebEngineView()
        self.page = CustomWebEnginePage(self.profile, self.view)
        self.view.setPage(self.page)

        # ── Navigation bar ──────────────────────────────────────────────
        nav = QToolBar("Navigation")
        nav.setMovable(False)
        nav.setIconSize(QSize(18, 18))
        nav.setStyleSheet("""
            QToolBar        { background:#1a1a2e; border-bottom:1px solid #2a2a4a; padding:4px 6px; spacing:4px; }
            QToolButton     { background:transparent; color:#c0c0d0; border:none; border-radius:4px;
                              font-size:15px; padding:3px 7px; }
            QToolButton:hover  { background:#2a2a4a; }
            QToolButton:pressed{ background:#3a3a5e; }
            QToolButton:disabled{ color:#505060; }
        """)
        self.addToolBar(nav)

        self.btn_back     = QAction("◀", self)
        self.btn_forward  = QAction("▶", self)
        self.btn_reload   = QAction("↻", self)
        self.btn_home     = QAction("⌂", self)
        self.btn_stop     = QAction("✕", self)
        self.btn_bookmark = QAction("☆", self)
        self.btn_mute     = QAction("🔊", self)
        self.btn_devtools = QAction("⚙", self)
        self.btn_settings = QAction("☰", self)

        self.btn_back.setToolTip("Back  (Alt+←)")
        self.btn_forward.setToolTip("Forward  (Alt+→)")
        self.btn_reload.setToolTip("Reload  (F5)")
        self.btn_home.setToolTip("Home")
        self.btn_stop.setToolTip("Stop loading")
        self.btn_bookmark.setToolTip("Bookmark this page  (Ctrl+D)")
        self.btn_mute.setToolTip("Mute / Unmute")
        self.btn_devtools.setToolTip("Developer Tools  (F12)")
        self.btn_settings.setToolTip("Settings")

        self.btn_back.triggered.connect(self.view.back)
        self.btn_forward.triggered.connect(self.view.forward)
        self.btn_reload.triggered.connect(self.view.reload)
        self.btn_home.triggered.connect(self._go_home)
        self.btn_stop.triggered.connect(self.view.stop)
        self.btn_bookmark.triggered.connect(self._toggle_bookmark)
        self.btn_mute.triggered.connect(self._toggle_mute)
        self.btn_devtools.triggered.connect(self._toggle_devtools)
        self.btn_settings.triggered.connect(self._show_settings)

        nav.addAction(self.btn_back)
        nav.addAction(self.btn_forward)
        nav.addAction(self.btn_reload)
        nav.addAction(self.btn_stop)
        nav.addAction(self.btn_home)
        nav.addAction(self.btn_bookmark)

        self.lock_label = QLabel("🔒")
        self.lock_label.setStyleSheet("color:#00cc44; font-size:13px; padding:0 4px;")
        self.lock_label.setToolTip("Connection security")
        nav.addWidget(self.lock_label)

        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText("Enter URL or search…")
        self.address_bar.returnPressed.connect(self._navigate_from_bar)
        self.address_bar.setStyleSheet("""
            QLineEdit {
                background:#0f0f1e; color:#e0e0e0;
                border:1px solid #3a3a5e; border-radius:5px;
                padding:4px 10px; font-size:13px;
            }
            QLineEdit:focus { border-color:#7070c0; }
        """)
        nav.addWidget(self.address_bar)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet("color:#808090; font-size:11px; padding:0 6px;")
        self.zoom_label.setToolTip("Zoom level")
        nav.addWidget(self.zoom_label)

        nav.addAction(self.btn_mute)
        nav.addAction(self.btn_devtools)
        nav.addAction(self.btn_settings)

        # ── Progress bar ────────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar           { background:#0f0f1e; border:none; }
            QProgressBar::chunk    { background:#7070f0; }
        """)
        self.progress.hide()

        # ── Find-in-page bar ────────────────────────────────────────────
        self.find_bar = QWidget()
        self.find_bar.setStyleSheet("background:#1a1a2e; border-top:1px solid #2a2a4a;")
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(8, 4, 8, 4)
        find_layout.setSpacing(4)

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find in page…")
        self.find_input.setFixedWidth(220)
        self.find_input.setStyleSheet("""
            QLineEdit {
                background:#0f0f1e; color:#e0e0e0;
                border:1px solid #3a3a5e; border-radius:4px;
                padding:3px 8px; font-size:12px;
            }
        """)
        self.find_input.textChanged.connect(lambda t: self._find_text(forward=True))
        self.find_input.returnPressed.connect(lambda: self._find_text(forward=True))

        btn_style = ("QPushButton { background:#2a2a4a; color:#c0c0d0; border:none; "
                     "border-radius:4px; padding:3px 10px; font-size:12px; } "
                     "QPushButton:hover { background:#3a3a5e; }")
        btn_find_next = QPushButton("▼ Next")
        btn_find_next.setStyleSheet(btn_style)
        btn_find_next.clicked.connect(lambda: self._find_text(forward=True))

        btn_find_prev = QPushButton("▲ Prev")
        btn_find_prev.setStyleSheet(btn_style)
        btn_find_prev.clicked.connect(lambda: self._find_text(forward=False))

        btn_find_close = QPushButton("✕")
        btn_find_close.setStyleSheet(btn_style)
        btn_find_close.clicked.connect(self._hide_find_bar)

        find_layout.addWidget(QLabel("Find:"))
        find_layout.addWidget(self.find_input)
        find_layout.addWidget(btn_find_next)
        find_layout.addWidget(btn_find_prev)
        find_layout.addStretch()
        find_layout.addWidget(btn_find_close)
        self.find_bar.hide()

        # ── Status bar ──────────────────────────────────────────────────
        self.status = QStatusBar()
        self.status.setStyleSheet("background:#1a1a2e; color:#808090; font-size:11px;")
        self.setStatusBar(self.status)

        self.tunnel_indicator = QLabel("● Tunnel")
        self.tunnel_indicator.setStyleSheet("color:#00cc44; font-size:11px; padding:0 8px;")
        self.status.addPermanentWidget(self.tunnel_indicator)

        # ── Central layout ──────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.progress)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.view)

        # ── Signals ─────────────────────────────────────────────────────
        self.view.urlChanged.connect(self._on_url_changed)
        self.view.titleChanged.connect(self._on_title_changed)
        self.view.loadStarted.connect(self._on_load_started)
        self.view.loadProgress.connect(self._on_load_progress)
        self.view.loadFinished.connect(self._on_load_finished)
        self.page.linkHovered.connect(lambda url: self.status.showMessage(url, 2000))
        self.page.fullScreenRequested.connect(self._on_fullscreen_requested)
        self.page.recentlyAudibleChanged.connect(self._on_audible_changed)
        self.profile.downloadRequested.connect(self._on_download_requested)

        # ── Tunnel health timer ──────────────────────────────────────────
        self._tunnel_timer = QTimer(self)
        self._tunnel_timer.timeout.connect(self._check_tunnel_health)
        self._tunnel_timer.start(15_000)

        # ── Keyboard shortcuts ───────────────────────────────────────────
        QShortcut(QKeySequence("F5"),                self, self.view.reload)
        QShortcut(QKeySequence("Ctrl+R"),            self, self.view.reload)
        QShortcut(QKeySequence("Ctrl+L"),            self, self._focus_address_bar)
        QShortcut(QKeySequence("Alt+Left"),          self, self.view.back)
        QShortcut(QKeySequence("Alt+Right"),         self, self.view.forward)
        QShortcut(QKeySequence("Escape"),            self, self._on_escape)
        QShortcut(QKeySequence("Ctrl+H"),            self, self._go_home)
        QShortcut(QKeySequence("F11"),               self, self._toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+F"),            self, self._show_find_bar)
        QShortcut(QKeySequence("Ctrl++"),            self, self._zoom_in)
        QShortcut(QKeySequence("Ctrl+="),            self, self._zoom_in)
        QShortcut(QKeySequence("Ctrl+-"),            self, self._zoom_out)
        QShortcut(QKeySequence("Ctrl+0"),            self, self._zoom_reset)
        QShortcut(QKeySequence("F12"),               self, self._toggle_devtools)
        QShortcut(QKeySequence("Ctrl+P"),            self, self._print_page)
        QShortcut(QKeySequence("Ctrl+D"),            self, self._toggle_bookmark)
        QShortcut(QKeySequence("Ctrl+Shift+B"),      self, self._show_bookmarks)
        QShortcut(QKeySequence("Ctrl+Shift+H"),      self, self._show_history)
        QShortcut(QKeySequence("Ctrl+Shift+Delete"), self, self._clear_session_data)

        self.view.load(QUrl(TARGET_URL))

    # ── Navigation helpers ───────────────────────────────────────────────

    def _navigate_from_bar(self):
        url = normalise_url(self.address_bar.text())
        self.view.load(QUrl(url))

    def _go_home(self):
        self.view.load(QUrl(TARGET_URL))

    def _focus_address_bar(self):
        self.address_bar.setFocus()
        self.address_bar.selectAll()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _on_escape(self):
        if self.find_bar.isVisible():
            self._hide_find_bar()
        else:
            self.view.stop()

    # ── Signal handlers ──────────────────────────────────────────────────

    def _on_url_changed(self, qurl: QUrl):
        url = qurl.toString()
        self.address_bar.setText(url)
        self.btn_back.setEnabled(self.view.history().canGoBack())
        self.btn_forward.setEnabled(self.view.history().canGoForward())
        self._update_lock_icon(qurl)
        self._update_bookmark_button(url)

    def _on_title_changed(self, title: str):
        self.setWindowTitle(f"{title}  —  {APP_DISGUISE}" if title else APP_DISGUISE)

    def _on_load_started(self):
        self.progress.show()
        self.progress.setValue(0)
        self.btn_stop.setEnabled(True)
        self.btn_reload.setEnabled(False)

    def _on_load_progress(self, pct: int):
        self.progress.setValue(pct)

    def _on_load_finished(self, ok: bool):
        self.progress.hide()
        self.btn_stop.setEnabled(False)
        self.btn_reload.setEnabled(True)
        if not ok:
            current_url = self.view.url().toString()
            error_html = ERROR_PAGE_HTML.format(url=current_url, home=TARGET_URL)
            self.view.setHtml(error_html)

    def _on_fullscreen_requested(self, request):
        request.accept()
        if request.toggleOn():
            self.showFullScreen()
        else:
            self.showNormal()

    def _on_audible_changed(self, audible: bool):
        muted = self.page.isAudioMuted()
        self.btn_mute.setText("🔇" if muted else "🔊")

    def _on_download_requested(self, item):
        suggested = item.suggestedFileName() or "download"
        path, _ = QFileDialog.getSaveFileName(self, "Save Download", suggested)
        if path:
            item.setDownloadDirectory(os.path.dirname(path))
            item.setDownloadFileName(os.path.basename(path))
            item.accept()
            item.receivedBytesChanged.connect(
                lambda: self.status.showMessage(
                    f"Downloading: {item.receivedBytes() // 1024} KB"
                )
            )
            item.isFinishedChanged.connect(
                lambda: self.status.showMessage(f"Download complete: {path}", 4000)
                if item.isFinished() else None
            )
        else:
            item.cancel()

    # ── Security lock icon ────────────────────────────────────────────────

    def _update_lock_icon(self, qurl: QUrl):
        scheme = qurl.scheme()
        if scheme == "https":
            self.lock_label.setText("🔒")
            self.lock_label.setStyleSheet("color:#00cc44; font-size:13px; padding:0 4px;")
            self.lock_label.setToolTip("Secure connection (HTTPS)")
        elif scheme == "http":
            self.lock_label.setText("⚠")
            self.lock_label.setStyleSheet("color:#cc4444; font-size:13px; padding:0 4px;")
            self.lock_label.setToolTip("Insecure connection (HTTP)")
        else:
            self.lock_label.setText("")
            self.lock_label.setToolTip("")

    # ── Zoom controls ────────────────────────────────────────────────────

    def _zoom_in(self):
        factor = min(5.0, self.view.zoomFactor() + 0.1)
        self.view.setZoomFactor(factor)
        self.zoom_label.setText(f"{int(factor * 100)}%")

    def _zoom_out(self):
        factor = max(0.25, self.view.zoomFactor() - 0.1)
        self.view.setZoomFactor(factor)
        self.zoom_label.setText(f"{int(factor * 100)}%")

    def _zoom_reset(self):
        self.view.setZoomFactor(1.0)
        self.zoom_label.setText("100%")

    # ── Find in page ─────────────────────────────────────────────────────

    def _show_find_bar(self):
        self.find_bar.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def _hide_find_bar(self):
        self.find_bar.hide()
        self.page.findText("")
        self.view.setFocus()

    def _find_text(self, forward: bool = True):
        text = self.find_input.text()
        if forward:
            self.page.findText(text)
        else:
            self.page.findText(text, QWebEnginePage.FindFlag.FindBackward)

    # ── Mute / Unmute ────────────────────────────────────────────────────

    def _toggle_mute(self):
        muted = self.page.isAudioMuted()
        self.page.setAudioMuted(not muted)
        self.btn_mute.setText("🔊" if muted else "🔇")
        self.btn_mute.setToolTip("Unmute" if not muted else "Mute / Unmute")

    # ── Developer Tools ──────────────────────────────────────────────────

    def _toggle_devtools(self):
        if self._devtools_dialog and self._devtools_dialog.isVisible():
            self._devtools_dialog.hide()
            return

        if self._devtools_dialog is None:
            self._devtools_dialog = QDialog(self)
            self._devtools_dialog.setWindowTitle("Developer Tools — TunnelFox")
            self._devtools_dialog.resize(1000, 600)
            self._devtools_dialog.setStyleSheet("background:#0f0f1e;")
            layout = QVBoxLayout(self._devtools_dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            devtools_view = QWebEngineView()
            self.page.setDevToolsPage(devtools_view.page())
            layout.addWidget(devtools_view)

        self._devtools_dialog.show()
        self._devtools_dialog.raise_()

    # ── Print ────────────────────────────────────────────────────────────

    def _print_page(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Page as PDF",
            f"page_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            "PDF Files (*.pdf)"
        )
        if path:
            self.page.printToPdf(path)
            self.status.showMessage(f"PDF saved: {path}", 4000)

    # ── Bookmarks ────────────────────────────────────────────────────────

    def _load_bookmarks(self) -> list:
        try:
            return json.loads(BOOKMARKS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_bookmarks(self, bookmarks: list):
        BOOKMARKS_PATH.write_text(
            json.dumps(bookmarks, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _toggle_bookmark(self):
        url = self.view.url().toString()
        if not url or url.startswith("about:"):
            return
        bookmarks = self._load_bookmarks()
        existing = next((b for b in bookmarks if b["url"] == url), None)
        if existing:
            bookmarks = [b for b in bookmarks if b["url"] != url]
            self.btn_bookmark.setText("☆")
            self.status.showMessage("Bookmark removed.", 2000)
        else:
            bookmarks.append({
                "url":   url,
                "title": self.view.title() or url,
                "added": datetime.now().isoformat(),
            })
            self.btn_bookmark.setText("★")
            self.status.showMessage("Bookmark saved.", 2000)
        self._save_bookmarks(bookmarks)

    def _update_bookmark_button(self, url: str):
        bookmarks = self._load_bookmarks()
        is_bookmarked = any(b["url"] == url for b in bookmarks)
        self.btn_bookmark.setText("★" if is_bookmarked else "☆")

    def _show_bookmarks(self):
        bookmarks = self._load_bookmarks()
        dlg = QDialog(self)
        dlg.setWindowTitle("Bookmarks")
        dlg.resize(520, 420)
        dlg.setStyleSheet("background:#0f0f1e; color:#e0e0e0;")
        layout = QVBoxLayout(dlg)

        lst = QListWidget()
        lst.setStyleSheet("""
            QListWidget { background:#0f0f1e; color:#e0e0e0;
                          border:1px solid #2a2a4a; font-size:13px; }
            QListWidget::item:hover { background:#2a2a4a; }
            QListWidget::item:selected { background:#3a3a5e; }
        """)
        for bm in bookmarks:
            item = QListWidgetItem(f"★  {bm['title']}")
            item.setData(Qt.ItemDataRole.UserRole, bm["url"])
            item.setToolTip(bm["url"])
            lst.addItem(item)

        def on_activate(item):
            url = item.data(Qt.ItemDataRole.UserRole)
            self.view.load(QUrl(url))
            dlg.accept()

        lst.itemDoubleClicked.connect(on_activate)
        layout.addWidget(lst)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.setStyleSheet("color:#e0e0e0;")
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec()

    # ── History panel ────────────────────────────────────────────────────

    def _show_history(self):
        history = self.view.history()
        items = history.items()

        dlg = QDialog(self)
        dlg.setWindowTitle("History")
        dlg.resize(560, 460)
        dlg.setStyleSheet("background:#0f0f1e; color:#e0e0e0;")
        layout = QVBoxLayout(dlg)

        lst = QListWidget()
        lst.setStyleSheet("""
            QListWidget { background:#0f0f1e; color:#e0e0e0;
                          border:1px solid #2a2a4a; font-size:13px; }
            QListWidget::item:hover { background:#2a2a4a; }
            QListWidget::item:selected { background:#3a3a5e; }
        """)
        for entry in reversed(items):
            title = entry.title() or entry.url().toString()
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, entry.url())
            item.setToolTip(entry.url().toString())
            lst.addItem(item)

        def on_activate(item):
            self.view.load(item.data(Qt.ItemDataRole.UserRole))
            dlg.accept()

        lst.itemDoubleClicked.connect(on_activate)
        layout.addWidget(lst)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.setStyleSheet("color:#e0e0e0;")
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec()

    # ── Clear session data ───────────────────────────────────────────────

    def _clear_session_data(self):
        reply = QMessageBox.question(
            self, "Clear Session Data",
            "Clear all cookies, history, and visited links?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.profile.clearAllVisitedLinks()
            self.profile.cookieStore().deleteAllCookies()
            self.view.history().clear()
            self.status.showMessage("Session data cleared.", 3000)

    # ── Tunnel health check ──────────────────────────────────────────────

    def _check_tunnel_health(self):
        active = is_tunnel_active()
        if active:
            self.tunnel_indicator.setText("● Tunnel")
            self.tunnel_indicator.setStyleSheet("color:#00cc44; font-size:11px; padding:0 8px;")
            self._tunnel_warned = False
        else:
            self.tunnel_indicator.setText("● Tunnel ✗")
            self.tunnel_indicator.setStyleSheet("color:#cc2200; font-size:11px; padding:0 8px;")
            if not self._tunnel_warned:
                self._tunnel_warned = True
                QMessageBox.warning(
                    self, "Tunnel Disconnected",
                    "The SOCKS5 tunnel appears to be down.\n\n"
                    "Your traffic may not be protected. Restart the tunnel."
                )

    # ── Settings dialog ──────────────────────────────────────────────────

    def _show_settings(self):
        global TARGET_URL, APP_DISGUISE, SEARCH_ENGINE

        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setFixedWidth(420)
        dlg.setStyleSheet("""
            QDialog    { background:#0f0f1e; color:#e0e0e0; }
            QLabel     { color:#c0c0d0; }
            QLineEdit  { background:#1a1a2e; color:#e0e0e0; border:1px solid #3a3a5e;
                         border-radius:4px; padding:4px 8px; }
            QSpinBox   { background:#1a1a2e; color:#e0e0e0; border:1px solid #3a3a5e;
                         border-radius:4px; padding:4px 8px; }
            QComboBox  { background:#1a1a2e; color:#e0e0e0; border:1px solid #3a3a5e;
                         border-radius:4px; padding:4px 8px; }
            QPushButton { background:#2a2a4a; color:#e0e0e0; border:none;
                          border-radius:4px; padding:6px 16px; }
            QPushButton:hover { background:#3a3a5e; }
        """)
        form = QFormLayout(dlg)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)

        url_edit = QLineEdit(TARGET_URL)
        name_edit = QLineEdit(APP_DISGUISE)
        port_spin = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(PROXY_PORT)
        engine_combo = QComboBox()
        engine_combo.addItems(["duckduckgo", "google", "bing", "brave"])
        engine_combo.setCurrentText(SEARCH_ENGINE)

        form.addRow("Home URL:", url_edit)
        form.addRow("App Name:", name_edit)
        form.addRow("Local Port:", port_spin)
        form.addRow("Search Engine:", engine_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            TARGET_URL    = url_edit.text().strip() or TARGET_URL
            APP_DISGUISE  = name_edit.text().strip() or APP_DISGUISE
            SEARCH_ENGINE = engine_combo.currentText()

            config["BROWSER"]["home_url"]      = TARGET_URL
            config["BROWSER"]["app_name"]      = APP_DISGUISE
            config["BROWSER"]["local_port"]    = str(port_spin.value())
            config["BROWSER"]["search_engine"] = SEARCH_ENGINE
            with open(CONFIG_PATH, "w") as f:
                config.write(f)

            self.setWindowTitle(APP_DISGUISE)
            self.status.showMessage("Settings saved. Restart for port changes to take effect.", 4000)

    # ── Dark palette ─────────────────────────────────────────────────────

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

    def closeEvent(self, event):
        if self._devtools_dialog:
            self._devtools_dialog.close()
        try:
            if os.path.exists(TEMP_DIR):
                shutil.rmtree(TEMP_DIR, ignore_errors=True)
        except Exception:
            pass
        event.accept()


# ============================================================
#  Entry Point
# ============================================================
if __name__ == "__main__":
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    configure_proxy_early()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISGUISE)
    app.setApplicationVersion("3.0")

    window = TunnelFoxBrowser()
    window.show()
    sys.exit(app.exec())