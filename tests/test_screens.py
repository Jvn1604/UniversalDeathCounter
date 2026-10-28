"""Tests for multi-monitor placement and capture clipping (made-up layouts)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect  # noqa: E402

from src.detection.game_window import clip_to_desktop, monitor_at  # noqa: E402
from src.utils.screens import (  # noqa: E402
    display_name,
    fit_to_screens,
    place_in_corner,
    screen_index_at,
)

# Primary 2560x1600 at the origin, a 1920x1080 display to its LEFT
# (negative x), as Windows reports when the second screen is arranged left.
PRIMARY = QRect(0, 0, 2560, 1560)  # available area (taskbar excluded)
LEFT = QRect(-1920, 200, 1920, 1040)
OVERLAY = QRect(0, 0, 300, 160)


def test_overlay_on_a_connected_display_stays_put() -> None:
    on_left = QRect(-1500, 400, 300, 160)
    assert fit_to_screens(on_left, [PRIMARY, LEFT]) == on_left


def test_overlay_on_an_unplugged_display_moves_to_primary() -> None:
    was_on_left = QRect(-1500, 400, 300, 160)
    fitted = fit_to_screens(was_on_left, [PRIMARY])  # left display unplugged
    assert PRIMARY.contains(fitted)
    assert fitted.size() == was_on_left.size()


def test_mostly_off_screen_overlay_is_pulled_back() -> None:
    hanging = QRect(2500, 100, 300, 160)  # only 60 px of 300 visible
    assert PRIMARY.contains(fit_to_screens(hanging, [PRIMARY, LEFT]))


def test_window_straddling_two_displays_is_left_alone() -> None:
    straddling = QRect(-100, 400, 300, 160)  # 1/3 left, 2/3 primary
    assert fit_to_screens(straddling, [PRIMARY, LEFT]) == straddling


def test_place_in_corner_uses_top_right_and_fits_small_screens() -> None:
    placed = place_in_corner(OVERLAY, LEFT)
    assert LEFT.contains(placed)
    assert placed.right() == LEFT.right() - 24 and placed.top() == LEFT.top() + 24
    tiny = QRect(0, 0, 200, 100)
    assert tiny.contains(place_in_corner(QRect(0, 0, 900, 900), tiny))


def test_screen_index_at() -> None:
    assert screen_index_at(QRect(-1000, 500, 100, 100), [PRIMARY, LEFT]) == 1
    assert screen_index_at(QRect(9000, 9000, 10, 10), [PRIMARY, LEFT]) is None


def test_display_name() -> None:
    assert display_name(1, (1920, 1080), False) == "Display 2: 1920×1080"
    assert display_name(0, (2560, 1600), True) == "Display 1: 2560×1600 (primary)"


# ----------------------------------------------------------------
# Capture across displays
# ----------------------------------------------------------------
DESKTOP = (-1920, 0, 1920 + 2560, 1600)  # bounding box of both displays


def test_game_on_left_display_is_captured_as_is() -> None:
    game = (-1920, 200, 1920, 1080)
    assert clip_to_desktop(game, DESKTOP) == game


def test_window_hanging_off_the_desktop_is_clipped() -> None:
    assert clip_to_desktop((2000, 1000, 1280, 720), DESKTOP) == (2000, 1000, 560, 600)
    assert clip_to_desktop((5000, 0, 100, 100), DESKTOP) is None


def test_monitor_at_cursor() -> None:
    monitors = [
        {"left": 0, "top": 0, "width": 2560, "height": 1600},
        {"left": -1920, "top": 200, "width": 1920, "height": 1080},
    ]
    assert monitor_at(monitors, -500, 600) is monitors[1]
    assert monitor_at(monitors, 100, 100) is monitors[0]
    assert monitor_at(monitors, -500, 50) is monitors[0]  # gap above left display
