import sys
import os
import configparser
from pathlib import Path

# ============================================================
#  TunnelFox v0.1  —  Load config.ini
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

config = configparser.ConfigParser()
config.read(CONFIG_PATH)

TARGET_URL   = config.get("BROWSER", "home_url",  fallback="https://google.com")
APP_DISGUISE = config.get("BROWSER", "app_name",  fallback="NotepadHelper")
PROXY_HOST   = "127.0.0.1"
PROXY_PORT   = config.getint("BROWSER", "local_port", fallback=1080)

if __name__ == "__main__":
    print(f"TunnelFox starting — target: {TARGET_URL}")
    print(f"Proxy: {PROXY_HOST}:{PROXY_PORT}")
