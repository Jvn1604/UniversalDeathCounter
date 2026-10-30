"""
"Start with Windows" (and "Open at Login" on macOS, "Start at Login" on Linux).

* Windows: the per-user ``HKCU\\...\\CurrentVersion\\Run`` registry key,
  which is exactly what Task Manager's Startup tab lists.
* macOS: a LaunchAgent in ``~/Library/LaunchAgents``.
* Linux: a ``.desktop`` file in ``~/.config/autostart`` (the freedesktop
  standard every desktop follows).

The OS entry itself is the source of truth (no copy in the settings table),
so turning the app off from Task Manager or the desktop's own settings is
reflected in the Settings dialog too.

Only available for the packaged app: a source checkout has no stable
command line to register.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import sys
from pathlib import Path

from src.utils.constants import APP_NAME, APP_ORG
from src.utils.logger import get_logger
from src.utils.platform_info import IS_MAC, IS_WINDOWS

if IS_WINDOWS:
    import winreg

logger = get_logger(__name__)

RUN_KEY: str = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Registry value name: a fixed internal id, so renaming the app's display
# name never orphans an existing start-with-Windows entry.
RUN_VALUE_NAME: str = APP_ORG
MAC_AGENT_LABEL: str = "com.dephantom.universaldeathcounter"


def startup_supported() -> bool:
    """True when running as the packaged app."""
    return bool(getattr(sys, "frozen", False))


def _executable() -> str:
    # An AppImage runs from a temporary mount; $APPIMAGE is the file itself.
    return os.environ.get("APPIMAGE") or sys.executable


def startup_command() -> str:
    """The command line the OS should run at login."""
    return f'"{_executable()}"'


def login_file() -> Path:
    """macOS / Linux: the file that makes the app start at login."""
    if IS_MAC:
        return Path.home() / "Library" / "LaunchAgents" / f"{MAC_AGENT_LABEL}.plist"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "autostart" / f"{APP_ORG.lower()}.desktop"


def _login_file_contents(executable: str) -> bytes:
    if IS_MAC:
        return plistlib.dumps(
            {"Label": MAC_AGENT_LABEL, "ProgramArguments": [executable], "RunAtLoad": True}
        )
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={shlex.quote(executable)}\n"
        "X-GNOME-Autostart-enabled=true\n"
    ).encode()


def _registered_command(key_path: str) -> str | None:
    if not IS_WINDOWS:
        try:
            return login_file().read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return None


def is_enabled(key_path: str = RUN_KEY) -> bool:
    """Whether the app is registered to start at login."""
    return _registered_command(key_path) is not None


def set_enabled(enabled: bool, key_path: str = RUN_KEY, command: str | None = None) -> None:
    """
    Register or unregister the app to start at login.

    Raises:
        OSError: If the registry or the login file cannot be written.
    """
    if not IS_WINDOWS:
        path = login_file()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_login_file_contents(command or _executable()))
            logger.info("Enabled start at login (%s)", path)
        elif path.exists():
            path.unlink()
            logger.info("Disabled start at login")
        return
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, command or startup_command())
        logger.info("Enabled start with Windows")
    elif _registered_command(key_path) is not None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
        logger.info("Disabled start with Windows")


def refresh_registration(key_path: str = RUN_KEY) -> None:
    """If enabled, point the entry at this app (e.g. after it was moved or updated)."""
    if not startup_supported():
        return
    registered = _registered_command(key_path)
    if IS_WINDOWS:
        current = startup_command()
    else:
        current = _login_file_contents(_executable()).decode()
    if registered is not None and registered != current:
        try:
            set_enabled(True, key_path)
        except OSError:
            logger.warning("Could not update the start-at-login entry", exc_info=True)
