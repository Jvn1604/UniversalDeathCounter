"""Unit tests for v1.5 features: defeated tracking, notes, profiles,
stream templates, CSV export, charts data, and update version parsing."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.counter_manager import CounterSnapshot  # noqa: E402
from src.database.database import Database  # noqa: E402
from src.utils.exporters import write_csv_summary  # noqa: E402
from src.utils.profiles import DEFAULT_PROFILE_NAME, ProfileManager  # noqa: E402
from src.utils.stream_writer import render_template  # noqa: E402
from src.utils.update_checker import _parse_version  # noqa: E402


@pytest.fixture()
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


# ----------------------------------------------------------------
# Boss defeated + deaths until victory
# ----------------------------------------------------------------
def test_mark_boss_defeated_captures_deaths(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    boss_id = db.create_boss(game_id, "Genichiro")
    session_id = db.start_session(game_id)
    for _ in range(7):
        db.add_death_event(game_id, boss_id, session_id, +1)

    db.set_boss_defeated(boss_id, True)
    boss = db.get_boss(boss_id)
    assert boss["defeated"] == 1
    assert boss["deaths_at_defeat"] == 7
    assert boss["defeated_at"] is not None


def test_unmark_boss_defeated_clears_fields(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    boss_id = db.create_boss(game_id, "Genichiro")
    db.set_boss_defeated(boss_id, True)
    db.set_boss_defeated(boss_id, False)
    boss = db.get_boss(boss_id)
    assert boss["defeated"] == 0
    assert boss["deaths_at_defeat"] is None


def test_defeated_survives_export_import(db: Database, tmp_path) -> None:
    game_id = db.create_game("Sekiro")
    boss_id = db.create_boss(game_id, "Genichiro")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, boss_id, session_id, +1)
    db.set_boss_defeated(boss_id, True)

    other = Database(tmp_path / "other.db")
    other.import_data(db.export_data(), mode="merge")
    imported_boss = other.get_bosses(other.get_games()[0]["id"])[0]
    assert imported_boss["defeated"] == 1
    assert imported_boss["deaths_at_defeat"] == 1
    other.close()


# ----------------------------------------------------------------
# Death notes
# ----------------------------------------------------------------
def test_death_event_note_round_trip(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    event_id = db.add_death_event(game_id, None, session_id, +1, note="fell off cliff")
    events = db.get_recent_events(game_id)
    assert events[0]["note"] == "fell off cliff"

    db.set_event_note(event_id, "phase 2 grab")
    events = db.get_recent_events(game_id)
    assert events[0]["note"] == "phase 2 grab"


def test_notes_survive_export_import(db: Database, tmp_path) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, None, session_id, +1, note="lightning grab")

    other = Database(tmp_path / "other.db")
    other.import_data(db.export_data(), mode="merge")
    events = other.get_recent_events(other.get_games()[0]["id"])
    assert events[0]["note"] == "lightning grab"
    other.close()


def test_get_recent_events_filters_by_boss(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    boss_a = db.create_boss(game_id, "A")
    boss_b = db.create_boss(game_id, "B")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, boss_a, session_id, +1)
    db.add_death_event(game_id, boss_b, session_id, +1)

    events = db.get_recent_events(game_id, boss_id=boss_a)
    assert len(events) == 1
    assert events[0]["boss_name"] == "A"


# ----------------------------------------------------------------
# Deaths per day (timeline chart data)
# ----------------------------------------------------------------
def test_get_deaths_per_day(db: Database) -> None:
    game_id = db.create_game("Sekiro")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, None, session_id, +1)
    db.add_death_event(game_id, None, session_id, +1)

    days = db.get_deaths_per_day(game_id)
    assert len(days) == 1
    assert days[0]["deaths"] == 2


# ----------------------------------------------------------------
# Profiles
# ----------------------------------------------------------------
def test_profile_manager_defaults(tmp_path) -> None:
    pm = ProfileManager(saves_dir=tmp_path)
    assert pm.active_profile == DEFAULT_PROFILE_NAME
    assert pm.list_profiles() == [DEFAULT_PROFILE_NAME]


def test_profile_create_switch_delete(tmp_path) -> None:
    pm = ProfileManager(saves_dir=tmp_path)
    pm.create_profile("Co-op Nights")
    assert "Co-op Nights" in pm.list_profiles()

    pm.set_active("Co-op Nights")
    assert pm.active_profile == "Co-op Nights"
    assert pm.active_db_path().name == "co-op_nights.db"

    # Registry persists across instances
    pm2 = ProfileManager(saves_dir=tmp_path)
    assert pm2.active_profile == "Co-op Nights"

    pm2.delete_profile("Co-op Nights")
    assert pm2.active_profile == DEFAULT_PROFILE_NAME
    assert "Co-op Nights" not in pm2.list_profiles()


def test_profile_default_cannot_be_deleted(tmp_path) -> None:
    pm = ProfileManager(saves_dir=tmp_path)
    with pytest.raises(ValueError):
        pm.delete_profile(DEFAULT_PROFILE_NAME)


def test_profile_duplicate_name_rejected(tmp_path) -> None:
    pm = ProfileManager(saves_dir=tmp_path)
    pm.create_profile("Runs")
    with pytest.raises(ValueError):
        pm.create_profile("Runs")


# ----------------------------------------------------------------
# deaths.txt template rendering
# ----------------------------------------------------------------
def _snapshot() -> CounterSnapshot:
    return CounterSnapshot(
        game_name="Elden Ring",
        boss_name="Malenia",
        session_deaths=5,
        total_deaths=120,
        boss_deaths=42,
    )


def test_render_template_all_placeholders() -> None:
    template = "{game}|{boss}|{deaths}|{session}|{boss_deaths}|{total}"
    result = render_template(template, _snapshot(), "boss")
    assert result == "Elden Ring|Malenia|42|5|42|120"


def test_render_template_counter_sources() -> None:
    snapshot = _snapshot()
    assert render_template("{deaths}", snapshot, "session") == "5"
    assert render_template("{deaths}", snapshot, "boss") == "42"
    assert render_template("{deaths}", snapshot, "total") == "120"


def test_render_template_stray_braces_safe() -> None:
    # str.format would raise on {unknown}; plain replacement must not.
    result = render_template("Deaths {deaths} {unknown} {{weird}}", _snapshot(), "session")
    assert "5" in result
    assert "{unknown}" in result


def test_render_template_no_game() -> None:
    snapshot = CounterSnapshot(None, None, 0, 0, 0)
    assert render_template("{game}:{boss}:{deaths}", snapshot, "session") == "No Game::0"


# ----------------------------------------------------------------
# CSV export
# ----------------------------------------------------------------
def test_csv_summary_export(db: Database, tmp_path) -> None:
    game_id = db.create_game("Sekiro")
    boss_id = db.create_boss(game_id, "Genichiro")
    session_id = db.start_session(game_id)
    db.add_death_event(game_id, boss_id, session_id, +1)
    db.add_death_event(game_id, boss_id, session_id, +1)
    db.set_boss_defeated(boss_id, True)

    csv_path = tmp_path / "summary.csv"
    row_count = write_csv_summary(db, csv_path)
    assert row_count == 2  # boss row + game total row

    with open(csv_path, newline="", encoding="utf-8") as file:
        rows = list(csv.reader(file))
    assert rows[0] == ["game", "boss", "total_deaths", "defeated", "deaths_until_victory"]
    assert rows[1] == ["Sekiro", "Genichiro", "2", "yes", "2"]
    assert rows[2][1] == "(All bosses)"
    assert rows[2][2] == "2"


# ----------------------------------------------------------------
# Update checker version parsing
# ----------------------------------------------------------------
def test_parse_version_variants() -> None:
    assert _parse_version("v1.5.0") == (1, 5, 0)
    assert _parse_version("1.5.0") == (1, 5, 0)
    assert _parse_version("v2.0.0-beta") == (2, 0, 0)
    assert _parse_version("garbage") == (0,)


def test_version_comparison() -> None:
    assert _parse_version("v1.5.1") > _parse_version("1.5.0")
    assert _parse_version("v2.0.0") > _parse_version("1.9.9")
    assert not _parse_version("v1.5.0") > _parse_version("1.5.0")
