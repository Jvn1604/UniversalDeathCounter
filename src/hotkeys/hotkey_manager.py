"""
Global hotkey listener.

Registers hotkeys with Windows' own ``RegisterHotKey`` API, so they fire
even while another application (i.e. the game itself) has focus. Unlike a
low-level keyboard hook, this only ever sees the registered key combos,
never other keystrokes, which keeps antivirus heuristics from flagging
the app as a keylogger.

Windows delivers ``WM_HOTKEY`` messages to the thread that registered the
keys, so a small daemon thread owns the registrations and runs a message
loop; its callbacks reach Qt's main thread through queued signals.

Two consequences of the OS API: a registered key is consumed (the game
does not also receive it), and a key combo another program has already
registered cannot be used, which :attr:`HotkeyManager.registration_failed`
reports. Global hotkeys are Windows-only; the in-app buttons work everywhere.
"""

from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QObject, Signal

from src.utils.logger import get_logger

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

logger = get_logger(__name__)

_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_MOD_NOREPEAT = 0x4000

_MODIFIERS: dict[str, int] = {
    "alt": 0x0001,
    "ctrl": 0x0002,
    "control": 0x0002,
    "shift": 0x0004,
    "win": 0x0008,
    "windows": 0x0008,
    "meta": 0x0008,
}

_NAMED_KEYS: dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "pause": 0x13,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pgup": 0x21,
    "page up": 0x21,
    "pgdown": 0x22,
    "page down": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "print": 0x2C,
    "ins": 0x2D,
    "insert": 0x2D,
    "del": 0x2E,
    "delete": 0x2E,
    ";": 0xBA,
    "=": 0xBB,
    ",": 0xBC,
    "-": 0xBD,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
    "[": 0xDB,
    "\\": 0xDC,
    "]": 0xDD,
    "'": 0xDE,
}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """
    Parse a combo such as ``"f9"`` or ``"ctrl+shift+d"`` into
    ``(modifier_flags, virtual_key_code)``. Returns None if unrecognized.

    Accepts the lower-cased ``QKeySequence`` text the Settings dialog
    stores (including ``"num+5"`` for keypad digits).
    """
    parts = [p.strip() for p in text.strip().lower().split("+") if p.strip()]
    if not parts:
        return None
    *modifier_names, key = parts
    modifiers, keypad = 0, False
    for name in modifier_names:
        if name == "num":
            keypad = True
        elif name in _MODIFIERS:
            modifiers |= _MODIFIERS[name]
        else:
            return None

    if keypad and len(key) == 1 and key.isdigit():
        return modifiers, 0x60 + int(key)
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x70 + int(key[1:]) - 1
    if len(key) == 1 and key.isascii() and key.isalnum():
        return modifiers, ord(key.upper())
    if key in _NAMED_KEYS:
        return modifiers, _NAMED_KEYS[key]
    return None


class _HotkeyThread(threading.Thread):
    """Owns the Windows hotkey registrations and pumps WM_HOTKEY messages."""

    def __init__(self, combos: list[tuple[str, int, int]], on_hotkey, on_failed) -> None:
        super().__init__(name="HotkeyListener", daemon=True)
        self._combos = combos  # (action, modifiers, vk)
        self._on_hotkey = on_hotkey
        self._on_failed = on_failed
        self._thread_id = 0
        self.ready = threading.Event()

    def run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        registered: list[int] = []
        failed: list[str] = []
        for hotkey_id, (action, modifiers, vk) in enumerate(self._combos, start=1):
            if _user32.RegisterHotKey(None, hotkey_id, modifiers | _MOD_NOREPEAT, vk):
                registered.append(hotkey_id)
            else:
                failed.append(action)
        self.ready.set()
        if failed:
            self._on_failed(failed)

        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == _WM_HOTKEY and 1 <= msg.wParam <= len(self._combos):
                self._on_hotkey(self._combos[msg.wParam - 1][0])

        for hotkey_id in registered:
            _user32.UnregisterHotKey(None, hotkey_id)

    def stop(self) -> None:
        self.ready.wait(timeout=2.0)
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)
        self.join(timeout=2.0)


