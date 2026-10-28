"""
Universal Death Counter — application entry point.

Run with:
    python -m src.app
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from src.ui.main_window import MainWindow
from src.utils.constants import APP_NAME, APP_ORG, ICONS_DIR
from src.utils.logger import get_logger
from src.utils.startup import refresh_registration

logger = get_logger(__name__)


def main() -> int:
    """Launch the Universal Death Counter application."""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)

    icon_path = ICONS_DIR / "app_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    try:
        window = MainWindow()
    except Exception:  # noqa: BLE001 - top-level guard for a clean error dialog
        logger.exception("Fatal error during application startup")
        QMessageBox.critical(
            None,
            "Startup Error",
            "Universal Death Counter failed to start. Check saves/logs/app.log for details.",
        )
        return 1

    refresh_registration()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
