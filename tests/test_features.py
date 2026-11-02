"""
Features can be switched off (Settings → General → Features): gone from the
sidebar, menus and tray, keys freed, work stopped; back when switched on.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.utils.constants import (  # noqa: E402
    SETTING_FEATURE_CONSOLE,
    SETTING_FEATURE_MINI,
    SETTING_FEATURE_STATS,
    SETTING_FEATURE_TIMER,
    SETTING_OVERLAY_COUNTER_SOURCE,
)


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
    game = win._database.create_game("Lies of P")
    win._reload_games(select_game_id=game)
    yield win
    win._quit_app()
    app.processEvents()


def _switch(window, key: str, on: bool) -> None:
    window._database.set_setting(key, "true" if on else "false")
    window._on_settings_changed()  # what saving Settings does


def test_everything_is_on_by_default(window) -> None:
    from src.ui.main_window import _PAGE_CONSOLE, _PAGE_STATS, _PAGE_TIMER

    for page in (_PAGE_TIMER, _PAGE_STATS, _PAGE_CONSOLE):
        assert window._nav_buttons[page].isVisibleTo(window)
    assert window._mini_nav.isVisibleTo(window)
    assert window._registered_bindings()["timer_split_key"]


def test_switching_the_timer_off_frees_its_keys(window) -> None:
    from src.ui.main_window import _PAGE_HOME, _PAGE_TIMER

    window._show_page(_PAGE_TIMER)
    window._database.set_setting(SETTING_OVERLAY_COUNTER_SOURCE, "run")
    window._timer_window.show()
    _switch(window, SETTING_FEATURE_TIMER, False)
    assert not window._nav_buttons[_PAGE_TIMER].isVisibleTo(window)
    assert window._pages.currentIndex() == _PAGE_HOME  # off its page
    assert not window._timer_window.isVisible()
    keys = window._registered_bindings()
    assert all(value == "" for action, value in keys.items() if action.startswith("timer_"))
    assert keys["increment_key"]  # the counter keys stay
    assert all(value == "" for action, value in window._pad_bindings().items()
               if action.startswith("timer_"))
    assert window._database.get_setting(SETTING_OVERLAY_COUNTER_SOURCE) == "total"
    window._timer_action("split")
    assert window._speedrun.timer.state == "idle"  # the key does nothing now

    _switch(window, SETTING_FEATURE_TIMER, True)
    assert window._nav_buttons[_PAGE_TIMER].isVisibleTo(window)
    assert window._registered_bindings()["timer_split_key"]


def test_stats_console_and_mini_mode_switch_off(window) -> None:
    from src.ui.main_window import _PAGE_CONSOLE, _PAGE_STATS

    window._toggle_mini_mode()
    assert window._mini.isVisible()
    for key in (SETTING_FEATURE_STATS, SETTING_FEATURE_CONSOLE, SETTING_FEATURE_MINI):
        _switch(window, key, False)
    assert not window._nav_buttons[_PAGE_STATS].isVisibleTo(window)
    assert not window._nav_buttons[_PAGE_CONSOLE].isVisibleTo(window)
    assert not window._mini_nav.isVisibleTo(window)
    assert not window._mini.isVisible()  # back to the full window


def test_the_switches_are_in_settings(window) -> None:
    from src.ui.main_window import _PAGE_SETTINGS

    window._show_page(_PAGE_SETTINGS)
    settings = window._settings
    check = settings._feature_checks[SETTING_FEATURE_TIMER]
    assert check.isChecked()
    assert settings._tabs.isTabVisible(settings.TAB_SPEEDRUN)
    check.setChecked(False)
    assert not settings._tabs.isTabVisible(settings.TAB_SPEEDRUN)
    settings._save()
    assert window._database.get_setting(SETTING_FEATURE_TIMER) == "false"
    from src.ui.main_window import _PAGE_TIMER

    assert not window._nav_buttons[_PAGE_TIMER].isVisibleTo(window)
    window._toast.action.click()  # Undo puts it back
    assert window._feature_on(SETTING_FEATURE_TIMER)
    assert window._nav_buttons[_PAGE_TIMER].isVisibleTo(window)
