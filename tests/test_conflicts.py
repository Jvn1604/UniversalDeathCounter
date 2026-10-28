"""Tests for keybind conflict detection."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hotkeys.conflicts import ERROR, WARNING, find_conflicts, has_errors  # noqa: E402

LABELS = {"increment": "+1 Death", "undo": "Undo", "overlay": "Toggle Overlay"}


def _check(keys=None, pads=None, available=lambda _k: True):
    keys = {"increment": "", "undo": "", "overlay": "", **(keys or {})}
    pads = {"increment": "", "undo": "", "overlay": "", **(pads or {})}
    return find_conflicts(keys, pads, LABELS, available)


def test_clean_bindings_have_no_conflicts() -> None:
    assert _check({"increment": "f9", "undo": "ctrl+z"}, {"increment": "back+dpad_up"}) == []


def test_duplicate_key_is_an_error_even_with_different_spelling() -> None:
    conflicts = _check({"increment": "ctrl+f9", "undo": "control+F9"})
    assert [(c.action, c.severity) for c in conflicts] == [("undo", ERROR)]
    assert "+1 Death" in conflicts[0].message


def test_plain_typing_keys_are_errors_but_modified_ones_are_fine() -> None:
    assert [c.action for c in _check({"increment": "a"})] == ["increment"]
    assert has_errors(_check({"undo": "space"}))
    assert _check({"increment": "ctrl+a", "undo": "alt+space", "overlay": "f7"}) == []
    assert _check({"increment": "shift+a"})[0].severity == ERROR  # Shift alone still types


def test_unsupported_key_is_an_error() -> None:
    conflicts = _check({"increment": "hyper+f9"})
    assert conflicts[0].severity == ERROR and "can't be used" in conflicts[0].message


def test_key_taken_by_another_program_is_a_warning() -> None:
    conflicts = _check({"overlay": "f12"}, available=lambda key: key != "f12")
    assert [(c.action, c.severity) for c in conflicts] == [("overlay", WARNING)]
    assert not has_errors(conflicts)


def test_duplicate_controller_combo_is_an_error() -> None:
    conflicts = _check(pads={"increment": "back+dpad_up", "undo": "dpad_up+back"})
    assert [(c.action, c.kind, c.severity) for c in conflicts] == [
        ("undo", "controller", ERROR)
    ]


def test_overlapping_controller_combos_warn() -> None:
    conflicts = _check(pads={"increment": "back+dpad_up", "undo": "back+lb+dpad_up"})
    assert [(c.severity, c.kind) for c in conflicts] == [(WARNING, "controller")]
    assert "+1 Death's combo is part of Undo's" in conflicts[0].message
