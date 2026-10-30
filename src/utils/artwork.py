"""
Game artwork: a faded banner behind the counter cards (optional, off by default).

The picture is the player's own (right-click the game → Choose Artwork…), or
found on Steam: the game's Steam app is read from its install folder
(``steamapps/common/<folder>`` and the ``appmanifest_*.acf`` next to it), and
only if that fails is the game's *name* looked up in the Steam store. Each
picture is downloaded once, in a background thread, and kept in
``saves/artwork``; a failed lookup isn't repeated.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from src.utils.constants import SAVES_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)

ARTWORK_DIR: Path = SAVES_DIR / "artwork"
_SEARCH_URL = "https://store.steampowered.com/api/storesearch/?l=english&cc=US&term={}"
# The wide "hero" banner first, the small store header if a game has none.
_IMAGE_URLS = (
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{}/library_hero.jpg",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{}/header.jpg",
)
_TIMEOUT_SECONDS = 8
_MAX_IMAGE_BYTES = 6 * 1024 * 1024
_INSTALLDIR = re.compile(r'"installdir"\s+"([^"]+)"', re.IGNORECASE)


def cached_path(game_id: int, folder: Path | None = None) -> Path:
    return (folder or ARTWORK_DIR) / f"{game_id}.jpg"


def steam_app_id_from_exe(exe_path: str | None) -> int | None:
    """The Steam app of a game installed by Steam, from the files next to it."""
    if not exe_path:
        return None
    parts = Path(exe_path).parts
    lowered = [part.lower() for part in parts]
    for index in range(len(lowered) - 2):
        if lowered[index] == "steamapps" and lowered[index + 1] == "common":
            steamapps = Path(*parts[: index + 1])
            install_dir = parts[index + 2].lower()
            try:
                manifests = list(steamapps.glob("appmanifest_*.acf"))
            except OSError:
                return None
            for manifest in manifests:
                try:
                    text = manifest.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                match = _INSTALLDIR.search(text)
                if match and match.group(1).lower() == install_dir:
                    digits = manifest.stem.removeprefix("appmanifest_")
                    return int(digits) if digits.isdigit() else None
    return None


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DUDC"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return response.read(_MAX_IMAGE_BYTES + 1)


def steam_app_id_by_name(name: str) -> int | None:
    """The first Steam store result for ``name`` (only the game's name is sent)."""
    payload = json.loads(_get(_SEARCH_URL.format(urllib.parse.quote(name))).decode("utf-8"))
    items = payload.get("items") or []
    return int(items[0]["id"]) if items else None


def download_artwork(game_id: int, name: str, exe_path: str | None, folder: Path) -> Path | None:
    """Find and save the game's Steam banner; None if there's none."""
    app_id = steam_app_id_from_exe(exe_path) or steam_app_id_by_name(name)
    if app_id is None:
        return None
    for url in _IMAGE_URLS:
        try:
            data = _get(url.format(app_id))
        except OSError:
            continue
        if len(data) > _MAX_IMAGE_BYTES or QImage.fromData(data).isNull():
            continue  # not a picture (or too big)
        folder.mkdir(parents=True, exist_ok=True)
        target = cached_path(game_id, folder)
        target.write_bytes(data)
        return target
    return None


class ArtworkFetcher(QObject):
    """
    Downloads a game's banner in a daemon thread.

    Signals:
        finished: ``(game_id, path)``; the path is "" when nothing was found.
    """

    finished = Signal(int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._busy: set[int] = set()

    def fetch(self, game_id: int, name: str, exe_path: str | None, folder: Path) -> None:
        if game_id in self._busy:
            return
        self._busy.add(game_id)
        threading.Thread(
            target=self._run, args=(game_id, name, exe_path, folder), daemon=True
        ).start()

    def _run(self, game_id: int, name: str, exe_path: str | None, folder: Path) -> None:
        try:
            path = download_artwork(game_id, name, exe_path, folder)
        except Exception:  # noqa: BLE001 - offline or Steam changed: no artwork, no crash
            logger.debug("Artwork lookup failed for %s", name, exc_info=True)
            path = None
        self._busy.discard(game_id)
        self.finished.emit(game_id, str(path) if path is not None else "")
