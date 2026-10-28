"""Main-window behavior that needs a real (offscreen) Qt window."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    yield win
    win._quit_app()
    app.processEvents()


def test_first_game_selected_when_no_last_game_saved(window) -> None:
    """Regression: with no saved last game, the dropdown picked its blank separator."""
    db = window._database
    first = db.create_game("Elden Ring")
    db.create_game("Hollow Knight")
    db.set_setting("last_game_id", "")
    window._reload_games()
    assert window._counter_manager.current_game_id == first
    assert window._game_combo.currentText() == "Elden Ring"


def test_last_game_restored(window) -> None:
    db = window._database
    db.create_game("Elden Ring")
    second = db.create_game("Hollow Knight")
    db.set_setting("last_game_id", second)
    window._reload_games()
    assert window._game_combo.currentText() == "Hollow Knight"


def test_window_uses_new_branding(window) -> None:
    from src.utils.constants import APP_NAME

    assert APP_NAME == "DePhantom Universal Death Counter"
    assert window.windowTitle() == APP_NAME
    assert window._overlay.windowTitle() == "DUDC Overlay"
