import sys
import os
import json
import socket
import subprocess
import configparser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QMessageBox, QToolBar, QProgressBar,
    QStatusBar, QLabel, QDialog, QFormLayout, QComboBox,
    QSpinBox, QListWidget, QListWidgetItem, QDialogButtonBox, QFileDialog,
    QSizePolicy, QTabWidget, QTextEdit
)
from PyQt6.QtGui import QColor, QPalette, QKeySequence, QAction, QShortcut
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEngineProfile, QWebEnginePage, QWebEngineSettings
)
from PyQt6.QtCore import QUrl, Qt, QSize, QTimer
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog

# ============================================================
#  TunnelFox — Load config.ini
#  Improvements: real SOCKS5 verification, in-app tunnel controls,
#  diagnostics support, multi-tab, profiles, command palette, etc.
#  Clean OSS release.
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

# Connection settings (used for in-app tunnel restart)
VM_IP     = config.get("CONNECTION", "vm_ip",     fallback="")
KEY_PATH  = config.get("CONNECTION", "key_path",  fallback="")
VM_USER   = config.get("CONNECTION", "vm_user",   fallback="")

BOOKMARKS_PATH = Path.home() / ".tunnelfox" / "bookmarks.json"
BOOKMARKS_PATH.parent.mkdir(parents=True, exist_ok=True)

PROFILES_PATH = Path.home() / ".tunnelfox" / "profiles.json"
PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)

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


def is_tunnel_active() -> bool:
    """Return True only if a working SOCKS5 proxy is reachable on the configured port.

    This performs a real SOCKS5 handshake + a test CONNECT to prove the ssh -D
    tunnel is actually forwarding traffic (not just that something is listening).
    """
    return _test_socks5_proxy(PROXY_HOST, PROXY_PORT)


