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


def test_the_sidebar_follows_the_ticks_before_saving(window) -> None:
    from src.ui.main_window import _PAGE_SETTINGS, _PAGE_TIMER

    window._show_page(_PAGE_SETTINGS)
    settings = window._settings
    settings._feature_checks[SETTING_FEATURE_TIMER].setChecked(False)
    assert not window._nav_buttons[_PAGE_TIMER].isVisibleTo(window)  # right away
    settings.reload()  # Discard Changes
    assert window._nav_buttons[_PAGE_TIMER].isVisibleTo(window)


def test_speedrun_timer_only(window) -> None:
    from src.ui.main_window import _PAGE_COUNTER, _PAGE_HOME, _PAGE_STATS, _PAGE_TIMER
    from src.utils.constants import SETTING_FEATURE_COUNTER

    window._toggle_overlay()
    _switch(window, SETTING_FEATURE_COUNTER, False)
    for page in (_PAGE_HOME, _PAGE_COUNTER, _PAGE_STATS):
        assert not window._nav_buttons[page].isVisibleTo(window)
    assert not window._overlay_nav.isVisibleTo(window) and not window._mini_nav.isVisibleTo(window)
    assert not window._overlay_active()
    assert window._pages.currentIndex() == _PAGE_TIMER
    keys = window._registered_bindings()
    assert keys["increment_key"] == "" and keys["undo_key"] == ""
    assert keys["timer_split_key"]  # the timer's keys stay
    _switch(window, SETTING_FEATURE_COUNTER, True)
    assert window._nav_buttons[_PAGE_HOME].isVisibleTo(window)


def test_the_installers_choice_is_applied_once(window, tmp_path, monkeypatch) -> None:
    import src.ui.main_window as mw
    from src.utils.constants import SETTING_FEATURE_COUNTER

    edition = tmp_path / "edition.txt"
    monkeypatch.setattr(mw, "edition_file", lambda: edition)
    edition.write_text("speedrun")
    window._apply_edition()
    assert not window._feature_on(SETTING_FEATURE_COUNTER)
    assert window._feature_on(SETTING_FEATURE_TIMER)
    window._database.set_setting(SETTING_FEATURE_COUNTER, "true")  # changed in Settings later
    window._apply_edition()  # an update writes the same choice again
    assert window._feature_on(SETTING_FEATURE_COUNTER)  # the player's change sticks
    edition.write_text("counter")  # installed again, choosing differently
    window._apply_edition()
    assert not window._feature_on(SETTING_FEATURE_TIMER)


def test_counter_and_timer_cant_both_be_off(window) -> None:
    from src.ui.main_window import _PAGE_SETTINGS
    from src.utils.constants import SETTING_FEATURE_COUNTER

    window._show_page(_PAGE_SETTINGS)
    checks = window._settings._feature_checks
    checks[SETTING_FEATURE_TIMER].setChecked(False)
    checks[SETTING_FEATURE_COUNTER].setChecked(False)
    assert checks[SETTING_FEATURE_TIMER].isChecked()  # turned back on
    window._settings.reload()
