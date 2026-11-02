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
# After a counted death, give the game this long to write it to the save.
_SETTLE_SECONDS = 6.0


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
        self._deaths, self._last_death = deaths, 0.0
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
        if not self._pending or time.monotonic() - self._last_death < _SETTLE_SECONDS:
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
        location = self._learner.observe(contents, deaths)
        if location is None:
            left = max(0, DEATHS_TO_LEARN - self._learner.deaths_seen)
            self._set_status(
                "Learning: keep playing. Die "
                + (f"{left} more time{'s' if left != 1 else ''}" if left else "once or twice more")
                + " (count each death here as usual) and the game's own count appears."
            )
            return
        value = self._learner.finish(contents)
        self._location = location
        self._config["location"] = None  # stored by _store, with the count
        if value is not None:
            self._store(value)

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
