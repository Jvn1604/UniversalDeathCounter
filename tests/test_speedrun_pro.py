"""Game vs real time, comparisons, records, auto-pause, auto-save and crash recovery."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.speedrun import (  # noqa: E402
    AHEAD,
    BEHIND,
    COMPARE_BEST,
    COMPARE_PREVIOUS,
    FINISHED,
    GAME,
    GOLD,
    PAUSED,
    REAL,
    RUNNING,
    RunRecord,
    SpeedrunController,
    SpeedrunTimer,
    compute_records,
    format_time,
)
from src.database.database import SCREEN_DEATH, SCREEN_PAUSE, Database  # noqa: E402
from src.detection.matchers import is_loading_frame  # noqa: E402

SPLITS = ["A", "B", "C"]


class FakeClock:
    def __init__(self) -> None:
        self.now = 50.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _run(times, finished=True, deaths=0, game=None) -> RunRecord:
    return RunRecord(list(SPLITS), list(times), finished, deaths, game_times=list(game or []))


# ----------------------------------------------------------------
# Precision
# ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("digits", "text"), [(0, "1:23"), (1, "1:23.4"), (2, "1:23.45"), (3, "1:23.456")]
)
def test_precision(digits, text) -> None:
    assert format_time(83_456, digits) == text


# ----------------------------------------------------------------
# Real vs game time
# ----------------------------------------------------------------
def test_game_time_stops_for_loads_real_time_keeps_going() -> None:
    clock = FakeClock()
    timer = SpeedrunTimer(SPLITS, clock)
    timer.split()
    clock.advance(10)
    timer.set_game_paused(True)  # loading screen
    clock.advance(4)
    timer.set_game_paused(False)
    clock.advance(1)
    assert timer.elapsed_ms(REAL) == 15_000
    assert timer.elapsed_ms(GAME) == 11_000
    timer.split()
    assert timer.split_times == [15_000] and timer.game_times == [11_000]


def test_manual_pause_stops_both_clocks() -> None:
    clock = FakeClock()
    timer = SpeedrunTimer(SPLITS, clock)
    timer.split()
    clock.advance(5)
    timer.toggle_pause()
    clock.advance(30)
    timer.set_game_paused(True)  # a load while paused changes nothing
    timer.set_game_paused(False)
    timer.toggle_pause()
    clock.advance(1)
    assert timer.elapsed_ms(REAL) == 6_000 == timer.elapsed_ms(GAME)


def test_undo_after_finishing_continues_seamlessly() -> None:
    clock = FakeClock()
    timer = SpeedrunTimer(["Only"], clock)
    timer.split()
    clock.advance(10)
    timer.split()
    assert timer.state == FINISHED
    clock.advance(3)  # the clock kept going underneath
    timer.undo_split()
    assert timer.state == RUNNING
    assert timer.elapsed_ms() == 13_000


def test_snapshot_restores_paused_at_the_saved_time() -> None:
    clock = FakeClock()
    timer = SpeedrunTimer(SPLITS, clock)
    timer.split()
    clock.advance(20)
    timer.split()
    timer.set_game_paused(True)
    clock.advance(5)
    timer.add_deaths(3)
    data = json.loads(json.dumps(timer.snapshot()))  # survives the settings table

    later = FakeClock()
    later.now = 9_999.0
    restored = SpeedrunTimer.restore(data, later)
    assert restored.state == PAUSED
    assert restored.split_times == [20_000] and restored.deaths == 3
    assert restored.elapsed_ms(REAL) == 25_000
    assert restored.elapsed_ms(GAME) == 20_000
    later.advance(60)  # crash downtime isn't counted while paused
    restored.toggle_pause()
    later.advance(2)
    assert restored.elapsed_ms(REAL) == 27_000


def test_restoring_a_finished_run_keeps_it_finished() -> None:
    clock = FakeClock()
    timer = SpeedrunTimer(["Only"], clock)
    timer.split()
    clock.advance(7)
    timer.split()
    restored = SpeedrunTimer.restore(timer.snapshot(), clock)
    assert restored.state == FINISHED and restored.elapsed_ms() == 7_000


# ----------------------------------------------------------------
# Comparisons, previous segment, records
# ----------------------------------------------------------------
def _controller(runs, clock, comparison="pb", method=REAL) -> SpeedrunController:
    controller = SpeedrunController(1, "Game", SPLITS, runs, len(runs), lambda *_: None, clock)
    controller.set_options(method, comparison, 2)
    return controller


def test_compare_against_previous_run() -> None:
    clock = FakeClock()
    runs = [_run([10_000, 20_000, 30_000]), _run([12_000, None, None], finished=False)]
    controller = _controller(runs, clock, COMPARE_PREVIOUS)
    view = controller.view()
    assert [row.time for row in view.rows] == ["0:12.00", "-", "-"]
    assert view.comparison == "Previous Run"
    controller.split()
    clock.advance(11)
    controller.split()
    assert controller.view().rows[0].delta == "-1.00"


def test_compare_against_best_segments() -> None:
    runs = [_run([10_000, 30_000, 40_000]), _run([15_000, 25_000, 45_000])]
    controller = _controller(runs, FakeClock(), COMPARE_BEST)
    # best segments 10 + 10 + 10 → cumulative 10, 20, 30
    assert [row.time for row in controller.view().rows] == ["0:10.00", "0:20.00", "0:30.00"]


def test_previous_segment_ahead_behind_and_gold() -> None:
    clock = FakeClock()
    controller = _controller([_run([10_000, 20_000, 30_000])], clock)
    controller.split()
    clock.advance(12)
    controller.split()  # 12 vs PB segment 10
    view = controller.view()
    assert view.previous_segment == "+2.00" and view.previous_segment_status == BEHIND
    clock.advance(5)
    controller.split()  # 5 vs 10: ahead, and the best ever → gold
    view = controller.view()
    assert view.previous_segment == "-5.00" and view.previous_segment_status == GOLD


def test_game_time_view_shows_reason_and_real_time() -> None:
    clock = FakeClock()
    controller = _controller([], clock, method=GAME)
    controller.split()
    clock.advance(10)
    controller.set_game_paused("Loading")
    clock.advance(5)
    view = controller.view()
    assert view.time == "0:10.00"
    assert view.paused_reason == "Loading"
    assert view.other_time == "Real 0:15.00"


def test_game_time_pb_and_runs_without_game_times() -> None:
    old = _run([10_000, 20_000, 30_000])  # saved before game time existed
    assert old.times(GAME) == [None, None, None] and old.total(GAME) is None
    newer = _run([11_000, 22_000, 33_000], game=[9_000, 18_000, 27_000])
    controller = _controller([old, newer], FakeClock(), method=GAME)
    assert controller.view().pb == "0:27.00"


def test_new_pb_detection() -> None:
    clock = FakeClock()
    controller = _controller([_run([10_000, 20_000, 30_000])], clock)
    controller.split()
    for _ in range(3):
        clock.advance(9)
        controller.split()
    assert controller.is_new_pb()
    assert controller.view().time_status == GOLD
    controller.reset()
    assert controller.last_reset_was_pb
    assert controller.view().pb == "0:27.00"
    controller.split()
    for _ in range(3):
        clock.advance(10)
        controller.split()
    assert not controller.is_new_pb() and controller.view().time_status == BEHIND


def test_records() -> None:
    runs = [
        _run([10_000, 20_000, 30_000], deaths=5),
        _run([12_000, 21_000, 35_000], deaths=1),
        _run([8_000, None, None], finished=False, deaths=0),
    ]
    records = compute_records(runs, SPLITS, attempts=4)
    assert records.attempts == 4 and records.finished == 2
    assert records.pb is runs[0]
    assert records.fewest_deaths is runs[1]
    assert records.best_segments == [("A", 8_000), ("B", 9_000), ("C", 10_000)]
    assert records.sum_of_best == 27_000


def test_running_time_is_ahead_while_under_the_comparison() -> None:
    clock = FakeClock()
    controller = _controller([_run([10_000, 20_000, 30_000])], clock)
    controller.split()
    clock.advance(9)
    assert controller.view().time_status == AHEAD


# ----------------------------------------------------------------
# Loading-screen heuristic
# ----------------------------------------------------------------
def test_loading_frame_heuristic() -> None:
    black = np.zeros((360, 640, 3), dtype=np.uint8)
    assert is_loading_frame(black)
    with_logo = black.copy()
    with_logo[300:340, 560:620] = 230  # small spinner in a corner
    assert is_loading_frame(with_logo)
    rng = np.random.default_rng(1)
    gameplay = rng.integers(30, 200, size=(360, 640, 3), dtype=np.uint8)
    assert not is_loading_frame(gameplay)
    dark_cave = np.full((360, 640, 3), 6, dtype=np.uint8)
    dark_cave[:, 200:440] = 140  # a lit area
    assert not is_loading_frame(dark_cave)


def test_watcher_reports_activity_only_when_asked() -> None:
    from src.detection.death_watcher import ACTIVITY_LOADING, DeathWatcher, WatchConfig

    watcher = DeathWatcher()
    seen: list[tuple[int, str]] = []
    watcher.activity_changed.connect(lambda gid, activity: seen.append((gid, activity)))
    quiet = WatchConfig(game_id=1, exe_path="game.exe", matcher=None)
    watcher._report(quiet, ACTIVITY_LOADING)
    loud = WatchConfig(game_id=1, exe_path="game.exe", matcher=None, watch_activity=True)
    watcher._report(loud, ACTIVITY_LOADING)
    watcher._report(loud, ACTIVITY_LOADING)  # unchanged: not repeated
    assert seen == [(1, ACTIVITY_LOADING)]


# ----------------------------------------------------------------
# Storage
# ----------------------------------------------------------------
def test_game_times_ids_and_deleting_runs(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    try:
        game_id = db.create_game("Game")
        record = _run([1, 2, 3], game=[1, 1, 2])
        db.add_speedrun_run(game_id, record)
        assert record.run_id is not None
        stored = db.get_speedrun_runs(game_id, SPLITS)[0]
        assert stored.game_times == [1, 1, 2] and stored.run_id == record.run_id
        db.delete_speedrun_run(record.run_id)
        assert db.get_speedrun_runs(game_id, SPLITS) == []
    finally:
        db.close()


def test_pause_screens_are_kept_apart_from_death_screens(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    try:
        game_id = db.create_game("Game")
        db.add_death_template(game_id, "[0,0,1,1]", b"death")
        db.add_death_template(game_id, "[0,0,1,1]", b"pause", SCREEN_PAUSE)
        assert len(db.get_death_templates(game_id)) == 1
        assert len(db.get_death_templates(game_id, SCREEN_PAUSE)) == 1
        db.clear_death_templates(game_id, SCREEN_PAUSE)
        assert len(db.get_death_templates(game_id, SCREEN_DEATH)) == 1
    finally:
        db.close()


def test_old_tables_are_migrated(tmp_path) -> None:
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE games (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                            created_at TEXT NOT NULL);
        CREATE TABLE death_templates (id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL, region TEXT NOT NULL, template BLOB NOT NULL,
            created_at TEXT NOT NULL);
        CREATE TABLE speedrun_runs (id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL, started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
            finished INTEGER NOT NULL, deaths INTEGER NOT NULL DEFAULT 0,
            split_names TEXT NOT NULL, split_times TEXT NOT NULL);
        INSERT INTO games VALUES (1, 'Old', '2024-01-01');
        INSERT INTO death_templates VALUES (1, 1, '[0,0,1,1]', x'00', '2024-01-01');
        INSERT INTO speedrun_runs VALUES (1, 1, 'a', 'b', 1, 0, '["A", "B", "C"]', '[1,2,3]');
        """
    )
    connection.commit()
    connection.close()
    db = Database(path)
    try:
        assert len(db.get_death_templates(1)) == 1  # old screens are death screens
        run = db.get_speedrun_runs(1, SPLITS)[0]
        assert run.game_times == [] and run.times(GAME) == [None, None, None]
    finally:
        db.close()


