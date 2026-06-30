"""
SQLite database access layer for Universal Death Counter.

This module is the *only* place in the codebase that should execute raw
SQL. All other modules go through :class:`Database` so that the schema and
query logic stay in one auditable location.

Schema design notes
--------------------
Rather than storing a single mutable "death count" column (which makes
undo and statistics awkward), every death/undo action is recorded as a row
in ``death_events`` with a ``delta`` of +1 or -1. Totals, session counts,
and the "Statistics" feature set required by the spec are all derived by
aggregating this event log. This gives us:

* Free, reliable undo (just remove the most recent event).
* Accurate per-session and per-boss totals via SUM().
* A full audit trail for future features (graphs, CSV/JSON export, OCR
  plugin verification, etc.) without any schema changes.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from src.utils.constants import DATABASE_PATH, DEFAULT_SETTINGS
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """
    Thin wrapper around an SQLite connection providing CRUD operations
    for games, bosses, sessions, death events, and settings.
    """

    def __init__(self, db_path: Path = DATABASE_PATH) -> None:
        """
        Initialize the database, creating the file and schema if needed.

        Args:
            db_path: Filesystem path to the SQLite database file.
        """
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()
        self._seed_default_settings()
        logger.info("Database initialized at %s", self._db_path)

    # ----------------------------------------------------------------
    # Schema management
    # ----------------------------------------------------------------
    def _create_schema(self) -> None:
        """Create all required tables if they do not already exist."""
        schema_statements = (
            """
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS bosses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE,
                UNIQUE (game_id, name)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE
            )
            """,
            # death_events is the append-only ledger described above.
            # `delta` is +1 for a death, -1 for an undo/manual decrement.
            """
            CREATE TABLE IF NOT EXISTS death_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                boss_id INTEGER,
                session_id INTEGER NOT NULL,
                delta INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE,
                FOREIGN KEY (boss_id) REFERENCES bosses (id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
        )
        with self._cursor() as cursor:
            for statement in schema_statements:
                cursor.execute(statement)

    def _seed_default_settings(self) -> None:
        """Insert default settings for any keys not already present."""
        with self._cursor() as cursor:
            for key, value in DEFAULT_SETTINGS.items():
                cursor.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )

    # ----------------------------------------------------------------
    # Low-level helpers
    # ----------------------------------------------------------------
    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        """Context manager yielding a cursor and committing on success."""
        cursor = self._connection.cursor()
        try:
            yield cursor
            self._connection.commit()
        except sqlite3.Error:
            self._connection.rollback()
            logger.exception("Database operation failed; transaction rolled back")
            raise
        finally:
            cursor.close()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._connection.close()
        logger.info("Database connection closed")

    # ----------------------------------------------------------------
    # Games
    # ----------------------------------------------------------------
    def create_game(self, name: str) -> int:
        """
        Insert a new game.

        Args:
            name: The display name of the game. Must be unique.

        Returns:
            The newly created game's primary key.

        Raises:
            sqlite3.IntegrityError: If a game with this name already exists.
        """
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO games (name, created_at) VALUES (?, ?)",
                (name.strip(), _utc_now_iso()),
            )
            game_id = cursor.lastrowid
        logger.info("Created game '%s' (id=%s)", name, game_id)
        return int(game_id)

    def delete_game(self, game_id: int) -> None:
        """Delete a game and (via cascade) all its bosses/sessions/events."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM games WHERE id = ?", (game_id,))
        logger.info("Deleted game id=%s", game_id)

    def get_games(self) -> list[sqlite3.Row]:
        """Return all games ordered alphabetically."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM games ORDER BY name COLLATE NOCASE")
            return cursor.fetchall()

    def get_game(self, game_id: int) -> sqlite3.Row | None:
        """Return a single game row by id, or ``None`` if not found."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
            return cursor.fetchone()

    # ----------------------------------------------------------------
    # Bosses
    # ----------------------------------------------------------------
    def create_boss(self, game_id: int, name: str) -> int:
        """
        Insert a new boss under the given game.

        Args:
            game_id: The owning game's id.
            name: The boss's display name. Must be unique within the game.

        Returns:
            The newly created boss's primary key.
        """
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO bosses (game_id, name, created_at) VALUES (?, ?, ?)",
                (game_id, name.strip(), _utc_now_iso()),
            )
            boss_id = cursor.lastrowid
        logger.info("Created boss '%s' (id=%s) for game_id=%s", name, boss_id, game_id)
        return int(boss_id)

    def delete_boss(self, boss_id: int) -> None:
        """Delete a boss and (via cascade) its associated death events."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM bosses WHERE id = ?", (boss_id,))
        logger.info("Deleted boss id=%s", boss_id)

    def get_bosses(self, game_id: int) -> list[sqlite3.Row]:
        """Return all bosses belonging to a game, ordered alphabetically."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM bosses WHERE game_id = ? ORDER BY name COLLATE NOCASE",
                (game_id,),
            )
            return cursor.fetchall()

    # ----------------------------------------------------------------
    # Sessions
    # ----------------------------------------------------------------
    def start_session(self, game_id: int) -> int:
        """Start (and persist) a new play session for a game."""
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO sessions (game_id, started_at, ended_at) VALUES (?, ?, NULL)",
                (game_id, _utc_now_iso()),
            )
            session_id = cursor.lastrowid
        logger.info("Started session id=%s for game_id=%s", session_id, game_id)
        return int(session_id)

    def end_session(self, session_id: int) -> None:
        """Mark a session as ended (sets ``ended_at``)."""
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?",
                (_utc_now_iso(), session_id),
            )
        logger.info("Ended session id=%s", session_id)

    def get_session_death_count(self, session_id: int) -> int:
        """Return the net death count (sum of deltas) for one session."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(SUM(delta), 0) AS total FROM death_events WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            return int(row["total"])

    # ----------------------------------------------------------------
    # Death events (counter actions)
    # ----------------------------------------------------------------
    def add_death_event(
        self, game_id: int, boss_id: int | None, session_id: int, delta: int
    ) -> int:
        """
        Record a death-count change.

        Args:
            game_id: The active game's id.
            boss_id: The active boss's id, or ``None`` if no boss selected.
            session_id: The active session's id.
            delta: +1 for a death, -1 for a decrement/undo.

        Returns:
            The id of the newly inserted event (used for fine-grained undo).
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO death_events (game_id, boss_id, session_id, delta, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (game_id, boss_id, session_id, delta, _utc_now_iso()),
            )
            event_id = cursor.lastrowid
        return int(event_id)

    def remove_last_event(self, session_id: int) -> bool:
        """
        Remove the most recent death event for a session (true undo).

        Args:
            session_id: The session to undo the last action for.

        Returns:
            ``True`` if an event was removed, ``False`` if none existed.
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM death_events
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            cursor.execute("DELETE FROM death_events WHERE id = ?", (row["id"],))
        logger.info("Removed last death event (id=%s) for session_id=%s", row["id"], session_id)
        return True

    def get_total_deaths(self, game_id: int | None = None) -> int:
        """Return total net deaths, optionally filtered by game."""
        with self._cursor() as cursor:
            if game_id is None:
                cursor.execute("SELECT COALESCE(SUM(delta), 0) AS total FROM death_events")
            else:
                cursor.execute(
                    "SELECT COALESCE(SUM(delta), 0) AS total FROM death_events WHERE game_id = ?",
                    (game_id,),
                )
            return int(cursor.fetchone()["total"])

    def get_boss_deaths(self, boss_id: int) -> int:
        """Return total net deaths recorded against a specific boss."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(SUM(delta), 0) AS total FROM death_events WHERE boss_id = ?",
                (boss_id,),
            )
            return int(cursor.fetchone()["total"])

    def reset_total(self, game_id: int) -> None:
        """Wipe all death events for a game, resetting its total to zero."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM death_events WHERE game_id = ?", (game_id,))
        logger.info("Reset total deaths for game_id=%s", game_id)

    def reset_session(self, session_id: int) -> None:
        """Wipe all death events for a single session."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM death_events WHERE session_id = ?", (session_id,))
        logger.info("Reset session id=%s", session_id)

    # ----------------------------------------------------------------
    # Statistics support queries
    # ----------------------------------------------------------------
    def get_boss_death_totals(self, game_id: int) -> list[sqlite3.Row]:
        """Return (boss name, total deaths) rows for every boss in a game."""
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT b.id, b.name, COALESCE(SUM(d.delta), 0) AS total
                FROM bosses b
                LEFT JOIN death_events d ON d.boss_id = b.id
                WHERE b.game_id = ?
                GROUP BY b.id
                ORDER BY total DESC
                """,
                (game_id,),
            )
            return cursor.fetchall()

    def get_most_played_game(self) -> sqlite3.Row | None:
        """Return the game with the most sessions recorded."""
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT g.id, g.name, COUNT(s.id) AS session_count
                FROM games g
                LEFT JOIN sessions s ON s.game_id = g.id
                GROUP BY g.id
                ORDER BY session_count DESC
                LIMIT 1
                """
            )
            return cursor.fetchone()

    def get_total_sessions(self, game_id: int | None = None) -> int:
        """Return the number of sessions (play runs), optionally per game."""
        with self._cursor() as cursor:
            if game_id is None:
                cursor.execute("SELECT COUNT(*) AS total FROM sessions")
            else:
                cursor.execute(
                    "SELECT COUNT(*) AS total FROM sessions WHERE game_id = ?", (game_id,)
                )
            return int(cursor.fetchone()["total"])

    # ----------------------------------------------------------------
    # Settings
    # ----------------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        """Return a setting's value, or ``default`` if not set."""
        with self._cursor() as cursor:
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row is not None else default

    def set_setting(self, key: str, value: Any) -> None:
        """Insert or update a setting value (stored as text)."""
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )

    def get_all_settings(self) -> dict[str, str]:
        """Return all settings as a plain dict."""
        with self._cursor() as cursor:
            cursor.execute("SELECT key, value FROM settings")
            return {row["key"]: row["value"] for row in cursor.fetchall()}
