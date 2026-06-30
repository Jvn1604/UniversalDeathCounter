"""
Theme loading and application.

Adding a new theme is a two-step process: drop a ``<name>.qss`` file into
``src/themes/`` and add ``<name>`` to ``AVAILABLE_THEMES`` in
``src/utils/constants.py``. No other code changes are required.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from src.utils.constants import AVAILABLE_THEMES, THEMES_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)


def load_stylesheet(theme_name: str) -> str:
    """
    Load a theme's QSS stylesheet text from disk.

    Args:
        theme_name: One of :data:`AVAILABLE_THEMES`. Falls back to "dark"
            if the name is unrecognized or the file is missing.

    Returns:
        The raw QSS stylesheet contents.
    """
    if theme_name not in AVAILABLE_THEMES:
        logger.warning("Unknown theme '%s'; falling back to 'dark'", theme_name)
        theme_name = "dark"

    qss_path = THEMES_DIR / f"{theme_name}.qss"
    try:
        return qss_path.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to load theme file %s", qss_path)
        return ""


def apply_theme(widget: QWidget, theme_name: str) -> None:
    """
    Apply a theme's stylesheet to a widget (typically the top-level window).

    Args:
        widget: The widget to style. Stylesheets cascade to children.
        theme_name: One of :data:`AVAILABLE_THEMES`.
    """
    stylesheet = load_stylesheet(theme_name)
    widget.setStyleSheet(stylesheet)
    logger.info("Applied theme '%s'", theme_name)
