"""
Built-in quick-add templates for popular Soulslike / boss-rush games.

This gives players "instant setup" freedom: pick a template and its game
+ full boss list are created in one click, instead of typing each boss
name by hand. Players remain completely free to add/rename/delete
anything afterward — templates are just a convenient starting point, and
the app works with ANY game, template or not.

Adding a new template requires no code changes elsewhere: just append a
new entry to :data:`GAME_TEMPLATES`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.database.database import Database


@dataclass(slots=True, frozen=True)
class GameTemplate:
    """A predefined game name plus its common boss list."""

    name: str
    bosses: tuple[str, ...]


GAME_TEMPLATES: tuple[GameTemplate, ...] = (
    GameTemplate(
        "Elden Ring",
        (
            "Margit, the Fell Omen",
            "Godrick the Grafted",
            "Rennala, Queen of the Full Moon",
            "Starscourge Radahn",
            "Morgott, the Omen King",
            "Malenia, Blade of Miquella",
            "Maliketh, the Black Blade",
            "Fire Giant",
            "Placidusax, Lord of the Frenzied Flame",
            "Radagon / Elden Beast",
        ),
    ),
    GameTemplate(
        "Dark Souls III",
        (
            "Iudex Gundyr",
            "Vordt of the Boreal Valley",
            "Abyss Watchers",
            "Pontiff Sulyvahn",
            "Aldrich, Devourer of Gods",
            "Dancer of the Boreal Valley",
            "Champion Gundyr",
            "Lorian & Lothric",
            "Soul of Cinder",
        ),
    ),
    GameTemplate(
        "Sekiro: Shadows Die Twice",
        (
            "Gyoubu Oniwa",
            "Lady Butterfly",
            "Genichiro Ashina",
            "Guardian Ape",
            "Corrupted Monk",
            "Great Shinobi Owl",
            "Emma, the Gentle Blade / Isshin",
            "Sword Saint Isshin",
        ),
    ),
    GameTemplate(
        "Bloodborne",
        (
            "Cleric Beast",
            "Father Gascoigne",
            "Vicar Amelia",
            "Shadow of Yharnam",
            "Rom, the Vacuous Spider",
            "Ludwig, the Holy Blade",
            "Lady Maria of the Astral Clocktower",
            "Gehrman, the First Hunter",
            "Moon Presence",
        ),
    ),
    GameTemplate(
        "Hollow Knight",
        (
            "False Knight",
            "Hornet",
            "Broken Vessel",
            "Soul Master",
            "Watcher Knights",
            "Dung Defender",
            "Traitor Lord",
            "The Radiance",
        ),
    ),
    GameTemplate(
        "Cuphead",
        (
            "The Root Pack",
            "Cagney Carnation",
            "Ribby & Croaks",
            "Baroness Von Bon Bon",
            "Beppi the Clown",
            "Wally Warbles",
            "Grim Matchstick",
            "Djimmi the Great",
            "Sally Stageplay",
            "King Dice",
            "The Devil",
        ),
    ),
)


def get_template_names() -> list[str]:
    """Return the display names of all available templates."""
    return [template.name for template in GAME_TEMPLATES]


def add_template_bosses(database: Database, template: GameTemplate) -> tuple[int, int]:
    """
    Create the template's game (or reuse one with that name) and its bosses.

    Bosses already in the game are skipped. Returns ``(game id, bosses added)``.
    """
    existing = {game["name"]: game["id"] for game in database.get_games()}
    game_id = existing.get(template.name)
    if game_id is None:
        game_id = database.create_game(template.name)
    have = {boss["name"] for boss in database.get_bosses(game_id)}
    added = 0
    for boss_name in template.bosses:  # in story order, which next-boss relies on
        if boss_name not in have:
            database.create_boss(game_id, boss_name)
            added += 1
    return game_id, added


def get_template(name: str) -> GameTemplate | None:
    """Look up a template by its game name, or ``None`` if not found."""
    for template in GAME_TEMPLATES:
        if template.name == name:
            return template
    return None
