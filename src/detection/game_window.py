"""
Locating a running game and capturing its window.

The player picks the game's .exe once; from then on we find its process
with ``psutil``, find that process's main window through the Win32 API
(via ``ctypes``, no extra dependency), and grab the window's client area
with ``mss``. This is plain screen capture: no memory reading and no
injection, so it is safe to use alongside anti-cheat.

Exclusive-fullscreen games may capture as solid black; borderless or
windowed mode always works.
"""

from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.utils.logger import get_logger

logger = get_logger(__name__)

DETECTION_SUPPORTED: bool = sys.platform == "win32"

try:
    import mss
    import psutil

    _DEPENDENCIES_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    _DEPENDENCIES_AVAILABLE = False

if DETECTION_SUPPORTED:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

Rect = tuple[int, int, int, int]  # left, top, width, height in screen pixels


@dataclass(frozen=True)
class WindowInfo:
    """A window on the desktop that detection could watch."""

    title: str
    exe_path: str
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.title}  —  {Path(self.exe_path).name}  ({self.width}×{self.height})"


def open_screen_capture() -> mss.base.MSSBase:
    """A screen-capture context (``mss.MSS`` in mss 10.2+, ``mss.mss`` before)."""
    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


def detection_available() -> bool:
    """True if this platform and environment can run auto-detection."""
    return DETECTION_SUPPORTED and _DEPENDENCIES_AVAILABLE


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def find_process_ids(exe_path: str) -> list[int]:
    """
    Return the pids of running processes started from ``exe_path``.

    Falls back to matching the file name alone when a process's full path
    cannot be read (e.g. it runs elevated).
    """
    if not _DEPENDENCIES_AVAILABLE:
        return []
    exe_name = Path(exe_path).name.lower()
    pids: list[int] = []
    for process in psutil.process_iter(["pid", "name", "exe"]):
        info = process.info
        if (info.get("name") or "").lower() != exe_name:
            continue
        running_exe = info.get("exe")
        if running_exe is None or _same_path(running_exe, exe_path):
            pids.append(int(info["pid"]))
    return pids


def running_exe_paths(exe_paths: list[str]) -> set[str]:
    """
    Return which of ``exe_paths`` currently have a running process.

    One pass over the process list, reading each process's full path only
    when its file name matches, so it is cheap enough to poll every few
    seconds.
    """
    if not _DEPENDENCIES_AVAILABLE or not exe_paths:
        return set()
    by_name: dict[str, list[str]] = {}
    for path in exe_paths:
        by_name.setdefault(Path(path).name.lower(), []).append(path)
    running: set[str] = set()
    for process in psutil.process_iter(["name"]):
        candidates = by_name.get((process.info.get("name") or "").lower())
        if not candidates:
            continue
        try:
            running_exe = process.exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            running_exe = None
        for path in candidates:
            if running_exe is None or _same_path(running_exe, path):
                running.add(path)
    return running


def exe_display_name(exe_path: str) -> str:
    """
    A friendly game name for an executable.

    Uses the exe's embedded ProductName / FileDescription (e.g.
    ``eldenring.exe`` → "ELDEN RING"), falling back to a tidied file name.
    """
    name = _version_info_name(exe_path) if DETECTION_SUPPORTED else None
    if not name:
        stem = Path(exe_path).stem
        for suffix in ("-Win64-Shipping", "-Win32-Shipping", "_x64", "64"):
            stem = stem.removesuffix(suffix)
        name = stem.replace("_", " ").replace("-", " ").strip()
        if name.islower():
            name = name.title()
    return " ".join(name.replace("™", "").replace("®", "").split()) or Path(exe_path).stem


def _version_info_name(exe_path: str) -> str | None:
    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(exe_path, None)
    if not size:
        return None
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(exe_path, 0, size, buffer):
        return None
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(
        buffer, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)
    ) or length.value < 4:
        return None
    language, codepage = struct.unpack_from("<HH", ctypes.string_at(pointer, 4))
    for field in ("ProductName", "FileDescription"):
        query = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{field}"
        if version.VerQueryValueW(buffer, query, ctypes.byref(pointer), ctypes.byref(length)):
            value = ctypes.wstring_at(pointer, length.value).rstrip("\0").strip()
            if value and "operating system" not in value.lower():
                return value
    return None


def window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def find_main_window(pids: list[int], title: str = "") -> int | None:
    """
    Return the largest visible top-level window owned by any of ``pids``.

    With ``title``, only windows whose title contains it (any case) count:
    e.g. one OBS projector out of OBS's many windows, for console players.
    """
    if not DETECTION_SUPPORTED or not pids:
        return None
    wanted = set(pids)
    wanted_title = title.casefold()
    best: tuple[int, int] | None = None  # (area, hwnd)

    def _visit(hwnd: int, _lparam: int) -> bool:
        nonlocal best
        if not _user32.IsWindowVisible(hwnd):
            return True
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value not in wanted:
            return True
        if wanted_title and wanted_title not in window_title(hwnd).casefold():
            return True
        rect = wintypes.RECT()
        _user32.GetClientRect(hwnd, ctypes.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)
        if area > 0 and (best is None or area > best[0]):
            best = (area, hwnd)
        return True

    _user32.EnumWindows(_EnumWindowsProc(_visit), 0)
    return best[1] if best is not None else None


_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_TRANSPARENT = 0x00000020  # click-through overlays (e.g. GeForce Experience)
_DWMWA_CLOAKED = 14


def _is_hidden_layer(hwnd: int) -> bool:
    """Tool windows, click-through overlays and "cloaked" (invisible) system windows."""
    style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    if style & (_WS_EX_TOOLWINDOW | _WS_EX_TRANSPARENT):
        return True
    cloaked = wintypes.DWORD()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    )
    return result == 0 and cloaked.value != 0


