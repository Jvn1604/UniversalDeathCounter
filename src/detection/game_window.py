"""
Locating a running game and capturing its window.

The player picks the game's .exe once; from then on we find its process
with ``psutil``, find that process's main window through the OS (via
``ctypes``, no extra dependency), and grab the window's client area with
``mss``. This is plain screen capture: no memory reading and no
injection, so it is safe to use alongside anti-cheat.

* Windows: the Win32 API.
* macOS: Quartz (:mod:`src.detection.mac_windows`); the app needs Screen
  Recording permission. The game can be a ``.app`` or (CrossOver) an .exe.
* Linux: X11 (:mod:`src.detection.x11_windows`). Proton and Wine games are
  X11 windows; their process is matched by the .exe's name, since the
  running program is Wine itself. A Wayland desktop doesn't let apps
  capture other windows, so there OBS is the way (see :func:`capture_hint`).

Exclusive-fullscreen games may capture as solid black; borderless or
windowed mode always works.
"""

from __future__ import annotations

import os
import plistlib
import struct
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

import numpy as np

from src.utils.logger import get_logger
from src.utils.platform_info import IS_LINUX, IS_MAC, IS_WINDOWS, is_wayland

logger = get_logger(__name__)

DETECTION_SUPPORTED: bool = IS_WINDOWS or IS_MAC or IS_LINUX

try:
    import mss
    import psutil

    _DEPENDENCIES_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    _DEPENDENCIES_AVAILABLE = False

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
elif IS_MAC:
    from src.detection import mac_windows as _native
elif IS_LINUX:
    from src.detection import x11_windows as _native

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
        return f"{self.title}  —  {file_name(self.exe_path)}  ({self.width}×{self.height})"


def file_name(path: str) -> str:
    """The file name of a path from this OS or a Windows one (as Wine reports them)."""
    return PureWindowsPath(path).name


def open_screen_capture() -> mss.base.MSSBase:
    """A screen-capture context (``mss.MSS`` in mss 10.2+, ``mss.mss`` before)."""
    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


def detection_available() -> bool:
    """True if this platform and environment can run auto-detection."""
    return DETECTION_SUPPORTED and _DEPENDENCIES_AVAILABLE


def capture_hint() -> str:
    """Why the game's window can't be watched here (and what to do), or ""."""
    if IS_LINUX and is_wayland() and not os.environ.get("DISPLAY"):
        return (
            "This Wayland desktop doesn't let apps see other windows. Count deaths with "
            "the buttons, phone remote or controller, or read the game from OBS "
            "(Console page)."
        )
    if IS_LINUX and is_wayland():
        return (
            "On a Wayland desktop only Proton, Wine and other X11 games can be watched. "
            "If the capture stays black, read the game from OBS instead (Console page)."
        )
    if IS_MAC and not _native.capture_allowed():
        return (
            "macOS needs Screen Recording permission for auto-detect: System Settings → "
            "Privacy & Security → Screen Recording, then turn this app on and reopen it."
        )
    return ""


def request_capture_permission() -> None:
    """macOS: show the Screen Recording prompt if the player hasn't answered it yet."""
    if IS_MAC and not _native.capture_allowed():
        _native.request_capture()


def _bundle_info(path: str) -> dict:
    try:
        with open(os.path.join(path, "Contents", "Info.plist"), "rb") as file:
            return plistlib.load(file)
    except (OSError, plistlib.InvalidFileException):
        return {}


def _bundle_executable(path: str) -> str:
    """A macOS ``.app`` -> the program inside it; anything else unchanged."""
    if not path.endswith(".app") or not os.path.isdir(path):
        return path
    executable = _bundle_info(path).get("CFBundleExecutable") or Path(path).stem
    return os.path.join(path, "Contents", "MacOS", executable)


def _bundle_name(path: str) -> str | None:
    if not path.endswith(".app"):
        return None
    info = _bundle_info(path)
    return info.get("CFBundleDisplayName") or info.get("CFBundleName")


