"""CSV export: a spreadsheet-friendly summary of per-boss and per-game totals."""

from __future__ import annotations

import csv
from pathlib import Path

from src.database.database import Database
from src.utils.logger import get_logger

logger = get_logger(__name__)

_HEADER = ["game", "boss", "total_deaths", "defeated", "deaths_until_victory"]


def write_csv_summary(database: Database, path: Path) -> int:
    """
    Write a summary CSV of all games and bosses.

    One row per boss, plus a "(All bosses)" total row per game.

    Args:
        database: The database to export from.
        path: Destination .csv path.

    Returns:
        The number of data rows written.

    Raises:
        OSError: If the file cannot be written.
    """
    rows: list[list[object]] = []
    for game in database.get_games():
        game_id, game_name = game["id"], game["name"]
        for boss in database.get_bosses(game_id):
            rows.append(
                [
                    game_name,
                    boss["name"],
                    database.get_boss_deaths(boss["id"]),
                    "yes" if boss["defeated"] else "no",
                    boss["deaths_at_defeat"] if boss["defeated"] else "",
                ]
            )
        rows.append([game_name, "(All bosses)", database.get_total_deaths(game_id), "", ""])

    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(_HEADER)
        writer.writerows(rows)

    logger.info("CSV summary exported to %s (%d rows)", path, len(rows))
    return len(rows)
