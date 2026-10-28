"""Tests for controller bindings: button mapping, combos, and the listener loop."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hotkeys import gamepad  # noqa: E402
from src.hotkeys.gamepad import (  # noqa: E402
    ComboRecorder,
    ComboTracker,
    combo_label,
    combo_text,
    dpad_from_pov,
    parse_combo,
    winmm_buttons,
    xinput_buttons,
)

SONY, NINTENDO = 0x054C, 0x057E


# ----------------------------------------------------------------
# Names, parsing, labels
# ----------------------------------------------------------------
def test_parse_and_store_combo_in_stable_order() -> None:
    assert parse_combo("dpad_up+back") == {"back", "dpad_up"}
    assert combo_text({"dpad_up", "back"}) == "back+dpad_up"
    assert combo_text({"south", "lb", "start"}) == "start+lb+south"
    assert parse_combo("button7+back") == {"button7", "back"}


@pytest.mark.parametrize("text", ["", "back+", "back+jump", "buttonX"])
def test_parse_combo_rejects_unknown(text: str) -> None:
    assert parse_combo(text) == (frozenset() if text != "back+" else {"back"})


def test_labels_show_xbox_and_playstation_names() -> None:
    assert combo_label("back+dpad_up") == "View/Share + D-pad Up"
    assert combo_label("lb+rb") == "LB/L1 + RB/R1"
    assert combo_label("start+button13") == "Menu/Options + Button 13"
    assert combo_label("") == ""


# ----------------------------------------------------------------
# Hardware mappings
# ----------------------------------------------------------------
def test_xinput_buttons_and_triggers() -> None:
    assert xinput_buttons(0x0020 | 0x0001, 0, 0) == {"back", "dpad_up"}
    assert xinput_buttons(0x1000 | 0x8000, 0, 0) == {"south", "north"}
    assert xinput_buttons(0, 200, 50) == {"lt"}  # right trigger below threshold


def test_playstation_buttons_map_to_shared_names() -> None:
    cross, share, options, ps = 1 << 1, 1 << 8, 1 << 9, 1 << 12
    assert winmm_buttons(cross | share, 0xFFFF, SONY) == {"south", "back"}
    assert winmm_buttons(options | ps, 0xFFFF, SONY) == {"start", "guide"}


def test_generic_controller_uses_numbered_buttons() -> None:
    assert winmm_buttons(1 | (1 << 6), 0xFFFF, NINTENDO) == {"button1", "button7"}


@pytest.mark.parametrize(
    ("pov", "expected"),
    [
        (0xFFFF, set()),
        (0, {"dpad_up"}),
        (4500, {"dpad_up", "dpad_right"}),
        (9000, {"dpad_right"}),
        (18000, {"dpad_down"}),
        (27000, {"dpad_left"}),
        (31500, {"dpad_up", "dpad_left"}),
    ],
)
def test_pov_hat_to_dpad(pov: int, expected: set[str]) -> None:
    assert dpad_from_pov(pov) == expected


# ----------------------------------------------------------------
# Combo firing and recording
# ----------------------------------------------------------------
def test_combo_fires_once_per_press() -> None:
    tracker = ComboTracker({"increment": "back+dpad_up"})
    assert tracker.update({"back"}) == []
    assert tracker.update({"back", "dpad_up"}) == ["increment"]
    assert tracker.update({"back", "dpad_up"}) == []  # still held: no repeat
    assert tracker.update({"back", "dpad_up", "south"}) == []  # extra button: no repeat
    assert tracker.update({"back"}) == []
    assert tracker.update({"back", "dpad_up"}) == ["increment"]  # pressed again


def test_larger_combo_wins_over_its_subset() -> None:
    tracker = ComboTracker({"increment": "back+dpad_up", "undo": "back+lb+dpad_up"})
    tracker.update({"back", "lb"})
    assert tracker.update({"back", "lb", "dpad_up"}) == ["undo"]


def test_unbound_actions_never_fire() -> None:
    tracker = ComboTracker({"increment": "", "undo": "lb+rb"})
    assert tracker.update({"lb", "rb"}) == ["undo"]


def test_recorder_returns_peak_combo_after_release() -> None:
    recorder = ComboRecorder()
    assert recorder.update({"back"}) is None
    assert recorder.update({"back", "dpad_up"}) is None
    assert recorder.update({"dpad_up"}) is None  # releasing one by one
    assert recorder.update(set()) == {"back", "dpad_up"}
    assert recorder.update(set()) is None  # nothing pressed since


# ----------------------------------------------------------------
# Listener thread with a fake controller
# ----------------------------------------------------------------
class _FakeBackends:
    frames: list[set[str]] = []

    def __init__(self) -> None:
        self._index = 0

    def connected(self) -> bool:
        return True

    def held(self) -> set[str]:
        frame = self.frames[min(self._index, len(self.frames) - 1)]
        self._index += 1
        return frame


def _run_manager(monkeypatch, frames, bindings, record=False):
    from PySide6.QtCore import QCoreApplication

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(gamepad, "_Backends", _FakeBackends)
    _FakeBackends.frames = frames
    app = QCoreApplication.instance() or QCoreApplication([])
    manager = gamepad.GamepadManager(bindings)
    actions: list[str] = []
    recorded: list[str] = []
    manager.action_triggered.connect(actions.append)
    manager.combo_recorded.connect(recorded.append)
    if record:
        manager.start_recording()
    manager.start()
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    manager.stop()
    app.processEvents()
    return manager, actions, recorded


def test_manager_emits_bound_action(monkeypatch) -> None:
    frames = [set(), {"back"}, {"back", "dpad_up"}, {"back", "dpad_up"}, set()]
    manager, actions, _ = _run_manager(monkeypatch, frames, {"increment": "back+dpad_up"})
    assert actions == ["increment"]
    assert manager.connected


def test_manager_recording_captures_combo_without_firing(monkeypatch) -> None:
    frames = [set(), {"lb"}, {"lb", "rb"}, set(), set()]
    _, actions, recorded = _run_manager(monkeypatch, frames, {"undo": "lb+rb"}, record=True)
    assert recorded == ["lb+rb"]
    assert actions == []
