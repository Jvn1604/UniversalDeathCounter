"""
Multi-monitor helpers.

Windows remember absolute positions, so a monitor being unplugged, or a
laptop leaving its dock, can strand the overlay or main window
off-screen. :func:`fit_to_screens` pulls a rectangle back onto a
connected display. The other helpers name displays and pick a corner for
the "Move Overlay to Display" menu. All of it is plain QRect math, so it
is unit tested with made-up monitor layouts.
"""

from __future__ import annotations

from PySide6.QtCore import QRect

# Fraction of a window that must be on some screen to leave it where it is.
MIN_VISIBLE_FRACTION: float = 0.5
CORNER_MARGIN: int = 24


def _visible_area(rect: QRect, screens: list[QRect]) -> int:
    return max((rect.intersected(s).width() * rect.intersected(s).height() for s in screens),
               default=0)


def fit_to_screens(rect: QRect, screens: list[QRect]) -> QRect:
    """
    Return ``rect`` unchanged if at least half of it is on one screen,
    otherwise moved (and shrunk if needed) into the first screen, which
    callers pass as the primary display.
    """
    if not screens or rect.isEmpty():
        return QRect(rect)
    if _visible_area(rect, screens) >= rect.width() * rect.height() * MIN_VISIBLE_FRACTION:
        return QRect(rect)
    return place_in_corner(rect, screens[0])


def place_in_corner(rect: QRect, screen: QRect, margin: int = CORNER_MARGIN) -> QRect:
    """Same size as ``rect`` (capped to the screen), at ``screen``'s top-right corner."""
    width = min(rect.width(), screen.width() - 2 * margin)
    height = min(rect.height(), screen.height() - 2 * margin)
    return QRect(screen.right() - margin - width + 1, screen.top() + margin, width, height)


def screen_index_at(rect: QRect, screens: list[QRect]) -> int | None:
    """Index of the screen showing most of ``rect``, or None if it's on none."""
    best, best_area = None, 0
    for index, screen in enumerate(screens):
        overlap = rect.intersected(screen)
        area = overlap.width() * overlap.height()
        if area > best_area:
            best, best_area = index, area
    return best


def display_name(index: int, size: tuple[int, int], primary: bool) -> str:
    """Menu label such as "Display 2: 1920×1080 (primary)"."""
    suffix = " (primary)" if primary else ""
    return f"Display {index + 1}: {size[0]}×{size[1]}{suffix}"
