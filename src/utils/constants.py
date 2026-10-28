"""
Application-wide constants for Universal Death Counter.

Centralizing constants here avoids magic numbers/strings scattered
throughout the codebase and makes future configuration changes trivial.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Application metadata
# --------------------------------------------------------------------------
APP_NAME: str = "DePhantom Universal Death Counter"
APP_SHORT_NAME: str = "DUDC"
APP_BRAND: str = "DePhantom"  # big header text; APP_SUBTITLE goes underneath
APP_SUBTITLE: str = "Universal Death Counter (DUDC)"
# APP_ORG (below), the exe name and the data folder intentionally keep the
# old internal name, so existing installs upgrade in place and keep data.
APP_VERSION: str = "2.0.0"
APP_ORG: str = "UniversalDeathCounter"

# GitHub repository ("owner/repo") used by the update checker. Edit this
# to match the actual repository the project is published under.
GITHUB_REPO: str = "Jvn1604/UniversalDeathCounter"

# --------------------------------------------------------------------------
# Filesystem paths
# --------------------------------------------------------------------------
# When running from source, PROJECT_ROOT is the repo root and everything
# (including saves/) lives inside it, as it always has.
#
# When frozen by PyInstaller, `__file__` resolves inside a temporary
# extraction directory (sys._MEIPASS) that is wiped after the process
# exits. Bundled *read-only* resources (themes, icons) are fine to read
# from there, but user data (the SQLite DB, logs) MUST live somewhere
# persistent, or every session would silently lose its history. For a
# frozen build we therefore store data next to the executable if that
# location is writable, falling back to the user's per-app data folder
# (%APPDATA% on Windows, ~/.local/share elsewhere) otherwise.


def _is_frozen() -> bool:
    """Return True if running as a PyInstaller-frozen executable."""
    return bool(getattr(sys, "frozen", False))


def _resolve_persistent_data_dir() -> Path:
    """Choose a writable, persistent directory for the database and logs."""
    if not _is_frozen():
        return PROJECT_ROOT / "saves"

    exe_dir = Path(sys.executable).resolve().parent
    try:
        candidate = exe_dir / "saves"
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write_test"
        probe.touch()
        probe.unlink()
        return candidate
    except OSError:
        # Installed to a protected location (e.g. Program Files); fall back
        # to the standard per-user application data directory instead.
        base = Path(os.environ.get("APPDATA", Path.home() / ".local" / "share"))
        return base / APP_ORG / "saves"


PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
SAVES_DIR: Path = _resolve_persistent_data_dir()
DATABASE_PATH: Path = SAVES_DIR / "death_counter.db"
LOG_DIR: Path = SAVES_DIR / "logs"
LOG_FILE: Path = LOG_DIR / "app.log"

# Bundled read-only resources: safe to resolve relative to PROJECT_ROOT even
# when frozen, since PyInstaller's datas= preserves this relative layout
# inside the (temporary but valid-for-this-run) extraction directory.
THEMES_DIR: Path = PROJECT_ROOT / "src" / "themes"
ICONS_DIR: Path = PROJECT_ROOT / "assets" / "icons"

# --------------------------------------------------------------------------
# Default hotkeys (lower-cased QKeySequence text, e.g. "ctrl+f12")
# --------------------------------------------------------------------------
DEFAULT_HOTKEY_INCREMENT: str = "f9"
DEFAULT_HOTKEY_DECREMENT: str = "f10"
DEFAULT_HOTKEY_UNDO: str = "f11"
DEFAULT_HOTKEY_TOGGLE_OVERLAY: str = "ctrl+f12"  # plain F12 is often taken (Steam, debuggers)
DEFAULT_HOTKEY_CALIBRATE: str = "f8"
DEFAULT_HOTKEY_PAUSE_DETECTION: str = "ctrl+f8"

# --------------------------------------------------------------------------
# Settings keys (used in the `settings` table)
# --------------------------------------------------------------------------
SETTING_THEME: str = "theme"
SETTING_OVERLAY_FONT_SIZE: str = "overlay_font_size"
SETTING_OVERLAY_OPACITY: str = "overlay_opacity"
SETTING_OVERLAY_ALWAYS_ON_TOP: str = "overlay_always_on_top"
SETTING_HOTKEY_INCREMENT: str = "hotkey_increment"
SETTING_HOTKEY_DECREMENT: str = "hotkey_decrement"
SETTING_HOTKEY_UNDO: str = "hotkey_undo"
SETTING_HOTKEY_TOGGLE_OVERLAY: str = "hotkey_toggle_overlay"
SETTING_LAST_GAME_ID: str = "last_game_id"
SETTING_LAST_BOSS_ID: str = "last_boss_id"
SETTING_OVERLAY_GEOMETRY: str = "overlay_geometry"
SETTING_MAIN_WINDOW_GEOMETRY: str = "main_window_geometry"  # Qt saveGeometry, base64

# --- v1.5 overlay & streaming ---
SETTING_OVERLAY_BG_MODE: str = "overlay_bg_mode"  # "dark" | "chroma"
SETTING_OVERLAY_TEXT_COLOR: str = "overlay_text_color"
SETTING_OVERLAY_COUNTER_SOURCE: str = "overlay_counter_source"  # session|boss|total
SETTING_OVERLAY_SHOW_GAME: str = "overlay_show_game"
SETTING_OVERLAY_SHOW_BOSS: str = "overlay_show_boss"
SETTING_OVERLAY_SHOW_STATS: str = "overlay_show_stats"
SETTING_DEATHS_TXT_ENABLED: str = "deaths_txt_enabled"
SETTING_DEATHS_TXT_PATH: str = "deaths_txt_path"
SETTING_DEATHS_TXT_TEMPLATE: str = "deaths_txt_template"

# --- v1.5 quality of life ---
SETTING_MINIMIZE_TO_TRAY: str = "minimize_to_tray"
SETTING_CHECK_UPDATES: str = "check_updates"

# --- auto death detection ---
SETTING_HOTKEY_CALIBRATE: str = "hotkey_calibrate"
SETTING_HOTKEY_PAUSE_DETECTION: str = "hotkey_pause_detection"


# Every bindable action: (action name, label, keyboard setting, default key).
# Controller bindings are stored under "pad_<action>" (unbound by default,
# since controller presses also reach the game).
CONTROL_ACTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("increment", "+1 Death", SETTING_HOTKEY_INCREMENT, DEFAULT_HOTKEY_INCREMENT),
    ("decrement", "-1 Death", SETTING_HOTKEY_DECREMENT, DEFAULT_HOTKEY_DECREMENT),
    ("undo", "Undo", SETTING_HOTKEY_UNDO, DEFAULT_HOTKEY_UNDO),
    (
        "toggle_overlay",
        "Toggle Overlay",
        SETTING_HOTKEY_TOGGLE_OVERLAY,
        DEFAULT_HOTKEY_TOGGLE_OVERLAY,
    ),
    ("calibrate", "Calibrate Death Screen", SETTING_HOTKEY_CALIBRATE, DEFAULT_HOTKEY_CALIBRATE),
    (
        "pause_detection",
        "Pause Auto-Detect",
        SETTING_HOTKEY_PAUSE_DETECTION,
        DEFAULT_HOTKEY_PAUSE_DETECTION,
    ),
)


def pad_setting(action: str) -> str:
    """Settings key holding an action's controller combo."""
    return f"pad_{action}"
