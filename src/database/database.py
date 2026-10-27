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
        self._migrate_schema()
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
                defeated INTEGER NOT NULL DEFAULT 0,
                defeated_at TEXT,
                deaths_at_defeat INTEGER,
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
                note TEXT,
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

    def _migrate_schema(self) -> None:
        """
        Upgrade databases created by older app versions in place.

        Uses ``PRAGMA table_info`` to detect missing columns and ALTERs them
        in, so v1.0/v1.1 databases open seamlessly in v1.5+ without any user
        action or data loss.
        """
        with self._cursor() as cursor:
            cursor.execute("PRAGMA table_info(bosses)")
            boss_columns = {row["name"] for row in cursor.fetchall()}
            if "defeated" not in boss_columns:
                cursor.execute(
                    "ALTER TABLE bosses ADD COLUMN defeated INTEGER NOT NULL DEFAULT 0"
                )
                cursor.execute("ALTER TABLE bosses ADD COLUMN defeated_at TEXT")
                cursor.execute("ALTER TABLE bosses ADD COLUMN deaths_at_defeat INTEGER")
                logger.info("Migrated schema: added defeated columns to bosses")

            cursor.execute("PRAGMA table_info(death_events)")
            event_columns = {row["name"] for row in cursor.fetchall()}
            if "note" not in event_columns:
                cursor.execute("ALTER TABLE death_events ADD COLUMN note TEXT")
                logger.info("Migrated schema: added note column to death_events")

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

    def rename_game(self, game_id: int, new_name: str) -> None:
        """
        Rename an existing game.

        Args:
            game_id: The game to rename.
            new_name: The new display name (must remain unique).

        Raises:
            sqlite3.IntegrityError: If another game already has this name.
        """
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE games SET name = ? WHERE id = ?", (new_name.strip(), game_id)
            )
        logger.info("Renamed game id=%s to '%s'", game_id, new_name)

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

    def rename_boss(self, boss_id: int, new_name: str) -> None:
        """
        Rename an existing boss.

        Args:
            boss_id: The boss to rename.
            new_name: The new display name (must remain unique within its game).
        """
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE bosses SET name = ? WHERE id = ?", (new_name.strip(), boss_id)
            )
        logger.info("Renamed boss id=%s to '%s'", boss_id, new_name)

    def get_boss(self, boss_id: int) -> sqlite3.Row | None:
        """Return a single boss row by id, or ``None`` if not found."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM bosses WHERE id = ?", (boss_id,))
            return cursor.fetchone()

    def set_boss_defeated(self, boss_id: int, defeated: bool) -> None:
        """
        Mark or unmark a boss as defeated.

        When marking as defeated, the boss's current death total is captured
        as ``deaths_at_defeat`` — the "deaths until victory" number that
        challenge runners care about. Unmarking clears both fields.

        Args:
            boss_id: The boss to update.
            defeated: ``True`` to mark defeated, ``False`` to unmark.
        """
        if defeated:
            deaths = self.get_boss_deaths(boss_id)
            with self._cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE bosses
                    SET defeated = 1, defeated_at = ?, deaths_at_defeat = ?
                    WHERE id = ?
                    """,
                    (_utc_now_iso(), deaths, boss_id),
                )
            logger.info("Boss id=%s marked defeated after %s death(s)", boss_id, deaths)
        else:
            with self._cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE bosses
                    SET defeated = 0, defeated_at = NULL, deaths_at_defeat = NULL
                    WHERE id = ?
                    """,
                    (boss_id,),
                )
            logger.info("Boss id=%s unmarked as defeated", boss_id)

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

    def get_sessions_with_counts(self, game_id: int) -> list[sqlite3.Row]:
        """
        Return every session for a game, newest first, with its death count.

        Used by the Session History dialog so players can review or delete
        individual runs.
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT s.id, s.started_at, s.ended_at,
                       COALESCE(SUM(d.delta), 0) AS deaths
                FROM sessions s
                LEFT JOIN death_events d ON d.session_id = s.id
                WHERE s.game_id = ?
                GROUP BY s.id
                ORDER BY s.id DESC
                """,
                (game_id,),
            )
            return cursor.fetchall()

    def delete_session(self, session_id: int) -> None:
        """Delete a session and (via cascade) its death events."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        logger.info("Deleted session id=%s", session_id)

    # ----------------------------------------------------------------
    # Death events (counter actions)
    # ----------------------------------------------------------------
    def add_death_event(
        self,
        game_id: int,
        boss_id: int | None,
        session_id: int,
        delta: int,
        note: str | None = None,
    ) -> int:
        """
        Record a death-count change.

        Args:
            game_id: The active game's id.
            boss_id: The active boss's id, or ``None`` if no boss selected.
            session_id: The active session's id.
            delta: +1 for a death, -1 for a decrement/undo.
            note: Optional free-text note attached to this event.

        Returns:
            The id of the newly inserted event (used for fine-grained undo).
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO death_events (game_id, boss_id, session_id, delta, timestamp, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (game_id, boss_id, session_id, delta, _utc_now_iso(), note),
            )
            event_id = cursor.lastrowid
        return int(event_id)

    def set_event_note(self, event_id: int, note: str) -> None:
        """Attach or replace the free-text note on a death event."""
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE death_events SET note = ? WHERE id = ?", (note, event_id)
            )
        logger.info("Updated note on event id=%s", event_id)

    def get_recent_events(
        self, game_id: int, boss_id: int | None = None, limit: int = 200
    ) -> list[sqlite3.Row]:
        """
        Return recent death events for a game (optionally one boss), newest
        first, with the boss name joined in for display.
        """
        query = """
            SELECT d.id, d.delta, d.timestamp, d.note, b.name AS boss_name
            FROM death_events d
            LEFT JOIN bosses b ON b.id = d.boss_id
            WHERE d.game_id = ?
        """
        params: list[Any] = [game_id]
        if boss_id is not None:
            query += " AND d.boss_id = ?"
            params.append(boss_id)
        query += " ORDER BY d.id DESC LIMIT ?"
        params.append(limit)
        with self._cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def get_deaths_per_day(self, game_id: int) -> list[sqlite3.Row]:
        """Return (day, deaths) rows for a game, oldest first (for graphs)."""
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT date(timestamp) AS day, SUM(delta) AS deaths
                FROM death_events
                WHERE game_id = ?
                GROUP BY day
                ORDER BY day ASC
                """,
                (game_id,),
            )
            return cursor.fetchall()

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

    def set_session_death_count(
        self, game_id: int, boss_id: int | None, session_id: int, target: int
    ) -> None:
        """
        Force the session's death count to an exact value.

        Rather than mutating history, this inserts a single corrective
        event equal to the difference, preserving the append-only ledger
        design (and therefore undo/audit-trail integrity).

        Args:
            game_id: The active game's id.
            boss_id: The active boss's id, or ``None``.
            session_id: The session to correct.
            target: The desired resulting session death count (>= 0).
        """
        target = max(0, target)
        current = self.get_session_death_count(session_id)
        delta = target - current
        if delta != 0:
            self.add_death_event(game_id, boss_id, session_id, delta)
        logger.info("Set session id=%s death count to %s (delta=%s)", session_id, target, delta)

    def set_total_death_count(self, game_id: int, boss_id: int | None, target: int) -> None:
        """
        Force a game's total death count to an exact value.

        Args:
            game_id: The game to correct.
            boss_id: An optional boss to attribute the corrective event to.
            target: The desired resulting total death count (>= 0).
        """
        target = max(0, target)
        current = self.get_total_deaths(game_id)
        delta = target - current
        if delta != 0:
            # Corrective events for the total are attached to a synthetic
            # session-less bucket by reusing the most recent session, or -1
            # if none exists yet, to keep the NOT NULL constraint satisfied.
            with self._cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM sessions WHERE game_id = ? ORDER BY id DESC LIMIT 1",
                    (game_id,),
                )
                row = cursor.fetchone()
            session_id = row["id"] if row is not None else self.start_session(game_id)
            self.add_death_event(game_id, boss_id, session_id, delta)
        logger.info("Set total deaths for game_id=%s to %s (delta=%s)", game_id, target, delta)

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

    # ----------------------------------------------------------------
    # Full backup / restore (JSON export-import) and reset
    # ----------------------------------------------------------------
    def export_data(self) -> dict[str, Any]:
        """
        Export every game, boss, session, and death event as plain dicts.

        Returns:
            A JSON-serializable dict suitable for :meth:`import_data`.
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM games")
            games = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM bosses")
            bosses = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM sessions")
            sessions = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM death_events")
            death_events = [dict(row) for row in cursor.fetchall()]
        return {
            "format_version": 1,
            "games": games,
            "bosses": bosses,
            "sessions": sessions,
            "death_events": death_events,
        }

    def import_data(self, data: dict[str, Any], mode: str = "merge") -> None:
        """
        Import games/bosses/sessions/death events from an export dict.

        Args:
            data: A dict previously produced by :meth:`export_data`.
            mode: ``"merge"`` adds imported games alongside existing ones
                (renaming on name collision). ``"replace"`` wipes all
                existing game data first.

        Raises:
            ValueError: If ``data`` is missing required keys.
        """
        required_keys = {"games", "bosses", "sessions", "death_events"}
        if not required_keys.issubset(data):
            raise ValueError(f"Import file is missing required keys: {required_keys - data.keys()}")

        if mode == "replace":
            self.clear_all_data()

        existing_names = {g["name"] for g in self.get_games()}

        # Map old ids -> new ids so relationships survive re-insertion.
        game_id_map: dict[int, int] = {}
        boss_id_map: dict[int, int] = {}
        session_id_map: dict[int, int] = {}

        for game in data["games"]:
            name = game["name"]
            while name in existing_names:
                name = f"{name} (Imported)"
            new_id = self.create_game(name)
            existing_names.add(name)
            game_id_map[game["id"]] = new_id

        for boss in data["bosses"]:
            new_game_id = game_id_map.get(boss["game_id"])
            if new_game_id is None:
                continue
            new_id = self.create_boss(new_game_id, boss["name"])
            boss_id_map[boss["id"]] = new_id
            if boss.get("defeated"):
                # Restore the exact captured values rather than recomputing.
                with self._cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE bosses
                        SET defeated = 1, defeated_at = ?, deaths_at_defeat = ?
                        WHERE id = ?
                        """,
                        (boss.get("defeated_at"), boss.get("deaths_at_defeat"), new_id),
                    )

        for session in data["sessions"]:
            new_game_id = game_id_map.get(session["game_id"])
            if new_game_id is None:
                continue
            new_id = self.start_session(new_game_id)
            if session.get("ended_at"):
                self.end_session(new_id)
            session_id_map[session["id"]] = new_id

        for event in data["death_events"]:
            new_game_id = game_id_map.get(event["game_id"])
            new_session_id = session_id_map.get(event["session_id"])
            if new_game_id is None or new_session_id is None:
                continue
            new_boss_id = boss_id_map.get(event["boss_id"]) if event.get("boss_id") else None
            self.add_death_event(
                new_game_id, new_boss_id, new_session_id, event["delta"], event.get("note")
            )

        logger.info(
            "Imported %d game(s) in '%s' mode", len(data["games"]), mode
        )

    def clear_all_data(self) -> None:
        """
        Delete every game (and, via cascade, all bosses/sessions/events).

        Settings are preserved intentionally, so theme/hotkey preferences
        survive a full data wipe.
        """
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM games")
        logger.warning("All game data cleared (settings preserved)")
