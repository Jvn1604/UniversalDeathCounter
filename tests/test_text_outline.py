"""Overlay text keeps a solid black outline on bright scenes (BUG-007)."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect

from src.overlay.capture_window import OutlineEffect
from src.overlay.overlay_window import OverlayWindow


def test_new_installs_get_the_outline_and_every_choice_applies() -> None:
    overlay = OverlayWindow()
    overlay.apply_display_settings({})
    assert overlay.text_edge == "outline"
    assert isinstance(overlay._death_label.graphicsEffect(), OutlineEffect)
    assert isinstance(overlay._skull_label.graphicsEffect(), OutlineEffect)
    overlay.apply_display_settings({"overlay_text_outline": "true"})
    assert isinstance(overlay._death_label.graphicsEffect(), QGraphicsDropShadowEffect)
    overlay.apply_display_settings({"overlay_text_outline": "false"})
    assert overlay._death_label.graphicsEffect() is None
    overlay.close()


def test_the_outline_draws_black_around_white_text() -> None:
    overlay = OverlayWindow()
    overlay.apply_display_settings({"overlay_bg_mode": "transparent",
                                    "overlay_text_color": "#ffffff",
                                    "overlay_font_size": "40"})
    overlay._death_label.setText("DEATH - 4")
    overlay._death_label.adjustSize()
    image = overlay._death_label.grab().toImage()
    colors = {QColor(image.pixel(x, y)).name() for x in range(0, image.width(), 2)
              for y in range(0, image.height(), 2) if QColor(image.pixelColor(x, y)).alpha() > 200}
    assert "#000000" in colors and "#ffffff" in colors
    overlay.close()
