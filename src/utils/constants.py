"""
Application-wide constants for Universal Death Counter.

Centralizing constants here avoids magic numbers/strings scattered
throughout the codebase and makes future configuration changes trivial.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.utils.platform_info import IS_WINDOWS, user_data_dir

# --------------------------------------------------------------------------
# Application metadata
# --------------------------------------------------------------------------
APP_NAME: str = "DePhantom Universal Death Counter"
APP_SHORT_NAME: str = "DUDC"
APP_BRAND: str = "DePhantom"  # big header text; APP_SUBTITLE goes underneath
APP_SUBTITLE: str = "Universal Death Counter (DUDC)"
# APP_ORG (below), the exe name and the data folder intentionally keep the
# old internal name, so existing installs upgrade in place and keep data.
APP_VERSION: str = "2.13.0"
APP_ORG: str = "UniversalDeathCounter"

# GitHub repository ("owner/repo") used by the update checker. Edit this
# to match the actual repository the project is published under.
GITHUB_REPO: str = "Jvn1604/UniversalDeathCounter"
# The maker, credited in the sidebar and About.
CREATOR_NAME: str = "DePhantom"
CREATOR_CHANNEL_URL: str = "https://www.youtube.com/@ImDePhantom"

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
# frozen Windows build we therefore store data next to the executable if
# that location is writable, falling back to %APPDATA% otherwise. A macOS
# .app and a Linux AppImage are read-only (and replaced on update), so they
# always use the per-user folder (~/Library/Application Support, or
# ~/.local/share).


def _is_frozen() -> bool:
    """Return True if running as a PyInstaller-frozen executable."""
    return bool(getattr(sys, "frozen", False))


def _resolve_persistent_data_dir() -> Path:
    """Choose a writable, persistent directory for the database and logs."""
    if not _is_frozen():
        return PROJECT_ROOT / "saves"
    if not IS_WINDOWS:
        return user_data_dir(APP_ORG) / "saves"

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
        return user_data_dir(APP_ORG) / "saves"


PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
SAVES_DIR: Path = _resolve_persistent_data_dir()
DATABASE_PATH: Path = SAVES_DIR / "death_counter.db"
LOG_DIR: Path = SAVES_DIR / "logs"
# Copies of the images picked as backgrounds, so moving the original is harmless.
BACKGROUNDS_DIR: Path = SAVES_DIR / "backgrounds"
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
DEFAULT_HOTKEY_PREV_BOSS: str = "ctrl+f9"
DEFAULT_HOTKEY_NEXT_BOSS: str = "ctrl+f10"
DEFAULT_HOTKEY_BOSS_DEFEATED: str = "ctrl+f11"
# Speedrun timer: LiveSplit's numpad layout (needs Num Lock on).
DEFAULT_HOTKEY_TIMER_SPLIT: str = "num+1"
DEFAULT_HOTKEY_TIMER_PAUSE: str = "num+5"
DEFAULT_HOTKEY_TIMER_RESET: str = "num+3"
DEFAULT_HOTKEY_TIMER_UNDO: str = "num+8"
DEFAULT_HOTKEY_TIMER_SKIP: str = "num+2"

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
# Main-window colors; "" means the theme's own color.
SETTING_UI_TEXT_COLOR: str = "ui_text_color"
SETTING_UI_COUNTER_COLOR: str = "ui_counter_color"
SETTING_UI_FONT: str = "ui_font"  # font family; "" = the theme's
SETTING_UI_BG_IMAGE: str = "ui_background_image"  # path in BACKGROUNDS_DIR; "" = none
SETTING_UI_BG_DIM: str = "ui_background_dim"  # 0-90: % of theme color laid over the image

# --- overlay appearance ---
SETTING_OVERLAY_FONT: str = "overlay_font"  # "" = the app's default font
SETTING_OVERLAY_CARD_COLOR: str = "overlay_card_color"  # "" = near-black
SETTING_OVERLAY_SECONDARY_COLOR: str = "overlay_secondary_color"  # "" = automatic
SETTING_OVERLAY_BG_IMAGE: str = "overlay_background_image"  # used by the "image" background
SETTING_OVERLAY_CORNER_RADIUS: str = "overlay_corner_radius"
SETTING_OVERLAY_TEXT_OUTLINE: str = "overlay_text_outline"  # "true" = shadow behind text
SETTING_OVERLAY_COUNTER_SOURCE: str = "overlay_counter_source"  # session|boss|total
# The big number shows the game's all-time deaths unless the player picks
# otherwise: a session restarts at 0, which looked like lost deaths.
DEFAULT_COUNTER_SOURCE: str = "total"
SETTING_OVERLAY_SHOW_GAME: str = "overlay_show_game"
SETTING_OVERLAY_SHOW_BOSS: str = "overlay_show_boss"
SETTING_OVERLAY_SHOW_STATS: str = "overlay_show_stats"
SETTING_OVERLAY_SHOW_SKULL: str = "overlay_show_skull"  # the evolving skull badge
SETTING_OVERLAY_LOCKED: str = "overlay_locked"  # "true" = can't be dragged
# Console players
SETTING_PHONE_REMOTE: str = "phone_remote_enabled"  # "true" = serve the phone page
SETTING_PHONE_REMOTE_KEY: str = "phone_remote_key"  # secret part of the phone link
# Detection option: watch the window of the game's .exe whose title contains this.
OPTION_WINDOW_TITLE: str = "window_title"
# Detection option: read this OBS source (a capture card) instead of a window.
OPTION_OBS_SOURCE: str = "obs_source"
SETTING_OBS_HOST: str = "obs_host"
SETTING_OBS_PORT: str = "obs_port"
SETTING_OBS_PASSWORD: str = "obs_password"  # OBS's WebSocket password (local only)
SETTING_DEATHS_TXT_ENABLED: str = "deaths_txt_enabled"
SETTING_DEATHS_TXT_PATH: str = "deaths_txt_path"
SETTING_DEATHS_TXT_TEMPLATE: str = "deaths_txt_template"

# --- v1.5 quality of life ---
SETTING_MINIMIZE_TO_TRAY: str = "minimize_to_tray"
SETTING_CONFIRM_CLOSE: str = "confirm_close"
SETTING_SIDEBAR_COLLAPSED: str = "sidebar_collapsed"
SETTING_CHECK_UPDATES: str = "check_updates"

# --- auto death detection ---
SETTING_HOTKEY_CALIBRATE: str = "hotkey_calibrate"
SETTING_HOTKEY_PAUSE_DETECTION: str = "hotkey_pause_detection"
SETTING_HOTKEY_PREV_BOSS: str = "hotkey_prev_boss"
SETTING_HOTKEY_NEXT_BOSS: str = "hotkey_next_boss"
SETTING_HOTKEY_BOSS_DEFEATED: str = "hotkey_boss_defeated"
# Boss kills: detected from saved victory screens, or the Boss Defeated key.
SETTING_BOSS_DETECTION: str = "boss_detection"
SETTING_BOSS_AUTO_ADVANCE: str = "boss_auto_advance"  # select the next boss
SETTING_BOSS_AUTO_SPLIT: str = "boss_auto_split"  # split a running speedrun
SETTING_HOTKEY_TIMER_SPLIT: str = "hotkey_timer_split"
SETTING_HOTKEY_TIMER_PAUSE: str = "hotkey_timer_pause"
SETTING_HOTKEY_TIMER_RESET: str = "hotkey_timer_reset"
SETTING_HOTKEY_TIMER_UNDO: str = "hotkey_timer_undo"
SETTING_HOTKEY_TIMER_SKIP: str = "hotkey_timer_skip"
SETTING_TIMER_GEOMETRY: str = "timer_geometry"
SETTING_TIMER_VISIBLE: str = "timer_visible"
SETTING_MINI_GEOMETRY: str = "mini_geometry"  # compact mini mode window
SETTING_WELCOME_SHOWN: str = "welcome_shown"  # "true" once the first-run guide closed
SETTING_QUICK_START_HIDDEN: str = "quick_start_hidden"  # Home's "getting started" banner
SETTING_OVERLAY_EVER_SHOWN: str = "overlay_ever_shown"  # ticks the guide's stream step
SETTING_TIMER_METHOD: str = "timer_method"  # "real" | "game"
SETTING_TIMER_COMPARISON: str = "timer_comparison"  # "pb" | "previous" | "best"
SETTING_TIMER_DIGITS: str = "timer_digits"  # decimals: 0-3 (3 = milliseconds)
# Auto-pause: the game closing/crashing pauses the whole timer; the rest
# only stop game time (real time keeps running, as in LiveSplit).
SETTING_TIMER_PAUSE_ON_CLOSE: str = "timer_pause_on_close"
SETTING_TIMER_PAUSE_NOT_RESPONDING: str = "timer_pause_not_responding"
SETTING_TIMER_PAUSE_LOADING: str = "timer_pause_loading"
SETTING_TIMER_PAUSE_SCREENS: str = "timer_pause_screens"
SETTING_TIMER_PAUSE_BACKGROUND: str = "timer_pause_background"
# JSON snapshot of the run in progress, rewritten every few seconds; left
# behind only if the app didn't close normally (crash recovery).
SETTING_TIMER_AUTOSAVE: str = "timer_autosave"


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
    ("prev_boss", "Previous Boss", SETTING_HOTKEY_PREV_BOSS, DEFAULT_HOTKEY_PREV_BOSS),
    ("next_boss", "Next Boss", SETTING_HOTKEY_NEXT_BOSS, DEFAULT_HOTKEY_NEXT_BOSS),
    (
        "boss_defeated",
        "Boss Defeated",
        SETTING_HOTKEY_BOSS_DEFEATED,
        DEFAULT_HOTKEY_BOSS_DEFEATED,
    ),
    (
        "timer_split",
        "Timer: Start / Split",
        SETTING_HOTKEY_TIMER_SPLIT,
        DEFAULT_HOTKEY_TIMER_SPLIT,
    ),
    ("timer_pause", "Timer: Pause", SETTING_HOTKEY_TIMER_PAUSE, DEFAULT_HOTKEY_TIMER_PAUSE),
    ("timer_reset", "Timer: Reset", SETTING_HOTKEY_TIMER_RESET, DEFAULT_HOTKEY_TIMER_RESET),
    ("timer_undo", "Timer: Undo Split", SETTING_HOTKEY_TIMER_UNDO, DEFAULT_HOTKEY_TIMER_UNDO),
    ("timer_skip", "Timer: Skip Split", SETTING_HOTKEY_TIMER_SKIP, DEFAULT_HOTKEY_TIMER_SKIP),
)


def pad_setting(action: str) -> str:
    """Settings key holding an action's controller combo."""
    return f"pad_{action}"
