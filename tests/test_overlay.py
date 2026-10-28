"""The overlay must actually paint its background (OBS chroma key relies on it)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.overlay.overlay_window import CHROMA_GREEN, OverlayWindow  # noqa: E402


def _corner_inside(overlay: OverlayWindow):
    image = overlay.grab().toImage()
    return image.pixelColor(image.width() // 2, image.height() - 6)  # below the text


def test_chroma_mode_paints_solid_green() -> None:
    """Regression: the stylesheet background was ignored, so the green never showed."""
    overlay = OverlayWindow()
    overlay.apply_display_settings({"overlay_bg_mode": "chroma"})
    color = _corner_inside(overlay)
    assert color.name() == CHROMA_GREEN
    assert color.alpha() == 255


def test_dark_mode_paints_translucent_card() -> None:
    overlay = OverlayWindow()
    overlay.apply_display_settings({"overlay_bg_mode": "dark", "overlay_opacity": "0.85"})
    color = _corner_inside(overlay)
    assert color.alpha() > 150  # a visible card, not fully transparent
    assert max(color.red(), color.green(), color.blue()) < 60  # and it is dark
