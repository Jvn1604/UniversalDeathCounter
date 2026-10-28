"""
Death-screen matching logic for automatic death detection.

Everything here is pure numpy and framework-agnostic so it can be unit
tested without a game, a screen, or Qt. Frames are ``(H, W, 3)`` uint8
RGB arrays.

Three strategies are provided:

* :class:`TemplateMatcher` — works for ANY game. The player calibrates
  once by selecting the death-screen text (e.g. "YOU DIED") on a
  screenshot; afterwards the same relative region of each live frame is
  compared to that reference with normalized cross-correlation, which is
  insensitive to brightness/contrast changes such as fade-ins.
* :class:`SoulsPresetMatcher` — zero-setup heuristic for FromSoftware
  games, whose death screens show red text in the middle of the screen.
* :class:`HealthBarMatcher` — for games with no death screen. The player
  marks their health bar once at full health; a death is the bar emptying
  after health was already low.

:class:`DeathDebouncer` turns a stream of per-frame matches into discrete
death events so one death screen is never counted twice.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from src.utils.constants import (
    DETECTION_MODE_HEALTH,
    DETECTION_MODE_SOULS,
    DETECTION_MODE_TEMPLATE,
)

# Reference patches are normalized to this width (height keeps aspect).
TEMPLATE_WIDTH: int = 96
_MIN_TEMPLATE_HEIGHT: int = 8
_MAX_TEMPLATE_HEIGHT: int = 96

# Normalized cross-correlation needed for a frame to count as a match.
TEMPLATE_MATCH_THRESHOLD: float = 0.80
# Patches flatter than this (std of gray levels) carry no usable detail.
_MIN_PATCH_STD: float = 4.0

# Executable names that get the Souls preset suggested automatically.
SOULS_PRESET_EXES: frozenset[str] = frozenset(
    {
        "eldenring.exe",
        "darksoulsiii.exe",
        "darksoulsii.exe",
        "darksoulsremastered.exe",
        "darksouls.exe",
        "sekiro.exe",
    }
)

Region = tuple[float, float, float, float]  # x, y, w, h as fractions of the frame


class Matcher(Protocol):
    """Anything that can decide whether a frame shows a death screen."""

    def match(self, frame: np.ndarray) -> tuple[bool, float]:
        """Return ``(is_death_screen, score)`` for an RGB frame."""
        ...

    def regions(self) -> list[Region]:
        """The parts of the frame :meth:`match` reads (the watcher captures only these)."""
        ...


def pixel_box(regions: Iterable[Region], width: int, height: int) -> tuple[int, int, int, int]:
    """
    ``(left, top, right, bottom)`` pixels covering every region of a
    ``width`` x ``height`` frame, exactly as :func:`crop_region` cuts them.
    """
    boxes = []
    for x, y, w, h in regions:
        left = min(max(int(round(x * width)), 0), width - 1)
        top = min(max(int(round(y * height)), 0), height - 1)
        right = min(max(int(round((x + w) * width)), left + 1), width)
        bottom = min(max(int(round((y + h) * height)), top + 1), height)
        boxes.append((left, top, right, bottom))
    if not boxes:
        return 0, 0, width, height
    return _union(boxes)


def _union(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _area(box: tuple[int, int, int, int]) -> int:
    return (box[2] - box[0]) * (box[3] - box[1])


def pixel_boxes(regions: list[Region], width: int, height: int) -> list[tuple[int, int, int, int]]:
    """
    Boxes to capture so every region is covered: one box around all of them,
    or one per region when that's clearly less screen (regions far apart,
    like the Souls preset's middle band and top/bottom edges).
    """
    separate = [pixel_box([region], width, height) for region in regions]
    union = pixel_box(regions, width, height)
    if len(separate) > 1 and sum(_area(b) for b in separate) < 0.8 * _area(union):
        return separate
    return [union]


# ----------------------------------------------------------------
# Image helpers
# ----------------------------------------------------------------
def to_gray(frame: np.ndarray) -> np.ndarray:
    """Convert an RGB uint8 frame to float32 luminance."""
    rgb = frame[..., :3].astype(np.float32)
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def resize_area(image: np.ndarray, height: int, width: int) -> np.ndarray:
    """
    Downscale a 2-D image by averaging source pixels over each output cell.

    Uses an integral image so it stays fast for large crops. Upscaling
    falls back to nearest-neighbor sampling of the same cells.
    """
    src_h, src_w = image.shape
    integral = np.zeros((src_h + 1, src_w + 1), dtype=np.float64)
    integral[1:, 1:] = image.astype(np.float64).cumsum(0).cumsum(1)

    ys = np.linspace(0, src_h, height + 1).astype(np.int64)
    xs = np.linspace(0, src_w, width + 1).astype(np.int64)
    y0, y1 = ys[:-1], np.maximum(ys[1:], ys[:-1] + 1)
    x0, x1 = xs[:-1], np.maximum(xs[1:], xs[:-1] + 1)
    y1 = np.minimum(y1, src_h)
    x1 = np.minimum(x1, src_w)
    y0 = np.minimum(y0, y1 - 1)
    x0 = np.minimum(x0, x1 - 1)

    total = (
        integral[np.ix_(y1, x1)]
        - integral[np.ix_(y0, x1)]
        - integral[np.ix_(y1, x0)]
        + integral[np.ix_(y0, x0)]
    )
    area = np.outer(y1 - y0, x1 - x0)
    return (total / area).astype(np.float32)


def crop_region(frame: np.ndarray, region: Region) -> np.ndarray:
    """Crop a fractional ``(x, y, w, h)`` region out of a frame (at least 1x1 px)."""
    height, width = frame.shape[:2]
    x, y, w, h = region
    left = min(max(int(round(x * width)), 0), width - 1)
    top = min(max(int(round(y * height)), 0), height - 1)
    right = min(max(int(round((x + w) * width)), left + 1), width)
    bottom = min(max(int(round((y + h) * height)), top + 1), height)
    return frame[top:bottom, left:right]


def template_shape(crop_height: int, crop_width: int) -> tuple[int, int]:
    """Normalized ``(height, width)`` for a reference patch of the given crop size."""
    height = round(TEMPLATE_WIDTH * crop_height / max(crop_width, 1))
    return min(max(height, _MIN_TEMPLATE_HEIGHT), _MAX_TEMPLATE_HEIGHT), TEMPLATE_WIDTH


def normalized_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Zero-mean normalized cross-correlation of two same-shape patches, in [-1, 1]."""
    a = a.astype(np.float32) - a.mean()
    b = b.astype(np.float32) - b.mean()
    denominator = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if denominator == 0.0:
        return 0.0
    return float((a * b).sum() / denominator)


