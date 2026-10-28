"""Tests for the health-bar and log-file detection modes."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.database.database import Database  # noqa: E402
from src.detection.log_watcher import LogTail, compile_death_pattern, scan_log  # noqa: E402
from src.detection.matchers import (  # noqa: E402
    AnyMatcher,
    DeathDebouncer,
    HealthBar,
    HealthBarMatcher,
    build_matcher,
)
from src.utils.constants import (  # noqa: E402
    DETECTION_MODE_HEALTH,
    DETECTION_MODE_LOG,
    DETECTION_MODE_TEMPLATE,
)

BAR_REGION = (0.05, 0.05, 0.30, 0.04)  # top-left health bar
BAR_COLOR = (200, 30, 40)


@pytest.fixture()
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def _frame_with_bar(fill: float | None, seed: int = 0) -> np.ndarray:
    """Gameplay frame with the health bar ``fill`` full (None = HUD hidden)."""
    rng = np.random.default_rng(seed)
    frame = rng.integers(40, 160, size=(360, 640, 3), dtype=np.uint8)
    frame[..., 0] //= 2  # keep the background from looking like the red bar
    if fill is None:
        return frame
    x, y, w, h = (int(round(v * s)) for v, s in zip(BAR_REGION, (640, 360, 640, 360), strict=True))
    frame[y : y + h, x : x + w] = (25, 25, 25)  # empty bar track
    frame[y : y + h, x : x + int(w * fill)] = BAR_COLOR
    return frame


def _bar() -> HealthBar:
    return HealthBar.from_frame(_frame_with_bar(1.0), BAR_REGION)


# ----------------------------------------------------------------
# Health bar
# ----------------------------------------------------------------
def test_health_bar_learns_color_and_reads_fill() -> None:
    bar = _bar()
    assert max(abs(a - b) for a, b in zip(bar.color, BAR_COLOR, strict=True)) <= 10
    assert bar.fill(_frame_with_bar(1.0, seed=3)) == pytest.approx(1.0, abs=0.03)
    assert bar.fill(_frame_with_bar(0.5, seed=4)) == pytest.approx(0.5, abs=0.05)
    assert bar.fill(_frame_with_bar(0.0, seed=5)) < HealthBarMatcher.EMPTY_FILL


def test_health_bar_rejects_dark_or_empty_selection() -> None:
    with pytest.raises(ValueError):
        HealthBar.from_frame(np.zeros((360, 640, 3), dtype=np.uint8), BAR_REGION)
    with pytest.raises(ValueError):  # mostly background, hardly any bar
        HealthBar.from_frame(_frame_with_bar(0.1), BAR_REGION)


def test_health_bar_options_round_trip() -> None:
    bar = _bar()
    restored = HealthBar.from_options(bar.to_options())
    assert restored is not None
    assert restored.color == bar.color
    assert restored.region == pytest.approx(bar.region)
    assert HealthBar.from_options({}) is None
    assert HealthBar.from_options({"health_region": "junk"}) is None


def _run(matcher: HealthBarMatcher, fills: list[float | None]) -> int:
    """Feed one frame per fill at 5 fps through the debouncer; return deaths counted."""
    debouncer = DeathDebouncer(required_frames=HealthBarMatcher.REQUIRED_FRAMES)
    deaths = 0
    for index, fill in enumerate(fills):
        matched, _ = matcher.match(_frame_with_bar(fill, seed=index))
        deaths += debouncer.update(matched, index / 5)
    return deaths


def test_bar_draining_to_empty_counts_one_death() -> None:
    fills = [1.0] * 5 + [0.7, 0.45, 0.2, 0.05] + [0.0] * 20 + [1.0] * 5
    assert _run(HealthBarMatcher(_bar()), fills) == 1


def test_menu_hiding_hud_at_high_health_does_not_count() -> None:
    fills = [1.0] * 5 + [None] * 30 + [1.0] * 5
    assert _run(HealthBarMatcher(_bar()), fills) == 0


def test_brief_low_health_blink_does_not_count() -> None:
    # Low-health bars often flash; a few empty frames are not a death.
    fills = [0.3, 0.3] + [0.3, 0.0, 0.0, 0.3] * 6
    assert _run(HealthBarMatcher(_bar()), fills) == 0


def test_two_deaths_with_respawn_count_twice() -> None:
    life = [1.0] * 5 + [0.4, 0.1] + [0.0] * 8
    respawn = [1.0] * 45  # 9 s, longer than the cooldown
    assert _run(HealthBarMatcher(_bar()), life + respawn + life) == 2


def test_build_matcher_health_mode() -> None:
    options = _bar().to_options()
    assert isinstance(build_matcher(DETECTION_MODE_HEALTH, [], options), HealthBarMatcher)
    assert build_matcher(DETECTION_MODE_HEALTH, [], {}) is None  # bar not marked yet
    assert build_matcher(DETECTION_MODE_TEMPLATE, [], options) is None
    assert build_matcher(DETECTION_MODE_LOG, [], options) is None


def test_build_matcher_health_mode_includes_death_screens() -> None:
    from src.detection.matchers import DeathTemplate

    frame = _frame_with_bar(1.0)
    frame[150:200, 200:440] = 255
    frame[165:185, 220:420] = 0
    template = DeathTemplate.from_frame(frame, (0.3, 0.4, 0.4, 0.17))
    stored = [(template.region_json(), template.patch_bytes())]
    matcher = build_matcher(DETECTION_MODE_HEALTH, stored, _bar().to_options())
    assert isinstance(matcher, AnyMatcher)
    assert matcher.match(frame)[0]


# ----------------------------------------------------------------
# Detection options storage
# ----------------------------------------------------------------
def test_detection_options_merge_and_survive_mode_changes(db: Database) -> None:
    game_id = db.create_game("Minecraft")
    assert db.get_detection_options(game_id) == {}
    db.update_detection_options(game_id, log_path="C:/latest.log", log_pattern="died")
    db.set_game_detection(game_id, "C:/javaw.exe", DETECTION_MODE_LOG)
    db.update_detection_options(game_id, log_pattern="was slain")
    assert db.get_detection_options(game_id) == {
        "log_path": "C:/latest.log",
        "log_pattern": "was slain",
    }
    db.update_detection_options(game_id, log_path=None)
    assert db.get_detection_options(game_id) == {"log_pattern": "was slain"}
    assert db.get_game_detection(game_id)["mode"] == DETECTION_MODE_LOG


def test_old_database_gets_options_column(tmp_path) -> None:
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE game_detection (game_id INTEGER PRIMARY KEY, exe_path TEXT, "
        "mode TEXT NOT NULL DEFAULT 'off')"
    )
    connection.commit()
    connection.close()
    database = Database(path)
    try:
        game_id = database.create_game("Hollow Knight")
        database.update_detection_options(game_id, log_pattern="x")
        assert database.get_detection_options(game_id) == {"log_pattern": "x"}
    finally:
        database.close()


# ----------------------------------------------------------------
# Log files
# ----------------------------------------------------------------
def _append(path: Path, text: str) -> None:
    with open(path, "a", encoding="utf-8", newline="") as handle:
        handle.write(text)


def test_log_tail_skips_existing_lines_then_reads_new_ones(tmp_path) -> None:
    log = tmp_path / "latest.log"
    log.write_text("Steve was slain by Zombie\n", encoding="utf-8")
    tail = LogTail(log)
    assert tail.poll() == []  # old deaths are not recounted
    _append(log, "Steve fell from a high place\r\nAlex joined\n")
    assert tail.poll() == ["Steve fell from a high place", "Alex joined"]
    assert tail.poll() == []


def test_log_tail_holds_partial_lines(tmp_path) -> None:
    log = tmp_path / "latest.log"
    log.write_text("", encoding="utf-8")
    tail = LogTail(log)
    tail.poll()
    _append(log, "Steve was sl")
    assert tail.poll() == []
    _append(log, "ain by Zombie\n")
    assert tail.poll() == ["Steve was slain by Zombie"]


def test_log_tail_follows_a_new_log_file(tmp_path) -> None:
    log = tmp_path / "latest.log"
    log.write_text("old session line\n" * 50, encoding="utf-8")
    tail = LogTail(log)
    tail.poll()
    # The game starts a new, shorter log on its next launch.
    log.write_text("Steve died\n", encoding="utf-8")
    assert tail.poll() == ["Steve died"]


def test_log_tail_reads_a_file_created_later_from_the_start(tmp_path) -> None:
    log = tmp_path / "latest.log"
    tail = LogTail(log)
    assert tail.poll() is None
    log.write_text("Steve died\n", encoding="utf-8")
    assert tail.poll() == ["Steve died"]


def test_log_tail_survives_invalid_utf8(tmp_path) -> None:
    log = tmp_path / "game.log"
    log.write_bytes(b"")
    tail = LogTail(log)
    tail.poll()
    with open(log, "ab") as handle:
        handle.write(b"Player died \xff\xfe\n")
    lines = tail.poll()
    assert lines is not None and lines[0].startswith("Player died")


def test_death_pattern_is_case_insensitive_and_validated() -> None:
    pattern = compile_death_pattern("steve was slain|steve died")
    assert pattern.search("[12:00:01] [CHAT] Steve was slain by Zombie")
    assert pattern.search("STEVE DIED")
    assert not pattern.search("Alex was slain by Zombie")
    for bad in ("", "   ", "(unclosed"):
        with pytest.raises(ValueError):
            compile_death_pattern(bad)


def test_scan_log_counts_matches(tmp_path) -> None:
    log = tmp_path / "latest.log"
    log.write_text("Steve died\nAlex joined\nSteve was slain\n", encoding="utf-8")
    count, last = scan_log(log, compile_death_pattern("steve (died|was slain)"))
    assert count == 2
    assert last == "Steve was slain"


def test_log_watcher_emits_death_for_new_lines(tmp_path) -> None:
    from PySide6.QtCore import QCoreApplication

    from src.detection.log_watcher import LogWatchConfig, LogWatcher

    app = QCoreApplication.instance()
    log = tmp_path / "latest.log"
    log.write_text("Steve died long ago\n", encoding="utf-8")
    watcher = LogWatcher()
    deaths: list[int] = []
    watcher.death_detected.connect(deaths.append)
    watcher.configure(
        LogWatchConfig(game_id=7, log_path=str(log), pattern=compile_death_pattern("died"))
    )
    try:
        import time

        time.sleep(0.8)  # first poll skips the existing line
        _append(log, "Steve died\n")
        deadline = time.monotonic() + 5
        while not deaths and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.05)
    finally:
        watcher.stop()
    assert deaths == [7]
