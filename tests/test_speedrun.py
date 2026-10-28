"""Speedrun timer: timing, splits, PB / golds / sum of best, storage, and wiring."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.speedrun import (  # noqa: E402
    AHEAD,
    BEHIND,
    FINISHED,
    GOLD,
    IDLE,
    PAUSED,
    RUNNING,
    RunRecord,
    SpeedrunController,
    SpeedrunTimer,
    best_segments,
    format_delta,
    format_time,
    personal_best,
    segment_times,
    sum_of_best,
)
from src.database.database import Database  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


SPLITS = ["Asylum Demon", "Taurus Demon", "Bell Gargoyles"]


def _run(times: list[int | None], finished: bool = True, deaths: int = 0) -> RunRecord:
    return RunRecord(list(SPLITS), times, finished, deaths)


# ----------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("ms", "text"),
    [(None, "-"), (0, "0:00.00"), (3_450, "0:03.45"), (123_450, "2:03.45"),
     (3_723_450, "1:02:03.45"), (-5, "0:00.00")],
)
def test_format_time(ms, text) -> None:
    assert format_time(ms) == text


@pytest.mark.parametrize(
    ("ms", "text"), [(-1_200, "-1.2"), (12_300, "+12.3"), (65_000, "+1:05.0"), (0, "+0.0")]
)
def test_format_delta(ms, text) -> None:
    assert format_delta(ms) == text


# ----------------------------------------------------------------
# Timer
# ----------------------------------------------------------------
def test_split_starts_records_and_finishes() -> None:
    clock = FakeClock()
    timer = SpeedrunTimer(SPLITS, clock)
    assert timer.state == IDLE and timer.elapsed_ms() == 0
    timer.split()  # start
    clock.advance(10)
    timer.split()
    clock.advance(5)
    timer.split()
    clock.advance(20)
    assert timer.elapsed_ms() == 35_000
    timer.split()
    assert timer.state == FINISHED
    assert timer.split_times == [10_000, 15_000, 35_000]
    clock.advance(99)
    assert timer.elapsed_ms() == 35_000  # stops at the final split


def test_pause_excludes_paused_time() -> None:
    clock = FakeClock()
    timer = SpeedrunTimer(SPLITS, clock)
    timer.split()
    clock.advance(4)
    timer.toggle_pause()
    assert timer.state == PAUSED
    clock.advance(60)
    assert timer.elapsed_ms() == 4_000
    timer.split()  # splitting while paused does nothing
    assert timer.split_times == []
    timer.toggle_pause()
    clock.advance(1)
    assert timer.elapsed_ms() == 5_000


def test_undo_skip_and_unfinish() -> None:
    clock = FakeClock()
    timer = SpeedrunTimer(SPLITS, clock)
    timer.split()
    clock.advance(10)
    timer.skip_split()
    assert timer.split_times == [None]
    timer.undo_split()
    assert timer.split_times == []
    timer.split()
    timer.split()
    timer.skip_split()  # can't skip the last split
    clock.advance(1)
    timer.split()
    assert timer.state == FINISHED
    timer.undo_split()  # oops, too early
    assert timer.state == RUNNING
    clock.advance(2)
    timer.split()
    assert timer.split_times[-1] == 13_000


def test_reset_returns_the_attempt() -> None:
    clock = FakeClock()
    timer = SpeedrunTimer(SPLITS, clock)
    assert timer.reset() is None
    timer.split()
    timer.add_deaths(+1)
    timer.add_deaths(+1)
    timer.add_deaths(-5)  # never negative
    timer.add_deaths(+3)
    clock.advance(8)
    timer.split()
    record = timer.reset()
    assert record is not None and not record.finished
    assert record.split_times == [8_000]
    assert record.deaths == 3
    assert timer.state == IDLE
    timer.add_deaths(1)  # idle: not counted
    assert timer.deaths == 0


def test_no_splits_means_one_finish_split() -> None:
    timer = SpeedrunTimer([], FakeClock())
    assert timer.split_names == ["Finish"]
    timer.split()
    timer.split()
    assert timer.state == FINISHED


# ----------------------------------------------------------------
# Comparisons
# ----------------------------------------------------------------
def test_segments_pb_golds_and_sum_of_best() -> None:
    runs = [
        _run([10_000, 25_000, 40_000]),
        _run([12_000, 22_000, 45_000]),  # faster 2nd segment
        _run([9_000, None, None], finished=False),  # reset early: best 1st segment
        _run([11_000, None, 38_000]),  # skipped split: no segment for 2 or 3
    ]
    assert segment_times([10_000, None, 30_000]) == [10_000, None, None]
    assert personal_best(runs).total_ms == 38_000
    assert best_segments(runs, 3) == [9_000, 10_000, 15_000]
    assert sum_of_best([9_000, 10_000, 15_000]) == 34_000
    assert sum_of_best([9_000, None, 1]) is None


def _controller(runs, clock, stored=None) -> SpeedrunController:
    return SpeedrunController(
        game_id=1,
        game_name="Dark Souls",
        split_names=SPLITS,
        runs=runs,
        attempts=len(runs),
        store=lambda gid, run: (stored if stored is not None else []).append((gid, run)),
        clock=clock,
    )


def test_view_shows_deltas_golds_and_timer_color() -> None:
    clock = FakeClock()
    stored: list = []
    controller = _controller([_run([10_000, 25_000, 40_000], deaths=4)], clock, stored)
    view = controller.view()
    assert view.state == IDLE
    assert [row.time for row in view.rows] == ["0:10.00", "0:25.00", "0:40.00"]  # PB times
    assert view.pb == "0:40.00" and view.sum_of_best == "0:40.00" and view.pb_deaths == 4

    controller.split()
    assert controller.view().attempts == 2
    clock.advance(8)
    assert controller.view().time_status == AHEAD
    controller.split()  # 8.0 vs PB 10.0: ahead, and a gold segment
    clock.advance(20)  # 28.0: past the PB's 25.0 for split 2
    view = controller.view()
    assert view.rows[0].delta_status == GOLD
    assert view.rows[0].delta == "-2.0"
    assert view.rows[1].current and view.rows[1].delta == "+3.0"
    assert view.rows[1].delta_status == BEHIND
    assert view.time_status == BEHIND

    controller.split()  # split 2 at 28.0
    clock.advance(5)
    controller.split()  # finish at 33.0, beating the 40.0 PB
    view = controller.view()
    assert view.state == FINISHED and view.time_status == GOLD
    record = controller.reset()
    assert record.finished and stored == [(1, record)]
    assert controller.view().pb == "0:33.00"


def test_deaths_only_count_for_the_runs_game() -> None:
    clock = FakeClock()
    controller = _controller([], clock)
    controller.split()
    controller.add_deaths(1, +1)
    controller.add_deaths(2, +1)  # another game
    assert controller.view().deaths == 1


def test_view_keeps_the_current_split_visible() -> None:
    names = [f"Split {i}" for i in range(20)]
    controller = SpeedrunController(1, "Long", names, [], 0, lambda *_: None, FakeClock())
    for _ in range(12):
        controller.split()
    view = controller.view(max_rows=8)
    assert len(view.rows) == 8
    assert any(row.current and row.name == "Split 11" for row in view.rows)


# ----------------------------------------------------------------
# Storage
# ----------------------------------------------------------------
def test_splits_and_runs_storage(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    try:
        game_id = db.create_game("Dark Souls")
        assert db.get_speedrun_splits(game_id) == []
        db.set_speedrun_splits(game_id, SPLITS)
        assert db.get_speedrun_splits(game_id) == SPLITS
        db.add_speedrun_run(game_id, _run([1, 2, 3], deaths=2))
        db.add_speedrun_run(game_id, RunRecord(["Other"], [5], True))
        runs = db.get_speedrun_runs(game_id, SPLITS)
        assert len(runs) == 1 and runs[0].split_times == [1, 2, 3] and runs[0].deaths == 2
        assert db.count_speedrun_attempts(game_id) == 2
        db.clear_speedrun_runs(game_id)
        assert db.count_speedrun_attempts(game_id) == 0
        db.add_speedrun_run(game_id, _run([1, 2, 3]))
        db.delete_game(game_id)
        assert db.count_speedrun_attempts(game_id) == 0  # removed with the game
    finally:
        db.close()


# ----------------------------------------------------------------
# Hotkeys and main window
# ----------------------------------------------------------------
def test_hotkey_manager_accepts_any_action() -> None:
    from src.hotkeys.hotkey_manager import HotkeyManager

    manager = HotkeyManager(timer_split_key="num+1", increment_key="f9")
    fired: list[str] = []
    manager.action_triggered.connect(fired.append)
    manager._emit_action("timer_split")
    assert fired == ["timer_split"]
    with pytest.raises(TypeError):
        HotkeyManager(timer_split="num+1")


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


def test_timer_follows_game_and_counts_run_deaths(window) -> None:
    db = window._database
    game_id = db.create_game("Dark Souls")
    db.set_speedrun_splits(game_id, SPLITS)
    window._reload_games(select_game_id=game_id)
    controller = window._speedrun
    assert controller is not None and controller.timer.split_names == SPLITS

    window._action_handlers["timer_split"]()  # start
    assert controller.timer.state == RUNNING
    assert window._timer_window.isVisible()  # starting shows the timer
    window._on_increment()
    window._on_increment()
    window._on_decrement()
    assert controller.timer.deaths == 1

    other = db.create_game("Sekiro")
    window._reload_games(select_game_id=other)
    assert window._speedrun is controller  # a run in progress survives a game switch
    window._action_handlers["timer_reset"]()
    assert db.count_speedrun_attempts(game_id) == 1
    assert window._speedrun.game_id == other  # then follows the selected game


def test_closing_saves_the_attempt_in_progress(window) -> None:
    db = window._database
    game_id = db.create_game("Dark Souls")
    window._reload_games(select_game_id=game_id)
    window._action_handlers["timer_split"]()
    window._end_speedrun()
    assert db.count_speedrun_attempts(game_id) == 1


def test_timer_window_renders_a_view(window) -> None:
    db = window._database
    game_id = db.create_game("Dark Souls")
    db.set_speedrun_splits(game_id, SPLITS)
    window._reload_games(select_game_id=game_id)
    timer_window = window._timer_window
    timer_window.refresh()
    assert timer_window._title_label.text() == "Dark Souls"
    assert timer_window._rows[0][0].text() == "Asylum Demon"
    assert timer_window._time_label.text() == "0:00.00"
    window._action_handlers["timer_split"]()
    assert timer_window._tick.isActive()  # ticks only while running
    window._action_handlers["timer_pause"]()
    timer_window.refresh()
    assert not timer_window._tick.isActive()