# ----------------------------------------------------------------
# Template (calibrated) matching — any game
# ----------------------------------------------------------------
@dataclass(slots=True)
class DeathTemplate:
    """A calibrated reference: where the death text appears, and what it looks like."""

    region: Region
    patch: np.ndarray  # float32 grayscale, shape == template_shape(...)

    @classmethod
    def from_frame(cls, frame: np.ndarray, region: Region) -> DeathTemplate:
        """
        Build a template from a screenshot and the player's selected region.

        Raises:
            ValueError: If the selected area is blank (no detail to match on).
        """
        crop = to_gray(crop_region(frame, region))
        height, width = template_shape(*crop.shape)
        patch = resize_area(crop, height, width)
        if float(patch.std()) < _MIN_PATCH_STD:
            raise ValueError(
                "The selected area is almost a flat color. Select the death text itself."
            )
        return cls(region=region, patch=patch)

    def region_json(self) -> str:
        """Serialize the region for storage."""
        return json.dumps([round(v, 6) for v in self.region])

    def patch_bytes(self) -> bytes:
        """Serialize the patch as ``<height><width>`` header + uint8 pixels."""
        height, width = self.patch.shape
        pixels = np.clip(np.round(self.patch), 0, 255).astype(np.uint8)
        return struct.pack("<HH", height, width) + pixels.tobytes()

    @classmethod
    def from_storage(cls, region_json: str, patch_bytes: bytes) -> DeathTemplate:
        """Inverse of :meth:`region_json` / :meth:`patch_bytes`."""
        x, y, w, h = (float(v) for v in json.loads(region_json))
        height, width = struct.unpack_from("<HH", patch_bytes)
        pixels = np.frombuffer(patch_bytes, dtype=np.uint8, offset=4)
        patch = pixels.reshape(height, width).astype(np.float32)
        return cls(region=(x, y, w, h), patch=patch)