class HotkeyManager(QObject):
    """
    Registers global hotkeys and emits Qt signals when they fire.

    Signals:
        increment_triggered: Emitted when the +1 death hotkey is pressed.
        decrement_triggered: Emitted when the -1 death hotkey is pressed.
        undo_triggered: Emitted when the undo hotkey is pressed.
        toggle_overlay_triggered: Emitted when the overlay-toggle hotkey
            is pressed.
        calibrate_triggered: Emitted when the death-screen calibration
            hotkey is pressed.
        pause_detection_triggered: Emitted when the pause/resume
            auto-detection hotkey is pressed.
        registration_failed: Emitted with ``[(action, key), ...]`` for keys
            that could not be registered (unknown key, or already taken
            by another program).
    """

    increment_triggered = Signal()
    decrement_triggered = Signal()
    undo_triggered = Signal()
    toggle_overlay_triggered = Signal()
    calibrate_triggered = Signal()
    pause_detection_triggered = Signal()
    registration_failed = Signal(list)

    def __init__(
        self,
        increment_key: str,
        decrement_key: str,
        undo_key: str,
        toggle_overlay_key: str,
        calibrate_key: str = "f8",
        pause_detection_key: str = "ctrl+f8",
        parent: QObject | None = None,
    ) -> None:
        """
        Args:
            increment_key: Key combo (e.g. ``"f9"``) for +1 death.
            decrement_key: Key combo for -1 death.
            undo_key: Key combo for undo.
            toggle_overlay_key: Key combo for toggling the overlay.
            calibrate_key: Key combo for capturing a death-screen calibration.
            pause_detection_key: Key combo for pausing/resuming auto-detection.
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self._bindings: dict[str, str] = {
            "increment": increment_key,
            "decrement": decrement_key,
            "undo": undo_key,
            "toggle_overlay": toggle_overlay_key,
            "calibrate": calibrate_key,
            "pause_detection": pause_detection_key,
        }
        self._signals: dict[str, Signal] = {
            "increment": self.increment_triggered,
            "decrement": self.decrement_triggered,
            "undo": self.undo_triggered,
            "toggle_overlay": self.toggle_overlay_triggered,
            "calibrate": self.calibrate_triggered,
            "pause_detection": self.pause_detection_triggered,
        }
        self._thread: _HotkeyThread | None = None

        if sys.platform != "win32":
            logger.warning("Global hotkeys need Windows; in-app buttons still work.")

    def start(self) -> None:
        """Register all hotkeys with Windows."""
        if sys.platform != "win32" or self._thread is not None:
            return
        combos: list[tuple[str, int, int]] = []
        unknown: list[tuple[str, str]] = []
        for action, key in self._bindings.items():
            if not key.strip():
                continue  # cleared in Settings: unbound
            parsed = parse_hotkey(key)
            if parsed is None:
                unknown.append((action, key))
            else:
                combos.append((action, *parsed))

        self._thread = _HotkeyThread(combos, self._emit_action, self._report_taken)
        self._thread.start()
        self._thread.ready.wait(timeout=2.0)
        if unknown:
            logger.warning("Unrecognized hotkeys: %s", unknown)
            self.registration_failed.emit(unknown)
        logger.info("Hotkeys registered: %s", self._bindings)

    def stop(self) -> None:
        """Unregister all hotkeys."""
        if self._thread is None:
            return
        self._thread.stop()
        self._thread = None
        logger.info("Hotkeys unregistered")

    def update_bindings(
        self,
        increment_key: str,
        decrement_key: str,
        undo_key: str,
        toggle_overlay_key: str,
        calibrate_key: str = "f8",
        pause_detection_key: str = "ctrl+f8",
    ) -> None:
        """Stop, rebind, and restart hotkeys with new key combinations."""
        was_active = self._thread is not None
        self.stop()
        self._bindings = {
            "increment": increment_key,
            "decrement": decrement_key,
            "undo": undo_key,
            "toggle_overlay": toggle_overlay_key,
            "calibrate": calibrate_key,
            "pause_detection": pause_detection_key,
        }
        if was_active:
            self.start()

    def _emit_action(self, action: str) -> None:
        # Called on the listener thread; Qt queues the signal to the main thread.
        self._signals[action].emit()

    def _report_taken(self, actions: list[str]) -> None:
        taken = [(action, self._bindings[action]) for action in actions]
        logger.warning("Hotkeys already in use by another program: %s", taken)
        self.registration_failed.emit(taken)
