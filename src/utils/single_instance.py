"""
Allow one running copy of the app.

Two copies would fight over the global hotkeys (the second gets none) and
write the same database. The first copy holds a lock (a named mutex on
Windows, a locked file on macOS and Linux); a second launch brings that
copy's window forward instead and exits.

On macOS and Linux the first copy also listens on a local socket, so the
second can ask it to show its window (other programs' windows can't be
raised from outside there).
"""

from __future__ import annotations

import contextlib
import os
import socket
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

MUTEX_NAME = "Local\\DePhantomUniversalDeathCounter"
_SOCKET_NAME = "DePhantomUniversalDeathCounter"
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9
_handle: int | None = None  # held for the life of the process
_lock_file = None  # macOS / Linux: the open, locked file
_server = None  # macOS / Linux: (socket, notifier) the second copy knocks on


def _lock_path() -> Path:
    from src.utils.constants import SAVES_DIR

    return SAVES_DIR / ".running.lock"


def acquire(name: str = MUTEX_NAME) -> bool:
    """Claim the one-copy lock; False if another running copy holds it."""
    global _handle
    if sys.platform != "win32":
        return _acquire_file_lock(_lock_path())
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


def _acquire_file_lock(path: Path) -> bool:
    """An exclusive flock, released by the OS when the process exits (even on a crash)."""
    global _lock_file
    import fcntl

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(path, "a+")  # noqa: SIM115 - held open for the app's lifetime
    except OSError:
        logger.warning("Could not create the single-instance lock; allowing this copy")
        return True
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return False
    _lock_file = lock_file
    return True


def release() -> None:
    """Give the lock back (normally the process exiting does this)."""
    global _handle, _lock_file, _server
    if _handle is not None and sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.CloseHandle(_handle)
    _handle = None
    if _lock_file is not None:
        _lock_file.close()
        _lock_file = None
    if _server is not None:
        server, notifier = _server
        notifier.setEnabled(False)
        server.close()
        _server = None


def _socket_path() -> str:
    folder = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    path = os.path.join(folder, f"dudc-{os.getuid()}.sock")
    # Socket paths are limited to 104 bytes on macOS (108 on Linux).
    return path if len(path.encode()) < 100 else f"/tmp/dudc-{os.getuid()}.sock"


def listen_for_others(show_window: Callable[[], None]) -> None:
    """macOS / Linux: call ``show_window`` when a second copy is launched."""
    global _server
    if sys.platform == "win32" or _server is not None:
        return
    from PySide6.QtCore import QSocketNotifier

    path = _socket_path()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)  # left behind by a crash; we hold the lock, so it's ours
        server.bind(path)
        server.listen(4)
        server.setblocking(False)
    except OSError:
        logger.warning("Could not listen for other copies", exc_info=True)
        server.close()
        return

    def on_knock() -> None:
        with contextlib.suppress(OSError):
            connection, _ = server.accept()
            connection.close()
            show_window()

    notifier = QSocketNotifier(server.fileno(), QSocketNotifier.Type.Read)
    notifier.activated.connect(on_knock)
    _server = (server, notifier)


def bring_existing_to_front(title_prefix: str) -> bool:
    """
    Restore and focus the other copy's main window.

    Returns False if it has no visible window (e.g. it's minimized to the tray).
    """
    if sys.platform != "win32":
        return _knock_on_first_copy()
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


def _knock_on_first_copy() -> bool:
    knock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    knock.settimeout(1.0)
    try:
        knock.connect(_socket_path())
        return True
    except OSError:
        return False
    finally:
        knock.close()
