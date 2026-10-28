"""Boss-kill detection: victory screens, marking defeated, next boss, auto-split."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.database.database import SCREEN_DEATH, SCREEN_VICTORY  # noqa: E402
from src.detection.matchers import DeathTemplate, build_screen_matcher  # noqa: E402

BANNER_REGION = (0.25, 0.42, 0.5, 0.16)


def _frame(text_pattern: int, seed: int = 0) -> np.ndarray:
    """Gameplay with a banner whose 'letters' depend on ``text_pattern``."""
    rng = np.random.default_rng(seed)
    frame = rng.integers(40, 160, size=(360, 640, 3), dtype=np.uint8)
    frame[150:210, 160:480] = 20  # dark banner strip
    pattern = np.random.default_rng(text_pattern).integers(0, 2, size=(4, 24)).astype(bool)
    for row in range(4):
        for col in range(24):
            if pattern[row, col]:
                y, x = 160 + row * 10, 170 + col * 12
                frame[y : y + 8, x : x + 10] = (215, 180, 90)  # gold letters
    return frame


def _template(pattern: int) -> tuple[str, bytes]:
    template = DeathTemplate.from_frame(_frame(pattern), BANNER_REGION)
    return template.region_json(), template.patch_bytes()


def test_victory_template_matches_its_banner_but_not_other_banners() -> None:
    """'GREAT ENEMY FELLED' must not fire on 'LOST GRACE DISCOVERED' in the same style."""
    matcher = build_screen_matcher([_template(pattern=1)])
    assert matcher.match(_frame(1, seed=7))[0]  # same banner, other background
    assert not matcher.match(_frame(2, seed=7))[0]  # different words
    assert not matcher.match(np.random.default_rng(3).integers(40, 160, (360, 640, 3)).astype(
        np.uint8
    ))[0]
    assert build_screen_matcher([]) is None


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    yield win
    win._quit_app()
    app.processEvents()


def _game_with_bosses(window, bosses=("Margit", "Godrick", "Rennala")):
    db = window._database
    game_id = db.create_game("Elden Ring")
    ids = [db.create_boss(game_id, name) for name in bosses]
    db.set_game_detection(game_id, "C:/Games/eldenring.exe", "off")
    window._reload_games(select_game_id=game_id)
    window._boss_combo.setCurrentIndex(window._boss_combo.findData(ids[0]))
    return game_id, ids


def test_detected_kill_marks_defeated_and_selects_next_boss(window) -> None:
    db = window._database
    game_id, (margit, godrick, _) = _game_with_bosses(window)
    for _ in range(3):
        window._on_increment()
    window._on_boss_victory_detected(game_id)
    boss = db.get_boss(margit)
    assert boss["defeated"] and boss["deaths_at_defeat"] == 3
    assert window._counter_manager.current_boss_id == godrick
    assert "Margit defeated after 3 deaths" in window._detect_last_label.text()
    assert window._boss_combo.itemText(window._boss_combo.findData(margit)).startswith("✓")

    window._on_boss_victory_detected(game_id + 1)  # another game: ignored
    assert not db.get_boss(godrick)["defeated"]


def test_kill_splits_a_running_speedrun(window) -> None:
    db = window._database
    game_id, (margit, _, _) = _game_with_bosses(window)
    db.set_speedrun_splits(game_id, ["Margit", "Godrick", "Rennala"])
    window._load_speedrun(force=True)
    window._action_handlers["timer_split"]()  # start
    window._on_boss_victory_detected(game_id)
    assert len(window._speedrun.timer.split_times) == 1


def test_auto_advance_and_auto_split_can_be_turned_off(window) -> None:
    db = window._database
    db.set_setting("boss_auto_advance", "false")
    db.set_setting("boss_auto_split", "false")
    game_id, (margit, _, _) = _game_with_bosses(window)
    db.set_speedrun_splits(game_id, ["Margit", "Godrick", "Rennala"])
    window._load_speedrun(force=True)
    window._action_handlers["timer_split"]()
    window._on_boss_victory_detected(game_id)
    assert db.get_boss(margit)["defeated"]
    assert window._counter_manager.current_boss_id == margit  # stayed
    assert window._speedrun.timer.split_times == []  # no split


def test_boss_defeated_key_and_repeats(window) -> None:
    db = window._database
    game_id, (margit, godrick, rennala) = _game_with_bosses(window)
    window._action_handlers["boss_defeated"]()
    window._action_handlers["boss_defeated"]()
    assert db.get_boss(margit)["defeated"] and db.get_boss(godrick)["defeated"]
    assert window._counter_manager.current_boss_id == rennala
    window._boss_combo.setCurrentIndex(0)  # "(No Boss)"
    window._action_handlers["boss_defeated"]()  # nothing to mark
    assert not db.get_boss(rennala)["defeated"]


def test_victory_watching_follows_the_selected_boss(window) -> None:
    from src.detection.game_window import detection_available

    db = window._database
    game_id, (margit, _, _) = _game_with_bosses(window)
    row = db.get_game_detection(game_id)
    assert window._victory_matcher(game_id, row) is None  # no victory screen saved yet
    region, patch = _template(pattern=1)
    db.add_death_template(game_id, region, patch, SCREEN_VICTORY)
    assert len(db.get_death_templates(game_id, SCREEN_DEATH)) == 0  # kept apart
    if detection_available():
        assert window._victory_matcher(game_id, row) is not None
        window._configure_detection()
        assert window._death_watcher._config.victory_matcher is not None
    window._boss_combo.setCurrentIndex(0)  # no boss: nothing to watch for
    assert window._victory_matcher(game_id, row) is None
    window._boss_combo.setCurrentIndex(window._boss_combo.findData(margit))
    db.set_setting("boss_detection", "false")
    assert window._victory_matcher(game_id, row) is None


def test_capture_dialog_switches_to_victory(window) -> None:
    from src.ui.auto_detect_window import DeathScreenDialog

    dialog = DeathScreenDialog([], parent=window)
    assert dialog.kind == SCREEN_DEATH
    dialog._kind_combo.setCurrentIndex(dialog._kind_combo.findData(SCREEN_VICTORY))
    assert "boss defeated" in dialog._count_check.text()
    dialog.close()


def test_boss_settings_round_trip(window) -> None:
    from src.ui.settings_window import SettingsWindow

    db = window._database
    dialog = SettingsWindow(db)
    assert all(check.isChecked() for check in dialog._boss_checks.values())
    dialog._boss_checks["boss_auto_split"].setChecked(False)
    assert dialog._apply()
    assert db.get_setting("boss_auto_split") == "false"
    assert db.get_setting("boss_detection") == "true"
    dialog.close()