class TemplateMatcher:
    """Compares the calibrated region of each frame with the reference patch."""

    def __init__(
        self, template: DeathTemplate, threshold: float = TEMPLATE_MATCH_THRESHOLD
    ) -> None:
        self._template = template
        self._threshold = threshold

    def match(self, frame: np.ndarray) -> tuple[bool, float]:
        crop = to_gray(crop_region(frame, self._template.region))
        height, width = self._template.patch.shape
        patch = resize_area(crop, height, width)
        if float(patch.std()) < _MIN_PATCH_STD:
            return False, 0.0  # black/loading screen: nothing to compare
        score = normalized_correlation(patch, self._template.patch)
        return score >= self._threshold, score

    def regions(self) -> list[Region]:
        return [self._template.region]


# ----------------------------------------------------------------
# Souls preset — red death text in the middle of the screen
# ----------------------------------------------------------------
class SoulsPresetMatcher:
    """
    Heuristic for FromSoftware death screens ("YOU DIED", Sekiro's 死).

    Looks for saturated red pixels concentrated in the central band of the
    screen while the top and bottom edges stay free of red. Requiring the
    edges to be clean keeps red-tinted areas (e.g. Caelid's sky) from
    triggering it.
    """

    # Central band that must contain the red text.
    _BAND: Region = (0.20, 0.30, 0.60, 0.40)
    # Top and bottom strips that must stay (mostly) red-free.
    _EDGES: tuple[Region, Region] = ((0.20, 0.0, 0.60, 0.15), (0.20, 0.85, 0.60, 0.15))
    _MIN_BAND_RED: float = 0.02
    _MAX_EDGE_RED: float = 0.02
    _BAND_TO_EDGE_RATIO: float = 4.0

    @staticmethod
    def _red_fraction(pixels: np.ndarray) -> float:
        rgb = pixels[::2, ::2, :3].astype(np.int16)  # half-res is plenty here
        red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        mask = (red >= 90) & (red * 10 >= green * 18) & (red * 10 >= blue * 18)
        return float(mask.mean()) if mask.size else 0.0

    def match(self, frame: np.ndarray) -> tuple[bool, float]:
        band = self._red_fraction(crop_region(frame, self._BAND))
        edge = max(self._red_fraction(crop_region(frame, r)) for r in self._EDGES)
        matched = (
            band >= self._MIN_BAND_RED
            and edge <= self._MAX_EDGE_RED
            and band >= edge * self._BAND_TO_EDGE_RATIO
        )
        return matched, band

    def regions(self) -> list[Region]:
        return [self._BAND, *self._EDGES]


# ----------------------------------------------------------------
# Health bar — for games without a death screen
# ----------------------------------------------------------------
# Max per-channel difference for a pixel to count as the bar's color.
_BAR_COLOR_TOLERANCE: int = 48
# The bar must fill at least this share of the selected box at full health.
_MIN_BAR_COVERAGE: float = 0.25


def color_fraction(pixels: np.ndarray, color: tuple[int, int, int]) -> float:
    """Share of ``pixels`` (``(H, W, 3)`` RGB) within tolerance of ``color``."""
    if pixels.size == 0:
        return 0.0
    diff = np.abs(pixels[..., :3].astype(np.int16) - np.array(color, dtype=np.int16))
    return float((diff.max(axis=-1) <= _BAR_COLOR_TOLERANCE).mean())