def _wine_program(process) -> str | None:
    """
    The .exe a Wine/Proton process runs (Linux and macOS), from its command line.

    Linux cuts process names to 15 characters and reports Wine as the
    executable, so ``darksoulsiii.exe`` shows as ``darksoulsiii.ex``.
    """
    try:
        cmdline = process.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return None
    if cmdline and cmdline[0].lower().endswith(".exe"):
        return file_name(cmdline[0]).lower()
    return None


def _name_matches(process, name: str, exe_name: str) -> bool:
    """Whether a process called ``name`` (lower case) is ``exe_name``."""
    if name == exe_name:
        return True
    if IS_WINDOWS or not exe_name.endswith(".exe"):
        return False
    if len(name) >= 15 and exe_name.startswith(name):
        return _wine_program(process) == exe_name
    return False


def _path_matches(running_exe: str | None, exe_path: str) -> bool:
    """Same program file; under Wine the running file is Wine itself, so any counts."""
    if running_exe is None or _same_path(running_exe, exe_path):
        return True
    return not IS_WINDOWS and file_name(running_exe).lower() != file_name(exe_path).lower()


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
    exe_path = _bundle_executable(exe_path)
    exe_name = file_name(exe_path).lower()
    pids: list[int] = []
    for process in psutil.process_iter(["pid", "name", "exe"]):
        info = process.info
        if not _name_matches(process, (info.get("name") or "").lower(), exe_name):
            continue
        if _path_matches(info.get("exe"), exe_path):
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
        by_name.setdefault(file_name(_bundle_executable(path)).lower(), []).append(path)
    running: set[str] = set()
    for process in psutil.process_iter(["name"]):
        name = (process.info.get("name") or "").lower()
        candidates = by_name.get(name)
        if not candidates and not IS_WINDOWS and len(name) >= 15:
            # A Wine game whose name Linux cut short: look at its command line.
            if any(exe.startswith(name) for exe in by_name):
                candidates = by_name.get(_wine_program(process) or "")
        if not candidates:
            continue
        try:
            running_exe = process.exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            running_exe = None
        for path in candidates:
            if _path_matches(running_exe, _bundle_executable(path)):
                running.add(path)
    return running


def exe_display_name(exe_path: str) -> str:
    """
    A friendly game name for an executable.

    Uses the exe's embedded ProductName / FileDescription (e.g.
    ``eldenring.exe`` → "ELDEN RING"), falling back to a tidied file name.
    """
    name = _version_info_name(exe_path) if IS_WINDOWS else _bundle_name(exe_path)
    if not name:
        stem = PureWindowsPath(exe_path).stem
        for suffix in ("-Win64-Shipping", "-Win32-Shipping", "_x64", "64"):
            stem = stem.removesuffix(suffix)
        name = stem.replace("_", " ").replace("-", " ").strip()
        if name.islower():
            name = name.title()
    cleaned = " ".join(name.replace("™", "").replace("®", "").split())
    return cleaned or PureWindowsPath(exe_path).stem


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
    if not IS_WINDOWS:
        return _native.title(hwnd)
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
    if not IS_WINDOWS:
        for window in _native.windows():
            if window.pid not in wanted or window.rect is None:
                continue
            if wanted_title and wanted_title not in window.title.casefold():
                continue
            area = window.rect[2] * window.rect[3]
            if best is None or area > best[0]:
                best = (area, window.handle)
        return best[1] if best is not None else None

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
    if not IS_WINDOWS:
        for window in _native.windows():
            title = window.title.strip()
            if not title or window.pid in (0, own_pid) or window.rect is None:
                continue
            if window.rect[2] < 200 or window.rect[3] < 150:
                continue
            exe_path = _program_path(window.pid)
            if exe_path is None:
                continue
            info = WindowInfo(title, exe_path, window.rect[2], window.rect[3])
            key = (title, exe_path)
            if key not in found or info.width * info.height > found[key].width * found[key].height:
                found[key] = info
        return sorted(found.values(), key=lambda w: -(w.width * w.height))

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


