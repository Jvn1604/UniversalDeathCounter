"""
A death screen taught from an uploaded screenshot still counts when the live
game is framed a little differently (BUG-009), without false deaths.
"""

from __future__ import annotations

import time

import numpy as np

from src.detection.matchers import DeathTemplate, TemplateMatcher

REGION = (0.36, 0.43, 0.28, 0.13)
_TEXT = (np.random.default_rng(42).random((14, 60)) > 0.55)  # the "YOU DIED" shape


def _screen(width: int, height: int, *, text: bool, dy: int = 0, scale: float = 1.0,
            seed: int = 0) -> np.ndarray:
    """A dark screen with clutter at the top and, optionally, the death text."""
    rng = np.random.default_rng(seed)
    frame = np.full((height, width, 3), (30, 24, 34), dtype=np.uint8)
    for _ in range(30):
        x, y = int(rng.integers(0, width - 80)), int(rng.integers(0, height // 4))
        frame[y:y + 40, x:x + 80] = rng.integers(0, 140, 3)
    if text:
        text_h, text_w = int(height * 0.09 * scale), int(width * 0.24 * scale)
        rows = (np.arange(text_h) * _TEXT.shape[0] // text_h)
        cols = (np.arange(text_w) * _TEXT.shape[1] // text_w)
        mask = _TEXT[rows][:, cols]
        top = int(height * 0.495) - text_h // 2 + dy
        left = width // 2 - text_w // 2
        frame[top:top + text_h, left:left + text_w][mask] = (200, 20, 30)
    return frame


def test_a_screenshot_framed_differently_still_counts() -> None:
    # Uploaded: 1920x1120 with a 40 px title bar pushing the picture down.
    template = DeathTemplate.from_frame(_screen(1920, 1120, text=True, dy=40), REGION)
    matcher = TemplateMatcher(template)
    assert matcher.match(_screen(2560, 1440, text=True, seed=3))[0]
    assert matcher.match(_screen(2560, 1440, text=True, scale=0.94, seed=4))[0]


def test_the_exact_spot_still_matches_as_before() -> None:
    frame = _screen(2560, 1440, text=True)
    matched, score = TemplateMatcher(DeathTemplate.from_frame(frame, REGION)).match(frame)
    assert matched and score > 0.95


def test_no_false_deaths_on_other_screens() -> None:
    template = DeathTemplate.from_frame(_screen(1920, 1120, text=True, dy=40), REGION)
    matcher = TemplateMatcher(template)
    rng = np.random.default_rng(7)
    for seed in range(40):
        frame = _screen(2560, 1440, text=False, seed=seed)
        band = frame[int(1440 * 0.38):int(1440 * 0.62)]
        band[:] = rng.integers(0, 256, band.shape, dtype=np.uint8)  # busy gameplay
        assert not matcher.match(frame)[0], seed


def test_matching_stays_cheap() -> None:
    template = DeathTemplate.from_frame(_screen(1920, 1120, text=True, dy=40), REGION)
    matcher = TemplateMatcher(template)
    frame = _screen(2560, 1440, text=False, seed=1)
    frame[500:900] = np.random.default_rng(1).integers(0, 256, (400, 2560, 3), dtype=np.uint8)
    matcher.match(frame)
    start = time.perf_counter()
    for _ in range(10):
        matcher.match(frame)
    assert (time.perf_counter() - start) / 10 < 0.05  # well under the 0.2 s between looks