# ----------------------------------------------------------------
# Main window: auto-pause, auto-save, recovery, history, settings
# ----------------------------------------------------------------
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


def _start(window, name="Game", splits=SPLITS) -> int:
    db = window._database
    game_id = db.create_game(name)
    db.set_speedrun_splits(game_id, splits)
    window._reload_games(select_game_id=game_id)
    window._action_handlers["timer_split"]()
    return game_id


def test_activity_pauses_game_time_and_crash_pauses_timer(window) -> None:
    from src.detection.death_watcher import (
        ACTIVITY_BACKGROUND,
        ACTIVITY_CLOSED,
        ACTIVITY_LOADING,
        ACTIVITY_PLAYING,
    )

    game_id = _start(window)
    controller = window._speedrun
    window._on_game_activity(game_id, ACTIVITY_LOADING)
    assert controller.game_pause_reason == "Loading" and controller.timer.game_paused
    window._on_game_activity(game_id, ACTIVITY_PLAYING)
    assert not controller.timer.game_paused
    window._on_game_activity(game_id, ACTIVITY_BACKGROUND)  # off by default
    assert not controller.timer.game_paused
    window._on_game_activity(game_id + 99, ACTIVITY_LOADING)  # another game
    assert not controller.timer.game_paused
    window._on_game_activity(game_id, ACTIVITY_CLOSED)
    assert controller.timer.state == PAUSED