@dataclass(slots=True)
class HealthBar:
    """A calibrated health bar: where it is, its fill color, and how full it looked."""

    region: Region
    color: tuple[int, int, int]
    full_fraction: float  # share of the region in the bar color at full health

    @classmethod
    def from_frame(cls, frame: np.ndarray, region: Region) -> HealthBar:
        """
        Learn the bar from a screenshot taken at full health.

        The fill color is the median of the region's most colorful, brightest
        pixels, which picks the bar over its dark background or frame.

        Raises:
            ValueError: If the box doesn't contain a clear bar.
        """
        crop = crop_region(frame, region)[..., :3].astype(np.int16)
        pixels = crop.reshape(-1, 3)
        salience = (pixels.max(axis=1) - pixels.min(axis=1)) + pixels.max(axis=1) // 2
        strong = pixels[salience >= np.percentile(salience, 60)]
        color = (int(v) for v in np.median(strong, axis=0))
        r, g, b = color
        if max(r, g, b) < 60:
            raise ValueError("The selected area is too dark. Box the health bar itself.")
        full = color_fraction(crop, (r, g, b))
        if full < _MIN_BAR_COVERAGE:
            raise ValueError(
                "Couldn't find a clear bar there. Box only the health bar, at full health."
            )
        return cls(region=region, color=(r, g, b), full_fraction=full)

    def fill(self, frame: np.ndarray) -> float:
        """How full the bar is in ``frame``, from 0.0 to 1.0."""
        current = color_fraction(crop_region(frame, self.region), self.color)
        return min(current / self.full_fraction, 1.0) if self.full_fraction > 0 else 0.0

    def to_options(self) -> dict[str, object]:
        """Serialize for the game's detection options."""
        return {
            "health_region": [round(v, 6) for v in self.region],
            "health_color": list(self.color),
            "health_full": round(self.full_fraction, 6),
        }

    @classmethod
    def from_options(cls, options: Mapping[str, object]) -> HealthBar | None:
        """Inverse of :meth:`to_options`; None if no bar is saved (or it's corrupt)."""
        try:
            x, y, w, h = (float(v) for v in options["health_region"])  # type: ignore[union-attr]
            r, g, b = (int(v) for v in options["health_color"])  # type: ignore[union-attr]
            full = float(options["health_full"])  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError):
            return None
        return cls(region=(x, y, w, h), color=(r, g, b), full_fraction=full)


class HealthBarMatcher:
    """
    Reports a death while the health bar is empty right after health was low.

    Requiring low health just before keeps menus, maps and cutscenes, which
    hide the HUD at any health, from counting. The trade-off: a one-hit kill
    from high health is missed, so count those by hand. Unlike the other
    matchers this one is stateful, so use one instance per watch session.
    """

    EMPTY_FILL: float = 0.03  # at or below this the bar counts as empty
    LOW_FILL: float = 0.6  # health must have been at or below this before emptying
    MEMORY_FRAMES: int = 25  # how long (frames) an empty bar stays a death candidate
    # Empty for this many frames (1 s) makes a death, so a low-health bar
    # that blinks doesn't count.
    REQUIRED_FRAMES: int = 5

    def __init__(self, bar: HealthBar) -> None:
        self._bar = bar
        self._last_visible_fill: float | None = None
        self._frames_empty = 0

    def match(self, frame: np.ndarray) -> tuple[bool, float]:
        fill = self._bar.fill(frame)
        if fill > self.EMPTY_FILL:
            self._last_visible_fill = fill
            self._frames_empty = 0
            return False, fill
        self._frames_empty += 1
        matched = (
            self._last_visible_fill is not None
            and self._last_visible_fill <= self.LOW_FILL
            and self._frames_empty <= self.MEMORY_FRAMES
        )
        return matched, fill

    def regions(self) -> list[Region]:
        return [self._bar.region]


# ----------------------------------------------------------------
# Loading screens — for the speedrun timer's game time
# ----------------------------------------------------------------
_LOADING_MAX_MEAN: float = 12.0
_LOADING_MAX_BRIGHT: float = 50.0  # 98th-percentile brightness


