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


# Each theme's main text color, swapped for the player's own text color.
_THEME_TEXT_COLORS: dict[str, str] = {
    "dark": "#e8e8e8",
    "light": "#1c1c1e",
}


def customize_stylesheet(
    stylesheet: str, theme_name: str, text_color: str = "", counter_color: str = ""
) -> str:
    """
    Apply the player's colors to a theme stylesheet.

    Args:
        stylesheet: The theme's QSS.
        theme_name: The theme it came from.
        text_color: Replaces the theme's main text color ("" keeps it).
        counter_color: Color of the big death number ("" keeps the theme's).
    """
    # Appended rules use the theme's own selectors, so coming later makes them win.
    if text_color:
        theme_color = _THEME_TEXT_COLORS.get(theme_name)
        if theme_color:
            stylesheet = stylesheet.replace(f"color: {theme_color};", f"color: {text_color};")
        stylesheet += f"\nQLabel#TitleLabel {{ color: {text_color}; }}\n"
    if counter_color:
        stylesheet += f"\nQLabel#CounterLabel {{ color: {counter_color}; }}\n"
    return stylesheet


def apply_theme(
    widget: QWidget, theme_name: str, text_color: str = "", counter_color: str = ""
) -> None:
    """
    Apply a theme's stylesheet to a widget (typically the top-level window).

    Args:
        widget: The widget to style. Stylesheets cascade to children.
        theme_name: One of :data:`AVAILABLE_THEMES`.
        text_color: Optional custom text color (e.g. ``"#7fd1ff"``).
        counter_color: Optional custom color for the big death number.
    """
    stylesheet = customize_stylesheet(
        load_stylesheet(theme_name), theme_name, text_color, counter_color
    )
    widget.setStyleSheet(stylesheet)
    logger.info("Applied theme '%s'", theme_name)
