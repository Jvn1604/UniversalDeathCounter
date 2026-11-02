"""
Exclusive-fullscreen games: the normal capture comes out black, so detection
switches to Desktop Duplication (Windows), which sees them.
"""

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
from src.detection import dxgi_capture  # noqa: E402
from src.detection.matchers import DeathTemplate, TemplateMatcher  # noqa: E402
from src.utils.platform_info import IS_WINDOWS  # noqa: E402

REGION = (0.30, 0.40, 0.40, 0.15)


def _screen(death: bool) -> np.ndarray:
    rng = np.random.default_rng(5)
    screen = (rng.random((600, 800, 4)) * 40).astype(np.uint8) + 30
    if death:
        x0, y0, w, h = int(0.30 * 800), int(0.40 * 600), int(0.40 * 800), int(0.15 * 600)
        screen[y0 : y0 + h, x0 : x0 + w // 2, :3] = 230
        screen[y0 : y0 + h, x0 + w // 2 : x0 + w, :3] = 10
    return screen


class _BlackScreen:
    """The normal capture of an exclusive-fullscreen game: all black."""

    monitors = [
        {"left": 0, "top": 0, "width": 800, "height": 600},
        {"left": 0, "top": 0, "width": 800, "height": 600},
    ]

    def grab(self, area: dict) -> np.ndarray:
        return np.zeros((area["height"], area["width"], 4), dtype=np.uint8)


class _Duplicator:
    """What Desktop Duplication sees: the real picture."""

    screen = _screen(death=False)
    opened = 0

    def __init__(self) -> None:
        type(self).opened += 1

    def grab(self, rect):
        left, top, width, height = rect
        return self.screen[top : top + height, left : left + width]

    def close(self) -> None:
        pass


def _watch(capture, seconds: float, watcher) -> None:
    watcher._stop_event.clear()
    thread = threading.Thread(target=watcher._watch_loop, args=(capture,), daemon=True)
    thread.start()
    time.sleep(seconds)
    watcher._stop_event.set()
    thread.join(2)


def _watcher(monkeypatch):
    from PySide6.QtCore import Qt

    monkeypatch.setattr(dw, "FRAMES_PER_SECOND", 50.0)
    monkeypatch.setattr(dw, "_FULL_FRAME_INTERVAL_MATCHING", 0.05)
    monkeypatch.setattr(dw, "_DUPLICATION_AFTER_SECONDS", 0.05)
    frame = np.ascontiguousarray(_screen(death=True)[..., 2::-1])
    matcher = TemplateMatcher(DeathTemplate.from_frame(frame, REGION))
    watcher = dw.DeathWatcher(cooldown_seconds=0.0)
    deaths: list[int] = []
    statuses: list[str] = []
    watcher.death_detected.connect(deaths.append, Qt.ConnectionType.DirectConnection)
    watcher.status_changed.connect(statuses.append, Qt.ConnectionType.DirectConnection)
    watcher.configure(dw.WatchConfig(game_id=7, exe_path="", matcher=matcher, screen_display=1))
    return watcher, deaths, statuses


def test_black_capture_switches_to_desktop_duplication(monkeypatch) -> None:
    monkeypatch.setattr(dxgi_capture, "DesktopDuplicator", _Duplicator)
    _Duplicator.screen = _screen(death=False)
    watcher, deaths, statuses = _watcher(monkeypatch)
    capture = dxgi_capture.FallbackCapture(_BlackScreen())
    _watch(capture, 0.4, watcher)
    assert capture.duplicating and deaths == []
    assert not any("black" in s for s in statuses)
    _Duplicator.screen = _screen(death=True)  # the fullscreen game's death screen
    _watch(capture, 0.6, watcher)
    assert deaths and deaths[0] == 7
    capture.reset()
    assert not capture.duplicating


def test_without_desktop_duplication_the_black_hint_still_shows(monkeypatch) -> None:
    def unavailable():
        raise dxgi_capture.DuplicationError("not here")

    monkeypatch.setattr(dxgi_capture, "DesktopDuplicator", unavailable)
    monkeypatch.setattr(dw, "_BLACK_SECONDS", 0.2)
    watcher, deaths, statuses = _watcher(monkeypatch)
    capture = dxgi_capture.FallbackCapture(_BlackScreen())
    _watch(capture, 0.6, watcher)
    assert not capture.duplicating and deaths == []
    assert any("is black" in s and "OBS" in s for s in statuses)


def test_a_rectangle_is_cut_to_its_display() -> None:
    class _Display:
        def __init__(self, rect) -> None:
            self.rect = rect
            self.asked = None

        def grab(self, left, top, width, height):
            self.asked = (left, top, width, height)
            return np.full((height, width, 4), 200, dtype=np.uint8)

    duplicator = object.__new__(dxgi_capture.DesktopDuplicator)
    first, second = _Display((0, 0, 1920, 1080)), _Display((1920, 0, 1280, 1024))
    duplicator._displays = [first, second]
    pixels = duplicator.grab((2000, 100, 300, 200))
    assert second.asked == (80, 100, 300, 200) and pixels.shape == (200, 300, 4)
    # Hanging off the bottom of the second display: the rest is black.
    pixels = duplicator.grab((2000, 900, 300, 200))
    assert second.asked == (80, 900, 300, 124)
    assert pixels.shape == (200, 300, 4) and pixels[150:].max() == 0 and pixels[:100].min() == 200
    assert duplicator.grab((-5000, -5000, 10, 10)) is None  # on no display


@pytest.mark.skipif(not IS_WINDOWS, reason="Desktop Duplication is Windows only")
def test_desktop_duplication_matches_the_normal_capture() -> None:
    import ctypes

    from src.detection.game_window import open_screen_capture

    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # as Qt does
    try:
        duplicator = dxgi_capture.DesktopDuplicator()
    except dxgi_capture.DuplicationError as exc:
        pytest.skip(f"no Desktop Duplication here: {exc}")  # e.g. no display on CI
    try:
        left, top, width, height = duplicator._displays[0].rect
        rect = (left + 10, top + 10, 200, 120)
        area = {"left": rect[0], "top": rect[1], "width": rect[2], "height": rect[3]}
        differences = []
        with open_screen_capture() as sct:
            for _ in range(3):  # the screen may change between the two grabs
                pixels = duplicator.grab(rect)
                if pixels is None:
                    pytest.skip("no frame from the display")
                assert pixels.shape == (120, 200, 4)
                normal = np.asarray(sct.grab(area))
                differences.append(
                    np.abs(pixels[..., :3].astype(int) - normal[..., :3].astype(int)).mean()
                )
                time.sleep(0.1)
        assert min(differences) < 10  # the same picture
    finally:
        duplicator.close()