def is_loading_frame(frame: np.ndarray) -> bool:
    """
    A black or near-black screen, perhaps with a small logo or spinner.

    That's what most loading screens and fade-to-black transitions look
    like. Checked on a 1-in-8 sample of pixels, so it costs next to nothing.
    """
    gray = to_gray(frame[::8, ::8])
    if gray.size == 0:
        return False
    return (
        float(gray.mean()) < _LOADING_MAX_MEAN
        and float(np.percentile(gray, 98)) < _LOADING_MAX_BRIGHT
    )


def build_screen_matcher(templates: Iterable[tuple[str, bytes]]) -> Matcher | None:
    """Any of several saved screens (e.g. pause / loading screens), or None."""
    matchers: list[Matcher] = [
        TemplateMatcher(DeathTemplate.from_storage(region, bytes(patch)))
        for region, patch in templates
    ]
    if not matchers:
        return None
    return matchers[0] if len(matchers) == 1 else AnyMatcher(matchers)


class AnyMatcher:
    """Matches when any of several matchers does (e.g. multiple death screens)."""

    def __init__(self, matchers: list[Matcher]) -> None:
        self._matchers = matchers

    def match(self, frame: np.ndarray) -> tuple[bool, float]:
        best = 0.0
        for matcher in self._matchers:
            matched, score = matcher.match(frame)
            if matched:
                return True, score
            best = max(best, score)
        return False, best

    def regions(self) -> list[Region]:
        return [region for matcher in self._matchers for region in matcher.regions()]


def build_matcher(
    mode: str,
    templates: Iterable[tuple[str, bytes]],
    options: Mapping[str, object] | None = None,
) -> Matcher | None:
    """
    Build the matcher for a game's detection mode, death screens and options.

    ``templates`` are stored ``(region_json, patch_bytes)`` pairs. In Souls and
    health-bar mode they supplement the main check (covering anything it
    misses). Returns None when detection is off or there is nothing to match yet.
    """
    if mode not in (DETECTION_MODE_TEMPLATE, DETECTION_MODE_SOULS, DETECTION_MODE_HEALTH):
        return None
    matchers: list[Matcher] = []
    if mode == DETECTION_MODE_HEALTH:
        bar = HealthBar.from_options(options or {})
        if bar is not None:
            # First, so AnyMatcher feeds it every frame and its state stays current.
            matchers.append(HealthBarMatcher(bar))
    matchers += [
        TemplateMatcher(DeathTemplate.from_storage(region, bytes(patch)))
        for region, patch in templates
    ]
    if mode == DETECTION_MODE_SOULS:
        matchers.append(SoulsPresetMatcher())
    if not matchers:
        return None
    return matchers[0] if len(matchers) == 1 else AnyMatcher(matchers)


# ----------------------------------------------------------------
# Debouncing
# ----------------------------------------------------------------
class DeathDebouncer:
    """
    Converts per-frame match results into single death events.

    A death fires once the death screen has been visible for
    ``required_frames`` consecutive frames. It then latches until the
    screen goes away, and a cooldown blocks re-triggering on fade
    flicker, so each death screen counts exactly once.
    """

    def __init__(self, required_frames: int = 3, cooldown_seconds: float = 8.0) -> None:
        self.required_frames = required_frames
        self.cooldown_seconds = cooldown_seconds
        self._streak = 0
        self._latched = False
        self._last_fired: float | None = None

    def reset(self) -> None:
        """Forget all state (e.g. when switching games)."""
        self._streak = 0
        self._latched = False
        self._last_fired = None

    def update(self, matched: bool, now: float) -> bool:
        """Feed one frame's result; return True exactly when a death should be counted."""
        if not matched:
            self._streak = 0
            self._latched = False
            return False
        self._streak += 1
        if self._latched or self._streak < self.required_frames:
            return False
        if self._last_fired is not None and now - self._last_fired < self.cooldown_seconds:
            return False
        self._latched = True
        self._last_fired = now
        return True
