"""The drawn overlay designs take the player's colours and font, and repaint cheaply."""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from src.overlay.designs import DesignStyle, paint_design, render_png, style_from_settings
from src.utils.constants import (
    SETTING_OVERLAY_DESIGN,
    SETTING_OVERLAY_DESIGN_ACCENT,
    SETTING_OVERLAY_DESIGN_FONT,
    SETTING_OVERLAY_DESIGN_NUMBER,
    SETTING_OVERLAY_DESIGN_WORD,
)

_DRAWN = ("seal", "neon", "tombstone", "banner")


def _draw(design: str, style: DesignStyle) -> QImage:
    image = QImage(380, 320, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    paint_design(painter, QRectF(image.rect()), design, "DEATH", 47, True, style)
    painter.end()
    return image


def test_style_from_settings_reads_every_touch() -> None:
    style = style_from_settings({
        SETTING_OVERLAY_DESIGN_ACCENT: "#2f7bff",
        SETTING_OVERLAY_DESIGN_NUMBER: "#ffd400",
        SETTING_OVERLAY_DESIGN_WORD: "#00ff00",
        SETTING_OVERLAY_DESIGN_FONT: "Arial",
    })
    assert style == DesignStyle("#2f7bff", "#ffd400", "#00ff00", "Arial")
    assert style_from_settings({}) == DesignStyle()


def test_empty_or_bad_colour_falls_back_to_the_designs_own() -> None:
    style = DesignStyle(accent="not a colour")
    assert style.color(style.accent, "#c4161c").name() == "#c4161c"
    assert style.color("", "#123456").name() == "#123456"
    assert style.families(["Segoe UI"]) == ["Segoe UI"]
    assert DesignStyle(font="Arial").families(["Segoe UI"]) == ["Arial"]


def test_every_design_changes_with_each_colour() -> None:
    for design in _DRAWN:
        own = _draw(design, DesignStyle())
        for field in ("accent", "number", "word"):
            touched = _draw(design, DesignStyle(**{field: "#00ff00"}))
            assert touched != own, (design, field)


def test_the_default_style_draws_as_before() -> None:
    for design in _DRAWN:
        assert render_png(design, "DEATH", 5) == render_png(design, "DEATH", 5, style=DesignStyle())


def test_overlay_draws_the_design_once_per_change() -> None:
    from src.overlay.overlay_window import OverlayWindow

    overlay = OverlayWindow()
    overlay.resize(380, 200)
    overlay.apply_display_settings({SETTING_OVERLAY_DESIGN: "seal"})
    first = overlay._design_pixmap()
    assert overlay._design_pixmap() is first  # just copied on the next repaint
    overlay.apply_display_settings({SETTING_OVERLAY_DESIGN: "seal",
                                    SETTING_OVERLAY_DESIGN_ACCENT: "#2f7bff"})
    assert overlay.design_style.accent == "#2f7bff"
    assert overlay._design_pixmap() is not first
    overlay.deleteLater()