def _program_path(pid: int) -> str | None:
    """A process's program; for Wine, the .exe it runs rather than Wine."""
    try:
        process = psutil.Process(pid)
        exe_path = process.exe()
        cmdline = process.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return None
    if cmdline and cmdline[0].lower().endswith(".exe") and not exe_path.lower().endswith(".exe"):
        return cmdline[0]
    return exe_path or None


def is_not_responding(hwnd: int) -> bool:
    """Windows' own "Not Responding" test (no input handled for ~5 s)."""
    return IS_WINDOWS and bool(_user32.IsHungAppWindow(hwnd))


def is_foreground(hwnd: int) -> bool:
    """Whether ``hwnd`` is the window the player is using right now."""
    if not IS_WINDOWS:
        front = _native.foreground() if DETECTION_SUPPORTED else None
        return front is None or front == hwnd  # unknown: assume the player is playing
    _user32.GetForegroundWindow.restype = wintypes.HWND  # full-width handle
    return _user32.GetForegroundWindow() == hwnd


def window_client_rect(hwnd: int) -> Rect | None:
    """Screen rectangle of a window's client area, or None if gone/minimized."""
    if not IS_WINDOWS:
        return _native.rect(hwnd) if DETECTION_SUPPORTED else None
    if not _user32.IsWindow(hwnd) or _user32.IsIconic(hwnd):
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
    return _rgb(shot, width, height)


def _rgb(shot, width: int, height: int) -> np.ndarray:
    """
    RGB view of a BGRA capture, ``height`` x ``width``.

    On a Retina Mac the capture has 2 pixels per point; every other one is
    kept, so frames are in points everywhere (and templates keep matching).
    """
    pixels = np.asarray(shot)
    rows, columns = pixels.shape[:2]
    if rows != height or columns != width:
        pixels = pixels[:: max(1, rows // height), :: max(1, columns // width)][:height, :width]
    return pixels[..., 2::-1]


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
    canvas[top:bottom, left:right] = _rgb(shot, right - left, bottom - top)


def display_rect(sct: mss.base.MSSBase, display: int) -> Rect:
    """Display ``display`` (1 = the first) as a rect; the first one if it's gone."""
    monitors = sct.monitors
    monitor = monitors[display] if 0 < display < len(monitors) else monitors[1]
    return monitor["left"], monitor["top"], monitor["width"], monitor["height"]


def list_displays() -> list[tuple[int, str]]:
    """``(number, label)`` per connected display, e.g. ``(1, "Display 1: 1920×1080 (main)")``."""
    if not detection_available():
        return []
    with open_screen_capture() as sct:
        return [
            (
                index,
                f"Display {index}: {m['width']}×{m['height']}"
                + (" (main)" if (m["left"], m["top"]) == (0, 0) else ""),
            )
            for index, m in enumerate(sct.monitors[1:], start=1)
        ]


def capture_game_frame(
    exe_path: str | None, title: str = "", display: int = 0
) -> np.ndarray | None:
    """
    One-off capture for calibration: ``display`` when the game is watched
    without its .exe, else the game's window if it is running, otherwise the
    display under the mouse cursor (where the player is looking). ``title``
    picks one window of the program (console capture). Returns None if
    capture is unavailable.
    """
    if not detection_available():
        return None
    with open_screen_capture() as sct:
        if display:
            return np.ascontiguousarray(grab_rect(sct, display_rect(sct, display)))
        if exe_path:
            hwnd = find_main_window(find_process_ids(exe_path), title)
            rect = window_client_rect(hwnd) if hwnd is not None else None
            if rect is not None:
                return np.ascontiguousarray(grab_rect(sct, rect))
        x, y = _cursor_position()
        monitor = monitor_at(sct.monitors[1:], x, y)
        return np.ascontiguousarray(
            grab_rect(sct, (monitor["left"], monitor["top"], monitor["width"], monitor["height"]))
        )


def _cursor_position() -> tuple[int, int]:
    if not IS_WINDOWS:
        return _native.cursor() or (0, 0)
    cursor = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(cursor))
    return cursor.x, cursor.y
