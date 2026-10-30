"""
Global hotkeys on Linux, through X11's ``XGrabKey`` (libX11 via ctypes).

Like Windows' ``RegisterHotKey``, a grab only ever delivers the grabbed key
combos, never other keystrokes, and a combo another program has grabbed
can't be taken (X reports ``BadAccess``). Games running through Proton or
Wine are X11 windows, so the keys also work in-game on a Wayland desktop
(through XWayland); native Wayland windows don't share their keys.

A daemon thread owns its own X connection and waits on its socket; a pipe
wakes it up to stop.
"""

from __future__ import annotations

import ctypes
import os
import select
import threading
from collections.abc import Callable

from src.utils import xlib
from src.utils.logger import get_logger

logger = get_logger(__name__)

_KEY_PRESS, _KEY_RELEASE = 2, 3
_GRAB_MODE_ASYNC = 1
_SHIFT, _LOCK, _CONTROL, _MOD1, _MOD2, _MOD4 = 1, 2, 4, 8, 16, 64
# Caps Lock and Num Lock change the modifier state, so each combo is
# grabbed once per lock combination.
_LOCK_VARIANTS = (0, _LOCK, _MOD2, _LOCK | _MOD2)
# hotkey_manager's (Windows-style) modifier flags -> X11 masks
_MODIFIER_MASKS = {0x1: _MOD1, 0x2: _CONTROL, 0x4: _SHIFT, 0x8: _MOD4}

_NAMED_KEYSYMS: dict[int, int] = {
    0x08: 0xFF08, 0x09: 0xFF09, 0x0D: 0xFF0D, 0x13: 0xFF13, 0x1B: 0xFF1B, 0x20: 0x20,
    0x21: 0xFF55, 0x22: 0xFF56, 0x23: 0xFF57, 0x24: 0xFF50, 0x25: 0xFF51, 0x26: 0xFF52,
    0x27: 0xFF53, 0x28: 0xFF54, 0x2C: 0xFF61, 0x2D: 0xFF63, 0x2E: 0xFFFF,
    0xBA: 0x3B, 0xBB: 0x3D, 0xBC: 0x2C, 0xBD: 0x2D, 0xBE: 0x2E, 0xBF: 0x2F,
    0xC0: 0x60, 0xDB: 0x5B, 0xDC: 0x5C, 0xDD: 0x5D, 0xDE: 0x27,
}


def keysym_for(vk: int) -> int | None:
    """The X11 keysym for a Windows virtual-key code from ``parse_hotkey``."""
    if 0x30 <= vk <= 0x39:
        return vk  # XK_0..XK_9
    if 0x41 <= vk <= 0x5A:
        return vk + 0x20  # XK_a..XK_z
    if 0x60 <= vk <= 0x69:
        return 0xFFB0 + vk - 0x60  # XK_KP_0..XK_KP_9
    if 0x70 <= vk <= 0x87:
        return 0xFFBE + vk - 0x70  # XK_F1..XK_F24
    return _NAMED_KEYSYMS.get(vk)


def modifier_mask(modifiers: int) -> int:
    mask = 0
    for flag, x_mask in _MODIFIER_MASKS.items():
        if modifiers & flag:
            mask |= x_mask
    return mask


