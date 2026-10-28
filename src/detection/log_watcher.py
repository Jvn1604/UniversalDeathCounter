"""
Log-file death detection.

Many games write a line to a log file when the player dies (Minecraft's
``logs/latest.log``, for example). :class:`LogWatcher` follows such a file
like ``tail -f`` and counts every new line matching the player's pattern.
It never captures the screen, so it costs almost nothing and is exact.

:class:`LogTail` and :func:`compile_death_pattern` are pure and unit tested;
the watcher thread reports through Qt signals, like :mod:`death_watcher`.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from src.utils.logger import get_logger

logger = get_logger(__name__)

_POLL_SECONDS: float = 0.5
_MAX_READ_BYTES: int = 1 << 20  # per poll, so a huge burst can't stall the thread
# Several matching lines this close together are one death (e.g. a death
# message followed by a respawn message that also matches).
_DUPLICATE_SECONDS: float = 1.0
# How much of the file's end the "Test" button scans.
_TEST_TAIL_BYTES: int = 256 * 1024


def compile_death_pattern(text: str) -> re.Pattern[str]:
    """
    Compile the player's death pattern (a case-insensitive regular expression).

    Plain words work as-is; ``|`` separates alternatives.

    Raises:
        ValueError: If the pattern is empty or not a valid expression.
    """
    if not text.strip():
        raise ValueError("Enter the text that appears in the log when you die.")
    try:
        return re.compile(text, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"That pattern isn't valid: {exc}") from exc


def _decode(line: bytes) -> str:
    return line.decode("utf-8", errors="replace").rstrip("\r")


class LogTail:
    """
    Returns the complete lines appended to a file since the previous poll.

    The first poll skips whatever the file already holds, so old deaths
    aren't recounted. When the game starts a new log (the file is replaced
    or truncated), the new file is read from its start.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._offset: int | None = None  # None until the first poll
        self._file_id: tuple[int, int] | None = None
        self._partial = b""

    def poll(self) -> list[str] | None:
        """
        New complete lines, or None if the file doesn't exist (yet).

        Raises:
            OSError: If the file exists but can't be read.
        """
        try:
            stat = os.stat(self.path)
        except FileNotFoundError:
            if self._offset is None:
                self._offset = 0  # created later: everything in it is new
            self._file_id = None
            return None
        file_id = (stat.st_dev, stat.st_ino)
        if self._offset is None:
            self._offset = stat.st_size
        elif file_id != self._file_id and self._file_id is not None:
            self._offset, self._partial = 0, b""  # a new log replaced the old one
        elif stat.st_size < self._offset:
            self._offset, self._partial = 0, b""  # truncated and rewritten
        self._file_id = file_id
        if stat.st_size == self._offset:
            return []
        with open(self.path, "rb") as handle:
            handle.seek(self._offset)
            chunk = handle.read(_MAX_READ_BYTES)
        self._offset += len(chunk)
        *lines, self._partial = (self._partial + chunk).split(b"\n")
        return [_decode(line) for line in lines]


def scan_log(path: Path, pattern: re.Pattern[str]) -> tuple[int, str]:
    """
    Check a pattern against the end of an existing log.

    Returns:
        ``(matching line count, last matching line)``.

    Raises:
        OSError: If the file can't be read.
    """
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        handle.seek(max(0, size - _TEST_TAIL_BYTES))
        lines = [_decode(line) for line in handle.read().split(b"\n")]
    matches = [line for line in lines if pattern.search(line)]
    return len(matches), matches[-1].strip() if matches else ""


@dataclass(slots=True, frozen=True)
class LogWatchConfig:
    """Which game the deaths belong to, which file to follow, and what a death looks like."""

    game_id: int
    log_path: str
    pattern: re.Pattern[str]


class LogWatcher(QObject):
    """
    Follows a game's log file and reports each death line.

    Signals:
        death_detected: Emitted with the game id for each death line.
        status_changed: Emitted with a short human-readable status line.
    """

    death_detected = Signal(int)
    status_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._config: LogWatchConfig | None = None
        self._config_version = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_status = ""

    def configure(self, config: LogWatchConfig | None) -> None:
        """Follow a new file (``None`` stops following). Starts the thread on first use."""
        with self._lock:
            self._config = config
            self._config_version += 1
        self._last_status = ""
        if config is not None and self._thread is None:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="LogWatcher", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and wait briefly for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _set_status(self, text: str) -> None:
        if text != self._last_status:
            self._last_status = text
            self.status_changed.emit(text)

    def _run(self) -> None:
        try:
            self._watch_loop()
        except Exception:  # noqa: BLE001 - detection must never crash the app
            logger.exception("Log watcher stopped unexpectedly")
            self._set_status("Log detection stopped (error, see log)")

    def _watch_loop(self) -> None:
        seen_version = -1
        tail: LogTail | None = None
        last_death = float("-inf")
        while not self._stop_event.is_set():
            with self._lock:
                config, version = self._config, self._config_version
            if version != seen_version:
                seen_version = version
                tail = LogTail(Path(config.log_path)) if config is not None else None
                last_death = float("-inf")
            if config is None or tail is None:
                self._stop_event.wait(_POLL_SECONDS * 2)
                continue

            name = tail.path.name
            try:
                lines = tail.poll()
            except OSError:
                self._set_status(f"Can't read {name}. Is it locked by the game?")
                self._stop_event.wait(_POLL_SECONDS * 4)
                continue
            if lines is None:
                self._set_status(f"Waiting for {name} to appear…")
            else:
                self._set_status(f"Watching {name} for deaths")
                for line in lines:
                    if not config.pattern.search(line):
                        continue
                    now = time.monotonic()
                    if now - last_death >= _DUPLICATE_SECONDS:
                        last_death = now
                        logger.info("Death line in %s: %s", name, line.strip()[:200])
                        self.death_detected.emit(config.game_id)
            self._stop_event.wait(_POLL_SECONDS)
