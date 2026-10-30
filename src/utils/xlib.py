"""
The few libX11 calls the app makes on Linux, loaded with ctypes.

Shared by the global hotkeys (key grabs) and auto-detect (finding the
game's window). Xlib's default error handler ends the whole process, so a
handler that only records the error is installed once, before any call;
:func:`take_errors` returns what the calling thread's last requests caused.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import threading

from src.utils.logger import get_logger

logger = get_logger(__name__)

BAD_ACCESS = 10  # a key combo another program has grabbed


class XErrorEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("resourceid", ctypes.c_ulong),
        ("serial", ctypes.c_ulong),
        ("error_code", ctypes.c_ubyte),
        ("request_code", ctypes.c_ubyte),
        ("minor_code", ctypes.c_ubyte),
    ]


_ErrorHandler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(XErrorEvent))
_lib = None
_load_lock = threading.Lock()
_local = threading.local()


@_ErrorHandler
def _record_error(_display, event):
    errors = getattr(_local, "errors", None)
    if errors is None:
        errors = _local.errors = []
    errors.append(event.contents.error_code)
    return 0


def take_errors() -> list[int]:
    """X error codes raised on this thread since the last call."""
    errors = getattr(_local, "errors", None) or []
    _local.errors = []
    return errors


def _declare(lib) -> None:
    c_void_p, c_ulong, c_int, c_uint = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint
    pointer = ctypes.POINTER
    signatures = {
        "XOpenDisplay": (c_void_p, [ctypes.c_char_p]),
        "XCloseDisplay": (c_int, [c_void_p]),
        "XDefaultRootWindow": (c_ulong, [c_void_p]),
        "XSync": (c_int, [c_void_p, c_int]),
        "XFree": (c_int, [c_void_p]),
        "XSetErrorHandler": (c_void_p, [c_void_p]),
        "XConnectionNumber": (c_int, [c_void_p]),
        "XPending": (c_int, [c_void_p]),
        "XNextEvent": (c_int, [c_void_p, c_void_p]),
        "XKeysymToKeycode": (ctypes.c_ubyte, [c_void_p, c_ulong]),
        "XGrabKey": (c_int, [c_void_p, c_int, c_uint, c_ulong, c_int, c_int, c_int]),
        "XUngrabKey": (c_int, [c_void_p, c_int, c_uint, c_ulong]),
        "XkbSetDetectableAutoRepeat": (c_int, [c_void_p, c_int, c_void_p]),
        "XInternAtom": (c_ulong, [c_void_p, ctypes.c_char_p, c_int]),
        "XGetWindowProperty": (c_int, [
            c_void_p, c_ulong, c_ulong, ctypes.c_long, ctypes.c_long, c_int, c_ulong,
            pointer(c_ulong), pointer(c_int), pointer(c_ulong), pointer(c_ulong),
            pointer(c_void_p),
        ]),
        "XGetGeometry": (c_int, [
            c_void_p, c_ulong, pointer(c_ulong), pointer(c_int), pointer(c_int),
            pointer(c_uint), pointer(c_uint), pointer(c_uint), pointer(c_uint),
        ]),
        "XTranslateCoordinates": (c_int, [
            c_void_p, c_ulong, c_ulong, c_int, c_int, pointer(c_int), pointer(c_int),
            pointer(c_ulong),
        ]),
        "XQueryPointer": (c_int, [
            c_void_p, c_ulong, pointer(c_ulong), pointer(c_ulong), pointer(c_int),
            pointer(c_int), pointer(c_int), pointer(c_int), pointer(c_uint),
        ]),
    }
    for name, (restype, argtypes) in signatures.items():
        function = getattr(lib, name)
        function.restype = restype
        function.argtypes = argtypes


def load():
    """libX11 with its prototypes declared; raises OSError if it isn't installed."""
    global _lib
    with _load_lock:
        if _lib is None:
            lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
            _declare(lib)
            lib.XSetErrorHandler(ctypes.cast(_record_error, ctypes.c_void_p))
            _lib = lib
    return _lib


def available() -> bool:
    """An X server is reachable (X11, or XWayland on a Wayland desktop) and libX11 loads."""
    if not os.environ.get("DISPLAY"):
        return False
    try:
        load()
    except OSError:
        return False
    return True


_shared_display = None  # 0 = tried and failed
_display_lock = threading.RLock()


@contextlib.contextmanager
def shared_display():
    """
    The app's one X connection for window queries, or None without X.

    Xlib connections aren't thread-safe, so whoever holds it holds the lock.
    """
    global _shared_display
    with _display_lock:
        if _shared_display is None:
            _shared_display = (load().XOpenDisplay(None) or 0) if available() else 0
            if not _shared_display:
                logger.warning("Could not open the X display %r", os.environ.get("DISPLAY"))
        yield _shared_display or None
