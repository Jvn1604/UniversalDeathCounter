"""
Save files: a full backup plus what was going on when it was written.

A save is :meth:`Database.export_data` with one more key, ``"resume"``: the
game, the session in progress and the speedrun run in progress. Loading a
save brings those back, so the player carries on where they were. Older
backups (no ``"resume"``) still load; they just don't resume anything.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.speedrun import format_time

RESUME_KEY = "resume"


def saves_folder(database_path: Path) -> Path:
    """Where saves go by default: next to the profile's database."""
    return database_path.parent / "Saved Progress"


def autosave_path(database_path: Path) -> Path:
    """The profile's auto-save, rewritten every few minutes and on close."""
    return saves_folder(database_path) / f"{database_path.stem}-autosave.json"


def manual_save_name(now: datetime | None = None) -> str:
    return f"DUDC save {(now or datetime.now()):%Y-%m-%d %H%M}.json"


def write_save(path: Path, data: dict[str, Any]) -> None:
    """Write atomically: a crash mid-write leaves the previous save intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(temp, path)


def read_save(path: Path) -> dict[str, Any]:
    """
    Raises:
        OSError: The file can't be read.
        ValueError: It isn't a save or backup of this app.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "games" not in data:
        raise ValueError("This file isn't a DUDC save or backup.")
    return data


def describe(data: dict[str, Any]) -> str:
    """One or two lines on what loading this save resumes."""
    resume = data.get(RESUME_KEY) or {}
    if not resume.get("game_name"):
        games = len(data.get("games", []))
        return f"{games} game{'' if games == 1 else 's'}, nothing in progress."
    lines = [resume["game_name"]]
    if resume.get("session_deaths") is not None:
        deaths = resume["session_deaths"]
        lines[0] += f"  ·  session: {deaths} death{'' if deaths == 1 else 's'}"
    run = resume.get("run")
    if run:
        done = sum(1 for t in run.get("split_times", []) if t is not None)
        lines.append(
            f"Speedrun run at {format_time(int(run.get('real_ms', 0)))}, "
            f"split {min(done + 1, len(run['split_names']))}/{len(run['split_names'])}, "
            f"{run.get('deaths', 0)} deaths"
        )
    saved = resume.get("saved_at")
    if saved:
        try:
            lines.append(f"Saved {datetime.fromisoformat(saved):%a %d %b, %H:%M}")
        except ValueError:
            pass
    return "\n".join(lines)
