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


def get_template(name: str) -> GameTemplate | None:
    """Look up a template by its game name, or ``None`` if not found."""
    for template in GAME_TEMPLATES:
        if template.name == name:
            return template
    return None
