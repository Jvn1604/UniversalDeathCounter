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
    desktop_clip,
    detection_available,
    find_main_window,
    find_process_ids,
    grab_into,
    grab_rect,
    is_foreground,
    is_not_responding,
    open_screen_capture,
    window_client_rect,
)
from src.detection.matchers import (
    DeathDebouncer,
    Matcher,
    Region,
    is_loading_frame,
    pixel_boxes,
)
from src.detection.obs_client import ObsClient, ObsError
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
_BLACK_SECONDS: float = 5.0
# Between full captures only the parts the matchers read are captured; a
# full frame still comes this often (recent frames, the black-capture hint).
_FULL_FRAME_INTERVAL: float = 1.0


# What the game is doing, reported for the speedrun timer's auto-pause.
ACTIVITY_WAITING = "waiting"  # not started yet
ACTIVITY_PLAYING = "playing"
ACTIVITY_LOADING = "loading"  # black / near-black screen, or no window yet
ACTIVITY_PAUSE_SCREEN = "pause_screen"  # one of the saved pause screens
ACTIVITY_NOT_RESPONDING = "not_responding"
ACTIVITY_BACKGROUND = "background"  # minimized or another window in front
ACTIVITY_CLOSED = "closed"  # was running, process gone (quit or crash)
# Consecutive frames needed before a loading / pause screen counts.
_LOADING_FRAMES: int = 3
_PAUSE_SCREEN_FRAMES: int = 2
# Solid black for longer than this is a capture problem, not a load.
_MAX_BLACK_LOADING_SECONDS: float = 30.0


# Recent frames kept for "missed a death?" captures: one per second, at most
# this many, downscaled to at most this width to bound memory (~25 MB).
RECENT_FRAME_COUNT: int = 8
_RECENT_FRAME_INTERVAL: float = 1.0
_RECENT_FRAME_MAX_WIDTH: int = 1280


def needed_regions(config: WatchConfig) -> list[Region] | None:
    """What the matchers read, or None when every frame must be captured whole."""
    if config.watch_activity:
        return None  # loading screens are judged on the whole frame
    matchers = [m for m in (config.matcher, config.victory_matcher) if m is not None]
    if not matchers:
        return None
    return [region for matcher in matchers for region in matcher.regions()]


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
    # Speedrun auto-pause: report what the game is doing (activity_changed),
    # optionally recognizing saved pause / loading screens.
    watch_activity: bool = False
    pause_matcher: Matcher | None = None
    # Boss kills: saved victory screens, watched while a boss is selected.
    victory_matcher: Matcher | None = None
    required_frames: int = 3
    setup_hint: str = "after you die, click Capture Screen (Detection page) to teach it"
    # Console players: watch the window of ``exe_path`` whose title contains
    # this (PS Remote Play, a capture card viewer, an OBS projector).
    window_title: str = ""
    # Console players with a capture card: read this OBS source instead of
    # a window (exe_path is then unused).
    obs_source: str = ""
    obs_host: str = ""
    obs_port: int = 0
    obs_password: str = ""


