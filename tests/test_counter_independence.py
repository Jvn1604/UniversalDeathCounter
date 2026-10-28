"""Session, boss and total counts stay independent and never go negative."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.counter_manager import CounterManager  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from src.database.database import Database  # noqa: E402


@pytest.fixture()
def counter(tmp_path):
    db = Database(tmp_path / "test.db")
    manager = CounterManager(db, SessionManager(db))
    game_id = db.create_game("Dark Souls")
    manager.set_current_game(game_id, "Dark Souls")
    yield db, manager, game_id
    db.close()


def test_minus_one_never_goes_below_zero(counter) -> None:
    _, manager, _ = counter
    snapshot = manager.decrement()
    assert (snapshot.session_deaths, snapshot.total_deaths) == (0, 0)
    manager.increment()
    manager.decrement()
    snapshot = manager.decrement()
    assert (snapshot.session_deaths, snapshot.total_deaths) == (0, 0)


def test_minus_one_never_takes_boss_below_zero(counter) -> None:
    db, manager, game_id = counter
    manager.increment()  # a death with no boss selected
    boss_id = db.create_boss(game_id, "Taurus Demon")
    manager.set_current_boss(boss_id, "Taurus Demon")
    snapshot = manager.decrement()
    assert snapshot.boss_deaths == 0
    assert snapshot.session_deaths == 1


def test_reset_total_keeps_session_and_boss(counter) -> None:
    db, manager, game_id = counter
    boss_id = db.create_boss(game_id, "Asylum Demon")
    manager.set_current_boss(boss_id, "Asylum Demon")
    for _ in range(3):
        manager.increment()
    snapshot = manager.reset_total()
    assert snapshot.total_deaths == 0
    assert snapshot.session_deaths == 3
    assert snapshot.boss_deaths == 3
    snapshot = manager.increment()
    assert (snapshot.session_deaths, snapshot.total_deaths) == (4, 1)


def test_reset_session_starts_fresh_and_keeps_history(counter) -> None:
    db, manager, game_id = counter
    for _ in range(10):
        manager.increment()
    snapshot = manager.reset_session()
    assert (snapshot.session_deaths, snapshot.total_deaths) == (0, 10)
    counts = [row["deaths"] for row in db.get_sessions_with_counts(game_id)]
    assert counts == [0, 10]  # newest first: the fresh session, then the old one


def test_set_total_leaves_session_alone(counter) -> None:
    db, manager, game_id = counter
    manager.increment()
    snapshot = manager.set_total_count(50)
    assert (snapshot.session_deaths, snapshot.total_deaths) == (1, 50)
    assert [row["deaths"] for row in db.get_sessions_with_counts(game_id)] == [1]


def test_undo_after_reset_total_cannot_go_negative(counter) -> None:
    _, manager, _ = counter
    manager.increment()
    manager.reset_total()
    snapshot = manager.undo()
    assert snapshot.total_deaths == 0
    assert snapshot.session_deaths == 1
    manager.increment()
    snapshot = manager.undo()  # undoing a death counted after the reset is fine
    assert (snapshot.session_deaths, snapshot.total_deaths) == (1, 0)


def test_backup_round_trip_keeps_total_corrections(counter, tmp_path) -> None:
    db, manager, _ = counter
    manager.increment()
    manager.increment()
    manager.reset_total()
    restored = Database(tmp_path / "restored.db")
    try:
        restored.import_data(db.export_data())
        game_id = restored.get_games()[0]["id"]
        assert restored.get_total_deaths(game_id) == 0
        assert [r["deaths"] for r in restored.get_sessions_with_counts(game_id)] == [2]
    finally:
        restored.close()


def test_old_database_gets_kind_column(tmp_path) -> None:
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE games (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                            created_at TEXT NOT NULL);
        CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER NOT NULL,
                               started_at TEXT NOT NULL, ended_at TEXT);
        CREATE TABLE death_events (id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL, boss_id INTEGER, session_id INTEGER NOT NULL,
            delta INTEGER NOT NULL, timestamp TEXT NOT NULL, note TEXT);
        INSERT INTO games VALUES (1, 'Old Game', '2024-01-01');
        INSERT INTO sessions VALUES (1, 1, '2024-01-01', NULL);
        INSERT INTO death_events VALUES (1, 1, NULL, 1, 1, '2024-01-01', NULL);
        """
    )
    connection.commit()
    connection.close()
    db = Database(path)
    try:
        assert db.get_session_death_count(1) == 1  # old deaths count as deaths
        assert db.get_total_deaths(1) == 1
    finally:
        db.close()
