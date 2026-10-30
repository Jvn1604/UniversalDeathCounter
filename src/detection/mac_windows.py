"""
Finding windows on macOS through Quartz (CoreGraphics via ctypes).

``CGWindowListCopyWindowInfo`` lists every window with its owner's process
id, its bounds and (with Screen Recording permission) its title. macOS
also needs that permission for any screen capture, so
:func:`capture_allowed` / :func:`request_capture` let the app check and ask.

Coordinates are in points with the origin at the top-left of the main
display, the same space ``mss`` captures in.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from src.utils.logger import get_logger

logger = get_logger(__name__)

Rect = tuple[int, int, int, int]

_CG_PATH = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
_CF_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_ON_SCREEN_ONLY = 1 << 0
_INCLUDING_WINDOW = 1 << 3
_EXCLUDE_DESKTOP = 1 << 4
_NULL_WINDOW = 0
_UTF8 = 0x08000100
_SINT64 = 4
_NORMAL_LAYER = 0


@dataclass(frozen=True)
class NativeWindow:
    handle: int
    pid: int
    title: str
    rect: Rect | None  # None while minimized or on another Space


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double),
                ("width", ctypes.c_double), ("height", ctypes.c_double)]


_cg = None
_cf = None
_keys: dict[str, int] = {}


def _load():
    global _cg, _cf
    if _cg is not None:
        return _cg, _cf
    cg, cf = ctypes.CDLL(_CG_PATH), ctypes.CDLL(_CF_PATH)
    c_void_p = ctypes.c_void_p
    cg.CGWindowListCopyWindowInfo.restype = c_void_p
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    cg.CGRectMakeWithDictionaryRepresentation.restype = ctypes.c_bool
    cg.CGRectMakeWithDictionaryRepresentation.argtypes = [c_void_p, ctypes.POINTER(_CGRect)]
    cg.CGEventCreate.restype = c_void_p
    cg.CGEventCreate.argtypes = [c_void_p]
    cg.CGEventGetLocation.restype = _CGPoint
    cg.CGEventGetLocation.argtypes = [c_void_p]
    for name in ("CGPreflightScreenCaptureAccess", "CGRequestScreenCaptureAccess"):
        if hasattr(cg, name):  # macOS 10.15+
            getattr(cg, name).restype = ctypes.c_bool
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [c_void_p]
    cf.CFArrayGetValueAtIndex.restype = c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [c_void_p, ctypes.c_long]
    cf.CFDictionaryGetValue.restype = c_void_p
    cf.CFDictionaryGetValue.argtypes = [c_void_p, c_void_p]
    cf.CFNumberGetValue.restype = ctypes.c_bool
    cf.CFNumberGetValue.argtypes = [c_void_p, ctypes.c_int, c_void_p]
    cf.CFStringCreateWithCString.restype = c_void_p
    cf.CFStringCreateWithCString.argtypes = [c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringGetLength.restype = ctypes.c_long
    cf.CFStringGetLength.argtypes = [c_void_p]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    cf.CFRelease.argtypes = [c_void_p]
    _cg, _cf = cg, cf
    return cg, cf


def available() -> bool:
    try:
        _load()
    except OSError:
        return False
    return True


def _key(name: str) -> int:
    """The CFString key (kCGWindowNumber's value is the string "kCGWindowNumber")."""
    if name not in _keys:
        _keys[name] = _cf.CFStringCreateWithCString(None, name.encode(), _UTF8)
    return _keys[name]


def _number(info: int, name: str) -> int | None:
    value = _cf.CFDictionaryGetValue(info, _key(name))
    out = ctypes.c_int64()
    if value and _cf.CFNumberGetValue(value, _SINT64, ctypes.byref(out)):
        return out.value
    return None


def _string(info: int, name: str) -> str:
    value = _cf.CFDictionaryGetValue(info, _key(name))
    if not value:
        return ""
    size = _cf.CFStringGetLength(value) * 4 + 1
    buffer = ctypes.create_string_buffer(size)
    if not _cf.CFStringGetCString(value, buffer, size, _UTF8):
        return ""
    return buffer.value.decode("utf-8", errors="replace")


def _bounds(info: int) -> Rect | None:
    value = _cf.CFDictionaryGetValue(info, _key("kCGWindowBounds"))
    rect = _CGRect()
    if not value or not _cg.CGRectMakeWithDictionaryRepresentation(value, ctypes.byref(rect)):
        return None
    if rect.width <= 0 or rect.height <= 0:
        return None
    return round(rect.x), round(rect.y), round(rect.width), round(rect.height)


def _window_infos(options: int, window: int = _NULL_WINDOW) -> list[NativeWindow]:
    try:
        _load()
    except OSError:
        return []
    array = _cg.CGWindowListCopyWindowInfo(options, window)
    if not array:
        return []
    found = []
    try:
        for index in range(_cf.CFArrayGetCount(array)):
            info = _cf.CFArrayGetValueAtIndex(array, index)
            if _number(info, "kCGWindowLayer") != _NORMAL_LAYER:
                continue  # menu bar, Dock, pop-up menus
            on_screen = bool(_number(info, "kCGWindowIsOnscreen"))
            # Without Screen Recording permission there's no title: use the app's name.
            title = _string(info, "kCGWindowName") or _string(info, "kCGWindowOwnerName")
            found.append(NativeWindow(
                _number(info, "kCGWindowNumber") or 0,
                _number(info, "kCGWindowOwnerPID") or 0,
                title,
                _bounds(info) if on_screen else None,
            ))
    finally:
        _cf.CFRelease(array)
    return found


def windows() -> list[NativeWindow]:
    """Ordinary app windows, front to back."""
    return _window_infos(_EXCLUDE_DESKTOP)


def _one(handle: int) -> NativeWindow | None:
    return next(iter(_window_infos(_INCLUDING_WINDOW, handle)), None)


def rect(handle: int) -> Rect | None:
    window = _one(handle)
    return window.rect if window is not None else None


def title(handle: int) -> str:
    window = _one(handle)
    return window.title if window is not None else ""


def foreground() -> int | None:
    """The frontmost ordinary window (the list comes front to back)."""
    front = _window_infos(_ON_SCREEN_ONLY | _EXCLUDE_DESKTOP)
    return front[0].handle if front else None


def cursor() -> tuple[int, int] | None:
    try:
        _load()
    except OSError:
        return None
    event = _cg.CGEventCreate(None)
    if not event:
        return None
    try:
        point = _cg.CGEventGetLocation(event)
    finally:
        _cf.CFRelease(event)
    return round(point.x), round(point.y)


def capture_allowed() -> bool:
    """Whether macOS lets this app record the screen (Privacy & Security settings)."""
    try:
        cg, _ = _load()
    except OSError:
        return False
    check = getattr(cg, "CGPreflightScreenCaptureAccess", None)
    return True if check is None else bool(check())


def request_capture() -> bool:
    """Ask for Screen Recording permission (macOS shows its prompt once)."""
    try:
        cg, _ = _load()
    except OSError:
        return False
    ask = getattr(cg, "CGRequestScreenCaptureAccess", None)
    return True if ask is None else bool(ask())
