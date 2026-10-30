"""
DePhantom Universal Death Counter (DUDC): application entry point.

Run with:
    python -m src.app
"""

from __future__ import annotations

import faulthandler
import os
import sys
from types import TracebackType

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from src.ui.main_window import MainWindow
from src.utils import single_instance
from src.utils.constants import APP_NAME, APP_ORG, ICONS_DIR, LOG_DIR
from src.utils.logger import get_logger
from src.utils.platform_info import has_x11_display
from src.utils.startup import refresh_registration

logger = get_logger(__name__)


def _install_crash_logging() -> None:
    """
    Record crashes in the log folder instead of losing them.

    Python errors go to app.log (and the app keeps running); hard crashes
    inside Qt or Windows are written to crash.log by faulthandler. A run in
    progress is auto-saved separately, and offered back on the next start.
    """

    def log_uncaught(
        kind: type[BaseException], error: BaseException, trace: TracebackType | None
    ) -> None:
        logger.critical("Unhandled error", exc_info=(kind, error, trace))
        sys.__excepthook__(kind, error, trace)

    sys.excepthook = log_uncaught
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Kept open for the app's lifetime: faulthandler writes to it on a crash.
        crash_log = open(LOG_DIR / "crash.log", "a", encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(crash_log)
    except OSError:
        logger.warning("Could not open crash.log; hard crashes won't be recorded")


def _prefer_x11() -> None:
    """
    Linux: run through X11 (XWayland on Wayland desktops) when it's there.

    Wayland doesn't let an app keep its overlay on top, place its windows or
    use global hotkeys; under X11 all of that works, and games running
    through Proton are X11 windows too. Falls back to Wayland if X11 can't
    load, and a QT_QPA_PLATFORM the player set themselves always wins.
    """
    if has_x11_display() and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"


def main() -> int:
    """Launch the DePhantom Universal Death Counter application."""
    _install_crash_logging()
    _prefer_x11()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)

    icon_path = ICONS_DIR / "app_icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    if not single_instance.acquire():
        logger.info("Another copy is already running; handing over to it")
        if not single_instance.bring_existing_to_front(APP_NAME):
            QMessageBox.information(
                None,
                APP_NAME,
                f"{APP_NAME} is already running. Open it from its icon in the "
                "system tray (the menu bar on a Mac).",
            )
        return 0

    try:
        window = MainWindow()
    except Exception:  # noqa: BLE001 - top-level guard for a clean error dialog
        logger.exception("Fatal error during application startup")
        QMessageBox.critical(
            None,
            "Startup Error",
            f"{APP_NAME} failed to start. Check saves/logs/app.log for details.",
        )
        return 1

    single_instance.listen_for_others(window.bring_to_front)
    refresh_registration()
    window.show()
    QTimer.singleShot(400, window.maybe_show_welcome)  # first run: the guide
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
