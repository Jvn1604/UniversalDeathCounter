"""
Picking up where you left off: an earlier death-counter session, an earlier
speedrun attempt, and "Deaths this run" as what the big number counts.
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.session_manager import RESUME_WITHIN  # noqa: E402
from src.core.speedrun import PAUSED, RunRecord, SpeedrunTimer  # noqa: E402

SPLITS = ["Margit", "Godrick", "Rennala"]


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


def _game(window, splits=SPLITS) -> int:
    db = window._database
    game_id = db.create_game("Elden Ring")
    db.set_speedrun_splits(game_id, splits)
    window._reload_games(select_game_id=game_id)
    return game_id


def test_a_break_of_up_to_16_hours_continues_the_session() -> None:
    assert RESUME_WITHIN == timedelta(hours=16)


# ---------------------------------------------------------------- past sessions
def test_continue_a_past_session_from_home(window, monkeypatch) -> None:
    from src.ui import session_history_window as history

    game = _game(window)
    for _ in range(4):
        window._on_increment()
    old_session = window._session_manager.current_session_id
    window._counter_manager.reset_session()  # a new session at 0
    window._on_increment()
    assert window._counter_manager.get_snapshot().session_deaths == 1

    shown: list[str] = []

    def pick_old(dialog):
        rows = [dialog._sessions_list.item(i) for i in range(dialog._sessions_list.count())]
        shown.extend(item.text() for item in rows)
        ids = [item.data(history._USER_ROLE) for item in rows]
        dialog._sessions_list.setCurrentRow(ids.index(old_session))
        dialog._continue_selected()
        return 1

    monkeypatch.setattr(history.SessionHistoryWindow, "exec", pick_old)
    window._sessions_btn.click()  # the Sessions button next to Undo

    assert window._session_manager.current_session_id == old_session
    snapshot = window._counter_manager.get_snapshot()
    assert (snapshot.session_deaths, snapshot.total_deaths) == (4, 5)
    assert any("now" in text for text in shown)  # the current session is marked
    assert any("4 deaths" in text for text in shown)
    window._on_increment()  # new deaths go into the continued session
    assert window._database.get_session_death_count(old_session) == 5
    assert game == window._counter_manager.current_game_id


def test_the_caption_under_the_big_number_isnt_clipped(window) -> None:
    window.resize(1100, 900)
    window.show()
    caption = window._counter_caption
    assert caption.height() >= caption.fontMetrics().height() + 8
    window.hide()


def test_the_current_session_cant_be_continued_or_deleted(window) -> None:
    from src.ui.session_history_window import SessionHistoryWindow

    game = _game(window)
    window._on_increment()
    current = window._session_manager.current_session_id
    dialog = SessionHistoryWindow(
        window._database, game, parent=window, can_continue=True, current_session_id=current
    )
    dialog._sessions_list.setCurrentRow(0)  # newest first: the current one
    assert not dialog._continue_btn.isEnabled()
    assert not dialog._delete_btn.isEnabled()
    dialog.close()


# ---------------------------------------------------------------- deaths this run
def test_big_number_can_count_deaths_this_run(window) -> None:
    _game(window)
    window._on_increment()  # before the run: not part of it
    window._set_overlay_setting("overlay_counter_source", "run")
    assert window._counter_caption.text() == "DEATHS THIS RUN"
    assert window._counter_label.text() == "0"
    window._action_handlers["timer_split"]()  # start the run
    window._on_increment()
    window._on_increment()
    assert window._counter_label.text() == "2"
    assert window._overlay._death_label.text() == "DEATH - 2"
    assert window._overlay._caption_label.text().startswith("THIS RUN")
    assert window._mini._count.text() == "2"
    window._action_handlers["timer_reset"]()
    assert window._counter_label.text() == "0"  # no run going


# ---------------------------------------------------------------- past runs
def test_reset_runs_remember_where_the_clock_stopped() -> None:
    now = [0.0]
    timer = SpeedrunTimer(SPLITS, clock=lambda: now[0])
    timer.split()  # start
    now[0] = 30.0
    timer.split()  # Margit at 0:30
    now[0] = 75.0
    record = timer.reset()
    assert record.split_times == [30000]
    assert record.real_ms == 75000 and record.game_ms == 75000
    data = record.resume_data()
    assert (data["real_ms"], data["finished"]) == (75000, False)


def test_older_runs_continue_from_their_last_split() -> None:
    old = RunRecord(split_names=SPLITS, split_times=[30000, None], finished=False, deaths=3)
    data = old.resume_data()
    assert data["real_ms"] == 30000 and data["deaths"] == 3


def test_continue_a_reset_run_from_run_history(window, monkeypatch) -> None:
    from src.ui import timer_window

    game = _game(window)
    window._action_handlers["timer_split"]()  # start
    window._action_handlers["timer_split"]()  # Margit
    window._on_increment()
    window._action_handlers["timer_reset"]()
    saved = window._database.get_speedrun_runs(game, SPLITS)
    assert len(saved) == 1 and saved[0].real_ms is not None

    def pick_run(dialog):
        dialog._table.selectRow(0)
        assert dialog._continue_button.isEnabled()
        dialog._continue_selected()
        return 1

    monkeypatch.setattr(timer_window.RunHistoryDialog, "exec", pick_run)
    window._open_run_history()

    timer = window._speedrun.timer
    assert timer.state == PAUSED  # waits for the pause key
    assert len(timer.split_times) == 1 and timer.deaths == 1
    assert timer.elapsed_ms() >= saved[0].real_ms
    # It's in progress again, so it isn't in the history twice.
    assert window._database.get_speedrun_runs(game, SPLITS) == []
    window._action_handlers["timer_pause"]()  # carry on
    window._action_handlers["timer_split"]()  # Godrick
    assert len(timer.split_times) == 2


def test_finished_runs_and_a_run_in_progress_cant_be_continued(window) -> None:
    from src.ui.timer_window import RunHistoryDialog

    _game(window, splits=["Only"])
    window._action_handlers["timer_split"]()  # start
    window._action_handlers["timer_split"]()  # finish
    window._action_handlers["timer_reset"]()  # save the finished run
    dialog = RunHistoryDialog(window._database, window._speedrun, parent=window)
    dialog._table.selectRow(0)
    assert not dialog._continue_button.isEnabled()  # finished
    dialog.close()

    window._action_handlers["timer_split"]()  # a new run is going
    window._action_handlers["timer_reset"]()  # reset at "Only": can be continued
    window._action_handlers["timer_split"]()  # and another run is going now
    dialog = RunHistoryDialog(window._database, window._speedrun, parent=window)
    dialog._table.selectRow(0)
    assert not dialog._continue_button.isEnabled()  # finish or reset this one first
    dialog.close()
