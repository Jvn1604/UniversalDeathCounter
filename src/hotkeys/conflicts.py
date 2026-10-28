"""
Binding conflict detection for the Controls editor.

Pure logic (the only OS call is injected as ``key_available``), so every
rule is unit tested:

* **error** (blocks saving):
  - two actions share a keyboard key or a controller combo;
  - a plain typing key (a letter, digit, Space, Enter…) without Ctrl/Alt/
    Win: global hotkeys are consumed system-wide, so it could no longer
    be typed anywhere;
  - a key that isn't supported as a global hotkey.
* **warning** (allowed, but shown):
  - another program already registered the key (it won't fire until that
    program releases it);
  - one controller combo contains another (pressing the buttons in some
    orders can trigger the smaller one first).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.hotkeys.gamepad import combo_label, parse_combo
from src.hotkeys.hotkey_manager import parse_hotkey

ERROR = "error"
WARNING = "warning"

_MOD_CTRL_ALT_WIN = 0x0001 | 0x0002 | 0x0008

# Virtual keys that type text or move the caret.
_TYPING_KEYS: frozenset[int] = frozenset(
    [*range(0x30, 0x3A), *range(0x41, 0x5B)]  # digits, letters
    + [0x08, 0x09, 0x0D, 0x1B, 0x20]  # backspace, tab, enter, esc, space
    + [*range(0x21, 0x29), 0x2D, 0x2E]  # page/home/end/arrows, ins, del
    + [0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE]  # punctuation
)


@dataclass(slots=True, frozen=True)
class Conflict:
    """One problem with one action's binding."""

    action: str
    kind: str  # "keyboard" or "controller"
    severity: str  # ERROR or WARNING
    message: str


def find_conflicts(
    keys: dict[str, str],
    pads: dict[str, str],
    labels: dict[str, str],
    key_available: Callable[[str], bool] = lambda _key: True,
) -> list[Conflict]:
    """
    Check every binding.

    Args:
        keys: action -> keyboard combo text ("" = unbound).
        pads: action -> controller combo text ("" = unbound).
        labels: action -> display name.
        key_available: returns False if another program holds the key.
    """
    conflicts: list[Conflict] = []

    seen_keys: dict[tuple[int, int], str] = {}
    for action, key in keys.items():
        if not key:
            continue
        parsed = parse_hotkey(key)
        shown = key.upper()
        if parsed is None:
            conflicts.append(Conflict(
                action, "keyboard", ERROR, f"{shown} can't be used as a global hotkey."
            ))
            continue
        modifiers, vk = parsed
        if parsed in seen_keys:
            other = labels[seen_keys[parsed]]
            conflicts.append(Conflict(
                action, "keyboard", ERROR, f"{shown} is already used by {other}."
            ))
            continue
        seen_keys[parsed] = action
        if vk in _TYPING_KEYS and not modifiers & _MOD_CTRL_ALT_WIN:
            conflicts.append(Conflict(
                action, "keyboard", ERROR,
                f"{shown} alone would stop you typing it in every app. Add Ctrl or Alt.",
            ))
        elif not key_available(key):
            conflicts.append(Conflict(
                action, "keyboard", WARNING,
                f"{shown} is taken by another program, so it won't work while that runs.",
            ))

    seen_pads: dict[frozenset[str], str] = {}
    for action, text in pads.items():
        combo = parse_combo(text)
        if not combo:
            continue
        if combo in seen_pads:
            other = labels[seen_pads[combo]]
            conflicts.append(Conflict(
                action, "controller", ERROR,
                f"{combo_label(text)} is already used by {other}.",
            ))
            continue
        for other_combo, other_action in seen_pads.items():
            if combo < other_combo or other_combo < combo:
                smaller, larger = sorted(
                    ((combo, action), (other_combo, other_action)), key=lambda c: len(c[0])
                )
                conflicts.append(Conflict(
                    action, "controller", WARNING,
                    f"{labels[smaller[1]]}'s combo is part of {labels[larger[1]]}'s, so it "
                    "can fire by accident. Prefer combos that don't overlap.",
                ))
        seen_pads[combo] = action
    return conflicts


def has_errors(conflicts: list[Conflict]) -> bool:
    return any(c.severity == ERROR for c in conflicts)
