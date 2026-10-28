"""
Session lifecycle management.

A "session" represents one play run for a game (e.g. from launching the
app/selecting a game, until switching games or closing the app). The
:class:`SessionManager` owns the currently-active session id and exposes
helpers to start, end, and reset it.
"""

from __future__ import annotations

from src.database.database import Database
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SessionManager:
    """Tracks the currently active play session for the selected game."""

    def __init__(self, database: Database) -> None:
        """
        Args:
            database: Shared :class:`Database` instance.
        """
        self._database = database
        self._current_session_id: int | None = None
        self._current_game_id: int | None = None

    @property
    def current_session_id(self) -> int | None:
        """The id of the currently active session, if any."""
        return self._current_session_id

    @property
    def current_game_id(self) -> int | None:
        """The game the active session belongs to, if any."""
        return self._current_game_id

    def start_new_session(self, game_id: int) -> int:
        """
        End any existing session and start a fresh one for ``game_id``.

        Args:
            game_id: The game the new session belongs to.

        Returns:
            The id of the newly created session.
        """
        self.end_current_session()
        self._current_session_id = self._database.start_session(game_id)
        self._current_game_id = game_id
        logger.info("New session started: id=%s game_id=%s", self._current_session_id, game_id)
        return self._current_session_id

    def end_current_session(self) -> None:
        """End the currently active session, if one exists."""
        if self._current_session_id is not None:
            self._database.end_session(self._current_session_id)
            logger.info("Session ended: id=%s", self._current_session_id)
        self._current_session_id = None
        self._current_game_id = None

    def get_session_deaths(self) -> int:
        """Return the death count for the current session (0 if none active)."""
        if self._current_session_id is None:
            return 0
        return self._database.get_session_death_count(self._current_session_id)

    def reset_session(self) -> None:
        """
        Start the session count over at zero by beginning a fresh session.

        The old session's deaths stay in history and in the game's total.
        """
        if self._current_game_id is not None:
            self.start_new_session(self._current_game_id)

    def ensure_session(self, game_id: int) -> int:
        """
        Return the active session id for ``game_id``, starting one if needed.

        This avoids creating a brand-new session every time the user simply
        re-selects the same game (e.g. switching boss dropdowns).
        """
        if self._current_session_id is None or self._current_game_id != game_id:
            return self.start_new_session(game_id)
        return self._current_session_id
