"""Unit tests for the v1.1 freedom features: rename, exact-set, backup/restore."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.counter_manager import CounterManager  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from src.database.database import Database  # noqa: E402
from src.utils.game_templates import GAME_TEMPLATES, get_template, get_template_names  # noqa: E402


@pytest.fixture()
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


# ----------------------------------------------------------------
# Rename
# ----------------------------------------------------------------
def test_rename_game(db: Database) -> None:
    game_id = db.create_game("Old Name")
    db.rename_game(game_id, "New Name")
    assert db.get_game(game_id)["name"] == "New Name"


def test_rename_boss(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    boss_id = db.create_boss(game_id, "Old Boss")
    db.rename_boss(boss_id, "New Boss")
    bosses = db.get_bosses(game_id)
    assert bosses[0]["name"] == "New Boss"


# ----------------------------------------------------------------
# Exact count corrections
# ----------------------------------------------------------------
def test_set_session_death_count(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, None, session_id, +1)

    db.set_session_death_count(game_id, None, session_id, 25)
    assert db.get_session_death_count(session_id) == 25

    db.set_session_death_count(game_id, None, session_id, 5)
    assert db.get_session_death_count(session_id) == 5


def test_set_session_death_count_clamps_negative(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    db.set_session_death_count(game_id, None, session_id, -10)
    assert db.get_session_death_count(session_id) == 0


def test_set_total_death_count(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, None, session_id, +1)
    db.add_death_event(game_id, None, session_id, +1)

    db.set_total_death_count(game_id, None, 100)
    assert db.get_total_deaths(game_id) == 100


def test_counter_manager_set_session_and_total(db: Database) -> None:
    session_manager = SessionManager(db)
    counter_manager = CounterManager(db, session_manager)
    game_id = db.create_game("Sekiro")
    counter_manager.set_current_game(game_id, "Sekiro")

    snapshot = counter_manager.set_session_count(42)
    assert snapshot.session_deaths == 42

    snapshot = counter_manager.set_total_count(7)
    assert snapshot.total_deaths == 7


# ----------------------------------------------------------------
# Session history
# ----------------------------------------------------------------
def test_get_sessions_with_counts(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, None, session_id, +1)
    db.add_death_event(game_id, None, session_id, +1)

    sessions = db.get_sessions_with_counts(game_id)
    assert len(sessions) == 1
    assert sessions[0]["deaths"] == 2


def test_delete_session(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    db.delete_session(session_id)
    assert db.get_sessions_with_counts(game_id) == []


# ----------------------------------------------------------------
# Export / Import (backup + restore)
# ----------------------------------------------------------------
def test_export_import_round_trip(db: Database, tmp_path) -> None:
    game_id = db.create_game("Sekiro")
    boss_id = db.create_boss(game_id, "Genichiro")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, boss_id, session_id, +1)
    db.add_death_event(game_id, boss_id, session_id, +1)

    exported = db.export_data()

    other_db = Database(tmp_path / "other.db")
    other_db.import_data(exported, mode="merge")

    games = other_db.get_games()
    assert len(games) == 1
    assert games[0]["name"] == "Sekiro"
    bosses = other_db.get_bosses(games[0]["id"])
    assert bosses[0]["name"] == "Genichiro"
    assert other_db.get_total_deaths(games[0]["id"]) == 2
    other_db.close()


def test_import_merge_renames_on_collision(db: Database, tmp_path) -> None:
    db.create_game("Sekiro")
    exported = db.export_data()

    # Importing into a db that already has "Sekiro" should rename, not fail.
    db.import_data(exported, mode="merge")
    names = {g["name"] for g in db.get_games()}
    assert "Sekiro" in names
    assert any("Imported" in name for name in names)


def test_import_replace_wipes_existing(db: Database, tmp_path) -> None:
    db.create_game("Will Be Wiped")
    other = Database(tmp_path / "source.db")
    other.create_game("Sekiro")
    exported = other.export_data()
    other.close()

    db.import_data(exported, mode="replace")
    names = {g["name"] for g in db.get_games()}
    assert names == {"Sekiro"}


def test_import_rejects_malformed_data(db: Database) -> None:
    with pytest.raises(ValueError):
        db.import_data({"games": []})


# ----------------------------------------------------------------
# Clear all data
# ----------------------------------------------------------------
def test_clear_all_data_preserves_settings(db: Database) -> None:
    db.create_game("Sekiro")
    db.set_setting("theme", "light")

    db.clear_all_data()

    assert db.get_games() == []
    assert db.get_setting("theme") == "light"


# ----------------------------------------------------------------
# Game templates
# ----------------------------------------------------------------
def test_template_library_not_empty() -> None:
    assert len(GAME_TEMPLATES) >= 1
    assert "Elden Ring" in get_template_names()


def test_get_template_returns_bosses() -> None:
    template = get_template("Elden Ring")
    assert template is not None
    assert len(template.bosses) > 0


def test_get_template_unknown_returns_none() -> None:
    assert get_template("Not A Real Game") is None
