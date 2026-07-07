"""Data model representing a Game tracked by the death counter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Game:
    """
    Represents a single game entry.

    Attributes:
        id: Primary key in the database. ``None`` if not yet persisted.
        name: Unique, human-readable game name (e.g. "Elden Ring").
        created_at: ISO-8601 timestamp string of creation time.
    """

    id: int | None
    name: str
    created_at: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name
