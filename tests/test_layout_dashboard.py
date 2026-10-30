"""
Home is the dashboard; counting lives on the Death Counter page. Settings is
a page too, the sidebar collapses, and rows rearrange to fit the window.
"""

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
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    yield win
    win._quit_app()
    app.processEvents()


def _game(window) -> int:
    db = window._database
    game = db.create_game("Phantom Blade Zero")
    for name in ("Tiger King", "Blind Monk"):
        db.create_boss(game, name)
    window._reload_games(select_game_id=game)
    return game


def test_home_is_a_dashboard_of_the_game(window) -> None:
    from src.ui.main_window import _PAGE_COUNTER, _PAGE_HOME

    _game(window)
    for _ in range(3):
        window._on_increment()
    window._show_page(_PAGE_HOME)
    window._refresh_home()
    assert window._home_game.text() == "Phantom Blade Zero"
    assert window._home_count.text() == "3"
    assert window._home_today.value.text() == "3"
    assert window._home_bosses.value.text() == "0/2"
    window._home_open_btn.click()
    assert window._pages.currentIndex() == _PAGE_COUNTER


def test_settings_is_a_page_that_asks_before_dropping_changes(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from src.ui.main_window import _PAGE_HOME, _PAGE_SETTINGS
    from src.ui.settings_window import SettingsWindow

    assert window._settings is None  # built on first use: quick startup
    window._open_settings_window(tab=SettingsWindow.TAB_OVERLAY)
    settings = window._settings
    assert window._pages.currentIndex() == _PAGE_SETTINGS
    assert settings._tabs.currentIndex() == SettingsWindow.TAB_OVERLAY
    assert not settings.has_changes()

    settings._confirm_close_check.setChecked(False)
    assert settings.has_changes()
    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda box: next(b for b in box.buttons() if b.text() == "Cancel").click(),
    )
    window._show_page(_PAGE_HOME)
    assert window._pages.currentIndex() == _PAGE_SETTINGS  # Cancel: stay

    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda box: next(b for b in box.buttons() if b.text() == "Save").click(),
    )
    window._show_page(_PAGE_HOME)
    assert window._pages.currentIndex() == _PAGE_HOME
    assert window._database.get_setting("confirm_close") == "false"

    window._database.set_setting("confirm_close", "true")  # changed elsewhere meanwhile
    window._show_page(_PAGE_SETTINGS)
    assert settings._confirm_close_check.isChecked()  # the page shows it
    window._show_page(_PAGE_HOME)
    window._database.set_setting("confirm_close", "false")
    window._show_page(_PAGE_SETTINGS)
    settings._confirm_close_check.setChecked(True)
    settings.reject()  # Discard Changes: back to what's saved, page stays
    assert not settings._confirm_close_check.isChecked()
    assert settings.isVisibleTo(window._settings_host)


def test_sidebar_collapses_and_remembers(window) -> None:
    from src.utils.constants import SETTING_SIDEBAR_COLLAPSED

    window._collapse_btn.click()
    assert window._sidebar.width() == 68
    assert all(not button.text() for button in window._nav_texts)
    assert window._nav_buttons[1].toolTip() == "Death Counter"
    assert window._database.get_setting(SETTING_SIDEBAR_COLLAPSED) == "true"
    window._collapse_btn.click()
    assert window._nav_buttons[1].text().strip() == "Death Counter"


def test_rows_rearrange_to_fit_a_narrow_window(window) -> None:
    _game(window)
    window._fit_to_width(1000)
    assert not any(grid.compact for grid in window._responsive)
    window._fit_to_width(560)
    assert all(grid.compact for grid in window._responsive)
    assert not window._skull_badge.isVisibleTo(window)


def test_status_pill_dot_follows_the_state() -> None:
    from src.ui.widgets import StatusPill

    pill = StatusPill()
    for text, state in (
        ("Auto-detect off", ""),
        ("Waiting for PBZ.exe to start…", "waiting"),
        ("Watching PBZ.exe", "active"),
        ("The game window is black", "warning"),
    ):
        pill.setText(text)
        assert pill.state() == state


def test_minus_one_and_undo_explain_the_difference(window) -> None:
    assert "counted by mistake" in window._minus_btn.toolTip()
    assert "as if it never happened" in window._undo_btn.toolTip()
    heights = {b.height() for b in (window._plus_btn, window._minus_btn, window._undo_btn)}
    assert heights == {58}
