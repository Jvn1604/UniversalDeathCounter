"""
Global hotkeys on macOS, through Carbon's ``RegisterEventHotKey`` (ctypes).

It's the macOS counterpart of Windows' ``RegisterHotKey``: only the
registered combos are delivered, nothing else is seen, and it needs no
Accessibility permission (a keyboard monitor would). A combo another app
already registered is refused with ``eventHotKeyExistsErr``.

The hot key events arrive through the main thread's event loop, which Qt
runs, so registration happens on the main thread and no thread is needed.

Qt names the Command key "Ctrl" and the Control key "Meta" on macOS, so a
binding saved as ``ctrl+f9`` means ⌘F9 here.
"""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable

from src.utils.logger import get_logger

logger = get_logger(__name__)

_CARBON_PATH = "/System/Library/Frameworks/Carbon.framework/Carbon"
_SIGNATURE = 0x44554443  # 'DUDC'
_EVENT_CLASS_KEYBOARD = 0x6B657962  # 'keyb'
_EVENT_HOTKEY_PRESSED = 5
_PARAM_DIRECT_OBJECT = 0x2D2D2D2D  # '----'
_TYPE_HOTKEY_ID = 0x686B6964  # 'hkid'
_NO_ERROR = 0
_CMD, _SHIFT, _OPTION, _CONTROL = 0x0100, 0x0200, 0x0800, 0x1000
# hotkey_manager's flags (alt, ctrl, shift, win/meta) -> Carbon modifiers
_MODIFIERS = {0x1: _OPTION, 0x2: _CMD, 0x4: _SHIFT, 0x8: _CONTROL}

# Windows virtual-key code -> macOS key code (by position on a US keyboard).
_LETTERS = {
    "A": 0x00, "S": 0x01, "D": 0x02, "F": 0x03, "H": 0x04, "G": 0x05, "Z": 0x06,
    "X": 0x07, "C": 0x08, "V": 0x09, "B": 0x0B, "Q": 0x0C, "W": 0x0D, "E": 0x0E,
    "R": 0x0F, "Y": 0x10, "T": 0x11, "O": 0x1F, "U": 0x20, "I": 0x22, "P": 0x23,
    "L": 0x25, "J": 0x26, "K": 0x28, "N": 0x2D, "M": 0x2E,
}
_DIGITS = [0x1D, 0x12, 0x13, 0x14, 0x15, 0x17, 0x16, 0x1A, 0x1C, 0x19]
_KEYPAD = [0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5B, 0x5C]
_F_KEYS = [
    0x7A, 0x78, 0x63, 0x76, 0x60, 0x61, 0x62, 0x64, 0x65, 0x6D, 0x67, 0x6F,
    0x69, 0x6B, 0x71, 0x6A, 0x40, 0x4F, 0x50, 0x5A,
]
_NAMED = {
    0x08: 0x33, 0x09: 0x30, 0x0D: 0x24, 0x1B: 0x35, 0x20: 0x31, 0x21: 0x74, 0x22: 0x79,
    0x23: 0x77, 0x24: 0x73, 0x25: 0x7B, 0x26: 0x7E, 0x27: 0x7C, 0x28: 0x7D, 0x2D: 0x72,
    0x2E: 0x75, 0xBA: 0x29, 0xBB: 0x18, 0xBC: 0x2B, 0xBD: 0x1B, 0xBE: 0x2F, 0xBF: 0x2C,
    0xC0: 0x32, 0xDB: 0x21, 0xDC: 0x2A, 0xDD: 0x1E, 0xDE: 0x27,
}


def key_code_for(vk: int) -> int | None:
    """The macOS key code for a Windows virtual-key code from ``parse_hotkey``."""
    if 0x41 <= vk <= 0x5A:
        return _LETTERS[chr(vk)]
    if 0x30 <= vk <= 0x39:
        return _DIGITS[vk - 0x30]
    if 0x60 <= vk <= 0x69:
        return _KEYPAD[vk - 0x60]
    if 0x70 <= vk < 0x70 + len(_F_KEYS):
        return _F_KEYS[vk - 0x70]
    return _NAMED.get(vk)


def modifier_flags(modifiers: int) -> int:
    flags = 0
    for flag, carbon in _MODIFIERS.items():
        if modifiers & flag:
            flags |= carbon
    return flags


class _HotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_HandlerProc = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_carbon = None
_handler = None  # the installed callback; kept alive for the process
_listeners: dict[int, Callable[[], None]] = {}  # hot key id -> what to call
_next_id = 1
_lock = threading.Lock()


