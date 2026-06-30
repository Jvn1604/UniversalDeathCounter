"""
Application-wide constants for Universal Death Counter.

Centralizing constants here avoids magic numbers/strings scattered
throughout the codebase and makes future configuration changes trivial.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Application metadata
# --------------------------------------------------------------------------
APP_NAME: str = "Universal Death Counter"
APP_VERSION: str = "1.0.0"
APP_ORG: str = "UniversalDeathCounter"

# --------------------------------------------------------------------------
# Filesystem paths
# --------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
SAVES_DIR: Path = PROJECT_ROOT / "saves"
DATABASE_PATH: Path = SAVES_DIR / "death_counter.db"
LOG_DIR: Path = SAVES_DIR / "logs"
LOG_FILE: Path = LOG_DIR / "app.log"
THEMES_DIR: Path = PROJECT_ROOT / "src" / "themes"
ICONS_DIR: Path = PROJECT_ROOT / "assets" / "icons"

# --------------------------------------------------------------------------
# Default hotkeys (keyboard library syntax)
# --------------------------------------------------------------------------
DEFAULT_HOTKEY_INCREMENT: str = "f9"
DEFAULT_HOTKEY_DECREMENT: str = "f10"
DEFAULT_HOTKEY_UNDO: str = "f11"
DEFAULT_HOTKEY_TOGGLE_OVERLAY: str = "f12"

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
SETTING_AUTOSAVE: str = "autosave"
SETTING_LAUNCH_ON_STARTUP: str = "launch_on_startup"
SETTING_LAST_GAME_ID: str = "last_game_id"
SETTING_LAST_BOSS_ID: str = "last_boss_id"
SETTING_OVERLAY_GEOMETRY: str = "overlay_geometry"

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
    SETTING_AUTOSAVE: "true",
    SETTING_LAUNCH_ON_STARTUP: "false",
    SETTING_LAST_GAME_ID: "",
    SETTING_LAST_BOSS_ID: "",
    SETTING_OVERLAY_GEOMETRY: "",
}

# --------------------------------------------------------------------------
# UI styling
# --------------------------------------------------------------------------
ACCENT_COLOR: str = "#ff4d4d"
AVAILABLE_THEMES: list[str] = ["dark", "light"]