def list_windows() -> list[WindowInfo]:
    """
    Visible, titled windows of other programs, largest first: what a console
    player can pick (PS Remote Play, the Xbox app, a capture card's viewer,
    an OBS projector).
    """
    if not detection_available():
        return []
    own_pid = os.getpid()
    found: dict[tuple[str, str], WindowInfo] = {}

    def _visit(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
            return True
        title = window_title(hwnd).strip()
        if not title or title == "Program Manager" or _is_hidden_layer(hwnd):
            return True
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own_pid:
            return True
        rect = window_client_rect(hwnd)
        if rect is None or rect[2] < 200 or rect[3] < 150:
            return True  # tool strips, tray helpers, tiny pop-ups
        try:
            exe_path = psutil.Process(pid.value).exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return True
        info = WindowInfo(title, exe_path, rect[2], rect[3])
        key = (title, exe_path)
        if key not in found or info.width * info.height > found[key].width * found[key].height:
            found[key] = info
        return True

    _user32.EnumWindows(_EnumWindowsProc(_visit), 0)
    return sorted(found.values(), key=lambda w: -(w.width * w.height))


def is_not_responding(hwnd: int) -> bool:
    """Windows' own "Not Responding" test (no input handled for ~5 s)."""
    return DETECTION_SUPPORTED and bool(_user32.IsHungAppWindow(hwnd))


def is_foreground(hwnd: int) -> bool:
    """Whether ``hwnd`` is the window the player is using right now."""
    if not DETECTION_SUPPORTED:
        return True
    _user32.GetForegroundWindow.restype = wintypes.HWND  # full-width handle
    return _user32.GetForegroundWindow() == hwnd


def window_client_rect(hwnd: int) -> Rect | None:
    """Screen rectangle of a window's client area, or None if gone/minimized."""
    if not DETECTION_SUPPORTED or not _user32.IsWindow(hwnd) or _user32.IsIconic(hwnd):
        return None
    rect = wintypes.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = wintypes.POINT(0, 0)
    _user32.ClientToScreen(hwnd, ctypes.byref(origin))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    return origin.x, origin.y, width, height


def clip_to_desktop(rect: Rect, desktop: Rect) -> Rect | None:
    """
    Intersect a window rect with the virtual desktop (all displays together).

    Displays left of or above the primary have negative coordinates, which
    is fine; only parts hanging off every display are cut. Returns None if
    nothing is visible.
    """
    left, top = max(rect[0], desktop[0]), max(rect[1], desktop[1])
    right = min(rect[0] + rect[2], desktop[0] + desktop[2])
    bottom = min(rect[1] + rect[3], desktop[1] + desktop[3])
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top


def monitor_at(monitors: list[dict], x: int, y: int) -> dict:
    """The monitor containing point (x, y), else the first one (the primary)."""
    for monitor in monitors:
        if (monitor["left"] <= x < monitor["left"] + monitor["width"]
                and monitor["top"] <= y < monitor["top"] + monitor["height"]):
            return monitor
    return monitors[0]


def desktop_clip(sct: mss.base.MSSBase, rect: Rect) -> Rect:
    """``rect`` cut to the parts that are on some display."""
    desktop = sct.monitors[0]  # bounding box of every display
    clipped = clip_to_desktop(
        rect, (desktop["left"], desktop["top"], desktop["width"], desktop["height"])
    )
    return clipped or rect


def grab_rect(sct: mss.base.MSSBase, rect: Rect) -> np.ndarray:
    """
    Capture a screen rectangle as an ``(H, W, 3)`` RGB uint8 array.

    The result is a view on the captured BGRA pixels, not a copy: turning a
    whole 1440p frame into a packed RGB array takes ~14 ms, while matchers
    only read small crops of it. Use ``np.ascontiguousarray`` to keep a frame.
    """
    left, top, width, height = desktop_clip(sct, rect)
    shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
    return np.asarray(shot)[..., 2::-1]


def grab_into(
    sct: mss.base.MSSBase,
    origin: tuple[int, int],
    box: tuple[int, int, int, int],
    canvas: np.ndarray,
) -> None:
    """
    Capture only ``box`` (``left, top, right, bottom`` in frame pixels) of a
    frame whose top-left is at screen point ``origin``, into the same spot
    of ``canvas``. Much cheaper than a full capture when matchers only read
    a small part of the screen.
    """
    left, top, right, bottom = box
    area = {"left": origin[0] + left, "top": origin[1] + top}
    shot = sct.grab({**area, "width": right - left, "height": bottom - top})
    canvas[top:bottom, left:right] = np.asarray(shot)[..., 2::-1]


def capture_game_frame(exe_path: str | None, title: str = "") -> np.ndarray | None:
    """
    One-off capture for calibration: the game's window if it is running,
    otherwise the display under the mouse cursor (where the player is
    looking). ``title`` picks one window of the program (console capture).
    Returns None if capture is unavailable.
    """
    if not detection_available():
        return None
    with open_screen_capture() as sct:
        if exe_path:
            hwnd = find_main_window(find_process_ids(exe_path), title)
            rect = window_client_rect(hwnd) if hwnd is not None else None
            if rect is not None:
                return np.ascontiguousarray(grab_rect(sct, rect))
        cursor = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(cursor))
        monitor = monitor_at(sct.monitors[1:], cursor.x, cursor.y)
        return np.ascontiguousarray(
            grab_rect(sct, (monitor["left"], monitor["top"], monitor["width"], monitor["height"]))
        )
