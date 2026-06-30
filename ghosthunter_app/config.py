from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

APP_NAME = "Ghost Hunter Pro"
APP_VERSION = "2.3.8"
APP_CREATOR = "TheMarch88"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    RUN_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    RUN_DIR = BASE_DIR


def _is_portable_mode() -> bool:
    # Manual override: create an empty file called `portable.mode`
    # next to the EXE/script to force local self-contained storage.
    if (RUN_DIR / "portable.mode").exists():
        return True

    # Source/dev runs should stay self-contained in the project folder.
    if not getattr(sys, "frozen", False):
        return True

    lowered = str(RUN_DIR).lower()
    # Installed copies under Program Files should use AppData because that
    # location is writable and won't break updates/permissions.
    if "program files" in lowered or lowered.startswith(r"c:\windows"):
        return False

    # Default for unpacked/portable EXEs: keep data near the executable.
    return True


PORTABLE_MODE = _is_portable_mode()
LOCALAPPDATA_BASE = os.environ.get("LOCALAPPDATA")
ROAMINGAPPDATA_BASE = os.environ.get("APPDATA")

if PORTABLE_MODE:
    DATA_DIR = RUN_DIR / ".ghosthunter_data"
else:
    APPDATA_BASE = LOCALAPPDATA_BASE or ROAMINGAPPDATA_BASE or str(RUN_DIR)
    DATA_DIR = Path(APPDATA_BASE) / "GhostHunterPro"

LEGACY_DATA_DIR = (Path(ROAMINGAPPDATA_BASE) / "GhostHunterPro") if ROAMINGAPPDATA_BASE else None
DATA_DIR.mkdir(parents=True, exist_ok=True)

if os.name == "nt":
    try:
        FILE_ATTRIBUTE_HIDDEN = 0x02
        ctypes.windll.kernel32.SetFileAttributesW(str(DATA_DIR), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass

STATE_FILE = DATA_DIR / "ghosthunter_state.json"
STEAM_CACHE_FILE = DATA_DIR / "ghosthunter_appcache.json"
PCGW_CACHE_FILE = DATA_DIR / "ghosthunter_pcgw_cache.json"
LOG_FILE = DATA_DIR / "ghosthunter_debug.log"

LEGACY_STATE_FILE = Path.home() / ".ghost_hunter_state.json"
LEGACY_STEAM_CACHE_FILE = Path.home() / ".ghost_hunter_steam_cache.json"

UI_PATH = BASE_DIR / "ghosthunter_app" / "ui" / "ghost_hunter_ui.html"
DOWNLOADS_DIR = Path.home() / "Downloads" / "GhostHunterPro"

STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"

# Update / release configuration
PUBLISHER = "GhostHunterPro"
APP_EXE_NAME = "GhostHunterPro.exe"
INSTALLER_BASENAME = "GhostHunterPro-Setup"
PORTABLE_BASENAME = "GhostHunterPro-Portable"

# GitHub Releases source
UPDATE_REPO_OWNER = "MarchTheDev"
UPDATE_REPO_NAME = "GhostHunterPro-GUI"

GITHUB_REPO_URL = (
    f"https://github.com/{UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}"
    if UPDATE_REPO_OWNER and UPDATE_REPO_NAME else ""
)
UPDATE_CHECK_URL = (
    f"https://api.github.com/repos/{UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}/releases/latest"
    if UPDATE_REPO_OWNER and UPDATE_REPO_NAME else ""
)

DEFAULT_STATE = {
    "archived_appids": [],
    "search_history": [],
    "theme": "neon",
    "font": "inter",
    "custom_theme_color": "#d946ef",
    "custom_theme_presets": [],
}
