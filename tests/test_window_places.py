"""
Stream windows remember where the player put them: saved as soon as they're
moved or resized, and a place on a display that isn't there yet (a second
monitor waking after the app started) is kept, not overwritten.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make(tmp_path, monkeypatch):
    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    return mw.MainWindow()


def _settle(app, seconds: float = 1.2) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


@pytest.fixture()
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_moving_the_overlay_is_remembered_at_once(tmp_path, monkeypatch, app) -> None:
    win = _make(tmp_path, monkeypatch)
    try:
        win._toggle_overlay()
        win._overlay.setGeometry(120, 90, 340, 180)  # the player drags and sizes it
        _settle(app)
        assert win._database.get_setting("overlay_geometry") == "120,90,340,180"
        win._timer_window.show()
        win._timer_window.setGeometry(400, 200, 280, 210)
        _settle(app)
        assert win._database.get_setting("timer_geometry") == "400,200,280,210"
    finally:
        win._quit_app()
        app.processEvents()
    again = _make(tmp_path, monkeypatch)  # the next day
    try:
        assert again._overlay.geometry_string() == "120,90,340,180"
        assert again._timer_window.geometry_string() == "400,200,280,210"
    finally:
        again._quit_app()
        app.processEvents()


def test_a_place_on_a_missing_display_is_kept(tmp_path, monkeypatch, app) -> None:
    from src.database.database import Database

    db = Database(tmp_path / "death_counter.db")
    db.set_setting("overlay_geometry", "5000,100,300,160")  # on the second monitor
    db.set_setting("overlay_state", "on")
    db.close()
    win = _make(tmp_path, monkeypatch)
    try:
        _settle(app)
        assert win._overlay.isVisible()
        assert win._overlay.geometry_string() != "5000,100,300,160"  # waits on the main one
        assert win._wanted_places[win._overlay] == "5000,100,300,160"
        assert win._database.get_setting("overlay_geometry") == "5000,100,300,160"
    finally:
        win._quit_app()  # closing keeps the player's place too
        app.processEvents()
    db = Database(tmp_path / "death_counter.db")
    try:
        assert db.get_setting("overlay_geometry") == "5000,100,300,160"
    finally:
        db.close()
