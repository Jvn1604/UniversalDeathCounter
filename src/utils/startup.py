"""
"Start with Windows" support.

Uses the per-user ``HKCU\\...\\CurrentVersion\\Run`` registry key, which is
exactly what Task Manager's Startup tab lists. The registry itself is the
source of truth (no copy in the settings table), so disabling the app from
Task Manager is reflected in the Settings dialog too.

Only available for the packaged .exe: a source checkout has no stable
command line to register.
"""

from __future__ import annotations

import sys

from src.utils.constants import APP_NAME
from src.utils.logger import get_logger

if sys.platform == "win32":
    import winreg

logger = get_logger(__name__)

RUN_KEY: str = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup_supported() -> bool:
    """True when running as a packaged Windows executable."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def startup_command() -> str:
    """The command line Windows should run at login."""
    return f'"{sys.executable}"'


def _registered_command(key_path: str) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return str(value)
    except FileNotFoundError:
        return None


def is_enabled(key_path: str = RUN_KEY) -> bool:
    """Whether the app is registered to start at login."""
    if sys.platform != "win32":
        return False
    return _registered_command(key_path) is not None


def set_enabled(enabled: bool, key_path: str = RUN_KEY, command: str | None = None) -> None:
    """
    Register or unregister the app to start at login.

    Raises:
        OSError: If the registry cannot be written.
    """
    if sys.platform != "win32":
        return
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command or startup_command())
        logger.info("Enabled start with Windows")
    elif _registered_command(key_path) is not None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        logger.info("Disabled start with Windows")


def refresh_registration(key_path: str = RUN_KEY) -> None:
    """If enabled, point the entry at this exe (e.g. after the app was moved or updated)."""
    if not startup_supported():
        return
    registered = _registered_command(key_path)
    if registered is not None and registered != startup_command():
        try:
            set_enabled(True, key_path)
        except OSError:
            logger.warning("Could not update the start-with-Windows entry", exc_info=True)