def _load_carbon():
    global _carbon
    if _carbon is not None:
        return _carbon
    lib = ctypes.CDLL(_CARBON_PATH)
    lib.GetApplicationEventTarget.restype = ctypes.c_void_p
    lib.InstallEventHandler.argtypes = [
        ctypes.c_void_p, _HandlerProc, ctypes.c_ulong, ctypes.POINTER(_EventTypeSpec),
        ctypes.c_void_p, ctypes.c_void_p,
    ]
    lib.InstallEventHandler.restype = ctypes.c_int32
    lib.RegisterEventHotKey.argtypes = [
        ctypes.c_uint32, ctypes.c_uint32, _HotKeyID, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.RegisterEventHotKey.restype = ctypes.c_int32
    lib.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
    lib.UnregisterEventHotKey.restype = ctypes.c_int32
    lib.GetEventParameter.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p,
    ]
    lib.GetEventParameter.restype = ctypes.c_int32
    _carbon = lib
    return lib


def available() -> bool:
    try:
        _load_carbon()
    except OSError:
        return False
    return True


def _on_event(_call_ref, event, _user_data) -> int:
    hotkey = _HotKeyID()
    status = _carbon.GetEventParameter(
        event, _PARAM_DIRECT_OBJECT, _TYPE_HOTKEY_ID, None,
        ctypes.sizeof(hotkey), None, ctypes.byref(hotkey),
    )
    if status == _NO_ERROR and hotkey.signature == _SIGNATURE:
        listener = _listeners.get(hotkey.id)
        if listener is not None:
            try:
                listener()
            except Exception:  # noqa: BLE001 - never let an error unwind into Carbon
                logger.exception("Hotkey handler failed")
    return _NO_ERROR


def _install_handler(carbon) -> None:
    global _handler
    if _handler is not None:
        return
    handler = _HandlerProc(_on_event)
    spec = _EventTypeSpec(_EVENT_CLASS_KEYBOARD, _EVENT_HOTKEY_PRESSED)
    status = carbon.InstallEventHandler(
        carbon.GetApplicationEventTarget(), handler, 1, ctypes.byref(spec), None, None
    )
    if status != _NO_ERROR:
        raise OSError(f"InstallEventHandler failed ({status})")
    _handler = handler


def _register(carbon, key_code: int, flags: int) -> tuple[int, ctypes.c_void_p] | None:
    global _next_id
    with _lock:
        hotkey_id = _next_id
        _next_id += 1
    ref = ctypes.c_void_p()
    status = carbon.RegisterEventHotKey(
        key_code, flags, _HotKeyID(_SIGNATURE, hotkey_id),
        carbon.GetApplicationEventTarget(), 0, ctypes.byref(ref),
    )
    if status != _NO_ERROR:
        return None
    return hotkey_id, ref


def probe(modifiers: int, vk: int) -> bool:
    """Whether the combo is free: register it, then let go."""
    key_code = key_code_for(vk)
    if key_code is None or not available():
        return key_code is not None
    carbon = _load_carbon()
    registered = _register(carbon, key_code, modifier_flags(modifiers))
    if registered is None:
        return False
    carbon.UnregisterEventHotKey(registered[1])
    return True


class MacHotkeys:
    """Holds the Carbon registrations for one set of bindings (main thread only)."""

    def __init__(
        self,
        combos: list[tuple[str, int, int]],
        on_hotkey: Callable[[str], None],
        on_failed: Callable[[list[str]], None],
    ) -> None:
        self._combos = combos
        self._on_hotkey = on_hotkey
        self._on_failed = on_failed
        self._registered: list[tuple[int, ctypes.c_void_p]] = []
        self.ready = threading.Event()
        self.held_combos: set[tuple[int, int]] = set()

    def start(self) -> None:
        failed: list[str] = []
        try:
            carbon = _load_carbon()
            _install_handler(carbon)
        except OSError:
            logger.warning("Carbon hot keys unavailable; global hotkeys are off", exc_info=True)
            self.ready.set()
            return
        for action, modifiers, vk in self._combos:
            key_code = key_code_for(vk)
            registered = (
                _register(carbon, key_code, modifier_flags(modifiers))
                if key_code is not None else None
            )
            if registered is None:
                failed.append(action)
                continue
            self._registered.append(registered)
            self.held_combos.add((modifiers, vk))
            _listeners[registered[0]] = lambda action=action: self._on_hotkey(action)
        self.ready.set()
        if failed:
            self._on_failed(failed)

    def stop(self) -> None:
        if _carbon is None:
            return
        for hotkey_id, ref in self._registered:
            _listeners.pop(hotkey_id, None)
            _carbon.UnregisterEventHotKey(ref)
        self._registered.clear()
        self.held_combos.clear()
