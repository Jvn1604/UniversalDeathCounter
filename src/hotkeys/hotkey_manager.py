"""
Global hotkey listener.

Uses the third-party ``keyboard`` library to capture key presses even when
another application (i.e. the game itself) has focus. Because ``keyboard``
runs its own listener thread and calls callbacks from that thread, this
module bridges those callbacks back into Qt's main thread via signals,
which is required for safely touching Qt widgets.

Note: on Linux, ``keyboard`` typically requires root privileges to read
the global input device; on Windows it works for the current user. This
is a known OS-level limitation of the library itself, not a bug here.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from src.utils.logger import get_logger

try:
    import keyboard  # type: ignore[import-untyped]

    _KEYBOARD_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    _KEYBOARD_AVAILABLE = False

logger = get_logger(__name__)


class HotkeyManager(QObject):
    """
    Registers global hotkeys and emits Qt signals when they fire.

    Signals:
        increment_triggered: Emitted when the +1 death hotkey is pressed.
        decrement_triggered: Emitted when the -1 death hotkey is pressed.
        undo_triggered: Emitted when the undo hotkey is pressed.
        toggle_overlay_triggered: Emitted when the overlay-toggle hotkey
            is pressed.
    """

    increment_triggered = Signal()
    decrement_triggered = Signal()
    undo_triggered = Signal()
    toggle_overlay_triggered = Signal()

    def __init__(
        self,
        increment_key: str,
        decrement_key: str,
        undo_key: str,
        toggle_overlay_key: str,
        parent: QObject | None = None,
    ) -> None:
        """
        Args:
            increment_key: Key name (``keyboard`` syntax) for +1 death.
            decrement_key: Key name for -1 death.
            undo_key: Key name for undo.
            toggle_overlay_key: Key name for toggling the overlay.
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self._bindings: dict[str, str] = {
            "increment": increment_key,
            "decrement": decrement_key,
            "undo": undo_key,
            "toggle_overlay": toggle_overlay_key,
        }
        self._registered_hooks: list[object] = []
        self._active = False

        if not _KEYBOARD_AVAILABLE:
            logger.warning(
                "The 'keyboard' package is not installed/available; "
                "global hotkeys are disabled. In-app buttons still work."
            )

    def start(self) -> None:
        """Register all hotkeys with the OS-level listener."""
        if not _KEYBOARD_AVAILABLE or self._active:
            return
        try:
            self._register("increment", self.increment_triggered)
            self._register("decrement", self.decrement_triggered)
            self._register("undo", self.undo_triggered)
            self._register("toggle_overlay", self.toggle_overlay_triggered)
            self._active = True
            logger.info("Hotkeys registered: %s", self._bindings)
        except Exception:  # noqa: BLE001 - hotkey registration is best-effort
            logger.exception("Failed to register global hotkeys")

    def stop(self) -> None:
        """Unregister all previously registered hotkeys."""
        if not _KEYBOARD_AVAILABLE or not self._active:
            return
        for hook in self._registered_hooks:
            try:
                keyboard.remove_hotkey(hook)
            except (KeyError, ValueError):
                pass
        self._registered_hooks.clear()
        self._active = False
        logger.info("Hotkeys unregistered")

    def update_bindings(
        self, increment_key: str, decrement_key: str, undo_key: str, toggle_overlay_key: str
    ) -> None:
        """Stop, rebind, and restart hotkeys with new key combinations."""
        was_active = self._active
        self.stop()
        self._bindings = {
            "increment": increment_key,
            "decrement": decrement_key,
            "undo": undo_key,
            "toggle_overlay": toggle_overlay_key,
        }
        if was_active:
            self.start()

    def _register(self, action: str, signal: Signal) -> None:
        """Register a single hotkey, wiring it to emit ``signal``."""
        key = self._bindings[action]
        hook = keyboard.add_hotkey(key, signal.emit)
        self._registered_hooks.append(hook)
