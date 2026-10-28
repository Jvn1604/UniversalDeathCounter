"""
Regenerate the README screenshots in docs/screenshots/ from the real UI.

Run from the project root (Windows, so real fonts are used):
    python packaging/make_screenshots.py

Uses a throwaway data folder filled with demo data, so your own saves are
never touched.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
sys.path.insert(0, str(ROOT))

import src.utils.constants as constants  # noqa: E402

_tmp = Path(tempfile.mkdtemp())
constants.SAVES_DIR = _tmp
constants.DATABASE_PATH = _tmp / "death_counter.db"
constants.LOG_DIR = _tmp / "logs"
constants.LOG_FILE = _tmp / "logs" / "app.log"

from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

import src.utils.profiles as profiles  # noqa: E402

profiles.SAVES_DIR, profiles.DATABASE_PATH = _tmp, _tmp / "death_counter.db"
profiles.ProfileManager.__init__.__defaults__ = (_tmp,)

from src.themes.theme_manager import apply_theme  # noqa: E402
from src.ui import main_window as mw  # noqa: E402
from src.ui.auto_detect_window import AutoDetectWindow  # noqa: E402
from src.ui.obs_guide_window import ObsGuideWindow  # noqa: E402
from src.ui.settings_window import SettingsWindow  # noqa: E402
from src.ui.statistics_window import StatisticsWindow  # noqa: E402

DEMO_BOSSES = [  # (boss, deaths, defeated)
    ("Margit, the Fell Omen", 14, True),
    ("Godrick the Grafted", 9, True),
    ("Rennala, Queen of the Full Moon", 6, True),
    ("Starscourge Radahn", 22, True),
    ("Malenia, Blade of Miquella", 57, False),
]


def _seed(db) -> tuple[int, int]:
    game = db.create_game("Elden Ring")
    malenia = None
    for name, deaths, defeated in DEMO_BOSSES:
        boss = db.create_boss(game, name)
        session = db.start_session(game)
        for _ in range(deaths):
            db.add_death_event(game, boss, session, +1)
        db.end_session(session)
        if defeated:
            db.set_boss_defeated(boss, True)
        else:
            malenia = boss
    db.create_game("Hollow Knight")
    db.set_game_detection(game, r"C:\Games\ELDEN RING\Game\eldenring.exe", "souls")
    db.set_setting("last_game_id", game)
    db.set_setting("last_boss_id", malenia)
    db.set_setting("pad_increment", "back+dpad_up")
    db.set_setting("pad_undo", "back+dpad_down")
    return game, malenia


def _settle() -> None:
    """Let freshly shown pages finish laying out before grabbing them."""
    for _ in range(5):
        QApplication.processEvents()
        time.sleep(0.05)


def _save(widget, name: str) -> None:
    _settle()
    widget.grab().save(str(OUT / name))
    print("saved", name)


def _save_on_backdrop(widget, name: str) -> None:
    """The overlay is translucent: show it over a dark, game-like backdrop."""
    QApplication.processEvents()
    shot = widget.grab()
    canvas = QPixmap(shot.width() + 80, shot.height() + 80)
    painter = QPainter(canvas)
    gradient = QLinearGradient(0, 0, canvas.width(), canvas.height())
    gradient.setColorAt(0, QColor("#2b1a12"))
    gradient.setColorAt(0.5, QColor("#3a2a1c"))
    gradient.setColorAt(1, QColor("#121a24"))
    painter.fillRect(canvas.rect(), gradient)
    painter.drawPixmap(40, 40, shot)
    painter.end()
    canvas.save(str(OUT / name))
    print("saved", name)


def main() -> int:
    app = QApplication(sys.argv)
    OUT.mkdir(parents=True, exist_ok=True)

    window = mw.MainWindow()
    db = window._database
    game, _ = _seed(db)
    window._reload_games()
    window._session_manager.start_new_session(game)
    for _ in range(3):
        window._on_increment()
    window._detect_status_label.setText("Watching eldenring.exe for deaths")
    window._detect_last_label.setText("Death auto-counted at 21:04:12 (F11 to undo)")
    window.resize(1000, 680)
    window.show()
    _save(window, "main-window.png")
    window._show_page(2)  # Stats
    _save(window, "dashboard-stats.png")
    window._show_page(0)

    overlay = window._overlay
    overlay.resize(300, 170)
    overlay.show()
    _save_on_backdrop(overlay, "overlay-dark.png")
    db.set_setting("overlay_bg_mode", "chroma")
    window._apply_saved_settings()
    _save(overlay, "overlay-chroma.png")
    db.set_setting("overlay_bg_mode", "dark")
    window._apply_saved_settings()
    overlay.hide()

    stats = StatisticsWindow(db, window._statistics_service, game, "Elden Ring", parent=window)
    apply_theme(stats, "dark")
    stats.resize(820, 560)
    stats.show()
    stats.findChild(QTabWidget).setCurrentIndex(1)
    _save(stats, "statistics.png")
    stats.close()

    setup = AutoDetectWindow(db, game, "Elden Ring", parent=window)
    apply_theme(setup, "dark")
    setup.show()
    _save(setup, "auto-detect.png")
    setup.close()

    settings = SettingsWindow(db, gamepad=None, hotkeys=None, parent=window)
    apply_theme(settings, "dark")
    settings.show()
    settings.resize(620, 720)
    settings.findChild(QTabWidget).setCurrentIndex(3)  # Controls
    _save(settings, "controls.png")
    settings.close()

    guide = ObsGuideWindow(
        "Ctrl+F12", Path(r"C:\Program Files\DUDC\saves\deaths.txt"), lambda: None, lambda: None,
        parent=window,
    )
    apply_theme(guide, "dark")
    guide.show()
    _save(guide, "obs-guide.png")
    guide.close()

    window._quit_app()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
