"""Overlay designs: drawn looks for the count, on the overlay and the OBS page."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.overlay import designs  # noqa: E402


def test_every_design_draws_something() -> None:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    for name, _label in designs.DESIGNS:
        if not designs.is_design(name):
            assert name == "classic"
            continue
        png = designs.render_png(name, "DEATH", 147, width=400)
        image = QImage.fromData(png)
        assert image.width() == 400
        painted = sum(
            1 for x in range(0, image.width(), 8) for y in range(0, image.height(), 8)
            if image.pixelColor(x, y).alpha() > 0
        )
        assert painted > 50, name  # not blank
        assert image.pixelColor(0, image.height() - 1).alpha() == 0  # see-through corner


def test_the_design_word() -> None:
    assert designs.word_for("DEATH") == "Deaths"
    assert designs.word_for("TRIES") == "TRIES"
    assert designs.word_for("") == ""


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    game = win._database.create_game("Sekiro")
    win._reload_games(select_game_id=game)
    yield win
    win._quit_app()
    app.processEvents()


def test_a_design_on_the_overlay_and_the_stream_page(window) -> None:
    overlay = window._overlay
    window._toggle_overlay()
    window._set_overlay_setting("overlay_design", "seal")
    assert overlay.design == "seal"
    assert not overlay._death_label.isVisibleTo(overlay)  # the design draws it all
    window._on_increment()
    assert overlay.count_text() == "DEATH - 1"

    window._set_stream_overlay(True)
    state = window._stream.state()
    assert state["frame"].startswith("seal-1-")
    with urllib.request.urlopen(window._stream.url() + "frame.png", timeout=5) as response:
        assert response.read()[:4] == b"\x89PNG"
    with urllib.request.urlopen(window._stream.url() + "state", timeout=5) as response:
        assert json.loads(response.read())["frame"] == state["frame"]

    window._set_overlay_setting("overlay_design", "classic")
    assert overlay._death_label.isVisibleTo(overlay)
    assert window._stream.state()["frame"] == ""


def test_the_design_is_picked_in_settings(window) -> None:
    from src.ui.main_window import _PAGE_SETTINGS

    window._show_page(_PAGE_SETTINGS)
    settings = window._settings
    combo = settings._design_combo
    combo.setCurrentIndex(combo.findData("neon"))
    settings._send_preview()  # what the debounce timer does
    assert window._overlay.design == "neon"  # live, before saving
    settings._save()
    assert window._database.get_setting("overlay_design") == "neon"


def test_every_design_shows_the_evolving_skull() -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    for name, _label in designs.DESIGNS:
        if designs.is_design(name):
            # Same number of digits, another skull tier: the picture changes.
            assert designs.render_png(name, "DEATH", 15, 300) != designs.render_png(
                name, "DEATH", 25, 300
            ), name


def test_the_skull_can_be_switched_off(window, monkeypatch) -> None:
    def no_skull(*_args, **_kwargs):
        raise AssertionError("the skull was drawn")

    for name, _label in designs.DESIGNS:
        if designs.is_design(name):
            with_skull = designs.render_png(name, "DEATH", 15, 300)
            with monkeypatch.context() as patch:
                patch.setattr(designs, "skull_shape", no_skull)
                patch.setattr(designs, "draw_skull", no_skull)
                without = designs.render_png(name, "DEATH", 15, 300, skull=False)
            assert with_skull != without, name
    window._toggle_overlay()
    window._set_overlay_setting("overlay_design", "neon")
    window._set_stream_overlay(True)
    assert "-1-" in window._stream.state()["frame"]
    window._set_overlay_setting("overlay_show_skull", "false")  # unticked
    assert not window._overlay._show_skull
    assert window._stream.state()["frame"].startswith("neon-0-0-")
