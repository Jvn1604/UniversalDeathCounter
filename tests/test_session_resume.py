"""
Restarting the app (an update, a crash, a quick break) keeps the session.

Regression: after updating, a player's overlay showed "DEATH - 0" because
every app start opened a new session, and it looked like their deaths
were gone.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.counter_manager import CounterManager  # noqa: E402
from src.core.session_manager import RESUME_WITHIN, SessionManager  # noqa: E402
from src.database.database import Database  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def _open_app(db: Database, game_id: int) -> CounterManager:
    """What starting the app does: pick the last game."""
    manager = CounterManager(db, SessionManager(db))
    manager.set_current_game(game_id, "Phantom Blade Zero")
    return manager


def test_restart_continues_the_session(db) -> None:
    game = db.create_game("Phantom Blade Zero")
    first = _open_app(db, game)
    for _ in range(7):
        first.increment()
    first_session = first._session_manager.current_session_id
    first._session_manager.end_current_session()  # the app closes for the update

    second = _open_app(db, game)
    snapshot = second.get_snapshot()
    assert (snapshot.session_deaths, snapshot.total_deaths) == (7, 7)
    assert second._session_manager.current_session_id == first_session


def test_a_long_break_starts_a_fresh_session(db) -> None:
    game = db.create_game("Phantom Blade Zero")
    manager = _open_app(db, game)
    manager.increment()
    sessions = manager._session_manager
    old = sessions.current_session_id
    sessions.end_current_session()
    later = datetime.now(UTC) + RESUME_WITHIN + timedelta(minutes=1)
    new = sessions.continue_or_start(game, now=later)
    assert new != old
    assert db.get_session_death_count(new) == 0
    assert db.get_total_deaths(game) == 1  # nothing is lost


def test_a_crashed_session_is_timed_by_its_last_death(db) -> None:
    game = db.create_game("G")
    manager = _open_app(db, game)
    manager.increment()
    crashed = manager._session_manager.current_session_id  # never ended: a crash
    sessions = SessionManager(db)
    soon = datetime.now(UTC) + timedelta(hours=1)
    assert sessions.continue_or_start(game, now=soon) == crashed
    sessions = SessionManager(db)
    much_later = datetime.now(UTC) + timedelta(days=2)
    assert sessions.continue_or_start(game, now=much_later) != crashed


def test_reset_session_still_starts_from_zero(db) -> None:
    game = db.create_game("G")
    manager = _open_app(db, game)
    manager.increment()
    snapshot = manager.reset_session()
    assert (snapshot.session_deaths, snapshot.total_deaths) == (0, 1)


def test_each_game_continues_its_own_session(db) -> None:
    first, second = db.create_game("A"), db.create_game("B")
    manager = _open_app(db, first)
    manager.increment()
    manager.set_current_game(second, "B")
    assert manager.get_snapshot().session_deaths == 0
    manager.set_current_game(first, "A")  # back to A a minute later
    assert manager.get_snapshot().session_deaths == 1


# ---------------------------------------------------------------- the main window
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


def test_game_already_running_at_startup_keeps_the_count(window) -> None:
    """The update restarts the app while the game runs: that's no new launch."""
    db = window._database
    game = db.create_game("Phantom Blade Zero")
    window._reload_games(select_game_id=game)
    for _ in range(3):
        window._on_increment()
    window._start_play_session(game)  # the launch check sees the game "start"
    assert window._counter_manager.get_snapshot().session_deaths == 3


def test_big_number_shows_all_time_by_default_and_switches_from_home(window, monkeypatch) -> None:
    import src.ui.main_window as mw

    db = window._database
    game = db.create_game("Phantom Blade Zero")
    window._reload_games(select_game_id=game)
    window._on_increment()
    window._counter_manager.reset_session()  # a new session: 0 this session
    window._refresh_counters()
    assert window._counter_label.text() == "1"  # still shows the game's deaths
    assert window._overlay._death_label.text() == "DEATH - 1"

    picked: list[str] = []

    class _Menu(mw.QMenu):
        def exec(self, *_args):
            action = next(a for a in self.actions() if a.text() == "Deaths this session")
            picked.append(action.text())
            action.trigger()

    monkeypatch.setattr(mw, "QMenu", _Menu)
    window._counter_caption.click()
    assert picked
    assert window._counter_caption.text() == "DEATHS THIS SESSION"
    assert window._counter_label.text() == "0"
    assert db.get_setting("overlay_counter_source", "") == "session"
