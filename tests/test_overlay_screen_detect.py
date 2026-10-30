"""
Release 2: the overlay keeps showing when Always on Top is turned off, gets
a transparent background and more options, and detection can watch a whole
display when the game's .exe isn't found.
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

from src.core.counter_manager import CounterSnapshot  # noqa: E402
from src.detection import death_watcher as dw  # noqa: E402
from src.detection.matchers import DeathTemplate, TemplateMatcher  # noqa: E402

REGION = (0.30, 0.40, 0.40, 0.15)


# ---------------------------------------------------------------- overlay
@pytest.fixture()
def overlay():
    from PySide6.QtWidgets import QApplication

    from src.overlay.overlay_window import OverlayWindow

    app = QApplication.instance() or QApplication([])
    window = OverlayWindow()
    yield window
    window.close()
    app.processEvents()


def test_turning_always_on_top_off_keeps_the_overlay_shown(overlay) -> None:
    from PySide6.QtCore import Qt

    overlay.show()
    overlay.move(120, 80)
    shown: list[bool] = []
    overlay.visibility_changed.connect(shown.append)
    overlay.set_always_on_top(False)
    assert overlay.isVisible()
    assert not overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert shown[-1] is True  # the sidebar's tag ends up ON again
    assert overlay.pos().x() == 120
    overlay.set_always_on_top(True)
    assert overlay.isVisible()


def test_click_through_keeps_the_overlay_shown(overlay) -> None:
    from PySide6.QtCore import Qt

    overlay.show()
    overlay.set_click_through(True)
    assert overlay.isVisible()
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    overlay.set_click_through(False)
    assert not overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput


def test_transparent_background_and_text_options(overlay) -> None:
    from PySide6.QtGui import QImage

    snapshot = CounterSnapshot("Elden Ring", "Margit", 3, 12, 1)
    overlay.update_counters(snapshot)
    overlay.apply_display_settings({
        "overlay_bg_mode": "transparent",
        "overlay_count_label": "",
        "overlay_show_caption": "false",
        "overlay_align": "center",
        "overlay_counter_source": "total",
    })
    assert overlay._death_label.text() == "12"  # no text before the number
    assert overlay._caption_label.isHidden()
    image = QImage(overlay.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    overlay.render(image)
    corner = image.pixelColor(2, 2)
    assert corner.alpha() <= 2  # no card: (almost) fully see-through, still clickable
    overlay.apply_display_settings({"overlay_count_label": "TRIES"})
    assert overlay._death_label.text().startswith("TRIES - ")


# ---------------------------------------------------------------- whole-display detection
class _FakeScreen:
    """Two displays side by side; the second shows a death screen once ``dead`` is set."""

    def __init__(self) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 1600, "height": 600},
            {"left": 0, "top": 0, "width": 800, "height": 600},
            {"left": 800, "top": 0, "width": 800, "height": 600},
        ]
        rng = np.random.default_rng(5)
        self.screen = (rng.random((600, 1600, 4)) * 40).astype(np.uint8) + 30
        self.grabs: list[dict] = []

    def show_death(self) -> None:
        x0, y0 = 800 + int(0.30 * 800), int(0.40 * 600)
        w, h = int(0.40 * 800), int(0.15 * 600)
        self.screen[y0 : y0 + h, x0 : x0 + w // 2, :3] = 230
        self.screen[y0 : y0 + h, x0 + w // 2 : x0 + w, :3] = 10

    def grab(self, area: dict) -> np.ndarray:
        self.grabs.append(area)
        x, y = area["left"], area["top"]
        return self.screen[y : y + area["height"], x : x + area["width"]]


def test_a_whole_display_is_watched_without_the_exe(monkeypatch) -> None:
    from PySide6.QtCore import Qt

    def no_exe(*_args, **_kwargs):
        raise AssertionError("no .exe lookups when watching a display")

    monkeypatch.setattr(dw, "find_process_ids", no_exe)
    monkeypatch.setattr(dw, "FRAMES_PER_SECOND", 50.0)
    screen = _FakeScreen()
    reference = _FakeScreen()
    reference.show_death()
    frame = np.ascontiguousarray(reference.screen[:, 800:1600, 2::-1])
    matcher = TemplateMatcher(DeathTemplate.from_frame(frame, REGION))
    watcher = dw.DeathWatcher(cooldown_seconds=0.0)
    deaths: list[int] = []
    statuses: list[str] = []
    watcher.death_detected.connect(deaths.append, Qt.ConnectionType.DirectConnection)
    watcher.status_changed.connect(statuses.append, Qt.ConnectionType.DirectConnection)
    watcher.configure(
        dw.WatchConfig(game_id=3, exe_path="", matcher=matcher, screen_display=2)
    )

    def run(seconds: float) -> None:
        watcher._stop_event.clear()
        thread = threading.Thread(target=watcher._watch_loop, args=(screen,), daemon=True)
        thread.start()
        time.sleep(seconds)
        watcher._stop_event.set()
        thread.join(2)

    run(0.4)
    assert deaths == []
    assert any(s == "Watching Display 2 for deaths" for s in statuses)
    assert all(area["left"] >= 800 for area in screen.grabs)  # only display 2
    screen.show_death()
    run(0.6)
    assert deaths and deaths[0] == 3


def test_display_rect_falls_back_to_the_first_display() -> None:
    from src.detection.game_window import display_rect

    screen = _FakeScreen()
    assert display_rect(screen, 2) == (800, 0, 800, 600)
    assert display_rect(screen, 9) == (0, 0, 800, 600)  # unplugged: the first one


def test_main_window_watches_the_chosen_display(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles
    from src.utils.constants import DETECTION_MODE_TEMPLATE, OPTION_SCREEN_DISPLAY

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    monkeypatch.setattr(mw, "detection_available", lambda: True)
    app = QApplication.instance() or QApplication([])
    window = mw.MainWindow()
    try:
        configs: list = []
        monkeypatch.setattr(
            window._death_watcher, "configure", lambda config, **_k: configs.append(config)
        )
        db = window._database
        game = db.create_game("Cloud Game")
        db.set_game_detection(game, None, DETECTION_MODE_TEMPLATE)
        db.update_detection_options(game, **{OPTION_SCREEN_DISPLAY: 2})
        window._reload_games(select_game_id=game)
        window._configure_detection()
        assert configs[-1] is not None and configs[-1].screen_display == 2
        window._show_page(mw._PAGE_DETECTION)
        assert "Display 2 (no .exe)" in window._detect_page_info.text()

        # Capturing the death screen (F8) mustn't then ask for the .exe.
        from src.detection.matchers import DeathTemplate

        asked: list = []
        monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: asked.append(a))
        monkeypatch.setattr(window, "_open_auto_detect_window", lambda: asked.append("setup"))
        frame = np.zeros((90, 160, 3), dtype=np.uint8)
        frame[40:60, 50:110] = 220
        window._save_death_template(game, DeathTemplate.from_frame(frame, REGION))
        assert asked == []
        assert len(db.get_death_templates(game)) == 1
    finally:
        window._quit_app()
        app.processEvents()


def test_setup_saves_a_display_without_an_exe(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    import src.ui.auto_detect_window as adw
    from src.database.database import Database
    from src.utils.constants import DETECTION_MODE_TEMPLATE, OPTION_SCREEN_DISPLAY

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(adw, "list_displays", lambda: [(1, "Display 1"), (2, "Display 2")])
    monkeypatch.setattr(adw.QMessageBox, "information", lambda *a, **k: None)
    db = Database(tmp_path / "d.db")
    game = db.create_game("Emulated Game")
    dialog = adw.AutoDetectWindow(db, game, "Emulated Game")
    dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData(DETECTION_MODE_TEMPLATE))
    dialog._source_combo.setCurrentIndex(1)  # A whole display
    dialog._display_combo.setCurrentIndex(1)  # Display 2
    dialog._save()
    assert dialog.result() == adw.AutoDetectWindow.DialogCode.Accepted
    assert db.get_detection_options(game)[OPTION_SCREEN_DISPLAY] == 2
    assert db.get_game_detection(game)["mode"] == DETECTION_MODE_TEMPLATE
    reopened = adw.AutoDetectWindow(db, game, "Emulated Game")
    assert reopened._source_combo.currentData() == "display"
    assert reopened._display_combo.currentData() == 2
    db.close()
