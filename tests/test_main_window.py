"""Main-window behavior that needs a real (offscreen) Qt window."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


def test_first_game_selected_when_no_last_game_saved(window) -> None:
    """Regression: with no saved last game, the dropdown picked its blank separator."""
    db = window._database
    first = db.create_game("Elden Ring")
    db.create_game("Hollow Knight")
    db.set_setting("last_game_id", "")
    window._reload_games()
    assert window._counter_manager.current_game_id == first
    assert window._game_combo.currentText() == "Elden Ring"


def test_last_game_restored(window) -> None:
    db = window._database
    db.create_game("Elden Ring")
    second = db.create_game("Hollow Knight")
    db.set_setting("last_game_id", second)
    window._reload_games()
    assert window._game_combo.currentText() == "Hollow Knight"


def test_window_uses_new_branding(window) -> None:
    from src.utils.constants import APP_NAME

    assert APP_NAME == "DePhantom Universal Death Counter"
    assert window.windowTitle() == APP_NAME
    assert window._overlay.windowTitle() == "DUDC Overlay"


class _StrictTray:
    """Stands in for QSystemTrayIcon with showMessage's real 4-argument signature."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, title, message, icon, msecs) -> None:  # noqa: N802
        assert isinstance(title, str) and isinstance(message, str)
        assert isinstance(msecs, int)
        self.messages.append(message)


def test_tray_notifications_use_valid_arguments(window) -> None:
    """Regression: stray extra arguments made every tray notification raise TypeError."""
    tray = _StrictTray()
    real_tray, window._tray = window._tray, tray
    window._toggle_detection_pause()
    window._toggle_detection_pause()
    window._on_update_available("9.9.9", "https://example.invalid")
    assert tray.messages[:2] == ["Auto-detect paused", "Auto-detect resumed"]
    window._tray = real_tray
    assert "9.9.9" in tray.messages[2]


def test_auto_detect_window_shows_rows_for_the_chosen_method(window) -> None:
    from src.ui.auto_detect_window import AutoDetectWindow
    from src.utils.constants import DETECTION_MODE_HEALTH, DETECTION_MODE_LOG

    game_id = window._database.create_game("Minecraft")
    dialog = AutoDetectWindow(window._database, game_id, "Minecraft", parent=window)
    dialog.show()
    combo = dialog._mode_combo
    combo.setCurrentIndex(combo.findData(DETECTION_MODE_LOG))
    assert dialog._log_row.isVisible() and dialog._pattern_row.isVisible()
    assert not dialog._health_row.isVisible() and not dialog._screens_row.isVisible()
    combo.setCurrentIndex(combo.findData(DETECTION_MODE_HEALTH))
    assert dialog._health_row.isVisible() and dialog._screens_row.isVisible()
    assert not dialog._log_row.isVisible()
    dialog.close()


def test_log_mode_saves_and_starts_the_log_watcher(window, tmp_path) -> None:
    from src.ui.auto_detect_window import AutoDetectWindow
    from src.utils.constants import DETECTION_MODE_LOG

    log = tmp_path / "latest.log"
    log.write_text("", encoding="utf-8")
    db = window._database
    game_id = db.create_game("Minecraft")
    window._reload_games(select_game_id=game_id)
    dialog = AutoDetectWindow(db, game_id, "Minecraft", parent=window)
    dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData(DETECTION_MODE_LOG))
    dialog._log_edit.setText(str(log))
    dialog._pattern_edit.setText("Steve died")
    dialog._save()  # no .exe needed in log mode
    assert db.get_game_detection(game_id)["mode"] == DETECTION_MODE_LOG
    assert db.get_detection_options(game_id)["log_pattern"] == "Steve died"

    window._configure_detection()
    config = window._log_watcher._config
    assert config is not None and config.game_id == game_id
    assert window._death_watcher._config is None  # no screen capture in log mode
    window._detection_paused = True
    window._configure_detection()
    assert window._log_watcher._config is None


def test_overlay_is_a_normal_owned_window_so_obs_can_list_it(window) -> None:
    """Regression: as a Qt.Tool window the overlay was missing from OBS's Window Capture."""
    from PySide6.QtCore import Qt

    assert window._overlay.windowType() == Qt.WindowType.Window  # was Qt.Tool
    owner = window._overlay.parentWidget()
    assert owner is not None and not owner.isVisible()  # keeps it off the taskbar


def test_next_and_previous_boss_skip_defeated(window) -> None:
    db = window._database
    game_id = db.create_game("Dark Souls")
    first = db.create_boss(game_id, "Asylum Demon")
    second = db.create_boss(game_id, "Taurus Demon")
    third = db.create_boss(game_id, "Bell Gargoyles")
    db.set_boss_defeated(second, True)
    window._reload_games(select_game_id=game_id)
    window._boss_combo.setCurrentIndex(window._boss_combo.findData(first))
    window._select_adjacent_boss(+1)
    assert window._counter_manager.current_boss_id == third
    window._select_adjacent_boss(+1)  # last boss: stays put
    assert window._counter_manager.current_boss_id == third
    window._select_adjacent_boss(-1)
    assert window._counter_manager.current_boss_id == first
    window._select_adjacent_boss(-1)
    assert window._counter_manager.current_boss_id is None  # "(No Boss)"


