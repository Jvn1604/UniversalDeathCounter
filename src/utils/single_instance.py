"""
Allow one running copy of the app.

Two copies would fight over the global hotkeys (the second gets none) and
write the same database. A named Windows mutex marks the first copy; a
second launch brings that copy's window forward instead and exits.
"""

from __future__ import annotations

import os
import sys

from src.utils.logger import get_logger

logger = get_logger(__name__)

MUTEX_NAME = "Local\\DePhantomUniversalDeathCounter"
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9
_handle: int | None = None  # held for the life of the process


def acquire(name: str = MUTEX_NAME) -> bool:
    """Claim the one-copy lock; False if another running copy holds it."""
    global _handle
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        logger.warning("Could not create the single-instance lock; allowing this copy")
        return True
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _handle = handle
    return True


def release() -> None:
    """Give the lock back (normally the process exiting does this)."""
    global _handle
    if _handle is not None and sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.CloseHandle(_handle)
    _handle = None


def bring_existing_to_front(title_prefix: str) -> bool:
    """
    Restore and focus the other copy's main window.

    Returns False if it has no visible window (e.g. it's minimized to the tray).
    """
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []
    own_pid = os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own_pid:
            return True
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buffer, 256)
        if buffer.value.startswith(title_prefix):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return False
    user32.ShowWindow(found[0], _SW_RESTORE)
    user32.SetForegroundWindow(found[0])
    return True