class DeathWatcher(QObject):
    """
    Watches the configured game's window for death screens.

    Signals:
        death_detected: Emitted with the game id when a death screen appears.
        status_changed: Emitted with a short human-readable status line.
        activity_changed: Emitted with (game id, ``ACTIVITY_*``) when what the
            game is doing changes; only with ``WatchConfig.watch_activity``.
        boss_defeated: Emitted with the game id when a saved victory screen
            (a boss-kill banner) appears.
    """

    death_detected = Signal(int)
    status_changed = Signal(str)
    activity_changed = Signal(int, str)
    boss_defeated = Signal(int)

    def __init__(self, cooldown_seconds: float = 8.0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._config: WatchConfig | None = None
        self._config_version = 0
        self._cooldown_seconds = cooldown_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_status = ""
        self._last_activity = ""
        self._recent_frames: deque[tuple[float, np.ndarray]] = deque(maxlen=RECENT_FRAME_COUNT)
        self._obs: ObsClient | None = None  # worker thread only

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

    def _report(self, config: WatchConfig, activity: str) -> None:
        if config.watch_activity and activity != self._last_activity:
            self._last_activity = activity
            self.activity_changed.emit(config.game_id, activity)

    def _run(self) -> None:
        try:
            with open_screen_capture() as sct:
                self._watch_loop(sct)
        except Exception:  # noqa: BLE001 - detection must never crash the app
            logger.exception("Death watcher stopped unexpectedly")
            self._set_status("Auto-detect stopped (error, see log)")
        finally:
            if self._obs is not None:
                self._obs.close()

    def _obs_frame(self, config: WatchConfig) -> np.ndarray | None:
        """The OBS source's picture, or None (with the reason as the status)."""
        if self._obs is None:
            self._obs = ObsClient(config.obs_host, config.obs_port, config.obs_password)
        try:
            return self._obs.screenshot(config.obs_source)
        except ObsError as exc:
            self._set_status(str(exc))
            return None

    def _watch_loop(self, sct: mss.base.MSSBase) -> None:
        seen_version = -1
        debouncer = DeathDebouncer()
        # A victory banner shows for a few seconds; count it once.
        victory_debouncer = DeathDebouncer(required_frames=3, cooldown_seconds=20.0)
        hwnd: int | None = None
        next_lookup = 0.0
        black_since: float | None = None
        next_recent = next_full = 0.0
        ever_seen = False
        loading_frames = pause_frames = 0
        regions: list[Region] | None = None
        canvas: np.ndarray | None = None  # full-size frame that region captures fill in
        boxes: list[tuple[int, int, int, int]] = []

        while not self._stop_event.is_set():
            with self._lock:
                config, version = self._config, self._config_version
                debouncer.cooldown_seconds = self._cooldown_seconds
                if version != seen_version:
                    self._recent_frames.clear()  # frames of another game
            if version != seen_version:
                seen_version = version
                debouncer.reset()
                victory_debouncer.reset()
                if config is not None:
                    debouncer.required_frames = config.required_frames
                regions = needed_regions(config) if config is not None else None
                if self._obs is not None:  # settings may have changed: reconnect when needed
                    self._obs.close()
                    self._obs = None
                canvas = None
                hwnd, next_lookup, black_since, next_recent, next_full = None, 0.0, None, 0.0, 0.0
                ever_seen, loading_frames, pause_frames = False, 0, 0
                self._last_activity = ""

            if config is None:
                self._stop_event.wait(_IDLE_POLL_SECONDS)
                continue

            exe_name = (
                config.obs_source or config.window_title or Path(config.exe_path).name
            )
            now = time.monotonic()
            if config.obs_source:
                frame = self._obs_frame(config)
                if frame is None:
                    self._stop_event.wait(_PROCESS_POLL_SECONDS)
                    continue
                hwnd = None
                if now >= next_recent:
                    next_recent = now + _RECENT_FRAME_INTERVAL
                    step = max(1, math.ceil(frame.shape[1] / _RECENT_FRAME_MAX_WIDTH))
                    with self._lock:
                        self._recent_frames.append((now, frame[::step, ::step].copy()))
                if int(frame[::4, ::4].max()) < 8:
                    black_since = now if black_since is None else black_since
                else:
                    black_since = None
            else:
                if hwnd is None or now >= next_lookup:
                    hwnd = find_main_window(find_process_ids(config.exe_path), config.window_title)
                    next_lookup = now + _WINDOW_LOOKUP_INTERVAL
                if hwnd is None:
                    if not ever_seen:
                        self._report(config, ACTIVITY_WAITING)
                    elif find_process_ids(config.exe_path):
                        self._report(config, ACTIVITY_LOADING)  # alive, window not up
                    else:
                        self._report(config, ACTIVITY_CLOSED)  # quit or crashed
                    self._set_status(f"Waiting for {exe_name} to start…")
                    self._stop_event.wait(_PROCESS_POLL_SECONDS)
                    continue
                ever_seen = True

                if is_not_responding(hwnd):
                    self._report(config, ACTIVITY_NOT_RESPONDING)
                    self._set_status(f"{exe_name} is not responding")
                    self._stop_event.wait(_IDLE_POLL_SECONDS)
                    continue

                rect = window_client_rect(hwnd)
                if rect is None:
                    self._report(config, ACTIVITY_BACKGROUND)
                    hwnd = None
                    self._set_status(f"{exe_name} is minimized")
                    self._stop_event.wait(_IDLE_POLL_SECONDS)
                    continue

                now = time.monotonic()
                on_screen = desktop_clip(sct, rect) == rect
                if regions is None or not on_screen or now >= next_full:
                    frame = grab_rect(sct, rect)
                    next_full = now + _FULL_FRAME_INTERVAL
                    if now >= next_recent:
                        next_recent = now + _RECENT_FRAME_INTERVAL
                        step = max(1, math.ceil(frame.shape[1] / _RECENT_FRAME_MAX_WIDTH))
                        with self._lock:
                            self._recent_frames.append((now, frame[::step, ::step].copy()))
                    if int(frame[::4, ::4].max()) < 8:
                        black_since = now if black_since is None else black_since
                    else:
                        black_since = None
                else:
                    height, width = rect[3], rect[2]
                    if canvas is None or canvas.shape[:2] != (height, width):
                        canvas = np.zeros((height, width, 3), dtype=np.uint8)
                        boxes = pixel_boxes(regions, width, height)
                    for box in boxes:
                        grab_into(sct, (rect[0], rect[1]), box, canvas)
                    frame = canvas
            black_for = now - black_since if black_since is not None else 0.0

            if black_for >= _BLACK_SECONDS and config.obs_source:
                self._set_status(
                    f"{exe_name} is black in OBS: is the console on and the card showing it?"
                )
            elif black_for >= _BLACK_SECONDS:
                self._set_status(
                    f"Capture of {exe_name} is black. Switch the game to borderless/windowed."
                )
            elif config.matcher is None:
                self._set_status(f"Watching {exe_name}: {config.setup_hint}")
            else:
                self._set_status(f"Watching {exe_name} for deaths")

            if config.watch_activity:
                loading = is_loading_frame(frame) and black_for < _MAX_BLACK_LOADING_SECONDS
                loading_frames = loading_frames + 1 if loading else 0
                paused = config.pause_matcher is not None and config.pause_matcher.match(
                    frame
                )[0]
                pause_frames = pause_frames + 1 if paused else 0
                if pause_frames >= _PAUSE_SCREEN_FRAMES:
                    self._report(config, ACTIVITY_PAUSE_SCREEN)
                elif loading_frames >= _LOADING_FRAMES:
                    self._report(config, ACTIVITY_LOADING)
                elif hwnd is not None and not is_foreground(hwnd):
                    self._report(config, ACTIVITY_BACKGROUND)
                elif not loading and not paused:
                    self._report(config, ACTIVITY_PLAYING)

            if config.matcher is not None:
                matched, _score = config.matcher.match(frame)
                if debouncer.update(matched, time.monotonic()):
                    logger.info("Death screen detected in %s", exe_name)
                    self.death_detected.emit(config.game_id)
            if config.victory_matcher is not None:
                won, _score = config.victory_matcher.match(frame)
                if victory_debouncer.update(won, time.monotonic()):
                    logger.info("Boss victory screen detected in %s", exe_name)
                    self.boss_defeated.emit(config.game_id)
            if (
                config.matcher is None
                and config.victory_matcher is None
                and not config.watch_activity
            ):
                self._stop_event.wait(_RECENT_FRAME_INTERVAL)  # buffer only, no matching
                continue

            self._stop_event.wait(1.0 / FRAMES_PER_SECOND)