def test_counter_labels_name_each_count(window) -> None:
    db = window._database
    game_id = db.create_game("Dark Souls")
    window._reload_games(select_game_id=game_id)
    window._on_increment()
    assert window._counter_caption.text() == "DEATHS THIS SESSION"
    assert window._tile_session.value.text() == "1"
    assert window._tile_boss.value.text() == "–"  # no boss selected
    assert window._tile_total.value.text() == "1"
    db.set_setting("overlay_counter_source", "total")
    window._refresh_counters()
    assert window._counter_caption.text() == "ALL-TIME DEATHS"


def test_profile_box_lists_profiles(window) -> None:
    assert window._profile_combo.currentText() == window._profile_manager.active_profile
    window._profile_manager.create_profile("Streaming")
    window._rebuild_profile_menu()
    items = [window._profile_combo.itemText(i) for i in range(window._profile_combo.count())]
    assert "Streaming" in items


def test_custom_ui_colors_apply() -> None:
    from src.themes.theme_manager import customize_stylesheet, load_stylesheet

    base = load_stylesheet("dark")
    custom = customize_stylesheet(base, "dark", "#7fd1ff", "#00ff88")
    assert "color: #ececf1;" not in custom
    assert "color: #7fd1ff;" in custom
    assert custom.rstrip().endswith("QLabel#CounterLabel { color: #00ff88; }")
    assert "color: #ffffff;" in custom  # text on red buttons stays readable
    assert customize_stylesheet(base, "dark") == base


def test_timeline_has_a_point_per_change(window) -> None:
    db = window._database
    game_id = db.create_game("Dark Souls")
    window._reload_games(select_game_id=game_id)
    for _ in range(3):
        window._on_increment()
    window._counter_manager.reset_total()
    assert [row["delta"] for row in db.get_total_timeline(game_id)] == [1, 1, 1, -3]


def test_sidebar_switches_pages(window) -> None:
    from src.ui.main_window import (
        _PAGE_CONSOLE,
        _PAGE_DETECTION,
        _PAGE_HOME,
        _PAGE_STATS,
        _PAGE_TIMER,
    )

    assert window._pages.currentIndex() == _PAGE_HOME
    for index in (_PAGE_TIMER, _PAGE_STATS, _PAGE_DETECTION, _PAGE_CONSOLE, _PAGE_HOME):
        window._nav_buttons[index].click()
        assert window._pages.currentIndex() == index
        assert window._nav_buttons[index].isChecked()
    assert window._pages.count() == 5


def test_stats_page_shows_this_games_numbers(window) -> None:
    from src.ui.main_window import _PAGE_STATS

    db = window._database
    game_id = db.create_game("Elden Ring")
    margit = db.create_boss(game_id, "Margit")
    db.create_boss(game_id, "Godrick")
    window._reload_games(select_game_id=game_id)
    window._boss_combo.setCurrentIndex(window._boss_combo.findData(margit))
    window._on_increment()
    window._on_increment()
    window._show_page(_PAGE_STATS)
    tiles = window._stat_tiles
    assert tiles["total"].value.text() == "2"
    assert tiles["today"].value.text() == "2"
    assert tiles["bosses"].value.text() == "0 / 2"
    assert tiles["worst"].value.text() == "2" and "MARGIT" in tiles["worst"].caption.text()
    assert window._recent_list.count() == 2
    window._on_increment()  # the open page follows new deaths
    assert tiles["total"].value.text() == "3"


def test_detection_status_shows_on_both_pages(window) -> None:
    from src.ui.main_window import _PAGE_DETECTION

    window._detect_status_label.setText("Watching game.exe for deaths")
    assert window._detect_status_label_mirror.text() == "Watching game.exe for deaths"
    assert window._detect_status_label.property("state") == "active"
    window._detect_status_label.setText("Capture of game.exe is black.")
    assert window._detect_status_label_mirror.property("state") == "warning"
    window._toggle_detection_pause()
    assert window._pause_btn_detect.text() == window._pause_btn.text() == " Resume"
    window._toggle_detection_pause()
    db = window._database
    game_id = db.create_game("Elden Ring")
    window._reload_games(select_game_id=game_id)
    window._show_page(_PAGE_DETECTION)
    assert "0 death" in window._detect_page_info.text()


def test_timer_page_mirrors_the_timer(window) -> None:
    from src.ui.main_window import _PAGE_TIMER

    db = window._database
    game_id = db.create_game("Elden Ring")
    db.set_speedrun_splits(game_id, ["Margit", "Godrick"])
    window._reload_games(select_game_id=game_id)
    window._show_page(_PAGE_TIMER)
    assert "FIRST SPLIT: MARGIT" in window._timer_page_split.text()
    window._timer_action("split")
    assert window._timer_page_split.text() == "NOW: MARGIT"
    assert window._page_timer.isActive() and window._page_timer.interval() == 50
    window._show_page(0)
    assert not window._page_timer.isActive()  # no ticking while hidden
