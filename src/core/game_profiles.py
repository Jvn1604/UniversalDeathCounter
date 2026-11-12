"""
One game per profile.

Every game lives in a profile of its own, named after it (the profile list
top right is then the game list). A profile that holds more than one game,
and the Default profile holding any, hands each extra game to its own
profile: games added later, games from a loaded save, and (once, after the
update) games already there.

Moving a game is careful: the profile is backed up first (Saved Progress),
the game is copied with everything it has (bosses, sessions, deaths, death
screens, speedrun splits and runs, its own settings), and it's only removed
from the old profile once the new one has every death.

Settings (keys, theme, overlay look...) are the player's, not a game's: a new
profile gets a copy, and switching profiles carries them along
(:func:`shared_settings`), so changing a key in one game's profile changes
it for all of them.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.database.database import Database
from src.utils import save_files
from src.utils.constants import (
    SETTING_LAST_BOSS_ID,
    SETTING_LAST_GAME_ID,
    SETTING_TIMER_AUTOSAVE,
)
from src.utils.logger import get_logger
from src.utils.profiles import DEFAULT_PROFILE_NAME, ProfileManager

logger = get_logger(__name__)

# Settings that belong to one game (their key ends with its id).
_PER_GAME_PREFIXES = ("save_deaths_", "artwork_path_", "artwork_missing_")
# Settings about what this profile was doing: never carried to another one.
_PROFILE_STATE = {SETTING_LAST_GAME_ID, SETTING_LAST_BOSS_ID, SETTING_TIMER_AUTOSAVE}

_GAME_TABLES = ("bosses", "sessions", "death_events", "game_detection", "screens",
                "speedrun_splits", "speedrun_runs")


def shared_settings(database: Database) -> dict[str, str]:
    """The player's settings in this profile, without any game's or profile's own."""
    return {
        key: value for key, value in database.get_all_settings().items()
        if key not in _PROFILE_STATE and not key.startswith(_PER_GAME_PREFIXES)
    }


def apply_settings(database: Database, settings: dict[str, str]) -> None:
    for key, value in settings.items():
        database.set_setting(key, value)


def game_export(database: Database, game_id: int) -> dict[str, Any]:
    """:meth:`Database.export_data` with only this game."""
    data = database.export_data()
    data["games"] = [g for g in data["games"] if g["id"] == game_id]
    for table in _GAME_TABLES:
        data[table] = [row for row in data.get(table, []) if row["game_id"] == game_id]
    return data


def gather_saves(saves_dir: Path) -> int:
    """
    Saves made in a profile before all profiles shared one Saved Progress
    folder (they were in profiles/Saved Progress): moved to the shared one,
    never over a file of the same name. Returns how many moved.
    """
    old = saves_dir / "profiles" / "Saved Progress"
    if not old.is_dir():
        return 0
    new = saves_dir / "Saved Progress"
    new.mkdir(parents=True, exist_ok=True)
    moved = 0
    for file in sorted(old.iterdir()):
        if not file.is_file() or file.suffix == ".tmp":
            continue
        target, number = new / file.name, 2
        while target.exists():
            target = new / f"{file.stem} ({number}){file.suffix}"
            number += 1
        try:
            file.replace(target)
            moved += 1
        except OSError:
            logger.exception("Couldn't move the save %s", file)
    try:
        old.rmdir()  # only if it's empty now
    except OSError:
        pass
    if moved:
        logger.info("Moved %d save(s) to the shared Saved Progress folder", moved)
    return moved


def _run_snapshot_of(database: Database, game_id: int) -> dict[str, Any] | None:
    """The crash snapshot of a run in progress, if it's this game's."""
    try:
        data = json.loads(database.get_setting(SETTING_TIMER_AUTOSAVE, "") or "null")
    except ValueError:
        return None
    if isinstance(data, dict) and data.get("game_id") == game_id:
        return data
    return None


def _profile_for(profiles: ProfileManager, name: str) -> tuple[str, bool]:
    """
    The profile a game called ``name`` goes to: one named after it that's
    empty or holds only that game, else ``name (2)``, ``name (3)``...
    Returns ``(profile name, created)``.
    """
    candidate, number = name, 1
    while True:
        if candidate == DEFAULT_PROFILE_NAME:
            pass  # never the Default profile
        elif candidate not in profiles.list_profiles():
            profiles.create_profile(candidate)
            return candidate, True
        else:
            database = Database(profiles.db_path(candidate))
            try:
                names = {g["name"] for g in database.get_games()}
            finally:
                database.close()
            if names <= {name}:
                return candidate, False
        number += 1
        candidate = f"{name} ({number})"


