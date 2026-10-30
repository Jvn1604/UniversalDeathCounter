"""
Which operating system the app runs on, and the few things that differ.

Windows, macOS and Linux share all of the app except the parts that talk
to the OS directly (global hotkeys, finding the game's window, controllers,
start at login). Those modules pick their backend from the flags here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS: bool = sys.platform == "win32"
IS_MAC: bool = sys.platform == "darwin"
IS_LINUX: bool = sys.platform.startswith("linux")


def is_wayland() -> bool:
    """A Linux Wayland session, where apps can't see or capture other windows."""
    return IS_LINUX and (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )


def has_x11_display() -> bool:
    """An X11 server (or XWayland) is reachable, so X11 calls can work."""
    return IS_LINUX and bool(os.environ.get("DISPLAY"))


def user_data_dir(app_folder: str) -> Path:
    """The per-user folder for app data on this OS."""
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / app_folder


def login_item_label() -> str:
    """What the "start when the computer starts" option is called here."""
    if IS_WINDOWS:
        return "Start with Windows"
    if IS_MAC:
        return "Open at Login"
    return "Start at Login"


def program_file_filter() -> str:
    """File dialog filter for picking a game."""
    if IS_WINDOWS:
        return "Programs (*.exe)"
    if IS_MAC:
        return "Apps (*.app);;Windows games (*.exe);;All files (*)"
    return "All files (*);;Windows games (*.exe)"
