"""
Finding windows on Linux through X11 (libX11 via ctypes, no dependency).

Reads the window manager's standard (EWMH) properties: the list of
top-level windows, each one's process id and title, the active window and
whether a window is minimized. Games running through Proton or Wine are
X11 windows, so this also finds them on a Wayland desktop (via XWayland).

Every function returns nothing useful (``[]`` / ``None``) without X.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from src.utils import xlib

Rect = tuple[int, int, int, int]

_ANY_TYPE = 0
_SUCCESS = 0
_MAX_ITEMS = 4096


@dataclass(frozen=True)
class NativeWindow:
    handle: int
    pid: int
    title: str
    rect: Rect | None  # None while minimized


def available() -> bool:
    return xlib.available()


def _atom(lib, display, name: str) -> int:
    return lib.XInternAtom(display, name.encode(), 0)


def _property(lib, display, window: int, name: str) -> tuple[int, int, bytes] | None:
    """(format, item count, raw data) of a window property, or None."""
    actual_type, actual_format = ctypes.c_ulong(), ctypes.c_int()
    count, remaining, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
    status = lib.XGetWindowProperty(
        display, window, _atom(lib, display, name), 0, _MAX_ITEMS, 0, _ANY_TYPE,
        ctypes.byref(actual_type), ctypes.byref(actual_format), ctypes.byref(count),
        ctypes.byref(remaining), ctypes.byref(data),
    )
    xlib.take_errors()  # a window that just closed raises BadWindow
    if status != _SUCCESS or not data.value:
        return None
    try:
        item_size = {8: 1, 16: ctypes.sizeof(ctypes.c_short), 32: ctypes.sizeof(ctypes.c_long)}
        size = item_size.get(actual_format.value, 1) * count.value
        return actual_format.value, count.value, ctypes.string_at(data.value, size)
    finally:
        lib.XFree(data)


def _longs(prop: tuple[int, int, bytes] | None) -> list[int]:
    """Format-32 property items (Xlib hands them out as C longs)."""
    if prop is None or prop[0] != 32:
        return []
    return list((ctypes.c_ulong * prop[1]).from_buffer_copy(prop[2]))


def _title(lib, display, window: int) -> str:
    for name in ("_NET_WM_NAME", "WM_NAME"):
        prop = _property(lib, display, window, name)
        if prop is not None and prop[0] == 8 and prop[2]:
            return prop[2].decode("utf-8", errors="replace")
    return ""


def _is_minimized(lib, display, window: int) -> bool:
    hidden = _atom(lib, display, "_NET_WM_STATE_HIDDEN")
    return hidden in _longs(_property(lib, display, window, "_NET_WM_STATE"))


def _rect(lib, display, window: int) -> Rect | None:
    root, x, y = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_int()
    width, height, border, depth = (ctypes.c_uint() for _ in range(4))
    ok = lib.XGetGeometry(
        display, window, ctypes.byref(root), ctypes.byref(x), ctypes.byref(y),
        ctypes.byref(width), ctypes.byref(height), ctypes.byref(border), ctypes.byref(depth),
    )
    if not ok or xlib.take_errors():
        return None
    left, top, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
    ok = lib.XTranslateCoordinates(
        display, window, root.value, 0, 0, ctypes.byref(left), ctypes.byref(top),
        ctypes.byref(child),
    )
    if not ok or xlib.take_errors() or width.value == 0 or height.value == 0:
        return None
    return left.value, top.value, width.value, height.value


def windows() -> list[NativeWindow]:
    """The window manager's top-level windows, bottom to top."""
    with xlib.shared_display() as display:
        if display is None:
            return []
        lib = xlib.load()
        root = lib.XDefaultRootWindow(display)
        found = []
        for window in _longs(_property(lib, display, root, "_NET_CLIENT_LIST")):
            pids = _longs(_property(lib, display, window, "_NET_WM_PID"))
            rect = None if _is_minimized(lib, display, window) else _rect(lib, display, window)
            found.append(NativeWindow(window, pids[0] if pids else 0,
                                      _title(lib, display, window), rect))
        return found


def rect(handle: int) -> Rect | None:
    """A window's client area on screen, or None if it's gone or minimized."""
    with xlib.shared_display() as display:
        if display is None:
            return None
        lib = xlib.load()
        if _is_minimized(lib, display, handle):
            return None
        return _rect(lib, display, handle)


def title(handle: int) -> str:
    with xlib.shared_display() as display:
        return "" if display is None else _title(xlib.load(), display, handle)


def foreground() -> int | None:
    """The active window, or None if the window manager doesn't say."""
    with xlib.shared_display() as display:
        if display is None:
            return None
        lib = xlib.load()
        active = _longs(_property(lib, display, lib.XDefaultRootWindow(display),
                                  "_NET_ACTIVE_WINDOW"))
        return active[0] if active and active[0] else None


def cursor() -> tuple[int, int] | None:
    with xlib.shared_display() as display:
        if display is None:
            return None
        lib = xlib.load()
        root_return, child = ctypes.c_ulong(), ctypes.c_ulong()
        x, y, win_x, win_y = (ctypes.c_int() for _ in range(4))
        mask = ctypes.c_uint()
        if not lib.XQueryPointer(
            display, lib.XDefaultRootWindow(display), ctypes.byref(root_return),
            ctypes.byref(child), ctypes.byref(x), ctypes.byref(y), ctypes.byref(win_x),
            ctypes.byref(win_y), ctypes.byref(mask),
        ):
            return None
        return x.value, y.value
