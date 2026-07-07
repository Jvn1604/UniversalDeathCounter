"""Data model representing a Boss (or challenge/segment) within a Game."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Boss:
    """
    Represents a single boss/challenge entry belonging to a game.

    Attributes:
        id: Primary key in the database. ``None`` if not yet persisted.
        game_id: Foreign key referencing the owning Game.
        name: Human-readable boss name (e.g. "Malenia, Blade of Miquella").
        created_at: ISO-8601 timestamp string of creation time.
    """

    id: int | None
    game_id: int
    name: str
    created_at: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name