def test_watching_starts_with_the_run(window) -> None:
    from src.detection.game_window import detection_available

    db = window._database
    game_id = db.create_game("Game")
    db.set_game_detection(game_id, "C:/Games/game.exe", "off")
    window._reload_games(select_game_id=game_id)
    row = db.get_game_detection(game_id)
    assert not window._timer_needs_watching(game_id, row)
    window._action_handlers["timer_split"]()
    assert window._timer_needs_watching(game_id, row) == detection_available()
    if detection_available():
        config = window._death_watcher._config
        assert config is not None and config.watch_activity and config.matcher is None


def test_autosave_and_clean_close(window) -> None:
    db = window._database
    _start(window)
    window._on_increment()
    saved = json.loads(db.get_setting("timer_autosave", ""))
    assert saved["deaths"] == 1 and saved["split_names"] == SPLITS
    window._end_speedrun()
    assert db.get_setting("timer_autosave", "") == ""


def test_crash_recovery_resumes_the_run(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    db = window._database
    game_id = _start(window)
    window._speedrun.timer.add_deaths(2)
    window._autosave()
    saved = db.get_setting("timer_autosave", "")
    # Simulate a crash: the run is gone from memory, the snapshot is left behind.
    window._speedrun.timer.reset()
    window._load_speedrun(force=True)
    db.set_setting("timer_autosave", saved)

    def click(text: str):
        def fake_exec(box: QMessageBox) -> int:
            next(b for b in box.buttons() if b.text() == text).click()
            return 0

        return fake_exec

    monkeypatch.setattr(QMessageBox, "exec", click("Resume Run"))
    window._offer_run_recovery()
    timer = window._speedrun.timer
    assert window._speedrun.game_id == game_id
    assert timer.state == PAUSED and timer.deaths == 2

    window._autosave()
    saved = db.get_setting("timer_autosave", "")
    window._speedrun.timer.reset()
    window._load_speedrun(force=True)
    db.set_setting("timer_autosave", saved)
    monkeypatch.setattr(QMessageBox, "exec", click("Save as Attempt"))
    before = db.count_speedrun_attempts(game_id)
    window._offer_run_recovery()
    assert db.count_speedrun_attempts(game_id) == before + 1
    assert db.get_setting("timer_autosave", "") == ""


def test_run_history_dialog_lists_and_deletes(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from src.ui.timer_window import RunHistoryDialog

    db = window._database
    game_id = _start(window)
    window._action_handlers["timer_reset"]()
    window._action_handlers["timer_split"]()
    window._action_handlers["timer_reset"]()
    controller = window._speedrun
    dialog = RunHistoryDialog(db, controller, parent=window)
    assert dialog._table.rowCount() == 2
    assert "Attempts:</b> 2" in dialog._records_label.text()
    assert dialog._table.item(0, 2).text() == "Reset at A"
    dialog._table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog._delete_selected()
    assert dialog._table.rowCount() == 1
    assert len(db.get_speedrun_runs(game_id, SPLITS)) == 1
    dialog.close()


def test_speedrun_settings_round_trip(window) -> None:
    from src.ui.settings_window import SettingsWindow

    db = window._database
    dialog = SettingsWindow(db)
    dialog._timer_method_combo.setCurrentIndex(dialog._timer_method_combo.findData("game"))
    dialog._timer_digits_combo.setCurrentIndex(dialog._timer_digits_combo.findData("3"))
    dialog._timer_comparison_combo.setCurrentIndex(
        dialog._timer_comparison_combo.findData("previous")
    )
    dialog._timer_pause_checks["timer_pause_loading"].setChecked(False)
    assert dialog._apply()
    assert db.get_setting("timer_method") == "game"
    assert db.get_setting("timer_digits") == "3"
    assert db.get_setting("timer_comparison") == "previous"
    assert db.get_setting("timer_pause_loading") == "false"
    dialog.close()
    game_id = db.create_game("Game")
    window._reload_games(select_game_id=game_id)
    window._on_settings_changed()
    assert window._speedrun.method == GAME and window._speedrun.digits == 3
