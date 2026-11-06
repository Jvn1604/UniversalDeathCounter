"""
Ready-made auto-detect setups ("presets"), shared between players.

A preset is one game's detection setup as a small JSON file: the detection
mode, the shareable options (health bar, log text, window title) and the
captured screens (death, boss victory, pause/loading). Screens are stored as
fractions of the window plus a small grey patch, so a preset works at any
resolution. Nothing tied to one PC goes in: no install path, log file path,
OBS source or display number.

The library is a folder of presets in this repository (``presets/``), listed
by ``presets/index.json``. It's only fetched when the player asks for it, or
adds a game (to suggest a preset for it).
"""

from __future__ import annotations

import base64
import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from src.database.database import SCREEN_DEATH, SCREEN_PAUSE, SCREEN_VICTORY, Database
from src.utils.constants import APP_VERSION, GITHUB_REPO
from src.utils.logger import get_logger

logger = get_logger(__name__)

PRESET_FORMAT = 1
PRESET_SUFFIX = ".dudc.json"
LIBRARY_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/presets/"
_TIMEOUT = 10
_MAX_PRESET_BYTES = 2 * 1024 * 1024
_MAX_INDEX_BYTES = 512 * 1024
_MAX_SCREENS = 40
_MODES = ("template", "souls", "health", "log")
_KINDS = (SCREEN_DEATH, SCREEN_VICTORY, SCREEN_PAUSE)
# Options that mean the same on every PC.
_SHARED_OPTIONS = ("health_region", "health_color", "health_full", "log_pattern",
                   "window_title")


class PresetError(ValueError):
    """Not a usable preset (wrong format, damaged, too big)."""


