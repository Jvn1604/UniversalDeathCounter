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
