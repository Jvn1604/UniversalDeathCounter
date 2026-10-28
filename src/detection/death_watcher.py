"""
Background death watcher.

Runs a daemon thread that waits for the configured game to start, then
captures its window a few times per second and feeds each frame to a
:class:`~src.detection.matchers.Matcher`. Results reach the UI through Qt
signals, which Qt queues onto the main thread automatically (the same
pattern as :mod:`src.hotkeys.hotkey_manager` and the update checker).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from src.detection.game_window import (
    detection_available,
    find_main_window,
    find_process_ids,
    grab_rect,
    open_screen_capture,
    window_client_rect,
)
from src.detection.matchers import DeathDebouncer, Matcher
from src.utils.logger import get_logger

try:
    import mss
except ImportError:  # pragma: no cover - environment dependent
    mss = None

logger = get_logger(__name__)

FRAMES_PER_SECOND: float = 5.0
_WINDOW_LOOKUP_INTERVAL: float = 3.0
_IDLE_POLL_SECONDS: float = 1.0
_PROCESS_POLL_SECONDS: float = 2.0
# ~5 s of solid black frames triggers the "use borderless" hint.
_BLACK_FRAME_LIMIT: int = int(FRAMES_PER_SECOND * 5)


# Recent frames kept for "missed a death?" captures: one per second, at most
# this many, downscaled to at most this width to bound memory (~25 MB).
RECENT_FRAME_COUNT: int = 8
_RECENT_FRAME_INTERVAL: float = 1.0
_RECENT_FRAME_MAX_WIDTH: int = 1280


@dataclass(slots=True, frozen=True)
class WatchConfig:
    """
    What to watch: which game (by id), its executable, and how to match.

    ``matcher`` may be None for a game with no death screen saved yet; the
    window is then only captured into the recent-frames buffer, so the
    player can pick their first death screen from it, and ``setup_hint``
    is shown as the status. ``required_frames`` is how many consecutive
    matching frames make a death.
    """

    game_id: int
    exe_path: str
    matcher: Matcher | None
    required_frames: int = 3
    setup_hint: str = "after you die, click 📷 Death Screen to teach it"


class DeathWatcher(QObject):
    """
    Watches the configured game's window for death screens.

    Signals:
        death_detected: Emitted with the game id when a death screen appears.
        status_changed: Emitted with a short human-readable status line.
    """

    death_detected = Signal(int)
    status_changed = Signal(str)

    def __init__(self, cooldown_seconds: float = 8.0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._config: WatchConfig | None = None
        self._config_version = 0
        self._cooldown_seconds = cooldown_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_status = ""
        self._recent_frames: deque[tuple[float, np.ndarray]] = deque(maxlen=RECENT_FRAME_COUNT)

    def recent_frames(self) -> list[tuple[float, np.ndarray]]:
        """``(time.monotonic() timestamp, RGB frame)`` pairs, oldest first."""
        with self._lock:
            return list(self._recent_frames)

    # ----------------------------------------------------------------
    # Control (main thread)
    # ----------------------------------------------------------------
    def start(self) -> None:
        """Start the background thread (idles until :meth:`configure` is called)."""
        if self._thread is not None or not detection_available():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="DeathWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and wait briefly for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def configure(self, config: WatchConfig | None, cooldown_seconds: float | None = None) -> None:
        """Replace what is being watched; ``None`` pauses detection."""
        with self._lock:
            self._config = config
            self._config_version += 1
            if cooldown_seconds is not None:
                self._cooldown_seconds = cooldown_seconds
        # The main window may have overwritten the status label; make the
        # worker re-announce its status even if it is unchanged.
        self._last_status = ""
        if config is None:
            self._set_status("Auto-detect off")

    # ----------------------------------------------------------------
    # Worker thread
    # ----------------------------------------------------------------
    def _set_status(self, text: str) -> None:
        if text != self._last_status:
            self._last_status = text
            self.status_changed.emit(text)

    def _run(self) -> None:
        try:
            with open_screen_capture() as sct:
                self._watch_loop(sct)
        except Exception:  # noqa: BLE001 - detection must never crash the app
            logger.exception("Death watcher stopped unexpectedly")
            self._set_status("Auto-detect stopped (error, see log)")

    def _watch_loop(self, sct: mss.base.MSSBase) -> None:
        seen_version = -1
        debouncer = DeathDebouncer()
        hwnd: int | None = None
        next_lookup = 0.0
        black_frames = 0
        next_recent = 0.0

        while not self._stop_event.is_set():
            with self._lock:
                config, version = self._config, self._config_version
                debouncer.cooldown_seconds = self._cooldown_seconds
                if version != seen_version:
                    self._recent_frames.clear()  # frames of another game
            if version != seen_version:
                seen_version = version
                debouncer.reset()
                if config is not None:
                    debouncer.required_frames = config.required_frames
                hwnd, next_lookup, black_frames, next_recent = None, 0.0, 0, 0.0

            if config is None:
                self._stop_event.wait(_IDLE_POLL_SECONDS)
                continue

            exe_name = Path(config.exe_path).name
            now = time.monotonic()
            if hwnd is None or now >= next_lookup:
                hwnd = find_main_window(find_process_ids(config.exe_path))
                next_lookup = now + _WINDOW_LOOKUP_INTERVAL
            if hwnd is None:
                self._set_status(f"Waiting for {exe_name} to start…")
                self._stop_event.wait(_PROCESS_POLL_SECONDS)
                continue

            rect = window_client_rect(hwnd)
            if rect is None:
                hwnd = None
                self._set_status(f"{exe_name} is minimized")
                self._stop_event.wait(_IDLE_POLL_SECONDS)
                continue

            frame = grab_rect(sct, rect)
            now = time.monotonic()
            if now >= next_recent:
                next_recent = now + _RECENT_FRAME_INTERVAL
                step = max(1, math.ceil(frame.shape[1] / _RECENT_FRAME_MAX_WIDTH))
                with self._lock:
                    self._recent_frames.append((now, frame[::step, ::step].copy()))

            black_frames = black_frames + 1 if int(frame.max()) < 8 else 0
            if black_frames >= _BLACK_FRAME_LIMIT:
                self._set_status(
                    f"Capture of {exe_name} is black. Switch the game to borderless/windowed."
                )
            elif config.matcher is None:
                self._set_status(f"Watching {exe_name}: {config.setup_hint}")
            else:
                self._set_status(f"Watching {exe_name} for deaths")

            if config.matcher is None:
                self._stop_event.wait(_RECENT_FRAME_INTERVAL)  # buffer only, no matching
                continue

            matched, _score = config.matcher.match(frame)
            if debouncer.update(matched, time.monotonic()):
                logger.info("Death screen detected in %s", exe_name)
                self.death_detected.emit(config.game_id)

            self._stop_event.wait(1.0 / FRAMES_PER_SECOND)
