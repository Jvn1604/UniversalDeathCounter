"""
Core death-counting logic.

:class:`CounterManager` is the single source of truth for "what is the
current game/boss, and what are the live counters". The UI layer and the
hotkey layer both call into this class so that behavior is identical
regardless of whether a death was registered by mouse click or by a
global hotkey while the game is focused.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.session_manager import SessionManager
from src.database.database import Database
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class CounterSnapshot:
    """Immutable snapshot of counter state, used to refresh the UI/overlay."""

    game_name: str | None
    boss_name: str | None
    session_deaths: int
    total_deaths: int
    boss_deaths: int = 0
    run_deaths: int = 0  # the speedrun in progress (filled in by the main window)


class CounterManager:
    """
    Owns the currently selected game/boss and mediates all death-count
    mutations (increment, decrement, undo, reset).
    """

    def __init__(self, database: Database, session_manager: SessionManager) -> None:
        """
        Args:
            database: Shared :class:`Database` instance.
            session_manager: Shared :class:`SessionManager` instance.
        """
        self._database = database
        self._session_manager = session_manager
        self._current_game_id: int | None = None
        self._current_game_name: str | None = None
        self._current_boss_id: int | None = None
        self._current_boss_name: str | None = None

    # ----------------------------------------------------------------
    # Selection
    # ----------------------------------------------------------------
    def set_current_game(self, game_id: int | None, game_name: str | None) -> None:
        """Select the active game, starting/reusing a session for it."""
        self._current_game_id = game_id
        self._current_game_name = game_name
        self._current_boss_id = None
        self._current_boss_name = None
        if game_id is not None:
            self._session_manager.ensure_session(game_id)
            self._database.set_setting("last_game_id", game_id)
        logger.info("Current game set to '%s' (id=%s)", game_name, game_id)

    def set_current_boss(self, boss_id: int | None, boss_name: str | None) -> None:
        """Select the active boss within the current game."""
        self._current_boss_id = boss_id
        self._current_boss_name = boss_name
        if boss_id is not None:
            self._database.set_setting("last_boss_id", boss_id)
        logger.info("Current boss set to '%s' (id=%s)", boss_name, boss_id)

    # ----------------------------------------------------------------
    # Counter actions
    # ----------------------------------------------------------------
    def increment(self) -> CounterSnapshot:
        """Register a death (+1) for the current game/boss/session."""
        return self._apply_delta(+1)

    def decrement(self) -> CounterSnapshot:
        """
        Manually remove one death (-1) for the current game/boss/session.

        Ignored when it would take the session, total or boss count below zero.
        """
        snapshot = self.get_snapshot()
        boss_empty = self._current_boss_id is not None and snapshot.boss_deaths <= 0
        if snapshot.session_deaths <= 0 or snapshot.total_deaths <= 0 or boss_empty:
            logger.info("Ignored -1: a counter is already at zero")
            return snapshot
        return self._apply_delta(-1)

    def undo(self) -> CounterSnapshot:
        """
        Remove the most recently recorded death event, if any.

        Undoing a +1 after the total was reset could make the total negative,
        so that is ignored.
        """
        session_id = self._session_manager.current_session_id
        if session_id is not None and self._current_game_id is not None:
            last = self._database.get_last_event(session_id)
            total = self._database.get_total_deaths(self._current_game_id)
            if last is not None and last["delta"] > total:
                logger.info("Ignored undo: the total is already at zero")
                return self.get_snapshot()
            removed = self._database.remove_last_event(session_id)
            if not removed:
                logger.debug("Undo requested but no events exist for session_id=%s", session_id)
        return self.get_snapshot()

    def reset_session(self) -> CounterSnapshot:
        """Start the session count over at zero; the total keeps its deaths."""
        self._session_manager.reset_session()
        return self.get_snapshot()

    def reset_total(self) -> CounterSnapshot:
        """Set the current game's total to zero; session and boss counts stay."""
        if self._current_game_id is not None:
            self._database.reset_total(self._current_game_id)
        return self.get_snapshot()

    def set_session_count(self, target: int) -> CounterSnapshot:
        """
        Force the current session's death count to an exact value.

        Args:
            target: The desired session death count (negative values are
                clamped to 0).
        """
        if self._current_game_id is not None:
            session_id = self._session_manager.ensure_session(self._current_game_id)
            self._database.set_session_death_count(
                self._current_game_id, self._current_boss_id, session_id, target
            )
        return self.get_snapshot()

    def set_total_count(self, target: int) -> CounterSnapshot:
        """
        Force the current game's total death count to an exact value.

        Args:
            target: The desired total death count (negative values are
                clamped to 0).
        """
        if self._current_game_id is not None:
            self._database.set_total_death_count(self._current_game_id, target)
        return self.get_snapshot()

    def _apply_delta(self, delta: int) -> CounterSnapshot:
        """Persist a +1/-1 death event for the current selection."""
        if self._current_game_id is None:
            logger.warning("Cannot record death: no game selected")
            return self.get_snapshot()
        session_id = self._session_manager.ensure_session(self._current_game_id)
        self._database.add_death_event(
            game_id=self._current_game_id,
            boss_id=self._current_boss_id,
            session_id=session_id,
            delta=delta,
        )
        return self.get_snapshot()

    # ----------------------------------------------------------------
    # Snapshot for UI/overlay refresh
    # ----------------------------------------------------------------
    def get_snapshot(self) -> CounterSnapshot:
        """Build a fresh :class:`CounterSnapshot` reflecting current totals."""
        total = (
            self._database.get_total_deaths(self._current_game_id)
            if self._current_game_id is not None
            else 0
        )
        boss_deaths = (
            self._database.get_boss_deaths(self._current_boss_id)
            if self._current_boss_id is not None
            else 0
        )
        return CounterSnapshot(
            game_name=self._current_game_name,
            boss_name=self._current_boss_name,
            session_deaths=self._session_manager.get_session_deaths(),
            total_deaths=total,
            boss_deaths=boss_deaths,
        )

    @property
    def current_game_id(self) -> int | None:
        """The currently selected game's id, if any."""
        return self._current_game_id

    @property
    def current_boss_id(self) -> int | None:
        """The currently selected boss's id, if any."""
        return self._current_boss_id
