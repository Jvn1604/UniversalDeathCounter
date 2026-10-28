"""Regression tests for the bugs and performance issues found in UAT."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.speedrun import RunRecord  # noqa: E402
from src.database.database import SCREEN_PAUSE, SCREEN_VICTORY, Database  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def _patch_profiles(tmp_path, monkeypatch):
    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    return mw


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    mw = _patch_profiles(tmp_path, monkeypatch)
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    yield win
    win._quit_app()
    app.processEvents()


# ---------------------------------------------------------------- 1. crash recovery
def test_crash_snapshot_survives_the_next_startup(tmp_path, monkeypatch) -> None:
    """Regression: loading the last game at startup wiped the crash snapshot."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    mw = _patch_profiles(tmp_path, monkeypatch)
    app = QApplication.instance() or QApplication([])
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: (shown.append(box.windowTitle()), 0)[1])

    first = mw.MainWindow()
    game_id = first._database.create_game("Elden Ring")
    first._reload_games(select_game_id=game_id)
    first._timer_action("split")  # a run is going, and auto-saved
    assert first._database.get_setting("timer_autosave", "")
    # Crash: none of the clean shutdown runs.
    for timer in (first._autosave_timer, first._recovery_timer, first._game_launch_timer):
        timer.stop()
    first._hotkey_manager.stop()
    first._gamepad_manager.stop()
    first._death_watcher.stop()
    first._database.close()

    second = mw.MainWindow()  # starts on the same game, as after a real restart
    try:
        for _ in range(5):
            app.processEvents()
            time.sleep(0.02)
        assert "Recover Run" in shown
    finally:
        second._quit_app()
        app.processEvents()


def test_idle_session_never_clears_a_waiting_snapshot(window) -> None:
    db = window._database
    db.set_setting("timer_autosave", '{"game_id": 1}')
    window._end_speedrun()
    window._autosave()  # no run going in this session
    assert db.get_setting("timer_autosave", "") == '{"game_id": 1}'


# ---------------------------------------------------------------- 2. deleting a boss
def test_deleting_a_boss_keeps_its_deaths(db) -> None:
    game = db.create_game("G")
    boss = db.create_boss(game, "Boss")
    session = db.start_session(game)
    for _ in range(10):
        db.add_death_event(game, boss, session, +1)
    db.add_death_event(game, None, session, +1)
    db.delete_boss(boss)
    assert db.get_total_deaths(game) == 11
    assert db.get_session_death_count(session) == 11
    assert db.get_bosses(game) == []


# ---------------------------------------------------------------- 3/4. deleted game mid-run
def test_deleting_the_game_mid_run_drops_the_run(window) -> None:
    db = window._database
    first = db.create_game("Elden Ring")
    second = db.create_game("Sekiro")
    window._reload_games(select_game_id=first)
    window._timer_action("split")
    db.delete_game(first)
    window._reload_games()  # what closing Games & Bosses does
    assert window._speedrun.game_id == second
    assert not window._speedrun.running
    window._timer_action("reset")  # used to raise IntegrityError
    assert db.count_speedrun_attempts(second) == 0


def test_clear_all_data_mid_run(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from src.ui.main_window import _PAGE_TIMER

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes)
    db = window._database
    game = db.create_game("Elden Ring")
    window._reload_games(select_game_id=game)
    window._timer_action("split")
    window._clear_all_data()
    assert window._speedrun is None or window._speedrun.game_id is None
    window._timer_action("reset")  # used to raise IntegrityError
    window._show_page(_PAGE_TIMER)
    assert window._timer_page_split.text() == "SELECT A GAME"