def _test_socks5_proxy(host: str, port: int, timeout: float = 2.8) -> bool:
    """Minimal SOCKS5 client: greeting + CONNECT to a public IP.

    Uses only the standard library. Designed to be fast and side-effect light
    for use in startup checks and the periodic health timer.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            # 1. Client greeting: SOCKS5, 1 method (0 = no authentication)
            sock.sendall(b"\x05\x01\x00")
            greeting = sock.recv(2)
            if len(greeting) != 2 or greeting[0] != 0x05 or greeting[1] != 0x00:
                return False  # Not a SOCKS5 proxy or it requires auth we don't support

            # 2. CONNECT request (IPv4 ATYP for speed, no DNS on the proxy for the test)
            #    Target: 1.1.1.1:53 (Cloudflare DNS - reliable, accepts TCP, very common)
            test_ip = "1.1.1.1"
            test_port = 53
            addr = socket.inet_aton(test_ip)
            connect_req = b"\x05\x01\x00\x01" + addr + test_port.to_bytes(2, "big")
            sock.sendall(connect_req)

            # Reply format: VER + REP + RSV + ATYP + BND.ADDR + BND.PORT
            # We only need the REP field (0x00 = success)
            reply = sock.recv(10)
            if len(reply) < 2 or reply[0] != 0x05 or reply[1] != 0x00:
                return False

            return True

    except (socket.timeout, OSError, ConnectionError):
        return False
    except Exception:
        # Never let a health check or preflight crash the application
        return False


def _fetch_egress_ip(host: str = "127.0.0.1", port: int = 1080, timeout: float = 6.0) -> str | None:
    """Fetch the public IP as seen through the SOCKS5 tunnel.

    Uses a minimal HTTP/1.0 request over a manually established SOCKS5 CONNECT.
    Returns the IP string on success, None on failure.
    This is the same technique used by diagnose_tunnel.py.
    """
    target_host = "ifconfig.me"
    target_port = 80

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            # SOCKS5 greeting
            sock.sendall(b"\x05\x01\x00")
            if sock.recv(2) != b"\x05\x00":
                return None

            # CONNECT to target (resolve target locally to avoid leaking DNS through the check itself if possible)
            try:
                target_ip = socket.gethostbyname(target_host)
            except socket.gaierror:
                target_ip = "1.1.1.1"  # fallback

            addr = socket.inet_aton(target_ip)
            req = b"\x05\x01\x00\x01" + addr + target_port.to_bytes(2, "big")
            sock.sendall(req)

            reply = sock.recv(10)
            if len(reply) < 2 or reply[1] != 0x00:
                return None

            # Send minimal HTTP request
            http_req = (
                f"GET / HTTP/1.0\r\n"
                f"Host: {target_host}\r\n"
                f"User-Agent: TunnelFox/1.0\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("ascii", errors="ignore")
            sock.sendall(http_req)

            # Read response body
            sock.settimeout(4.0)
            chunks: list[bytes] = []
            try:
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break
                    chunks.append(data)
            except socket.timeout:
                pass

            body = b"".join(chunks).decode("utf-8", errors="replace")
            lines = [l.strip() for l in body.splitlines() if l.strip()]

            # ifconfig.me typically returns just the IP address
            for line in reversed(lines[-6:]):
                line = line.strip()
                if len(line) > 6 and len(line) < 50 and all(c.isdigit() or c == "." for c in line):
                    # Quick validation: looks like IPv4
                    parts = line.split(".")
                    if len(parts) == 4 and all(0 <= int(p) <= 255 for p in parts if p.isdigit()):
                        return line

            return None

    except Exception:
        return None


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

        self._tunnel_ready = is_tunnel_active()

        self.setWindowTitle(APP_DISGUISE)
        self.resize(1280, 900)
        self._apply_dark_palette()

        self._devtools_dialog = None
        self._tunnel_warned = False
        self._recovery_attempts = 0
        self._last_egress_ip = None
        self._active_downloads = []  # for Download Manager (Feature C)

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

        # ── Tabs (Feature A: multi-tab support) ─────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Create the first tab WITHOUT loading URL yet (UI not ready; load later to avoid signal timing issues)
        self._add_new_tab(switch_to=True)  # no initial_url here

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

        self.btn_back.triggered.connect(self._tab_back)
        self.btn_forward.triggered.connect(self._tab_forward)
        self.btn_reload.triggered.connect(self._tab_reload)
        self.btn_home.triggered.connect(self._go_home)
        self.btn_stop.triggered.connect(self._tab_stop)
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

        self.btn_connection = QAction("ℹ", self)
        self.btn_connection.setToolTip("Connection Status / Verify Tunnel (Ctrl+I)")
        self.btn_connection.triggered.connect(self._show_connection_status)
        nav.addAction(self.btn_connection)

        self.btn_new_session = QAction("⊞", self)
        self.btn_new_session.setToolTip("New Clean Session (Ctrl+N) — fresh memory profile")
        self.btn_new_session.triggered.connect(self._new_clean_session)
        nav.addAction(self.btn_new_session)

        self.btn_downloads = QAction("⬇", self)
        self.btn_downloads.setToolTip("Downloads (Ctrl+J)")
        self.btn_downloads.triggered.connect(self._show_downloads)
        nav.addAction(self.btn_downloads)

        self.btn_palette = QAction("⌘", self)
        self.btn_palette.setToolTip("Command Palette (Ctrl+Shift+P)")
        self.btn_palette.triggered.connect(self._show_command_palette)
        nav.addAction(self.btn_palette)

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

        # ── Tunnel warning / reconnect bar ──────────────────────────────
        self.tunnel_bar = QWidget()
        self.tunnel_bar.setStyleSheet("background:#3a1a1a; border-bottom:1px solid #5a2a2a;")
        tunnel_layout = QHBoxLayout(self.tunnel_bar)
        tunnel_layout.setContentsMargins(12, 6, 12, 6)
        tunnel_layout.setSpacing(10)

        self.tunnel_bar_label = QLabel("🔴  Tunnel is not active — traffic is not protected")
        self.tunnel_bar_label.setStyleSheet("color:#ffaaaa; font-size:13px;")
        self.tunnel_bar_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.btn_restart_tunnel = QPushButton("Start / Restart Tunnel")
        self.btn_restart_tunnel.setStyleSheet(
            "QPushButton { background:#5a2a2a; color:#ffdddd; border:1px solid #7a3a3a; "
            "border-radius:4px; padding:4px 14px; font-size:12px; } "
            "QPushButton:hover { background:#6a3a3a; }"
        )
        self.btn_restart_tunnel.clicked.connect(self._restart_tunnel)

        tunnel_layout.addWidget(self.tunnel_bar_label)
        tunnel_layout.addWidget(self.btn_restart_tunnel)
        self.tunnel_bar.hide()  # shown only when needed

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

        # Egress IP indicator (usecase-centric: users want to *see* the tunnel is working)
        self.egress_label = QLabel("Egress: —")
        self.egress_label.setStyleSheet("color:#808090; font-size:11px; padding:0 6px;")
        self.egress_label.setToolTip("Public IP as seen through the tunnel (click refresh to verify)")
        self.status.addPermanentWidget(self.egress_label)

        self.egress_refresh_btn = QPushButton("⟳")
        self.egress_refresh_btn.setFixedSize(20, 18)
        self.egress_refresh_btn.setStyleSheet(
            "QPushButton { background:#2a2a4a; color:#a0a0b0; border:1px solid #3a3a5e; "
            "border-radius:3px; font-size:10px; padding:0; } "
            "QPushButton:hover { background:#3a3a5e; color:#c0c0d0; }"
        )
        self.egress_refresh_btn.setToolTip("Verify current egress IP through the tunnel")
        self.egress_refresh_btn.clicked.connect(lambda: self._verify_egress_ip())
        self.status.addPermanentWidget(self.egress_refresh_btn)

        # ── Central layout ──────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.progress)
        layout.addWidget(self.tunnel_bar)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.tabs)

        # ── Signals (connected to current tab in _on_tab_changed and per-tab) ─────
        self.profile.downloadRequested.connect(self._on_download_requested)
        # Initial tab signals are wired inside _add_new_tab; _on_tab_changed keeps UI in sync

        # ── Tunnel health timer ──────────────────────────────────────────
        self._tunnel_timer = QTimer(self)
        self._tunnel_timer.timeout.connect(self._check_tunnel_health)
        self._tunnel_timer.start(15_000)

        # ── Keyboard shortcuts ───────────────────────────────────────────
        QShortcut(QKeySequence("F5"),                self, self._tab_reload)
        QShortcut(QKeySequence("Ctrl+R"),            self, self._tab_reload)
        QShortcut(QKeySequence("Ctrl+L"),            self, self._focus_address_bar)
        QShortcut(QKeySequence("Alt+Left"),          self, self._tab_back)
        QShortcut(QKeySequence("Alt+Right"),         self, self._tab_forward)
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
        QShortcut(QKeySequence("Ctrl+I"),            self, self._show_connection_status)
        QShortcut(QKeySequence("Ctrl+N"),            self, self._new_clean_session)
        QShortcut(QKeySequence("Ctrl+J"),            self, self._show_downloads)
        QShortcut(QKeySequence("Ctrl+D"),            self, self._toggle_bookmark)
        QShortcut(QKeySequence("Ctrl+Shift+B"),      self, self._show_bookmarks)
        QShortcut(QKeySequence("Ctrl+Shift+H"),      self, self._show_history)
        QShortcut(QKeySequence("Ctrl+Shift+Delete"), self, self._clear_session_data)
        QShortcut(QKeySequence("Ctrl+Shift+P"),      self, self._show_command_palette)
        QShortcut(QKeySequence("Ctrl+T"),            self, lambda: self._add_new_tab(switch_to=True))
        QShortcut(QKeySequence("Ctrl+W"),            self, lambda: self._close_tab(self.tabs.currentIndex()) if hasattr(self, 'tabs') and self.tabs.count() > 1 else None)

        self._update_tunnel_ui_state()

        # Load the initial URL into the first tab now that all UI (address bar etc) is ready.
        # This avoids signals firing too early. Re-verify egress shortly after.
        if self._tunnel_ready:
            if v := self._current_view():
                v.load(QUrl(TARGET_URL))
            QTimer.singleShot(2500, lambda: self._verify_egress_ip())
        else:
            self.status.showMessage("Tunnel not active — use the bar above to start it.", 8000)

    # ── Tab helpers (for Feature A) + compat shims ────────────────────────

    def _add_new_tab(self, initial_url=None, switch_to=False):
        """Create a new tab with its own view + page. Load happens later in __init__ for the first tab to ensure UI is ready."""
        view = QWebEngineView()
        page = CustomWebEnginePage(self.profile, view)
        view.setPage(page)

        # Wire per-tab signals for address/title etc.
        view.urlChanged.connect(self._on_url_changed)
        view.titleChanged.connect(self._on_title_changed)
        view.loadStarted.connect(self._on_load_started)
        view.loadProgress.connect(self._on_load_progress)
        view.loadFinished.connect(self._on_load_finished)
        page.linkHovered.connect(lambda url: self.status.showMessage(url, 2000))
        page.fullScreenRequested.connect(self._on_fullscreen_requested)
        page.recentlyAudibleChanged.connect(self._on_audible_changed)

        # Override createWindow on the page so links can open new tabs
        # (we monkey the method to use our _add_new_tab)
        orig_create = page.createWindow
        def _create_window_in_new_tab(_type):
            new_view = self._add_new_tab(switch_to=True)
            return new_view.page() if new_view else orig_create(_type)
        page.createWindow = _create_window_in_new_tab

        idx = self.tabs.addTab(view, "New Tab")
        if switch_to:
            self.tabs.setCurrentIndex(idx)

        if initial_url:
            view.load(QUrl(initial_url))

        # For code that still does self.view / self.page (gradual migration)
        self.view = view
        self.page = page

        return view

    def _current_view(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, QWebEngineView) else None

    def _current_page(self):
        v = self._current_view()
        return v.page() if v else None

    def _close_tab(self, index):
        if self.tabs.count() <= 1:
            return  # keep at least one
        w = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if w:
            w.deleteLater()

    def _on_tab_changed(self, index):
        v = self._current_view()
        if not v:
            return
        # Sync UI from new current tab
        self.view = v
        self.page = v.page()
        self.address_bar.setText(v.url().toString())
        self.btn_back.setEnabled(v.history().canGoBack())
        self.btn_forward.setEnabled(v.history().canGoForward())
        title = self.tabs.tabText(index) or "New Tab"
        self.setWindowTitle(f"{title} — {APP_DISGUISE}" if title else APP_DISGUISE)
        # Update zoom label etc if needed
        try:
            z = int(v.zoomFactor() * 100)
            self.zoom_label.setText(f"{z}%")
        except Exception:
            pass

    # Compat shims so old direct calls keep working during refactor
    def _tab_back(self):
        if v := self._current_view(): v.back()

    def _tab_forward(self):
        if v := self._current_view(): v.forward()

    def _tab_reload(self):
        if v := self._current_view(): v.reload()

    def _tab_stop(self):
        if v := self._current_view(): v.stop()

    # ── Navigation helpers ───────────────────────────────────────────────

    def _navigate_from_bar(self):
        url = normalise_url(self.address_bar.text())
        if v := self._current_view():
            v.load(QUrl(url))

    def _go_home(self):
        if v := self._current_view():
            v.load(QUrl(TARGET_URL))

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
            if v := self._current_view():
                v.stop()

    # ── Signal handlers ──────────────────────────────────────────────────

    def _on_url_changed(self, qurl: QUrl):
        url = qurl.toString()
        self.address_bar.setText(url)
        if v := self._current_view():
            self.btn_back.setEnabled(v.history().canGoBack())
            self.btn_forward.setEnabled(v.history().canGoForward())
        self._update_lock_icon(qurl)
        self._update_bookmark_button(url)

    def _on_title_changed(self, title: str):
        self.setWindowTitle(f"{title}  —  {APP_DISGUISE}" if title else APP_DISGUISE)
        # Update current tab text too (for multi-tab)
        if hasattr(self, 'tabs'):
            idx = self.tabs.currentIndex()
            if idx >= 0:
                short = (title or "New Tab")[:30]
                self.tabs.setTabText(idx, short)

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
            if v := self._current_view():
                current_url = v.url().toString()
                error_html = ERROR_PAGE_HTML.format(url=current_url, home=TARGET_URL)
                v.setHtml(error_html)

    def _on_fullscreen_requested(self, request):
        request.accept()
        if request.toggleOn():
            self.showFullScreen()
        else:
            self.showNormal()

    def _on_audible_changed(self, audible: bool):
        if p := self._current_page():
            muted = p.isAudioMuted()
            self.btn_mute.setText("🔇" if muted else "🔊")

    def _on_download_requested(self, item):
        suggested = item.suggestedFileName() or "download"
        path, _ = QFileDialog.getSaveFileName(self, "Save Download", suggested)
        if path:
            item.setDownloadDirectory(os.path.dirname(path))
            item.setDownloadFileName(os.path.basename(path))
            item.accept()
            self._active_downloads.append(item)
            item.receivedBytesChanged.connect(
                lambda: self.status.showMessage(
                    f"Downloading: {item.receivedBytes() // 1024} KB"
                )
            )
            item.isFinishedChanged.connect(
                lambda finished=item: self._on_download_finished(finished, path)
            )
        else:
            item.cancel()

    def _on_download_finished(self, item, path):
        if item in self._active_downloads:
            self._active_downloads.remove(item)
        self.status.showMessage(f"Download complete: {path}", 4000)

    def _show_downloads(self):
        """Simple Download Manager dialog (Feature C). Lists active downloads."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Downloads — TunnelFox")
        dlg.resize(480, 320)
        dlg.setStyleSheet("background:#0f0f1e; color:#e0e0e0;")

        layout = QVBoxLayout(dlg)

        lst = QListWidget()
        lst.setStyleSheet("""
            QListWidget { background:#1a1a2e; color:#c0c0d0; border:1px solid #2a2a4a; }
            QListWidget::item:hover { background:#2a2a4a; }
        """)

        if not self._active_downloads:
            lst.addItem("No active downloads")
        else:
            for item in list(self._active_downloads):
                name = item.suggestedFileName() or item.downloadFileName() or "download"
                state = "Finished" if item.isFinished() else f"{item.receivedBytes()//1024} KB"
                lst.addItem(f"{name} — {state}")

        layout.addWidget(lst)

        btn_layout = QHBoxLayout()
        btn_clear = QPushButton("Clear List")
        btn_clear.clicked.connect(lambda: (lst.clear(), dlg.accept()))
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        btn_layout.addWidget(btn_clear)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        dlg.exec()

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
        if v := self._current_view():
            factor = min(5.0, v.zoomFactor() + 0.1)
            v.setZoomFactor(factor)
            self.zoom_label.setText(f"{int(factor * 100)}%")

    def _zoom_out(self):
        if v := self._current_view():
            factor = max(0.25, v.zoomFactor() - 0.1)
            v.setZoomFactor(factor)
            self.zoom_label.setText(f"{int(factor * 100)}%")

    def _zoom_reset(self):
        if v := self._current_view():
            v.setZoomFactor(1.0)
            self.zoom_label.setText("100%")

    # ── Find in page ─────────────────────────────────────────────────────

    def _show_find_bar(self):
        self.find_bar.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def _hide_find_bar(self):
        self.find_bar.hide()
        if p := self._current_page():
            p.findText("")
        if v := self._current_view():
            v.setFocus()

    def _find_text(self, forward: bool = True):
        text = self.find_input.text()
        if p := self._current_page():
            if forward:
                p.findText(text)
            else:
                p.findText(text, QWebEnginePage.FindFlag.FindBackward)

    # ── Mute / Unmute ────────────────────────────────────────────────────

    def _toggle_mute(self):
        if p := self._current_page():
            muted = p.isAudioMuted()
            p.setAudioMuted(not muted)
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
            if p := self._current_page():
                p.setDevToolsPage(devtools_view.page())
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
            if p := self._current_page():
                p.printToPdf(path)
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
        if v := self._current_view():
            url = v.url().toString()
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
                    "title": v.title() or url,
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
            if v := self._current_view():
                v.load(QUrl(url))
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
        if v := self._current_view():
            history = v.history()
        else:
            return
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
            if v := self._current_view():
                v.load(item.data(Qt.ItemDataRole.UserRole))
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
            if v := self._current_view():
                v.history().clear()
            self.status.showMessage("Session data cleared.", 3000)

    # ── Tunnel health check ──────────────────────────────────────────────

    def _check_tunnel_health(self):
        active = is_tunnel_active()
        previous = self._tunnel_ready
        self._tunnel_ready = active

        if active:
            self.tunnel_indicator.setText("● Tunnel")
            self.tunnel_indicator.setStyleSheet("color:#00cc44; font-size:11px; padding:0 8px;")
            self._tunnel_warned = False
            if not previous:
                # Tunnel just came back up — auto-recover
                self.status.showMessage("Tunnel restored. Loading home page...", 3000)
                if v := self._current_view():
                    if v.url().toString().startswith("about:") or not v.url().isValid():
                        v.load(QUrl(TARGET_URL))
                # Auto-verify egress so user sees proof immediately
                QTimer.singleShot(1200, lambda: self._verify_egress_ip())
        else:
            self.tunnel_indicator.setText("● Tunnel ✗")
            self.tunnel_indicator.setStyleSheet("color:#cc2200; font-size:11px; padding:0 8px;")
            if not self._tunnel_warned:
                self._tunnel_warned = True
                QMessageBox.warning(
                    self, "Tunnel Disconnected",
                    "The SOCKS5 tunnel is no longer forwarding traffic.\n\n"
                    "Your traffic may not be protected. Restart the tunnel."
                )

        self._update_tunnel_ui_state()

    def _restart_tunnel(self):
        """Attempt to (re)launch the SSH tunnel from inside the app."""
        if not (VM_IP and KEY_PATH and VM_USER):
            QMessageBox.warning(
                self, "Missing Configuration",
                "vm_ip, key_path, or vm_user is not set in config.ini.\n"
                "Please edit config.ini or use start_fox.bat / start_tunnel.bat instead."
            )
            return

        self.status.showMessage("Starting tunnel in background...", 4000)
        self.btn_restart_tunnel.setEnabled(False)
        self.btn_restart_tunnel.setText("Starting...")

        try:
            # Launch ssh in detached mode (similar to start_fox.bat)
            # We use creationflags so it doesn't die with the parent python process.
            cmd = ["ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=60", "-o", "StrictHostKeyChecking=no", "-o", "IdentitiesOnly=no"]
            if KEY_PATH:
                cmd.insert(1, "-i")
                cmd.insert(2, KEY_PATH)
            cmd.extend(["-D", str(PROXY_PORT), f"{VM_USER}@{VM_IP}"])

            # Windows-specific flags for true background process
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            DETACHED_PROCESS = 0x00000008
            flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

            subprocess.Popen(
                cmd,
                creationflags=flags,
                close_fds=True,
            )

            # Give it a moment, then start aggressive polling from the UI
            QTimer.singleShot(2500, self._poll_for_tunnel_recovery)

        except Exception as e:
            self.btn_restart_tunnel.setEnabled(True)
            self.btn_restart_tunnel.setText("Start / Restart Tunnel")
            QMessageBox.critical(
                self, "Failed to Start Tunnel",
                f"Could not launch ssh process:\n{e}\n\n"
                "Try running start_tunnel.bat manually for verbose output."
            )

    def _poll_for_tunnel_recovery(self):
        """Poll the SOCKS5 proxy after a restart attempt and recover when ready."""
        if is_tunnel_active():
            self._tunnel_ready = True
            self._update_tunnel_ui_state()
            self.status.showMessage("Tunnel is now active!", 4000)
            self.btn_restart_tunnel.setText("Start / Restart Tunnel")
            if v := self._current_view():
                if not v.url().isValid() or v.url().toString().startswith(("about:", "data:")):
                    v.load(QUrl(TARGET_URL))
            # Automatically verify egress IP now that the tunnel is live (great UX for trust)
            QTimer.singleShot(800, lambda: self._verify_egress_ip())
            return

        # Not ready yet — try a few more times with short interval
        if not hasattr(self, "_recovery_attempts"):
            self._recovery_attempts = 0
        self._recovery_attempts += 1

        if self._recovery_attempts < 12:  # ~30 seconds total
            self.status.showMessage(f"Waiting for tunnel... ({self._recovery_attempts})", 1500)
            QTimer.singleShot(2500, self._poll_for_tunnel_recovery)
        else:
            self._recovery_attempts = 0
            self.btn_restart_tunnel.setEnabled(True)
            self.btn_restart_tunnel.setText("Start / Restart Tunnel")
            self.status.showMessage("Tunnel did not come up. Check logs or try start_tunnel.bat.", 6000)

    def _new_clean_session(self):
        """Launch a completely fresh TunnelFox instance (new memory profile, new window).
        Useful for separating tasks while reusing the same tunnel. (Feature B)
        """
        self.status.showMessage("Launching new clean session...", 2000)
        try:
            if getattr(sys, "frozen", False):
                # Running as built exe (PyInstaller)
                exe_path = sys.executable
                work_dir = os.path.dirname(exe_path)
                # Detached, same style as tunnel restart
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                DETACHED_PROCESS = 0x00000008
                flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                subprocess.Popen([exe_path], cwd=work_dir, creationflags=flags, close_fds=True)
            else:
                # Dev / source run
                python = sys.executable
                script = os.path.abspath(__file__)
                subprocess.Popen([python, script], cwd=os.path.dirname(script))
        except Exception as e:
            QMessageBox.warning(self, "New Session Failed", f"Could not launch new instance:\n{e}")

    # ── Egress IP verification (core usecase: prove the tunnel is active while browsing) ──

    def _verify_egress_ip(self):
        """Perform an on-demand egress IP check through the current SOCKS5 tunnel and update the UI."""
        if not self._tunnel_ready:
            self.egress_label.setText("Egress: (no tunnel)")
            self.egress_label.setStyleSheet("color:#cc6666; font-size:11px; padding:0 6px;")
            self.status.showMessage("Cannot verify egress — tunnel is not active.", 3000)
            return

        self.egress_label.setText("Egress: verifying...")
        self.egress_label.setStyleSheet("color:#a0a0b0; font-size:11px; padding:0 6px;")
        self.egress_refresh_btn.setEnabled(False)

        # Run the check (quick enough for this use case; runs in main thread briefly)
        ip = _fetch_egress_ip(PROXY_HOST, PROXY_PORT)

        self.egress_refresh_btn.setEnabled(True)

        if ip:
            self.egress_label.setText(f"Egress: {ip}")
            self.egress_label.setStyleSheet("color:#66aa66; font-size:11px; padding:0 6px;")
            self.egress_label.setToolTip(f"Public IP through tunnel: {ip}\n(verified just now)")
            self.status.showMessage(f"Egress verified: {ip}", 4000)
            # Remember last good one in case we want to show it elsewhere
            self._last_egress_ip = ip
        else:
            self.egress_label.setText("Egress: ?")
            self.egress_label.setStyleSheet("color:#ccaa66; font-size:11px; padding:0 6px;")
            self.egress_label.setToolTip("Could not determine egress IP (check tunnel or try again)")
            self.status.showMessage("Egress verification failed. Is the tunnel forwarding HTTP?", 5000)

    def _show_connection_status(self):
        """Rich dialog showing tunnel + egress status, with actions. (Feature D)"""
        dlg = QDialog(self)
        dlg.setWindowTitle("Connection Status — TunnelFox")
        dlg.setMinimumWidth(480)
        dlg.setStyleSheet("background:#0f0f1e; color:#e0e0e0;")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Status summary
        info = QLabel()
        info.setTextFormat(Qt.TextFormat.RichText)
        tunnel_status = "🟢 Active" if self._tunnel_ready else "🔴 Inactive"
        egress = self._last_egress_ip or getattr(self, 'egress_label', QLabel()).text().replace("Egress: ", "") or "—"
        vm = VM_IP or "(from config)"
        port = PROXY_PORT

        text = f"""
<b>Tunnel:</b> {tunnel_status} on 127.0.0.1:{port}<br/>
<b>Jump Host:</b> {VM_USER or '?'}@{vm}<br/>
<b>Last Verified Egress IP:</b> {egress}<br/>
<b>Profile:</b> Memory-only, no persistent cookies
"""
        info.setText(text.strip())
        info.setStyleSheet("font-size:13px; line-height:1.4;")
        layout.addWidget(info)

        # Buttons row
        btn_layout = QHBoxLayout()
        btn_verify = QPushButton("Re-verify Egress IP")
        btn_verify.clicked.connect(lambda: (self._verify_egress_ip(), dlg.accept(), self._show_connection_status()))
        btn_restart = QPushButton("Restart Tunnel")
        btn_restart.clicked.connect(lambda: (self._restart_tunnel(), dlg.accept()))
        btn_diag = QPushButton("Run In-App Diagnostics")
        btn_diag.clicked.connect(lambda: (dlg.accept(), self._run_inapp_diagnostics()))
        btn_profiles = QPushButton("Profiles")
        btn_profiles.clicked.connect(lambda: (dlg.accept(), self._show_profiles()))
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)

        btn_layout.addWidget(btn_verify)
        btn_layout.addWidget(btn_restart)
        btn_layout.addWidget(btn_diag)
        btn_layout.addWidget(btn_profiles)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        # Note
        note = QLabel("All traffic is routed through the SSH SOCKS5 tunnel. Use diagnostics if verification fails.")
        note.setStyleSheet("color:#808090; font-size:11px;")
        layout.addWidget(note)

        dlg.exec()

    def _run_inapp_diagnostics(self):
        """In-app version of diagnostics (Feature H). Shows results in a dialog."""
        dlg = QDialog(self)
        dlg.setWindowTitle("In-App Diagnostics — TunnelFox")
        dlg.resize(520, 420)
        dlg.setStyleSheet("background:#0f0f1e; color:#e0e0e0;")

        layout = QVBoxLayout(dlg)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet("background:#1a1a2e; color:#c0c0d0; font-family:monospace; font-size:12px;")

        results = []
        results.append("=== TunnelFox In-App Diagnostics ===\n")

        # 1. Config
        results.append(f"[OK] Config loaded. Port={PROXY_PORT}, App={APP_DISGUISE}")
        if VM_IP:
            results.append(f"[OK] Jump: {VM_USER}@{VM_IP}")
        else:
            results.append("[WARN] No VM_IP in config")

        # 2. Key file
        key_p = Path(KEY_PATH) if KEY_PATH else None
        if key_p and key_p.exists():
            results.append(f"[OK] Key file exists: {key_p}")
        else:
            results.append(f"[FAIL] Key file missing or not configured: {KEY_PATH}")

        # 3. SOCKS5 test (using our real probe)
        ok, reason = _test_socks5_proxy(PROXY_HOST, PROXY_PORT, timeout=3.5)
        if ok:
            results.append(f"[OK] SOCKS5 probe: {reason}")
        else:
            results.append(f"[FAIL] SOCKS5 probe: {reason}")

        # 4. Egress
        if self._tunnel_ready:
            ip = _fetch_egress_ip(PROXY_HOST, PROXY_PORT)
            if ip:
                results.append(f"[OK] Egress IP through tunnel: {ip}")
            else:
                results.append("[FAIL] Could not fetch egress IP")
        else:
            results.append("[INFO] Skipping egress (tunnel not active)")

        # 5. Suggestions
        results.append("\n--- Suggestions ---")
        if not self._tunnel_ready:
            results.append("• Run start_fox.bat or use the 'Start / Restart Tunnel' button")
        results.append("• For verbose pre-launch: use tunnel-diagnose.bat")
        results.append("• Ensure the jump host allows dynamic forwarding (-D)")

        text.setPlainText("\n".join(results))
        layout.addWidget(text)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        dlg.exec()

    def _show_profiles(self):
        """Basic profiles switcher (Feature F). Named sets of CONNECTION+BROWSER."""
        profs = {}
        try:
            if PROFILES_PATH.exists():
                profs = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        except Exception:
            profs = {}

        dlg = QDialog(self)
        dlg.setWindowTitle("Profiles — TunnelFox")
        dlg.setFixedWidth(420)
        dlg.setStyleSheet("background:#0f0f1e; color:#e0e0e0;")

        layout = QVBoxLayout(dlg)

        lst = QListWidget()
        for name in sorted(profs.keys()):
            lst.addItem(name)
        if not profs:
            lst.addItem("(no saved profiles yet)")

        layout.addWidget(QLabel("Saved profiles:"))
        layout.addWidget(lst)

        name_edit = QLineEdit("my-jump")
        layout.addWidget(QLabel("Profile name to save current as:"))
        layout.addWidget(name_edit)

        btn_save = QPushButton("Save current settings as profile")
        btn_load = QPushButton("Load selected profile (applies now)")
        btn_close = QPushButton("Close")

        def do_save():
            n = name_edit.text().strip() or "default"
            profs[n] = {
                "BROWSER": {"home_url": TARGET_URL, "app_name": APP_DISGUISE, "local_port": str(PROXY_PORT), "search_engine": SEARCH_ENGINE},
                "CONNECTION": {"vm_ip": VM_IP, "vm_user": VM_USER, "key_path": KEY_PATH}
            }
            try:
                PROFILES_PATH.write_text(json.dumps(profs, indent=2), encoding="utf-8")
                QMessageBox.information(self, "Saved", f"Profile '{n}' saved.")
                dlg.accept()
                self._show_profiles()  # refresh
            except Exception as e:
                QMessageBox.warning(self, "Save failed", str(e))

        def do_load():
            if not lst.currentItem():
                return
            n = lst.currentItem().text()
            if n not in profs:
                return
            p = profs[n]
            global TARGET_URL, APP_DISGUISE, PROXY_PORT, SEARCH_ENGINE, VM_IP, VM_USER, KEY_PATH
            b = p.get("BROWSER", {})
            c = p.get("CONNECTION", {})
            TARGET_URL = b.get("home_url", TARGET_URL)
            APP_DISGUISE = b.get("app_name", APP_DISGUISE)
            PROXY_PORT = int(b.get("local_port", PROXY_PORT))
            SEARCH_ENGINE = b.get("search_engine", SEARCH_ENGINE)
            VM_IP = c.get("vm_ip", VM_IP)
            VM_USER = c.get("vm_user", VM_USER)
            KEY_PATH = c.get("key_path", KEY_PATH)
            # Also write to main config
            config["BROWSER"]["home_url"] = TARGET_URL
            config["BROWSER"]["app_name"] = APP_DISGUISE
            config["BROWSER"]["local_port"] = str(PROXY_PORT)
            config["BROWSER"]["search_engine"] = SEARCH_ENGINE
            config["CONNECTION"] = {"vm_ip": VM_IP, "vm_user": VM_USER, "key_path": KEY_PATH}
            with open(CONFIG_PATH, "w") as f: config.write(f)
            self.setWindowTitle(APP_DISGUISE)
            QMessageBox.information(self, "Loaded", f"Profile '{n}' applied. Restart tunnel if needed.")
            dlg.accept()

        btn_save.clicked.connect(do_save)
        btn_load.clicked.connect(do_load)
        btn_close.clicked.connect(dlg.accept)

        bl = QHBoxLayout()
        bl.addWidget(btn_save)
        bl.addWidget(btn_load)
        bl.addStretch()
        bl.addWidget(btn_close)
        layout.addLayout(bl)

        dlg.exec()

    # ── Command Palette (Feature E) ───────────────────────────────────────
    def _show_command_palette(self):
        """Searchable command palette (Ctrl+Shift+P). Power-user access to actions, bookmarks, etc."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Command Palette — TunnelFox")
        dlg.resize(520, 400)
        dlg.setStyleSheet("background:#0f0f1e; color:#e0e0e0;")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(8, 8, 8, 8)

        filter_edit = QLineEdit()
        filter_edit.setPlaceholderText("Type to filter actions, bookmarks, history… (e.g. clear, verify, new tab)")
        filter_edit.setStyleSheet("background:#1a1a2e; color:#e0e0e0; border:1px solid #3a3a5e; padding:6px; font-size:14px;")
        layout.addWidget(filter_edit)

        lst = QListWidget()
        lst.setStyleSheet("""
            QListWidget { background:#1a1a2e; color:#c0c0d0; border:1px solid #2a2a4a; font-size:13px; }
            QListWidget::item:hover { background:#2a2a4a; }
            QListWidget::item:selected { background:#3a3a5e; }
        """)
        layout.addWidget(lst)

        # Define actions (callables that work with current tab/profile)
        actions = [
            {"name": "New Clean Session", "desc": "Open a fresh ephemeral window (Ctrl+N)", "fn": self._new_clean_session},
            {"name": "New Tab", "desc": "Open new tab", "fn": lambda: self._add_new_tab(switch_to=True)},
            {"name": "Close Current Tab", "desc": "", "fn": lambda: self._close_tab(self.tabs.currentIndex()) if hasattr(self, 'tabs') and self.tabs.count() > 1 else None},
            {"name": "Verify Egress IP", "desc": "Check public IP through tunnel", "fn": self._verify_egress_ip},
            {"name": "Show Connection Status", "desc": "Tunnel / egress info + actions (Ctrl+I)", "fn": self._show_connection_status},
            {"name": "Restart Tunnel", "desc": "Start or restart the SSH tunnel", "fn": self._restart_tunnel},
            {"name": "Run Diagnostics", "desc": "In-app tunnel diagnostics (H)", "fn": self._run_inapp_diagnostics},
            {"name": "Show Profiles", "desc": "Switch or save jump host profiles (F)", "fn": self._show_profiles},
            {"name": "Clear Session Data", "desc": "Wipe cookies, history, visited links (Ctrl+Shift+Del)", "fn": self._clear_session_data},
            {"name": "Show Bookmarks", "desc": "Open bookmarks (Ctrl+Shift+B)", "fn": self._show_bookmarks},
            {"name": "Show History", "desc": "Open history (Ctrl+Shift+H)", "fn": self._show_history},
            {"name": "Open Downloads", "desc": "Download manager (Ctrl+J)", "fn": self._show_downloads},
            {"name": "Go Home", "desc": "Load home URL (Ctrl+H)", "fn": self._go_home},
            {"name": "Print Page to PDF", "desc": "Save current page as PDF (Ctrl+P)", "fn": self._print_page},
            {"name": "Toggle Mute", "desc": "", "fn": self._toggle_mute},
            {"name": "Find in Page", "desc": "Open find bar (Ctrl+F)", "fn": self._show_find_bar},
            {"name": "Toggle Fullscreen", "desc": "F11", "fn": self._toggle_fullscreen},
            {"name": "Open Settings", "desc": "☰ Settings dialog", "fn": self._show_settings},
            {"name": "Toggle Bookmark", "desc": "Bookmark current page (Ctrl+D)", "fn": self._toggle_bookmark},
        ]

        # Also inject recent bookmarks as quick actions
        try:
            for bm in self._load_bookmarks()[:5]:
                actions.append({
                    "name": f"Bookmark: {bm.get('title', bm['url'])[:40]}",
                    "desc": "Open bookmark",
                    "fn": lambda u=bm['url']: (self._current_view() or self).load(QUrl(u)) if hasattr(self, '_current_view') else None
                })
        except Exception:
            pass

        def populate(filtered_actions):
            lst.clear()
            for a in filtered_actions:
                item = QListWidgetItem(f"{a['name']}  —  {a.get('desc','')}")
                item.setData(Qt.ItemDataRole.UserRole, a)
                lst.addItem(item)

        def filter_actions():
            txt = filter_edit.text().lower().strip()
            if not txt:
                populate(actions)
                return
            filtered = [a for a in actions if txt in a['name'].lower() or txt in a.get('desc','').lower()]
            populate(filtered)

        filter_edit.textChanged.connect(filter_actions)
        populate(actions)

        def execute(item):
            if item:
                a = item.data(Qt.ItemDataRole.UserRole)
                dlg.accept()
                fn = a.get('fn')
                if callable(fn):
                    try:
                        fn()
                    except Exception as e:
                        self.status.showMessage(f"Action error: {e}", 3000)

        lst.itemDoubleClicked.connect(execute)
        filter_edit.returnPressed.connect(lambda: execute(lst.currentItem()) if lst.currentItem() else None)

        # Help text
        help_lbl = QLabel("Enter to run • Double-click • Esc to close • Filters actions + bookmarks")
        help_lbl.setStyleSheet("color:#808090; font-size:11px;")
        layout.addWidget(help_lbl)

        # Focus filter for immediate typing
        filter_edit.setFocus()
        dlg.exec()

    def _update_tunnel_ui_state(self):
        """Show or hide the prominent tunnel warning bar and enable/disable sensitive UI."""
        if self._tunnel_ready:
            self.tunnel_bar.hide()
            self.btn_restart_tunnel.setEnabled(True)
            self.egress_refresh_btn.setEnabled(True)
            # Re-enable basic nav if they were disabled
            if v := self._current_view():
                self.btn_back.setEnabled(v.history().canGoBack())
                self.btn_forward.setEnabled(v.history().canGoForward())
            self.btn_reload.setEnabled(True)
        else:
            self.tunnel_bar.show()
            self.btn_restart_tunnel.setEnabled(True)
            self.egress_refresh_btn.setEnabled(False)
            self.egress_label.setText("Egress: —")
            self.egress_label.setStyleSheet("color:#808090; font-size:11px; padding:0 6px;")
            # Optionally disable risky actions while tunnel is down
            self.btn_back.setEnabled(False)
            self.btn_forward.setEnabled(False)
            self.btn_reload.setEnabled(False)

    # ── Settings dialog ──────────────────────────────────────────────────

    def _show_settings(self):
        global TARGET_URL, APP_DISGUISE, SEARCH_ENGINE, VM_IP, VM_USER, KEY_PATH

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

        # CONNECTION for profiles / F
        vm_edit = QLineEdit(VM_IP)
        user_edit = QLineEdit(VM_USER)
        key_edit = QLineEdit(KEY_PATH)

        form.addRow("Home URL:", url_edit)
        form.addRow("App Name:", name_edit)
        form.addRow("Local Port:", port_spin)
        form.addRow("Search Engine:", engine_combo)
        form.addRow("Jump Host IP:", vm_edit)
        form.addRow("SSH User:", user_edit)
        form.addRow("Key Path:", key_edit)

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

            VM_IP = vm_edit.text().strip() or VM_IP
            VM_USER = user_edit.text().strip() or VM_USER
            KEY_PATH = key_edit.text().strip() or KEY_PATH

            config["BROWSER"]["home_url"]      = TARGET_URL
            config["BROWSER"]["app_name"]      = APP_DISGUISE
            config["BROWSER"]["local_port"]    = str(port_spin.value())
            config["BROWSER"]["search_engine"] = SEARCH_ENGINE
            if "CONNECTION" not in config:
                config["CONNECTION"] = {}
            config["CONNECTION"]["vm_ip"] = VM_IP
            config["CONNECTION"]["vm_user"] = VM_USER
            config["CONNECTION"]["key_path"] = KEY_PATH
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
        event.accept()


# ============================================================
#  Entry Point
# ============================================================
if __name__ == "__main__":
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    configure_proxy_early()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISGUISE)
    app.setApplicationVersion("1.0.0")

    window = TunnelFoxBrowser()
    window.show()
    sys.exit(app.exec())