class _XKeyEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("root", ctypes.c_ulong),
        ("subwindow", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("x_root", ctypes.c_int),
        ("y_root", ctypes.c_int),
        ("state", ctypes.c_uint),
        ("keycode", ctypes.c_uint),
        ("same_screen", ctypes.c_int),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xkey", _XKeyEvent), ("pad", ctypes.c_long * 24)]


def available() -> bool:
    """An X server is reachable (X11, or XWayland on a Wayland desktop)."""
    return xlib.available()


def _grab_all(lib, display, grabs: list[tuple[int, int]]) -> list[bool]:
    """Grab each (keycode, mask) on the root window; True where X accepted it."""
    root = lib.XDefaultRootWindow(display)
    accepted = []
    xlib.take_errors()
    for keycode, mask in grabs:
        for lock in _LOCK_VARIANTS:
            lib.XGrabKey(display, keycode, mask | lock, root, 0, _GRAB_MODE_ASYNC, _GRAB_MODE_ASYNC)
        lib.XSync(display, 0)  # this combo's errors arrive now
        accepted.append(xlib.BAD_ACCESS not in xlib.take_errors())
    return accepted


def _ungrab(lib, display, keycode: int, mask: int) -> None:
    root = lib.XDefaultRootWindow(display)
    for lock in _LOCK_VARIANTS:
        lib.XUngrabKey(display, keycode, mask | lock, root)


def probe(modifiers: int, vk: int) -> bool:
    """Whether the combo is free: grab it on a throwaway connection, then let go."""
    keysym = keysym_for(vk)
    if keysym is None or not xlib.available():
        return True
    lib = xlib.load()
    display = lib.XOpenDisplay(None)
    if not display:
        return True
    try:
        keycode = lib.XKeysymToKeycode(display, keysym)
        if not keycode:
            return False
        mask = modifier_mask(modifiers)
        free = _grab_all(lib, display, [(keycode, mask)])[0]
        _ungrab(lib, display, keycode, mask)
        lib.XSync(display, 0)
        xlib.take_errors()
        return free
    finally:
        lib.XCloseDisplay(display)


class X11HotkeyThread(threading.Thread):
    """Owns the X11 key grabs and turns key presses into actions."""

    def __init__(
        self,
        combos: list[tuple[str, int, int]],
        on_hotkey: Callable[[str], None],
        on_failed: Callable[[list[str]], None],
    ) -> None:
        super().__init__(name="HotkeyListener", daemon=True)
        self._combos = combos  # (action, modifiers, vk)
        self._on_hotkey = on_hotkey
        self._on_failed = on_failed
        self._wake_read, self._wake_write = os.pipe()
        self.ready = threading.Event()
        self.held_combos: set[tuple[int, int]] = set()

    def run(self) -> None:
        try:
            try:
                lib = xlib.load()
                display = lib.XOpenDisplay(None)
            except OSError:
                display = None
            if not display:
                logger.warning("No X11 display; global hotkeys are off")
                self.ready.set()
                return
            try:
                self._listen(lib, display)
            finally:
                lib.XCloseDisplay(display)
        finally:
            os.close(self._wake_read)

    def _listen(self, lib, display) -> None:
        # Holding a key sends one press (not press/release pairs) per repeat.
        lib.XkbSetDetectableAutoRepeat(display, 1, None)
        wanted: dict[tuple[int, int], tuple[str, int, int]] = {}  # (keycode, mask) -> combo
        failed: list[str] = []
        for action, modifiers, vk in self._combos:
            keysym = keysym_for(vk)
            keycode = lib.XKeysymToKeycode(display, keysym) if keysym is not None else 0
            if not keycode:
                failed.append(action)
                continue
            wanted[(keycode, modifier_mask(modifiers))] = (action, modifiers, vk)
        grabs = list(wanted)
        actions: dict[tuple[int, int], str] = {}
        for grab, ok in zip(grabs, _grab_all(lib, display, grabs), strict=True):
            action, modifiers, vk = wanted[grab]
            if ok:
                actions[grab] = action
                self.held_combos.add((modifiers, vk))
            else:
                failed.append(action)
                _ungrab(lib, display, *grab)  # the lock variants that did succeed
        self.ready.set()
        if failed:
            self._on_failed(failed)

        x_socket = lib.XConnectionNumber(display)
        event = _XEvent()
        down: set[int] = set()
        ignored = _LOCK | _MOD2
        while True:
            while lib.XPending(display):
                lib.XNextEvent(display, ctypes.byref(event))
                key = event.xkey
                if event.type == _KEY_RELEASE:
                    down.discard(key.keycode)
                elif event.type == _KEY_PRESS and key.keycode not in down:
                    down.add(key.keycode)
                    action = actions.get((key.keycode, key.state & ~ignored & 0xFF))
                    if action is not None:
                        self._on_hotkey(action)
            readable, _, _ = select.select([x_socket, self._wake_read], [], [])
            if self._wake_read in readable:
                break
        for grab in actions:
            _ungrab(lib, display, *grab)
        lib.XSync(display, 0)
        xlib.take_errors()

    def stop(self) -> None:
        self.ready.wait(timeout=2.0)
        try:
            os.write(self._wake_write, b"x")
            os.close(self._wake_write)
        except OSError:
            pass
        self.join(timeout=2.0)
