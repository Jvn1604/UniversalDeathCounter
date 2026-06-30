"""Unit tests for the SQLite database access layer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.database import Database  # noqa: E402


@pytest.fixture()
def db(tmp_path) -> Database:
    """Provide a fresh, isolated Database backed by a temp file."""
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def test_create_and_get_game(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    games = db.get_games()
    assert len(games) == 1
    assert games[0]["name"] == "Sekiro"
    assert games[0]["id"] == game_id


def test_duplicate_game_name_raises(db: Database) -> None:
    db.create_game("Sekiro")
    with pytest.raises(Exception):
        db.create_game("Sekiro")


def test_delete_game_cascades_to_bosses(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    db.create_boss(game_id, "Genichiro")
    db.delete_game(game_id)
    assert db.get_games() == []


def test_create_boss_and_list(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    db.create_boss(game_id, "Genichiro")
    db.create_boss(game_id, "Owl")
    bosses = db.get_bosses(game_id)
    assert {b["name"] for b in bosses} == {"Genichiro", "Owl"}


def test_death_event_increment_and_total(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    boss_id = db.create_boss(game_id, "Genichiro")
    session_id = db.start_session(game_id)

    db.add_death_event(game_id, boss_id, session_id, +1)
    db.add_death_event(game_id, boss_id, session_id, +1)
    db.add_death_event(game_id, boss_id, session_id, +1)

    assert db.get_total_deaths(game_id) == 3
    assert db.get_boss_deaths(boss_id) == 3
    assert db.get_session_death_count(session_id) == 3


def test_undo_removes_last_event(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, None, session_id, +1)
    db.add_death_event(game_id, None, session_id, +1)

    removed = db.remove_last_event(session_id)
    assert removed is True
    assert db.get_total_deaths(game_id) == 1


def test_undo_on_empty_session_returns_false(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    assert db.remove_last_event(session_id) is False


def test_reset_total(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, None, session_id, +1)
    db.add_death_event(game_id, None, session_id, +1)

    db.reset_total(game_id)
    assert db.get_total_deaths(game_id) == 0


def test_settings_round_trip(db: Database) -> None:
    db.set_setting("theme", "light")
    assert db.get_setting("theme") == "light"
    assert db.get_setting("nonexistent", "fallback") == "fallback"


def test_boss_death_totals_ordering(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    boss_a = db.create_boss(game_id, "Genichiro")
    boss_b = db.create_boss(game_id, "Owl")
    session_id = db.start_session(game_id)

    db.add_death_event(game_id, boss_a, session_id, +1)
    db.add_death_event(game_id, boss_b, session_id, +1)
    db.add_death_event(game_id, boss_b, session_id, +1)

    totals = db.get_boss_death_totals(game_id)
    assert totals[0]["name"] == "Owl"
    assert totals[0]["total"] == 2
