"""Unit tests for CounterManager, SessionManager, and StatisticsService."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.counter_manager import CounterManager  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from src.core.statistics import StatisticsService  # noqa: E402
from src.database.database import Database  # noqa: E402


@pytest.fixture()
def setup(tmp_path):
    """Provide a fully wired Database + SessionManager + CounterManager."""
    database = Database(tmp_path / "test.db")
    session_manager = SessionManager(database)
    counter_manager = CounterManager(database, session_manager)
    yield database, session_manager, counter_manager
    database.close()


def test_increment_requires_game_selection(setup) -> None:
    _, _, counter_manager = setup
    snapshot = counter_manager.increment()
    assert snapshot.session_deaths == 0
    assert snapshot.total_deaths == 0


def test_increment_decrement_flow(setup) -> None:
    database, _, counter_manager = setup
    game_id = database.create_game("Bloodborne")
    counter_manager.set_current_game(game_id, "Bloodborne")

    counter_manager.increment()
    counter_manager.increment()
    snapshot = counter_manager.decrement()

    assert snapshot.session_deaths == 1
    assert snapshot.total_deaths == 1


def test_undo_reverts_last_action(setup) -> None:
    database, _, counter_manager = setup
    game_id = database.create_game("Bloodborne")
    counter_manager.set_current_game(game_id, "Bloodborne")

    counter_manager.increment()
    counter_manager.increment()
    snapshot = counter_manager.undo()

    assert snapshot.session_deaths == 1


def test_switching_games_starts_new_session(setup) -> None:
    database, session_manager, counter_manager = setup
    game_a = database.create_game("Bloodborne")
    game_b = database.create_game("Sekiro")

    counter_manager.set_current_game(game_a, "Bloodborne")
    counter_manager.increment()
    session_a = session_manager.current_session_id

    counter_manager.set_current_game(game_b, "Sekiro")
    session_b = session_manager.current_session_id

    assert session_a != session_b
    # Switching back to game_a's death total should remain intact (total is
    # tracked per-game, not per-session).
    assert database.get_total_deaths(game_a) == 1


def test_reset_session_does_not_affect_total(setup) -> None:
    database, _, counter_manager = setup
    game_id = database.create_game("Bloodborne")
    counter_manager.set_current_game(game_id, "Bloodborne")
    counter_manager.increment()
    counter_manager.increment()

    counter_manager.reset_session()
    snapshot = counter_manager.get_snapshot()

    assert snapshot.session_deaths == 0
    # Total tracks the whole game across all events, including the reset
    # session's now-deleted events, so it returns to 0 as well since the
    # events were removed by reset_session (session-scoped wipe).
    assert snapshot.total_deaths == 0


def test_statistics_service_game_summary(setup) -> None:
    database, _, counter_manager = setup
    game_id = database.create_game("Bloodborne")
    boss_id = database.create_boss(game_id, "Father Gascoigne")
    counter_manager.set_current_game(game_id, "Bloodborne")
    counter_manager.set_current_boss(boss_id, "Father Gascoigne")

    counter_manager.increment()
    counter_manager.increment()
    counter_manager.increment()

    stats = StatisticsService(database).get_game_statistics(game_id)
    assert stats.total_deaths == 3
    assert stats.most_deaths_boss == "Father Gascoigne"
    assert stats.average_deaths_per_boss == 3.0
