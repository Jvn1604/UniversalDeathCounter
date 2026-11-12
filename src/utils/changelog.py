"""
The changelog (CHANGELOG.md, shipped with the app) for the What's New window.

The file has one ``## [version] - date`` section per release, newest first,
and ``## [Unreleased]`` on top for what's coming. Reading it is a few
milliseconds of plain text, done only when the window opens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.utils.constants import CHANGELOG_PATH

_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?:\s*-\s*(?P<date>\S+))?\s*$")
_LINK_LINE = re.compile(r"^\[[^\]]+\]:\s*\S+\s*$")  # the compare links at the bottom
UNRELEASED = "Unreleased"


@dataclass(frozen=True)
class Release:
    version: str  # "2.19.0", or "Unreleased"
    date: str  # "2026-11-07", "" when unreleased
    notes: str  # the section's Markdown (### New, bullets...)

    @property
    def title(self) -> str:
        if self.version == UNRELEASED:
            return "Coming next"
        return f"v{self.version}" + (f"  ·  {self.date}" if self.date else "")


def parse(text: str) -> list[Release]:
    """The releases in a changelog's text, newest first (empty sections left out)."""
    releases: list[Release] = []
    current: tuple[str, str] | None = None
    lines: list[str] = []

    def finish() -> None:
        notes = "\n".join(lines).strip()
        if current is not None and notes:
            releases.append(Release(current[0], current[1], notes))

    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            finish()
            current, lines = (heading["version"], heading["date"] or ""), []
        elif current is not None and not _LINK_LINE.match(line):
            lines.append(line)
    finish()
    return releases


def load(path: Path = CHANGELOG_PATH) -> list[Release]:
    """The shipped changelog's releases ([] if the file is missing or unreadable)."""
    try:
        return parse(path.read_text(encoding="utf-8"))
    except OSError:
        return []


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3])


def newer_than(releases: list[Release], seen: str, current: str) -> list[Release]:
    """Released versions after ``seen`` up to ``current`` (what an update brought)."""
    low, high = _key(seen), _key(current)
    return [r for r in releases
            if r.version != UNRELEASED and low < _key(r.version) <= high]
