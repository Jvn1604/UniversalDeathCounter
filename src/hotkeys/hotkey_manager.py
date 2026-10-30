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
reports.

macOS (Carbon hot keys, :mod:`src.hotkeys.mac_hotkeys`) and Linux (X11 key
grabs, :mod:`src.hotkeys.x11_hotkeys`) work the same way: only the bound
combos are ever seen. A Linux session without X11 (pure Wayland) has no
global hotkeys; the in-app buttons, phone remote and controller still work.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from src.utils.logger import get_logger
from src.utils.platform_info import IS_LINUX, IS_MAC, IS_WINDOWS

if IS_WINDOWS:
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
        self.held_combos: set[tuple[int, int]] = set()  # (modifiers, vk) we registered

    def run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        registered: list[int] = []
        failed: list[str] = []
        for hotkey_id, (action, modifiers, vk) in enumerate(self._combos, start=1):
            if _user32.RegisterHotKey(None, hotkey_id, modifiers | _MOD_NOREPEAT, vk):
                registered.append(hotkey_id)
                self.held_combos.add((modifiers, vk))
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


def global_hotkeys_available() -> bool:
    """Whether this OS session lets the app listen for keys while a game has focus."""
    if IS_WINDOWS:
        return True
    if IS_MAC:
        from src.hotkeys import mac_hotkeys

        return mac_hotkeys.available()
    if IS_LINUX:
        from src.hotkeys import x11_hotkeys

        return x11_hotkeys.available()
    return False


def _make_listener(combos, on_hotkey, on_failed):
    """This OS's listener: has start(), stop(), ready and held_combos."""
    if IS_MAC:
        from src.hotkeys.mac_hotkeys import MacHotkeys

        return MacHotkeys(combos, on_hotkey, on_failed)
    if IS_LINUX:
        from src.hotkeys.x11_hotkeys import X11HotkeyThread

        return X11HotkeyThread(combos, on_hotkey, on_failed)
    return _HotkeyThread(combos, on_hotkey, on_failed)


def _probe(modifiers: int, vk: int) -> bool:
    if IS_MAC:
        from src.hotkeys import mac_hotkeys

        return mac_hotkeys.probe(modifiers, vk)
    if IS_LINUX:
        from src.hotkeys import x11_hotkeys

        return x11_hotkeys.probe(modifiers, vk)
    probe_id = 0xBFFF  # top of the application hotkey id range
    if not _user32.RegisterHotKey(None, probe_id, modifiers | _MOD_NOREPEAT, vk):
        return False
    _user32.UnregisterHotKey(None, probe_id)
    return True


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
        action_triggered: Emitted with the action name for every hotkey,
            including actions without a dedicated signal (e.g. the timer's).
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
    prev_boss_triggered = Signal()
    next_boss_triggered = Signal()
    action_triggered = Signal(str)
    registration_failed = Signal(list)

    def __init__(self, parent: QObject | None = None, **keys: str) -> None:
        """
        Args:
            parent: Optional Qt parent object.
            **keys: One ``<action>_key`` combo per action, e.g.
                ``increment_key="f9"`` or ``timer_split_key="num+1"``.
                "" leaves that action unbound.
        """
        super().__init__(parent)
        self._bindings: dict[str, str] = self._parse_bindings(keys)
        self._signals: dict[str, Signal] = {
            "increment": self.increment_triggered,
            "decrement": self.decrement_triggered,
            "undo": self.undo_triggered,
            "toggle_overlay": self.toggle_overlay_triggered,
            "calibrate": self.calibrate_triggered,
            "pause_detection": self.pause_detection_triggered,
            "prev_boss": self.prev_boss_triggered,
            "next_boss": self.next_boss_triggered,
        }
        self._thread = None  # this OS's listener (see _make_listener)

        if not global_hotkeys_available():
            logger.warning("No global hotkeys in this session; in-app buttons still work.")

    def start(self) -> None:
        """Register all hotkeys with the OS."""
        if self._thread is not None or not global_hotkeys_available():
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

        self._thread = _make_listener(combos, self._emit_action, self._report_taken)
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

    @staticmethod
    def _parse_bindings(keys: dict[str, str]) -> dict[str, str]:
        bindings: dict[str, str] = {}
        for name, key in keys.items():
            if not name.endswith("_key"):
                raise TypeError(f"Unexpected argument {name!r}: expected <action>_key")
            bindings[name.removesuffix("_key")] = key
        return bindings

    def update_bindings(self, **keys: str) -> None:
        """Stop, rebind (same ``<action>_key`` arguments as the constructor), and restart."""
        was_active = self._thread is not None
        self.stop()
        self._bindings = self._parse_bindings(keys)
        if was_active:
            self.start()

    def _emit_action(self, action: str) -> None:
        # Called on the listener thread; Qt queues the signals to the main thread.
        signal = self._signals.get(action)
        if signal is not None:
            signal.emit()
        self.action_triggered.emit(action)

    def key_available(self, key: str) -> bool:
        """
        Whether ``key`` could be registered right now (for the Controls editor).

        Keys this manager already holds count as available. Others are
        probed by registering and immediately releasing them.
        """
        parsed = parse_hotkey(key)
        if parsed is None or not global_hotkeys_available():
            return True
        if self._thread is not None and parsed in self._thread.held_combos:
            return True
        return _probe(*parsed)

    def _report_taken(self, actions: list[str]) -> None:
        taken = [(action, self._bindings[action]) for action in actions]
        logger.warning("Hotkeys already in use by another program: %s", taken)
        self.registration_failed.emit(taken)