# ---------------------------------------------------------------- files
def export_preset(database: Database, game_id: int, author: str = "") -> dict[str, Any]:
    """The game's detection setup as a preset."""
    game = database.get_game(game_id)
    detection = database.get_game_detection(game_id)
    if game is None or detection is None or detection["mode"] in (None, "off"):
        raise PresetError("This game has no auto-detect setup to share yet.")
    options = database.get_detection_options(game_id)
    screens = [
        {"kind": kind, "region": json.loads(row["region"]),
         "patch": base64.b64encode(bytes(row["template"])).decode("ascii")}
        for kind in _KINDS
        for row in database.get_death_templates(game_id, kind)
    ]
    exe = PureWindowsPath(detection["exe_path"] or "").name
    return {
        "format": PRESET_FORMAT,
        "game": game["name"],
        "exe_names": [exe] if exe else [],
        "mode": detection["mode"],
        "options": {key: options[key] for key in _SHARED_OPTIONS if key in options},
        "screens": screens,
        "bosses": [boss["name"] for boss in database.get_bosses(game_id)],
        "author": author.strip()[:60],
        "app_version": APP_VERSION,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def preset_file_name(preset: dict[str, Any]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(preset.get("game", "game")).lower()).strip("-")
    return f"{slug or 'game'}{PRESET_SUFFIX}"


def write_preset(path: str | Path, preset: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(preset, indent=1), encoding="utf-8")


def read_preset(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if path.stat().st_size > _MAX_PRESET_BYTES:
        raise PresetError("That file is too big to be a setup.")
    return parse_preset(path.read_bytes())


def parse_preset(data: bytes) -> dict[str, Any]:
    """Check a preset thoroughly: it may come from anyone."""
    if len(data) > _MAX_PRESET_BYTES:
        raise PresetError("That file is too big to be a setup.")
    try:
        preset = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PresetError("That isn't a DUDC setup file.") from exc
    if not isinstance(preset, dict) or preset.get("format") != PRESET_FORMAT:
        raise PresetError("That isn't a DUDC setup file (or it's for a newer app).")
    if preset.get("mode") not in _MODES or not isinstance(preset.get("game"), str):
        raise PresetError("The setup file is damaged.")
    screens = preset.get("screens", [])
    if not isinstance(screens, list) or len(screens) > _MAX_SCREENS:
        raise PresetError("The setup file is damaged.")
    for screen in screens:
        try:
            region = [float(v) for v in screen["region"]]
            patch = base64.b64decode(screen["patch"], validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise PresetError("The setup file is damaged.") from exc
        height, width = (int.from_bytes(patch[i:i + 2], "little") for i in (0, 2))
        if (screen.get("kind") not in _KINDS or len(region) != 4
                or not all(0.0 <= v <= 1.0 for v in region)
                or len(patch) != 4 + height * width):
            raise PresetError("The setup file is damaged.")
    options = preset.get("options", {})
    if not isinstance(options, dict):
        raise PresetError("The setup file is damaged.")
    preset["options"] = {key: options[key] for key in _SHARED_OPTIONS if key in options}
    preset["bosses"] = [str(b)[:120] for b in preset.get("bosses", []) if str(b).strip()][:200]
    preset["exe_names"] = [str(e)[:80] for e in preset.get("exe_names", [])][:10]
    return preset


def apply_preset(database: Database, game_id: int, preset: dict[str, Any]) -> int:
    """
    Use ``preset`` for a game: its mode, options and screens (replacing the
    game's own screens of the kinds it brings), and any bosses it lists that
    the game doesn't have yet. Returns how many screens it added.
    """
    detection = database.get_game_detection(game_id)
    exe_path = detection["exe_path"] if detection is not None else None
    database.set_game_detection(game_id, exe_path, preset["mode"])
    if preset["options"]:
        database.update_detection_options(game_id, **preset["options"])
    screens = preset.get("screens", [])
    for kind in {screen["kind"] for screen in screens}:
        database.clear_death_templates(game_id, kind)
    for screen in screens:
        database.add_death_template(
            game_id, json.dumps(screen["region"]), base64.b64decode(screen["patch"]),
            screen["kind"],
        )
    have = {boss["name"].casefold() for boss in database.get_bosses(game_id)}
    for name in preset.get("bosses", []):
        if name.casefold() not in have:
            database.create_boss(game_id, name)
            have.add(name.casefold())
    return len(screens)


# ---------------------------------------------------------------- the library
@dataclass(frozen=True)
class LibraryEntry:
    game: str
    file: str
    exe_names: tuple[str, ...]
    mode: str
    screens: int
    author: str

    def matches_exe(self, exe_name: str) -> bool:
        name = exe_name.casefold()
        return any(name == exe.casefold() for exe in self.exe_names)


def _download(url: str, limit: int) -> bytes:
    if not url.startswith(LIBRARY_URL):
        raise PresetError("Not from the DUDC library.")
    request = urllib.request.Request(url, headers={"User-Agent": f"DUDC/{APP_VERSION}"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
        data = response.read(limit + 1)
    if len(data) > limit:
        raise PresetError("The library sent too much.")
    return data


def fetch_library() -> list[LibraryEntry]:
    """The presets in the online library (raises OSError when it can't be reached)."""
    try:
        index = json.loads(_download(LIBRARY_URL + "index.json", _MAX_INDEX_BYTES))
        return [
            LibraryEntry(
                game=str(item["game"]), file=str(item["file"]),
                exe_names=tuple(str(e) for e in item.get("exe_names", [])),
                mode=str(item.get("mode", "")), screens=int(item.get("screens", 0)),
                author=str(item.get("author", "")),
            )
            for item in index.get("presets", [])
            if re.fullmatch(r"[a-z0-9-]+\.dudc\.json", str(item.get("file", "")))
        ]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise OSError(f"The library's list is damaged: {exc}") from exc


def fetch_preset(entry: LibraryEntry) -> dict[str, Any]:
    return parse_preset(_download(LIBRARY_URL + entry.file, _MAX_PRESET_BYTES))


def library_index(presets: list[dict[str, Any]]) -> dict[str, Any]:
    """The library's index.json for these presets (kept by ``packaging/make_presets.py``)."""
    return {
        "format": PRESET_FORMAT,
        "presets": [
            {"game": p["game"], "file": preset_file_name(p), "exe_names": p["exe_names"],
             "mode": p["mode"], "screens": len(p.get("screens", [])),
             "author": p.get("author", "")}
            for p in sorted(presets, key=lambda p: p["game"].casefold())
        ],
    }