SETTING_DETECTION_COOLDOWN: str = "detection_cooldown"  # seconds between deaths

# Per-game detection modes (stored in the game_detection table)
DETECTION_MODE_OFF: str = "off"
DETECTION_MODE_TEMPLATE: str = "template"  # calibrated death screen, any game
DETECTION_MODE_SOULS: str = "souls"  # built-in red "YOU DIED" preset
DETECTION_MODE_HEALTH: str = "health"  # calibrated health bar emptying
DETECTION_MODE_LOG: str = "log"  # death lines appended to a game log file

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
    SETTING_OVERLAY_COUNTER_SOURCE: DEFAULT_COUNTER_SOURCE,
    SETTING_OVERLAY_SHOW_GAME: "true",
    SETTING_OVERLAY_SHOW_BOSS: "true",
    SETTING_OVERLAY_SHOW_STATS: "true",
    SETTING_OVERLAY_SHOW_SKULL: "true",
    SETTING_DEATHS_TXT_ENABLED: "false",
    SETTING_DEATHS_TXT_PATH: "",  # empty = SAVES_DIR/deaths.txt
    SETTING_DEATHS_TXT_TEMPLATE: "{game} - {boss}: {deaths}",
    SETTING_MINIMIZE_TO_TRAY: "false",
    SETTING_CONFIRM_CLOSE: "true",
    SETTING_CHECK_UPDATES: "true",
    SETTING_HOTKEY_CALIBRATE: DEFAULT_HOTKEY_CALIBRATE,
    SETTING_HOTKEY_PAUSE_DETECTION: DEFAULT_HOTKEY_PAUSE_DETECTION,
    SETTING_DETECTION_COOLDOWN: "8",
    SETTING_BOSS_DETECTION: "true",
    SETTING_BOSS_AUTO_ADVANCE: "true",
    SETTING_BOSS_AUTO_SPLIT: "true",
    SETTING_TIMER_METHOD: "real",
    SETTING_TIMER_COMPARISON: "pb",
    SETTING_TIMER_DIGITS: "2",
    SETTING_TIMER_PAUSE_ON_CLOSE: "true",
    SETTING_TIMER_PAUSE_NOT_RESPONDING: "true",
    SETTING_TIMER_PAUSE_LOADING: "true",
    SETTING_TIMER_PAUSE_SCREENS: "true",
    SETTING_TIMER_PAUSE_BACKGROUND: "false",
}

# --------------------------------------------------------------------------
# UI styling
# --------------------------------------------------------------------------
ACCENT_COLOR: str = "#ff4d4d"