SETTING_DETECTION_COOLDOWN: str = "detection_cooldown"  # seconds between deaths

# Per-game detection modes (stored in the game_detection table)
DETECTION_MODE_OFF: str = "off"
DETECTION_MODE_TEMPLATE: str = "template"  # calibrated death screen, any game
DETECTION_MODE_SOULS: str = "souls"  # built-in red "YOU DIED" preset

# --------------------------------------------------------------------------
# Default settings values
# --------------------------------------------------------------------------
DEFAULT_SETTINGS: dict[str, str] = {
    SETTING_THEME: "dark",
    SETTING_OVERLAY_FONT_SIZE: "24",
    SETTING_OVERLAY_OPACITY: "0.85",
    SETTING_OVERLAY_ALWAYS_ON_TOP: "true",
    SETTING_HOTKEY_INCREMENT: DEFAULT_HOTKEY_INCREMENT,
    SETTING_HOTKEY_DECREMENT: DEFAULT_HOTKEY_DECREMENT,
    SETTING_HOTKEY_UNDO: DEFAULT_HOTKEY_UNDO,
    SETTING_HOTKEY_TOGGLE_OVERLAY: DEFAULT_HOTKEY_TOGGLE_OVERLAY,
    SETTING_LAST_GAME_ID: "",
    SETTING_LAST_BOSS_ID: "",
    SETTING_OVERLAY_GEOMETRY: "",
    SETTING_OVERLAY_BG_MODE: "dark",
    SETTING_OVERLAY_TEXT_COLOR: "#ff4d4d",
    SETTING_OVERLAY_COUNTER_SOURCE: "session",
    SETTING_OVERLAY_SHOW_GAME: "true",
    SETTING_OVERLAY_SHOW_BOSS: "true",
    SETTING_OVERLAY_SHOW_STATS: "true",
    SETTING_DEATHS_TXT_ENABLED: "false",
    SETTING_DEATHS_TXT_PATH: "",  # empty = SAVES_DIR/deaths.txt
    SETTING_DEATHS_TXT_TEMPLATE: "{game} - {boss}: {deaths}",
    SETTING_MINIMIZE_TO_TRAY: "false",
    SETTING_CHECK_UPDATES: "true",
    SETTING_HOTKEY_CALIBRATE: DEFAULT_HOTKEY_CALIBRATE,
    SETTING_HOTKEY_PAUSE_DETECTION: DEFAULT_HOTKEY_PAUSE_DETECTION,
    SETTING_DETECTION_COOLDOWN: "8",
}

# --------------------------------------------------------------------------
# UI styling
# --------------------------------------------------------------------------
ACCENT_COLOR: str = "#ff4d4d"
AVAILABLE_THEMES: list[str] = ["dark", "light"]