def move_game(
    profiles: ProfileManager, source: Database, game_id: int, settings: dict[str, str]
) -> str | None:
    """
    Move one game out of ``source`` into its own profile; returns that
    profile's name (None if it couldn't be moved: then nothing changed).
    """
    game = source.get_game(game_id)
    if game is None:
        return None
    name = str(game["name"])
    profile, created = _profile_for(profiles, name)
    target = Database(profiles.db_path(profile))
    try:
        if created:
            apply_settings(target, settings)
        ids = target.import_data(game_export(source, game_id), mode="merge")
        new_id = ids["games"][game_id]
        # The game's own settings (its save-file count, its artwork), under its new id.
        for key, value in source.get_all_settings().items():
            for prefix in _PER_GAME_PREFIXES:
                if key == f"{prefix}{game_id}" and not target.get_setting(f"{prefix}{new_id}", ""):
                    target.set_setting(f"{prefix}{new_id}", value)
        target.set_setting(SETTING_LAST_GAME_ID, str(new_id))
        # The boss picked last, if it's this game's (bosses get new ids too).
        try:
            last_boss = int(source.get_setting(SETTING_LAST_BOSS_ID, "") or 0)
        except ValueError:
            last_boss = 0
        new_boss = ids["bosses"].get(last_boss)
        if new_boss is not None:
            target.set_setting(SETTING_LAST_BOSS_ID, str(new_boss))
        elif created:
            target.set_setting(SETTING_LAST_BOSS_ID, "")
        run = _run_snapshot_of(source, game_id)
        if run is not None:  # a run in progress (crash recovery) goes with its game
            target.set_setting(SETTING_TIMER_AUTOSAVE, json.dumps({**run, "game_id": new_id}))
        if target.get_total_deaths(new_id) < source.get_total_deaths(game_id):
            logger.error("Moving %r to its profile lost deaths; left where it was", name)
            return None
    except Exception:  # noqa: BLE001 - the game stays where it is, nothing lost
        logger.exception("Couldn't move %r to its own profile", name)
        return None
    finally:
        target.close()
    if _run_snapshot_of(source, game_id) is not None:
        source.set_setting(SETTING_TIMER_AUTOSAVE, "")
    source.delete_game(game_id)
    logger.info("Moved %r to its own profile %r", name, profile)
    return profile


def _keeper(profile: str, games: list) -> int | None:
    """The game a profile keeps: the one named like it, else its first; none for Default."""
    if profile == DEFAULT_PROFILE_NAME or not games:
        return None
    for game in games:
        if game["name"] == profile:
            return int(game["id"])
    return int(games[0]["id"])


def split_profile(
    profiles: ProfileManager, profile: str, database: Database
) -> dict[int, str]:
    """
    Give every extra game of ``profile`` (open as ``database``) its own
    profile. Returns ``{old game id: profile it went to}``.
    """
    games = list(database.get_games())
    keep = _keeper(profile, games)
    leaving = [int(g["id"]) for g in games if int(g["id"]) != keep]
    if not leaving:
        return {}
    backup = save_files.saves_folder(database.path) / (
        f"Before one profile per game {datetime.now():%Y-%m-%d %H%M%S}.json"
    )
    try:
        save_files.write_save(backup, database.export_data())
    except OSError:
        logger.exception("Couldn't back up %r first; its games stay together", profile)
        return {}
    settings = shared_settings(database)
    moved = {}
    for game_id in leaving:
        target = move_game(profiles, database, game_id, settings)
        if target is not None:
            moved[game_id] = target
    return moved


def split_all(profiles: ProfileManager, skip: str | None = None) -> dict[tuple[str, int], str]:
    """
    Every profile (except ``skip``, open elsewhere): one game each.
    Returns ``{(old profile, old game id): new profile}``.
    """
    moved: dict[tuple[str, int], str] = {}
    for profile in list(profiles.list_profiles()):
        if profile == skip:
            continue
        database = Database(profiles.db_path(profile))
        try:
            for game_id, target in split_profile(profiles, profile, database).items():
                moved[(profile, game_id)] = target
        finally:
            database.close()
    return moved
