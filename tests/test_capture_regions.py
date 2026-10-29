"""Detection captures only what the matchers read, and still detects deaths."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.detection import death_watcher as dw  # noqa: E402
from src.detection.matchers import (  # noqa: E402
    AnyMatcher,
    DeathTemplate,
    SoulsPresetMatcher,
    TemplateMatcher,
    crop_region,
    pixel_box,
    pixel_boxes,
)

WINDOW = (100, 50, 640, 360)  # screen x, y, width, height of the game's client area
REGION = (0.30, 0.40, 0.40, 0.15)


def _screen(death: bool) -> np.ndarray:
    """A 1000x600 BGRA desktop with the game window, showing a death screen or not."""
    rng = np.random.default_rng(1)
    screen = (rng.random((600, 1000, 4)) * 40).astype(np.uint8) + 30
    if death:
        x, y, w, h = WINDOW
        game = screen[y : y + h, x : x + w]
        crop = crop_region(game, REGION)
        crop[:, : crop.shape[1] // 2, :3] = 230  # "YOU DIED": half bright, half dark
        crop[:, crop.shape[1] // 2 :, :3] = 10
    return screen


class _FakeCapture:
    """Stands in for mss: grabs from a fake screen and records each grab's size."""

    def __init__(self) -> None:
        self.screen = _screen(death=False)
        self.monitors = [{"left": 0, "top": 0, "width": 1000, "height": 600}]
        self.sizes: list[tuple[int, int]] = []

    def grab(self, area: dict) -> np.ndarray:
        self.sizes.append((area["width"], area["height"]))
        x, y = area["left"], area["top"]
        return self.screen[y : y + area["height"], x : x + area["width"]]


def test_pixel_box_covers_every_crop_exactly() -> None:
    rng = np.random.default_rng(3)
    for _ in range(200):
        width, height = int(rng.integers(50, 3000)), int(rng.integers(50, 2000))
        regions = [
            (*rng.random(2) * 0.8, *(rng.random(2) * 0.2 + 0.001)) for _ in range(3)
        ]
        left, top, right, bottom = pixel_box(regions, width, height)
        frame = np.zeros((height, width), dtype=np.uint8)
        frame[top:bottom, left:right] = 1
        for region in regions:
            assert crop_region(frame, region).min() == 1  # nothing outside the box is read


def test_far_apart_regions_are_captured_separately() -> None:
    souls = SoulsPresetMatcher().regions()
    boxes = pixel_boxes(souls, 2560, 1440)
    assert len(boxes) == 3  # middle band, top and bottom strips: not the whole height
    assert pixel_boxes([REGION], 2560, 1440) == [pixel_box([REGION], 2560, 1440)]


def test_matchers_report_what_they_read() -> None:
    frame = (np.random.default_rng(0).random((200, 300, 3)) * 255).astype(np.uint8)
    template = TemplateMatcher(DeathTemplate.from_frame(frame, REGION))
    assert template.regions() == [REGION]
    assert len(SoulsPresetMatcher().regions()) == 3
    assert AnyMatcher([template, SoulsPresetMatcher()]).regions()[0] == REGION


@pytest.fixture()
def fake_game(monkeypatch):
    monkeypatch.setattr(dw, "find_process_ids", lambda exe: [1])
    monkeypatch.setattr(dw, "find_main_window", lambda pids, title="": 42)
    monkeypatch.setattr(dw, "window_client_rect", lambda hwnd: WINDOW)
    monkeypatch.setattr(dw, "is_not_responding", lambda hwnd: False)
    monkeypatch.setattr(dw, "is_foreground", lambda hwnd: True)
    monkeypatch.setattr(dw, "FRAMES_PER_SECOND", 50.0)  # a fast test
    return _FakeCapture()


def _run(watcher: dw.DeathWatcher, capture: _FakeCapture, seconds: float) -> None:
    watcher._stop_event.clear()
    thread = threading.Thread(target=watcher._watch_loop, args=(capture,), daemon=True)
    thread.start()
    time.sleep(seconds)
    watcher._stop_event.set()
    thread.join(2)


def test_watcher_grabs_only_the_death_text_area_and_still_counts(fake_game) -> None:
    from PySide6.QtCore import Qt

    capture = fake_game
    x, y, w, h = WINDOW
    death_frame = np.ascontiguousarray(_screen(death=True)[y : y + h, x : x + w, 2::-1])
    matcher = TemplateMatcher(DeathTemplate.from_frame(death_frame, REGION))
    watcher = dw.DeathWatcher(cooldown_seconds=0.0)
    deaths: list[int] = []
    watcher.death_detected.connect(deaths.append, Qt.ConnectionType.DirectConnection)
    watcher.configure(dw.WatchConfig(game_id=7, exe_path="game.exe", matcher=matcher))

    _run(watcher, capture, 0.4)
    assert deaths == []
    capture.screen = _screen(death=True)
    _run(watcher, capture, 0.4)
    assert deaths == [7]

    full = (w, h)
    left, top, right, bottom = pixel_box([REGION], w, h)
    small = (right - left, bottom - top)
    assert set(capture.sizes) == {full, small}
    assert capture.sizes.count(small) > 4 * capture.sizes.count(full)
    assert len(watcher.recent_frames()) >= 1  # whole frames still kept for Capture Screen


def test_speedrun_auto_pause_still_reads_whole_frames(fake_game) -> None:
    capture = fake_game
    watcher = dw.DeathWatcher()
    watcher.configure(
        dw.WatchConfig(game_id=1, exe_path="game.exe", matcher=SoulsPresetMatcher(),
                       watch_activity=True)
    )
    _run(watcher, capture, 0.3)
    assert set(capture.sizes) == {(WINDOW[2], WINDOW[3])}