# ---------------------------------------------------------------- 5. complete backups
def test_backup_round_trip_keeps_everything(tmp_path, db) -> None:
    game = db.create_game("Elden Ring")
    boss = db.create_boss(game, "Margit")
    session = db.start_session(game)
    db.add_death_event(game, boss, session, +1, timestamp="2026-01-02T03:04:05+00:00")
    db.set_game_detection(game, r"C:\Games\eldenring.exe", "souls")
    db.update_detection_options(game, log_pattern="died")
    db.add_death_template(game, "[0,0,1,1]", b"\x00\x01death")
    db.add_death_template(game, "[0,0,1,1]", b"\x02victory", SCREEN_VICTORY)
    db.add_death_template(game, "[0,0,1,1]", b"\x03pause", SCREEN_PAUSE)
    db.set_speedrun_splits(game, ["Margit", "Godrick"])
    db.add_speedrun_run(
        game, RunRecord(["Margit", "Godrick"], [1000, 2000], True, 3, "a", "b", [900, 1800])
    )

    data = json.loads(json.dumps(db.export_data()))  # through a real JSON file
    restored = Database(tmp_path / "restored.db")
    try:
        restored.import_data(data)
        new = restored.get_games()[0]["id"]
        row = restored.get_game_detection(new)
        assert row["exe_path"] == r"C:\Games\eldenring.exe" and row["mode"] == "souls"
        assert restored.get_detection_options(new) == {"log_pattern": "died"}
        assert bytes(restored.get_death_templates(new)[0]["template"]) == b"\x00\x01death"
        assert len(restored.get_death_templates(new, SCREEN_VICTORY)) == 1
        assert len(restored.get_death_templates(new, SCREEN_PAUSE)) == 1
        assert restored.get_speedrun_splits(new) == ["Margit", "Godrick"]
        run = restored.get_speedrun_runs(new, ["Margit", "Godrick"])[0]
        assert run.split_times == [1000, 2000] and run.game_times == [900, 1800]
        event = restored.get_recent_events(new)[0]
        assert event["timestamp"] == "2026-01-02T03:04:05+00:00"  # not "now"
        session_row = restored.get_sessions_with_counts(new)[0]
        original = db.get_sessions_with_counts(game)[0]
        assert session_row["started_at"] == original["started_at"]
    finally:
        restored.close()


def test_old_format_backups_still_import(tmp_path, db) -> None:
    game = db.create_game("Old")
    db.add_death_event(game, None, db.start_session(game), +1)
    data = db.export_data()
    for key in ("game_detection", "screens", "speedrun_splits", "speedrun_runs"):
        data.pop(key)
    data["format_version"] = 1
    restored = Database(tmp_path / "restored.db")
    try:
        restored.import_data(data)
        assert restored.get_total_deaths() == 1
    finally:
        restored.close()


# ---------------------------------------------------------------- 6. local dates
def test_deaths_per_day_uses_local_dates(db) -> None:
    game = db.create_game("G")
    stamp = "2026-03-01T20:30:00+00:00"  # a different calendar day in many time zones
    db.add_death_event(game, None, db.start_session(game), +1, timestamp=stamp)
    local_day = datetime.fromisoformat(stamp).astimezone().date().isoformat()
    assert [row["day"] for row in db.get_deaths_per_day(game)] == [local_day]


# ---------------------------------------------------------------- 7. single instance
@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex")
def test_only_one_copy_can_hold_the_lock() -> None:
    from src.utils import single_instance

    name = f"Local\\DUDCTest{os.getpid()}"
    try:
        assert single_instance.acquire(name)
        assert not single_instance.acquire(name)  # a second copy
    finally:
        single_instance.release()
    assert single_instance.acquire(name)  # free again once released
    single_instance.release()


# ---------------------------------------------------------------- 8. timers stop on close
def test_closing_stops_background_timers(window) -> None:
    window._quit_app()
    assert not window._game_launch_timer.isActive()
    assert not window._autosave_timer.isActive()


# ---------------------------------------------------------------- performance
def test_numpy_math_threads_are_limited() -> None:
    import src  # noqa: F401 - the package sets it on import

    assert os.environ.get("OPENBLAS_NUM_THREADS") == "1"


def test_hidden_timer_window_does_not_redraw(window) -> None:
    db = window._database
    game = db.create_game("G")
    window._reload_games(select_game_id=game)
    window._timer_action("split")  # starting shows the timer window
    timer_window = window._timer_window
    assert timer_window._tick.isActive()
    timer_window.hide()
    timer_window.refresh()
    assert not timer_window._tick.isActive()
    timer_window.show()
    assert timer_window._tick.isActive()
