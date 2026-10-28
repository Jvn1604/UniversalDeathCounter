"""Unit tests for automatic death detection: matchers, debouncing, and
per-game detection config storage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.database import Database  # noqa: E402
from src.detection.game_window import exe_display_name  # noqa: E402
from src.detection.matchers import (  # noqa: E402
    AnyMatcher,
    DeathDebouncer,
    DeathTemplate,
    SoulsPresetMatcher,
    TemplateMatcher,
    build_matcher,
    resize_area,
)
from src.utils.constants import (  # noqa: E402
    DETECTION_MODE_OFF,
    DETECTION_MODE_SOULS,
    DETECTION_MODE_TEMPLATE,
)

TEXT_REGION = (0.30, 0.45, 0.40, 0.10)


@pytest.fixture()
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def _gameplay_frame(seed: int, height: int = 360, width: int = 640) -> np.ndarray:
    """A busy, random 'gameplay' frame in muted (non-red) colors."""
    rng = np.random.default_rng(seed)
    gray = rng.integers(30, 160, size=(height // 8, width // 8), dtype=np.uint8)
    gray = np.kron(gray, np.ones((8, 8), dtype=np.uint8))
    return np.stack([gray, gray, gray], axis=-1)


def _draw_death_text(frame: np.ndarray, color=(170, 25, 25)) -> np.ndarray:
    """Paint a fake 'YOU DIED': a dark band with blocky glyphs in the centre."""
    out = frame.copy()
    height, width = out.shape[:2]
    out[int(height * 0.42) : int(height * 0.58), :] //= 4  # dark banner
    top, bottom = int(height * 0.46), int(height * 0.54)
    for i in range(8):  # eight glyphs with gaps between them
        left = int(width * (0.32 + i * 0.045))
        out[top:bottom, left : left + int(width * 0.03)] = color
    return out


# ----------------------------------------------------------------
# Image helpers
# ----------------------------------------------------------------
def test_resize_area_averages_blocks() -> None:
    image = np.array([[0, 0, 100, 100], [0, 0, 100, 100]], dtype=np.float32)
    assert resize_area(image, 1, 2).tolist() == [[0.0, 100.0]]


# ----------------------------------------------------------------
# Template matcher (any game)
# ----------------------------------------------------------------
def test_template_matches_same_death_screen_over_different_backgrounds() -> None:
    template = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    matcher = TemplateMatcher(template)

    matched, score = matcher.match(_draw_death_text(_gameplay_frame(2)))
    assert matched, score


def test_template_matches_dimmer_fade_in() -> None:
    template = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    faded = (_draw_death_text(_gameplay_frame(3)).astype(np.float32) * 0.5).astype(np.uint8)
    assert TemplateMatcher(template).match(faded)[0]


def test_template_rejects_plain_gameplay() -> None:
    template = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    matcher = TemplateMatcher(template)
    for seed in range(10, 20):
        assert not matcher.match(_gameplay_frame(seed))[0]


def test_template_rejects_black_loading_screen() -> None:
    template = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    black = np.zeros((360, 640, 3), dtype=np.uint8)
    assert TemplateMatcher(template).match(black) == (False, 0.0)


def test_template_works_at_a_different_resolution() -> None:
    template = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    big = _draw_death_text(_gameplay_frame(4, height=720, width=1280))
    assert TemplateMatcher(template).match(big)[0]


def test_calibrating_a_flat_area_is_rejected() -> None:
    flat = np.full((360, 640, 3), 40, dtype=np.uint8)
    with pytest.raises(ValueError):
        DeathTemplate.from_frame(flat, TEXT_REGION)


def test_template_storage_round_trip() -> None:
    template = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    restored = DeathTemplate.from_storage(template.region_json(), template.patch_bytes())
    assert restored.region == pytest.approx(template.region)
    assert np.abs(restored.patch - template.patch).max() <= 0.5


# ----------------------------------------------------------------
# Souls preset
# ----------------------------------------------------------------
def test_souls_preset_detects_red_death_text() -> None:
    assert SoulsPresetMatcher().match(_draw_death_text(_gameplay_frame(5)))[0]


def test_souls_preset_ignores_normal_gameplay() -> None:
    assert not SoulsPresetMatcher().match(_gameplay_frame(6))[0]


def test_souls_preset_ignores_red_tinted_scenes() -> None:
    # e.g. Caelid: red everywhere, including the top/bottom of the screen.
    frame = _gameplay_frame(7)
    frame[..., 0] = np.maximum(frame[..., 0], 180)
    frame[..., 1] //= 3
    frame[..., 2] //= 3
    assert not SoulsPresetMatcher().match(frame)[0]


def test_souls_preset_ignores_white_text() -> None:
    frame = _draw_death_text(_gameplay_frame(8), color=(230, 230, 230))
    assert not SoulsPresetMatcher().match(frame)[0]


# ----------------------------------------------------------------
# Debouncer
# ----------------------------------------------------------------
def test_debouncer_needs_consecutive_frames() -> None:
    debouncer = DeathDebouncer(required_frames=3, cooldown_seconds=8)
    results = [debouncer.update(m, t) for t, m in enumerate([True, True, False, True, True])]
    assert not any(results)
    assert debouncer.update(True, 5.0)


def test_debouncer_counts_a_long_death_screen_once() -> None:
    debouncer = DeathDebouncer(required_frames=2, cooldown_seconds=1)
    fired = [debouncer.update(True, t * 0.2) for t in range(50)]
    assert fired.count(True) == 1


def test_debouncer_counts_back_to_back_deaths_after_cooldown() -> None:
    debouncer = DeathDebouncer(required_frames=1, cooldown_seconds=8)
    assert debouncer.update(True, 0.0)
    debouncer.update(False, 1.0)
    assert not debouncer.update(True, 2.0)  # within cooldown: flicker, ignored
    debouncer.update(False, 3.0)
    assert debouncer.update(True, 10.0)


# ----------------------------------------------------------------
# build_matcher + multiple death screens
# ----------------------------------------------------------------
def _stored(template: DeathTemplate) -> tuple[str, bytes]:
    return template.region_json(), template.patch_bytes()


def test_build_matcher_by_mode() -> None:
    template = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    assert build_matcher(DETECTION_MODE_OFF, [_stored(template)]) is None
    assert build_matcher(DETECTION_MODE_TEMPLATE, []) is None  # nothing saved yet
    assert isinstance(build_matcher(DETECTION_MODE_SOULS, []), SoulsPresetMatcher)
    assert isinstance(build_matcher(DETECTION_MODE_TEMPLATE, [_stored(template)]), TemplateMatcher)
    assert isinstance(build_matcher(DETECTION_MODE_SOULS, [_stored(template)]), AnyMatcher)


def test_any_saved_death_screen_matches() -> None:
    # Two different death screens: red banner text, and a white "DEFEAT" card elsewhere.
    red = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    card_region = (0.05, 0.05, 0.25, 0.15)
    card_frame = _gameplay_frame(2)
    card_frame[18:72, 32:192] = 0
    card_frame[30:60, 48:176:12] = 255  # bright glyph stripes
    card = DeathTemplate.from_frame(card_frame, card_region)
    matcher = build_matcher(DETECTION_MODE_TEMPLATE, [_stored(red), _stored(card)])

    assert matcher.match(_draw_death_text(_gameplay_frame(3)))[0]
    other_card = _gameplay_frame(4)
    other_card[18:72, 32:192] = 0
    other_card[30:60, 48:176:12] = 255
    assert matcher.match(other_card)[0]
    assert not matcher.match(_gameplay_frame(5))[0]


def test_death_templates_storage(db: Database) -> None:
    game_id = db.create_game("Hollow Knight")
    assert db.get_death_templates(game_id) == []
    template = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    db.add_death_template(game_id, *_stored(template))
    db.add_death_template(game_id, *_stored(template))
    rows = db.get_death_templates(game_id)
    assert len(rows) == 2
    assert bytes(rows[0]["template"]) == template.patch_bytes()

    # Changing the exe/mode keeps saved death screens.
    db.set_game_detection(game_id, r"C:\Games\hollow_knight.exe", DETECTION_MODE_TEMPLATE)
    db.set_game_detection(game_id, r"D:\hk\hollow_knight.exe", DETECTION_MODE_TEMPLATE)
    assert len(db.get_death_templates(game_id)) == 2
    assert db.get_game_detection(game_id)["exe_path"] == r"D:\hk\hollow_knight.exe"

    db.clear_death_templates(game_id)
    assert db.get_death_templates(game_id) == []


def test_all_game_detections_lists_only_active(db: Database) -> None:
    er = db.create_game("Elden Ring")
    hk = db.create_game("Hollow Knight")
    off = db.create_game("Celeste")
    db.set_game_detection(er, r"C:\ER\eldenring.exe", DETECTION_MODE_SOULS)
    db.set_game_detection(hk, r"C:\HK\hollow_knight.exe", DETECTION_MODE_TEMPLATE)
    db.set_game_detection(off, r"C:\Celeste\Celeste.exe", DETECTION_MODE_OFF)
    assert {row["game_id"] for row in db.get_all_game_detections()} == {er, hk}


def test_detection_data_deleted_with_game(db: Database) -> None:
    game_id = db.create_game("Cuphead")
    db.set_game_detection(game_id, r"C:\Games\Cuphead.exe", DETECTION_MODE_TEMPLATE)
    template = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    db.add_death_template(game_id, *_stored(template))
    db.delete_game(game_id)
    assert db.get_game_detection(game_id) is None
    assert db.get_death_templates(game_id) == []


def test_backup_export_stays_json_serializable(db: Database) -> None:
    game_id = db.create_game("Elden Ring")
    template = DeathTemplate.from_frame(_draw_death_text(_gameplay_frame(1)), TEXT_REGION)
    db.add_death_template(game_id, *_stored(template))
    json.dumps(db.export_data())  # must not choke on the template BLOB


# ----------------------------------------------------------------
# Game names from executables
# ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (r"C:\Games\hollow_knight.exe", "Hollow Knight"),
        (r"C:\Games\LOP-Win64-Shipping.exe", "LOP"),
        (r"C:\Games\Cuphead.exe", "Cuphead"),
    ],
)
def test_exe_display_name_falls_back_to_file_name(path: str, expected: str) -> None:
    assert exe_display_name(path) == expected  # files don't exist: no version info
