"""Tests for global hotkeys: combo parsing and the Windows message loop."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hotkeys.hotkey_manager import HotkeyManager, parse_hotkey  # noqa: E402

ALT, CTRL, SHIFT, WIN = 0x1, 0x2, 0x4, 0x8


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("f9", (0, 0x78)),
        ("F12", (0, 0x7B)),
        ("ctrl+f12", (CTRL, 0x7B)),
        ("ctrl+shift+d", (CTRL | SHIFT, ord("D"))),
        ("alt+5", (ALT, ord("5"))),
        ("meta+space", (WIN, 0x20)),
        ("num+5", (0, 0x65)),
        ("pgdown", (0, 0x22)),
        ("shift+-", (SHIFT, 0xBD)),
    ],
)
def test_parse_hotkey(text: str, expected: tuple[int, int]) -> None:
    assert parse_hotkey(text) == expected


@pytest.mark.parametrize("text", ["", "ctrl+", "hyper+f9", "f25", "ctrl+é"])
def test_parse_hotkey_rejects_unknown(text: str) -> None:
    assert parse_hotkey(text) is None


@pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey is Windows-only")
def test_hotkey_message_reaches_signal_and_unregisters() -> None:
    import ctypes

    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    # Obscure combos so the test never clashes with real hotkeys.
    manager = HotkeyManager(
        increment_key="ctrl+alt+shift+f20",
        decrement_key="ctrl+alt+shift+f21",
        undo_key="ctrl+alt+shift+f22",
        toggle_overlay_key="ctrl+alt+shift+f23",
        calibrate_key="ctrl+alt+shift+f24",
        pause_detection_key="ctrl+alt+shift+f19",
    )
    fired: list[str] = []
    failed: list = []
    manager.increment_triggered.connect(lambda: fired.append("increment"))
    manager.undo_triggered.connect(lambda: fired.append("undo"))
    manager.registration_failed.connect(failed.extend)
    manager.start()
    try:
        thread_id = manager._thread._thread_id
        user32 = ctypes.windll.user32
        user32.PostThreadMessageW(thread_id, 0x0312, 1, 0)  # WM_HOTKEY, id 1 = increment
        user32.PostThreadMessageW(thread_id, 0x0312, 3, 0)  # id 3 = undo
        deadline = time.monotonic() + 2
        while len(fired) < 2 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert fired == ["increment", "undo"]
        assert failed == []
    finally:
        manager.stop()
    # After stop the combo is free again for other programs.
    assert ctypes.windll.user32.RegisterHotKey(None, 99, 0x2 | 0x1 | 0x4, 0x83)
    ctypes.windll.user32.UnregisterHotKey(None, 99)
