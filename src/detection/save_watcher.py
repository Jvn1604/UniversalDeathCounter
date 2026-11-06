"""
Keeps the game's own death count (from its save file) up to date.

Checks the save's timestamp every couple of seconds (cheap). When the game
has written it, the save is read on a worker thread and either taught to the
:class:`~src.detection.save_deaths.SaveLearner` (until the count is found)
or read at the learned spot. Results reach the UI through Qt signals.
"""

from __future__ import annotations

import json
import os
import threading
import time
import zlib

from PySide6.QtCore import QObject, QTimer, Signal

from src.detection.save_deaths import (
    DEATHS_TO_LEARN,
    SaveLearner,
    SaveLocation,
    SaveReadError,
    read_save,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_POLL_MS = 2000
# While learning, the save is compared only at checkpoints: this long after
# the app counted a death, when the save holds it whichever came first (games
# save the moment you die, a little before the death screen is spotted or F9
# pressed). Comparing at every write threw out the very field that counts
# deaths, because it went up while the app hadn't counted yet.
_SETTLE_SECONDS = 10.0
# Counted deaths without finding the count: the save probably doesn't keep one.
_GIVE_UP_DEATHS = 6


def load_config(text: str) -> dict:
    """A game's save-count settings: path, location, cycle_only, cycle_base, last."""
    try:
        config = json.loads(text) if text else {}
    except ValueError:
        config = {}
    return config if isinstance(config, dict) else {}


def shown_count(config: dict) -> int | None:
    """The count to show: the save's total, or this cycle's if chosen."""
    last = config.get("last")
    if last is None:
        return None
    base = config.get("cycle_base")
    if config.get("cycle_only") and base is not None:
        return max(0, last - base)
    return last


class SaveWatcher(QObject):
    """
    Watches one game's save file.

    Signals:
        config_changed: (game id, config) to store: the learned spot, the latest count.
        status_changed: What it's doing, for the Detection page.
    """

    config_changed = Signal(int, dict)
    status_changed = Signal(str)
    _loaded = Signal(int, object, str, int)  # token, contents, error text, deaths at read

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._game_id: int | None = None
        self._config: dict = {}
        self._location: SaveLocation | None = None
        self._learner = SaveLearner()
        self._deaths = 0
        self._last_death = 0.0
        self._checkpoint: int | None = None  # the app's count when the learner last looked
        self._learning_since: int | None = None  # the app's count when learning began
        self._scrambled = False  # the save looks compressed or encrypted
        self._stamp: tuple[int, int] | None = None
        self._pending = False
        self._reading = False
        self._token = 0
        self.status = ""
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._loaded.connect(self._on_loaded)

    # ---------------------------------------------------------------- setup
    def set_game(self, game_id: int | None, config: dict, deaths: int) -> None:
        """Watch ``game_id``'s save as ``config`` says (no path: stop)."""
        self._token += 1  # results of an earlier read are for another game/file
        self._game_id, self._config = game_id, dict(config)
        self._location = SaveLocation.from_json(config.get("location") or "")
        self._learner.reset()
        self._deaths, self._last_death, self._checkpoint = deaths, 0.0, None
        self._learning_since, self._scrambled = None, False
        self._stamp, self._pending, self._reading = None, True, False
        if game_id is None or not config.get("path"):
            self._timer.stop()
            self._set_status("")
            return
        self._set_status("Reading the save…")
        self._timer.start()
        self._poll()

    def stop(self) -> None:
        self._timer.stop()
        self._token += 1

    def note_deaths(self, deaths: int) -> None:
        """The app's count for the game (deaths counted, minus ones taken off)."""
        if deaths > self._deaths:
            self._last_death = time.monotonic()
        self._deaths = deaths

    @property
    def learning(self) -> bool:
        return self._location is None and bool(self._config.get("path"))

    # ---------------------------------------------------------------- polling
    def _poll(self) -> None:
        path = self._config.get("path")
        if not path or self._reading:
            return
        try:
            info = os.stat(path)
        except OSError:
            self._set_status(f"Save file not found: {path}")
            return
        stamp = (info.st_mtime_ns, info.st_size)
        if stamp != self._stamp:
            self._stamp, self._pending = stamp, True
        # Learning: a death the app counted is a checkpoint, even if the game
        # wrote the save before it was counted (no write after it to notice).
        checkpoint_due = self.learning and self._deaths != self._checkpoint
        if not (self._pending or checkpoint_due) or (
            time.monotonic() - self._last_death < _SETTLE_SECONDS
        ):
            return
        self._pending, self._reading = False, True
        token, deaths = self._token, self._deaths

        def work() -> None:
            contents, error = None, ""
            try:
                contents = read_save(path)
            except SaveReadError as exc:
                error = str(exc)
            except Exception as exc:  # noqa: BLE001 - never crash the app over a save
                logger.exception("Reading the save failed")
                error = f"Couldn't read the save: {exc}"
            self._loaded.emit(token, contents, error, deaths)

        threading.Thread(target=work, name="save-reader", daemon=True).start()

    def _on_loaded(self, token: int, contents: object, error: str, deaths: int) -> None:
        if token != self._token:
            return
        self._reading = False
        if error:
            self._set_status(error)
            return
        if self._location is not None:
            value = self._location.read(contents)
            if value is not None:
                self._store(value)
                return
            logger.info("Lost the death count in the save; learning it again")
            self._location = None
            self._config["location"] = None
            self._learner.reset()
            self._checkpoint = None
        if self._learning_since is None:
            self._learning_since = deaths
            self._scrambled = _looks_scrambled(contents)
        if self._checkpoint is not None and deaths == self._checkpoint:
            self._show_learning()  # an autosave between deaths: nothing to learn from
            return
        self._checkpoint = deaths
        location = self._learner.observe(contents, deaths)
        if location is None:
            self._show_learning()
            return
        value = self._learner.finish(contents)
        self._location = location
        self._config["location"] = None  # stored by _store, with the count
        if value is not None:
            self._store(value)

    def _show_learning(self) -> None:
        tried = self._deaths - (self._learning_since or 0)
        if tried >= _GIVE_UP_DEATHS:
            self._set_status(
                f"No death count found in this save after {tried} deaths. This game "
                "probably doesn't keep one in its save"
                + (", or the save is compressed or encrypted." if self._scrambled else ".")
                + " It keeps trying; Stop turns it off."
            )
            return
        if self._scrambled:
            self._set_status(
                "This save is compressed or encrypted in a way the app can't open "
                "(standard compression is unpacked; a game's own encryption or "
                "compression like Oodle isn't). It still tries as you die; auto-detect "
                "works for any game."
            )
            return
        left = max(0, DEATHS_TO_LEARN - self._learner.deaths_seen)
        self._set_status(
            "Learning the game's count: each time you die, let auto-detect count it or "
            "press +1 (F9). "
            + (f"{left} more death{'s' if left != 1 else ''} to go." if left
               else "Almost there: one or two more deaths.")
        )

    def _store(self, value: int) -> None:
        name = os.path.basename(self._config.get("path", ""))
        self._set_status(f"Reading the game's own count from {name}: {value:,} deaths.")
        location = self._location.to_json() if self._location is not None else None
        if value != self._config.get("last") or location != self._config.get("location"):
            self._config["last"] = value
            self._config["location"] = location  # its surroundings may have moved
            if self._game_id is not None:
                self.config_changed.emit(self._game_id, dict(self._config))

    def _set_status(self, text: str) -> None:
        if text != self.status:
            self.status = text
            self.status_changed.emit(text)


def _looks_scrambled(contents: object) -> bool:
    """
    No part of the save is readable: all still compressed or encrypted (data
    like that doesn't compress any further). Standard compression has been
    unpacked by then (see :func:`~src.detection.save_deaths.read_save`).
    """
    if isinstance(contents, str) or not contents:
        return False

    def scrambled(part: bytes) -> bool:
        sample = part[:262_144]
        return len(sample) > 4096 and len(zlib.compress(sample, 1)) > 0.95 * len(sample)

    return all(scrambled(part) for part in contents)
