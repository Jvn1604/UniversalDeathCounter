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

import base64
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.core.speedrun import RunRecord
from src.utils.constants import DATABASE_PATH, DEFAULT_SETTINGS
from src.utils.logger import get_logger

logger = get_logger(__name__)


# death_events.kind: a real death (or -1 correction) that counts toward the
# session, boss and total; or a correction to the total alone (Reset Total /
# Set Total), which leaves the session and boss counts untouched.
EVENT_DEATH: str = "death"
EVENT_TOTAL_ADJUST: str = "total_adjust"


# death_templates.kind
SCREEN_DEATH: str = "death"
SCREEN_PAUSE: str = "pause"
SCREEN_VICTORY: str = "victory"  # a boss-kill banner, e.g. "GREAT ENEMY FELLED"


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat(timespec="seconds")


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
                kind TEXT NOT NULL DEFAULT 'death',
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
            # Per-game auto-detection config and its calibrated death screens.
            # Kept out of `games` because the exe path is machine-specific and
            # templates are BLOBs, so neither belongs in JSON backups.
            """
            CREATE TABLE IF NOT EXISTS game_detection (
                game_id INTEGER PRIMARY KEY,
                exe_path TEXT,
                mode TEXT NOT NULL DEFAULT 'off',
                options TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE
            )
            """,
            # Speedrun splits per game (in order), and every attempt. An
            # attempt's split names and cumulative times are JSON lists, so
            # comparisons only use attempts made with the same splits.
            """
            CREATE TABLE IF NOT EXISTS speedrun_splits (
                game_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (game_id, position),
                FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS speedrun_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                finished INTEGER NOT NULL,
                deaths INTEGER NOT NULL DEFAULT 0,
                split_names TEXT NOT NULL,
                split_times TEXT NOT NULL,
                game_times TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE
            )
            """,
            # A game can have several death screens (variants, or extra
            # captures added after a missed death); any one matching counts.
            """
            CREATE TABLE IF NOT EXISTS death_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                region TEXT NOT NULL,
                template BLOB NOT NULL,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'death',
                FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE
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
            if "kind" not in event_columns:
                cursor.execute(
                    "ALTER TABLE death_events ADD COLUMN kind TEXT NOT NULL DEFAULT 'death'"
                )
                logger.info("Migrated schema: added kind column to death_events")

            cursor.execute("PRAGMA table_info(game_detection)")
            detection_columns = {row["name"] for row in cursor.fetchall()}
            if "options" not in detection_columns:
                cursor.execute(
                    "ALTER TABLE game_detection ADD COLUMN options TEXT NOT NULL DEFAULT '{}'"
                )
                logger.info("Migrated schema: added options column to game_detection")

            cursor.execute("PRAGMA table_info(death_templates)")
            if "kind" not in {row["name"] for row in cursor.fetchall()}:
                cursor.execute(
                    "ALTER TABLE death_templates ADD COLUMN kind TEXT NOT NULL DEFAULT 'death'"
                )
                logger.info("Migrated schema: added kind column to death_templates")

            cursor.execute("PRAGMA table_info(speedrun_runs)")
            if "game_times" not in {row["name"] for row in cursor.fetchall()}:
                cursor.execute(
                    "ALTER TABLE speedrun_runs ADD COLUMN game_times TEXT NOT NULL DEFAULT '[]'"
                )
                logger.info("Migrated schema: added game_times column to speedrun_runs")

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
    # Auto-detection config
    # ----------------------------------------------------------------
    def get_game_detection(self, game_id: int) -> sqlite3.Row | None:
        """Return a game's auto-detection config row, or ``None`` if never set."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM game_detection WHERE game_id = ?", (game_id,))
            return cursor.fetchone()

    def set_game_detection(self, game_id: int, exe_path: str | None, mode: str) -> None:
        """
        Set a game's executable and detection mode, keeping any calibration.

        Args:
            game_id: The game to configure.
            exe_path: Full path of the game's .exe (``None`` to clear).
            mode: One of the ``DETECTION_MODE_*`` constants.
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO game_detection (game_id, exe_path, mode) VALUES (?, ?, ?)
                ON CONFLICT (game_id) DO UPDATE
                SET exe_path = excluded.exe_path, mode = excluded.mode
                """,
                (game_id, exe_path, mode),
            )
        logger.info("Set detection for game_id=%s: mode=%s exe=%s", game_id, mode, exe_path)

    def get_detection_options(self, game_id: int) -> dict[str, Any]:
        """Return a game's mode-specific detection options (health bar, log file…)."""
        row = self.get_game_detection(game_id)
        try:
            options = json.loads(row["options"]) if row is not None else {}
        except (TypeError, ValueError):
            logger.warning("Ignoring corrupt detection options for game_id=%s", game_id)
            return {}
        return options if isinstance(options, dict) else {}

    def update_detection_options(self, game_id: int, **changes: Any) -> None:
        """Merge ``changes`` into a game's detection options (None removes a key)."""
        options = self.get_detection_options(game_id)
        for key, value in changes.items():
            if value is None:
                options.pop(key, None)
            else:
                options[key] = value
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO game_detection (game_id, options) VALUES (?, ?)
                ON CONFLICT (game_id) DO UPDATE SET options = excluded.options
                """,
                (game_id, json.dumps(options)),
            )

    def get_all_game_detections(self) -> list[sqlite3.Row]:
        """Return every game's detection config that has an executable set."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM game_detection WHERE exe_path IS NOT NULL AND mode != 'off'"
            )
            return cursor.fetchall()

    def add_death_template(
        self, game_id: int, region: str, template: bytes, kind: str = SCREEN_DEATH
    ) -> int:
        """
        Store one more calibrated screen for a game; returns its id.

        ``kind`` is ``SCREEN_DEATH`` (counts a death) or ``SCREEN_PAUSE`` (a
        pause, loading or cutscene screen that stops the timer's game time).
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO death_templates (game_id, region, template, created_at, kind)
                VALUES (?, ?, ?, ?, ?)
                """,
                (game_id, region, sqlite3.Binary(template), _utc_now_iso(), kind),
            )
            template_id = cursor.lastrowid
        logger.info("Stored death-screen template id=%s for game_id=%s", template_id, game_id)
        return int(template_id)

    def get_death_templates(self, game_id: int, kind: str = SCREEN_DEATH) -> list[sqlite3.Row]:
        """Return a game's calibrated screens of one kind, oldest first."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM death_templates WHERE game_id = ? AND kind = ? ORDER BY id",
                (game_id, kind),
            )
            return cursor.fetchall()

    def clear_death_templates(self, game_id: int, kind: str = SCREEN_DEATH) -> None:
        """Delete all of a game's calibrated screens of one kind."""
        with self._cursor() as cursor:
            cursor.execute(
                "DELETE FROM death_templates WHERE game_id = ? AND kind = ?", (game_id, kind)
            )
        logger.info("Cleared %s-screen templates for game_id=%s", kind, game_id)

    # ----------------------------------------------------------------
    # Speedrun splits and attempts
    # ----------------------------------------------------------------
    def get_speedrun_splits(self, game_id: int) -> list[str]:
        """A game's split names, in order (empty if none set up)."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT name FROM speedrun_splits WHERE game_id = ? ORDER BY position",
                (game_id,),
            )
            return [row["name"] for row in cursor.fetchall()]

    def set_speedrun_splits(self, game_id: int, names: list[str]) -> None:
        """Replace a game's split names (earlier attempts are kept)."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM speedrun_splits WHERE game_id = ?", (game_id,))
            cursor.executemany(
                "INSERT INTO speedrun_splits (game_id, position, name) VALUES (?, ?, ?)",
                [(game_id, index, name) for index, name in enumerate(names)],
            )
        logger.info("Set %d speedrun split(s) for game_id=%s", len(names), game_id)

    def add_speedrun_run(self, game_id: int, run: RunRecord) -> None:
        """Store one attempt (finished or reset)."""
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO speedrun_runs (game_id, started_at, ended_at, finished, deaths,
                                           split_names, split_times, game_times)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    run.started_at or _utc_now_iso(),
                    run.ended_at or _utc_now_iso(),
                    int(run.finished),
                    run.deaths,
                    json.dumps(run.split_names),
                    json.dumps(run.split_times),
                    json.dumps(run.game_times),
                ),
            )
            run.run_id = cursor.lastrowid

    def get_speedrun_runs(self, game_id: int, split_names: list[str]) -> list[RunRecord]:
        """A game's attempts made with exactly these splits, oldest first."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM speedrun_runs WHERE game_id = ? AND split_names = ? ORDER BY id",
                (game_id, json.dumps(split_names)),
            )
            rows = cursor.fetchall()
        return [
            RunRecord(
                split_names=json.loads(row["split_names"]),
                split_times=json.loads(row["split_times"]),
                finished=bool(row["finished"]),
                deaths=row["deaths"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                game_times=json.loads(row["game_times"] or "[]"),
                run_id=row["id"],
            )
            for row in rows
        ]

    def delete_speedrun_run(self, run_id: int) -> None:
        """Delete one attempt (e.g. a mistaken run in Run History)."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM speedrun_runs WHERE id = ?", (run_id,))
        logger.info("Deleted speedrun attempt id=%s", run_id)

    def count_speedrun_attempts(self, game_id: int) -> int:
        """Every attempt for a game, whatever its splits."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM speedrun_runs WHERE game_id = ?", (game_id,)
            )
            return int(cursor.fetchone()["n"])

    def clear_speedrun_runs(self, game_id: int) -> None:
        """Delete a game's attempts (resets PB, golds and the attempt count)."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM speedrun_runs WHERE game_id = ?", (game_id,))
        logger.info("Cleared speedrun attempts for game_id=%s", game_id)

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
        """
        Delete a boss, keeping its deaths in the game's totals (as "No boss").

        The schema's ON DELETE CASCADE would otherwise erase those deaths and
        silently lower the session and all-time counts.
        """
        with self._cursor() as cursor:
            cursor.execute("UPDATE death_events SET boss_id = NULL WHERE boss_id = ?", (boss_id,))
            cursor.execute("DELETE FROM bosses WHERE id = ?", (boss_id,))
        logger.info("Deleted boss id=%s", boss_id)

    def get_bosses(self, game_id: int) -> list[sqlite3.Row]:
        """
        Return all bosses belonging to a game, in the order they were added.

        That's story order for the built-in boss lists (and usually for bosses
        added while playing), which is what "next boss", auto-advance after a
        kill, and splits made from the boss list need.
        """
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM bosses WHERE game_id = ? ORDER BY id",
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

    def latest_session_activity(self, game_id: int) -> tuple[int, str] | None:
        """
        A game's newest session and when it was last used (ISO time), or None.

        "Last used" is the latest of its start, end and last death, so a
        session a crash never ended still has a sensible time.
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT s.id,
                       MAX(s.started_at, COALESCE(s.ended_at, ''),
                           COALESCE((SELECT MAX(timestamp) FROM death_events
                                     WHERE session_id = s.id), '')) AS last_used
                FROM sessions s
                WHERE s.game_id = ?
                ORDER BY s.id DESC
                LIMIT 1
                """,
                (game_id,),
            )
            row = cursor.fetchone()
        return (int(row["id"]), str(row["last_used"])) if row is not None else None

    def reopen_session(self, session_id: int) -> None:
        """Continue an ended session (clears ``ended_at``)."""
        with self._cursor() as cursor:
            cursor.execute("UPDATE sessions SET ended_at = NULL WHERE id = ?", (session_id,))
        logger.info("Reopened session id=%s", session_id)

    def get_session_death_count(self, session_id: int) -> int:
        """Return the net death count (sum of deltas) for one session."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(SUM(delta), 0) AS total FROM death_events "
                "WHERE session_id = ? AND kind = ?",
                (session_id, EVENT_DEATH),
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
                LEFT JOIN death_events d ON d.session_id = s.id AND d.kind = ?
                WHERE s.game_id = ?
                GROUP BY s.id
                ORDER BY s.id DESC
                """,
                (EVENT_DEATH, game_id),
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
        kind: str = EVENT_DEATH,
        timestamp: str | None = None,
    ) -> int:
        """
        Record a death-count change.

        Args:
            game_id: The active game's id.
            boss_id: The active boss's id, or ``None`` if no boss selected.
            session_id: The active session's id.
            delta: +1 for a death, -1 for a decrement/undo.
            note: Optional free-text note attached to this event.
            kind: ``EVENT_DEATH``, or ``EVENT_TOTAL_ADJUST`` for a correction
                that changes only the game's total.
            timestamp: When it happened (ISO 8601); now if omitted. Backups
                pass the original time.

        Returns:
            The id of the newly inserted event (used for fine-grained undo).
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO death_events
                    (game_id, boss_id, session_id, delta, timestamp, note, kind)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (game_id, boss_id, session_id, delta, timestamp or _utc_now_iso(), note, kind),
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

    def get_total_timeline(self, game_id: int) -> list[sqlite3.Row]:
        """Return every (timestamp, delta) change to a game's total, oldest first."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT timestamp, delta FROM death_events WHERE game_id = ? ORDER BY id",
                (game_id,),
            )
            return cursor.fetchall()

    def get_deaths_per_day(self, game_id: int) -> list[sqlite3.Row]:
        """Return (local day, deaths) rows for a game, oldest first (for graphs)."""
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT date(timestamp, 'localtime') AS day, SUM(delta) AS deaths
                FROM death_events
                WHERE game_id = ?
                GROUP BY day
                ORDER BY day ASC
                """,
                (game_id,),
            )
            return cursor.fetchall()

    def get_last_event(self, session_id: int) -> sqlite3.Row | None:
        """Return a session's most recent death (or -1) event, if any."""
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM death_events
                WHERE session_id = ? AND kind = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (session_id, EVENT_DEATH),
            )
            return cursor.fetchone()

    def remove_last_event(self, session_id: int) -> bool:
        """
        Remove the most recent death event for a session (true undo).

        Total-only corrections are skipped: undo is about deaths.

        Args:
            session_id: The session to undo the last action for.

        Returns:
            ``True`` if an event was removed, ``False`` if none existed.
        """
        row = self.get_last_event(session_id)
        if row is None:
            return False
        with self._cursor() as cursor:
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

    def set_total_death_count(self, game_id: int, target: int) -> None:
        """
        Force a game's total death count to an exact value.

        Inserts one total-only corrective event, so the current session's
        and every boss's counts stay as they are.

        Args:
            game_id: The game to correct.
            target: The desired resulting total death count (>= 0).
        """
        target = max(0, target)
        current = self.get_total_deaths(game_id)
        delta = target - current
        if delta != 0:
            # session_id is NOT NULL, so the correction is filed under the most
            # recent session; its kind keeps it out of that session's count.
            with self._cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM sessions WHERE game_id = ? ORDER BY id DESC LIMIT 1",
                    (game_id,),
                )
                row = cursor.fetchone()
            session_id = row["id"] if row is not None else self.start_session(game_id)
            self.add_death_event(game_id, None, session_id, delta, kind=EVENT_TOTAL_ADJUST)
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
        """
        Set a game's total to zero, keeping session and boss counts and history.
        """
        self.set_total_death_count(game_id, 0)

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
        Export everything a restore needs as plain dicts.

        Games, bosses, sessions and death events, plus (since format 2) each
        game's detection setup and saved screens, speedrun splits and runs.
        Settings and profiles are not included.

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
            # v2: everything else a restore needs on another PC.
            cursor.execute("SELECT game_id, exe_path, mode, options FROM game_detection")
            detection = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM death_templates")
            screens = [
                {**dict(row), "template": base64.b64encode(bytes(row["template"])).decode()}
                for row in cursor.fetchall()
            ]
            cursor.execute("SELECT * FROM speedrun_splits ORDER BY game_id, position")
            splits = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM speedrun_runs ORDER BY id")
            runs = [dict(row) for row in cursor.fetchall()]
        return {
            "format_version": 2,
            "games": games,
            "bosses": bosses,
            "sessions": sessions,
            "death_events": death_events,
            "game_detection": detection,
            "screens": screens,
            "speedrun_splits": splits,
            "speedrun_runs": runs,
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
            with self._cursor() as cursor:  # keep the original dates
                cursor.execute(
                    "INSERT INTO sessions (game_id, started_at, ended_at) VALUES (?, ?, ?)",
                    (
                        new_game_id,
                        session.get("started_at") or _utc_now_iso(),
                        session.get("ended_at"),
                    ),
                )
                session_id_map[session["id"]] = int(cursor.lastrowid)

        for event in data["death_events"]:
            new_game_id = game_id_map.get(event["game_id"])
            new_session_id = session_id_map.get(event["session_id"])
            if new_game_id is None or new_session_id is None:
                continue
            new_boss_id = boss_id_map.get(event["boss_id"]) if event.get("boss_id") else None
            self.add_death_event(
                new_game_id,
                new_boss_id,
                new_session_id,
                event["delta"],
                event.get("note"),
                kind=event.get("kind") or EVENT_DEATH,
                timestamp=event.get("timestamp"),
            )

        self._import_extras(data, game_id_map)
        logger.info(
            "Imported %d game(s) in '%s' mode", len(data["games"]), mode
        )

    def _import_extras(self, data: dict[str, Any], game_id_map: dict[int, int]) -> None:
        """Format-2 parts of a backup: detection setup, screens, splits and runs."""
        with self._cursor() as cursor:
            for row in data.get("game_detection", []):
                game_id = game_id_map.get(row["game_id"])
                if game_id is not None:
                    cursor.execute(
                        "INSERT OR REPLACE INTO game_detection (game_id, exe_path, mode, options) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            game_id,
                            row.get("exe_path"),
                            row.get("mode") or "off",
                            row.get("options") or "{}",
                        ),
                    )
            for row in data.get("screens", []):
                game_id = game_id_map.get(row["game_id"])
                if game_id is not None:
                    cursor.execute(
                        "INSERT INTO death_templates (game_id, region, template, created_at, kind) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            game_id,
                            row["region"],
                            sqlite3.Binary(base64.b64decode(row["template"])),
                            row.get("created_at") or _utc_now_iso(),
                            row.get("kind") or SCREEN_DEATH,
                        ),
                    )
            for row in data.get("speedrun_splits", []):
                game_id = game_id_map.get(row["game_id"])
                if game_id is not None:
                    cursor.execute(
                        "INSERT OR REPLACE INTO speedrun_splits (game_id, position, name) "
                        "VALUES (?, ?, ?)",
                        (game_id, row["position"], row["name"]),
                    )
            for row in data.get("speedrun_runs", []):
                game_id = game_id_map.get(row["game_id"])
                if game_id is not None:
                    cursor.execute(
                        "INSERT INTO speedrun_runs (game_id, started_at, ended_at, finished, "
                        "deaths, split_names, split_times, game_times) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            game_id,
                            row["started_at"],
                            row["ended_at"],
                            row["finished"],
                            row.get("deaths", 0),
                            row["split_names"],
                            row["split_times"],
                            row.get("game_times") or "[]",
                        ),
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
