"""Fonts, colors and background images for the main window and the overlay."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPixmap  # noqa: E402

from src.themes.theme_manager import customize_stylesheet, load_stylesheet  # noqa: E402
from src.utils.backgrounds import (  # noqa: E402
    MAX_IMAGE_SIDE,
    cover,
    import_background,
    load_background,
)


def _image(path: Path, width: int, height: int, alpha: bool = False) -> Path:
    fmt = QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32
    image = QImage(width, height, fmt)
    image.fill(QColor(120, 30, 200, 128 if alpha else 255))
    assert image.save(str(path))
    return path


def test_import_copies_and_reuses_the_same_image(tmp_path) -> None:
    source = _image(tmp_path / "wallpaper.png", 800, 450)
    dest = tmp_path / "backgrounds"
    first = import_background(source, dest)
    assert first.parent == dest and first.suffix == ".jpg"  # opaque → JPEG
    source.unlink()  # the copy keeps working after the original is gone
    assert load_background(str(first)) is not None
    again = import_background(_image(tmp_path / "copy.png", 800, 450), dest)
    assert again == first


def test_import_keeps_transparency_and_downscales_huge_images(tmp_path) -> None:
    dest = tmp_path / "backgrounds"
    clear = import_background(_image(tmp_path / "a.png", 300, 100, alpha=True), dest)
    assert clear.suffix == ".png"
    huge = import_background(_image(tmp_path / "huge.png", MAX_IMAGE_SIDE * 2, 1000), dest)
    assert max(QImage(str(huge)).width(), QImage(str(huge)).height()) == MAX_IMAGE_SIDE


def test_import_rejects_non_images(tmp_path) -> None:
    bogus = tmp_path / "notes.png"
    bogus.write_text("not an image", encoding="utf-8")
    with pytest.raises(ValueError):
        import_background(bogus, tmp_path / "backgrounds")
    assert load_background("") is None
    assert load_background(str(tmp_path / "missing.png")) is None


def test_cover_fills_the_area_exactly(tmp_path) -> None:
    pixmap = QPixmap(str(_image(tmp_path / "wide.png", 400, 100)))
    assert cover(pixmap, QSize(200, 200)).size() == QSize(200, 200)


def test_stylesheet_font_and_see_through() -> None:
    base = load_stylesheet("dark")
    custom = customize_stylesheet(base, "dark", font_family="Consolas", see_through=True)
    first_rule = custom.split("}", 1)[0]
    assert "background-color: transparent;" in first_rule
    assert 'QWidget { font-family: "Consolas"; }' in custom
    # Buttons and the counter card keep their own backgrounds.
    assert "background-color: #2f3136;" in custom
    assert "background-color: #27292d;" in custom
    light = customize_stylesheet(load_stylesheet("light"), "light", see_through=True)
    assert "background-color: transparent;" in light.split("}", 1)[0]


def test_overlay_applies_font_colors_image_and_outline(tmp_path) -> None:
    from src.overlay.overlay_window import OverlayWindow

    image = import_background(_image(tmp_path / "card.png", 600, 300), tmp_path / "bg")
    overlay = OverlayWindow()
    overlay.apply_display_settings(
        {
            "overlay_bg_mode": "image",
            "overlay_background_image": str(image),
            "overlay_font": "Consolas",
            "overlay_secondary_color": "#ffcc00",
            "overlay_card_color": "#223344",
            "overlay_corner_radius": "30",
            "overlay_text_outline": "true",
        }
    )
    assert overlay._bg_image is not None
    assert overlay._corner_radius == 30
    assert overlay._card_color == QColor("#223344")
    assert 'font-family: "Consolas";' in overlay._death_label.styleSheet()
    assert "#ffcc00" in overlay._game_label.styleSheet()
    assert overlay._death_label.graphicsEffect() is not None
    overlay.resize(280, 150)
    overlay.grab()  # paints the image mode without errors

    overlay.apply_display_settings({"overlay_text_outline": "false", "overlay_card_color": "bad"})
    assert overlay._death_label.graphicsEffect() is None
    assert overlay._card_color == QColor("#141416")  # invalid color → default
    overlay.close()


def test_settings_appearance_round_trip(tmp_path) -> None:
    from src.database.database import Database
    from src.ui.settings_window import SettingsWindow

    db = Database(tmp_path / "test.db")
    try:
        image = import_background(_image(tmp_path / "bg.png", 640, 360), tmp_path / "bg")
        db.set_setting("ui_background_image", str(image))
        db.set_setting("overlay_bg_mode", "image")
        dialog = SettingsWindow(db)
        assert dialog._bg_mode_combo.currentData() == "image"
        assert dialog._ui_bg_image.path() == str(image)
        dialog._ui_bg_dim.setValue(35)
        dialog._radius_spin.setValue(4)
        dialog._outline_check.setChecked(True)
        font_index = dialog._overlay_font_combo.count() - 1
        dialog._overlay_font_combo.setCurrentIndex(font_index)
        changed: list[bool] = []
        dialog.settings_changed.connect(lambda: changed.append(True))
        assert dialog._apply()  # Apply saves without closing
        assert changed == [True]
        assert db.get_setting("ui_background_dim") == "35"
        assert db.get_setting("overlay_corner_radius") == "4"
        assert db.get_setting("overlay_text_outline") == "true"
        assert db.get_setting("overlay_font") == dialog._overlay_font_combo.itemData(font_index)
        assert db.get_setting("overlay_bg_mode") == "image"
        dialog.close()
    finally:
        db.close()
