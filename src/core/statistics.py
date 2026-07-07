"""
Aggregate statistics computation.

This module turns the raw ``death_events``/``sessions``/``bosses`` tables
into the human-readable statistics required by the spec (most deaths on a
boss, average deaths per boss, most played game, etc.). Keeping this logic
separate from :class:`~src.database.database.Database` keeps the SQL layer
generic and the "business meaning" of the numbers in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.database.database import Database
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class GameStatistics:
    """Aggregate statistics scoped to a single game."""

    total_deaths: int
    most_deaths_boss: str | None
    most_deaths_count: int
    least_deaths_boss: str | None
    least_deaths_count: int
    average_deaths_per_boss: float
    total_runs: int


@dataclass(slots=True)
class GlobalStatistics:
    """Aggregate statistics across all games."""

    total_deaths_all_games: int
    most_played_game: str | None
    most_played_game_sessions: int
    total_play_sessions: int


class StatisticsService:
    """Computes statistics summaries on demand from the database."""

    def __init__(self, database: Database) -> None:
        """
        Args:
            database: Shared :class:`Database` instance.
        """
        self._database = database

    def get_game_statistics(self, game_id: int) -> GameStatistics:
        """
        Compute statistics for a single game.

        Args:
            game_id: The game to compute statistics for.

        Returns:
            A populated :class:`GameStatistics` instance.
        """
        boss_totals = self._database.get_boss_death_totals(game_id)
        total_deaths = self._database.get_total_deaths(game_id)
        total_runs = self._database.get_total_sessions(game_id)

        if boss_totals:
            most = max(boss_totals, key=lambda row: row["total"])
            least = min(boss_totals, key=lambda row: row["total"])
            average = sum(row["total"] for row in boss_totals) / len(boss_totals)
            most_name, most_count = most["name"], int(most["total"])
            least_name, least_count = least["name"], int(least["total"])
        else:
            most_name = least_name = None
            most_count = least_count = 0
            average = 0.0

        return GameStatistics(
            total_deaths=total_deaths,
            most_deaths_boss=most_name,
            most_deaths_count=most_count,
            least_deaths_boss=least_name,
            least_deaths_count=least_count,
            average_deaths_per_boss=round(average, 2),
            total_runs=total_runs,
        )

    def get_global_statistics(self) -> GlobalStatistics:
        """
        Compute statistics across every game.

        Returns:
            A populated :class:`GlobalStatistics` instance.
        """
        most_played = self._database.get_most_played_game()
        return GlobalStatistics(
            total_deaths_all_games=self._database.get_total_deaths(),
            most_played_game=most_played["name"] if most_played else None,
            most_played_game_sessions=int(most_played["session_count"]) if most_played else 0,
            total_play_sessions=self._database.get_total_sessions(),
        )
