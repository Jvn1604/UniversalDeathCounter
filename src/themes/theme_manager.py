"""
Theme loading, application, and the downloadable theme catalog.

Dark and Light ship with the app (``src/themes/<name>.qss``). Extra themes
(Glass, Clay) are listed in :data:`THEMES` but downloaded on request into
``saves/themes/<name>.qss``, so the install stays small and a theme the
player doesn't like can be removed again. Downloads come only from this
project's GitHub repository.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QWidget

from src.utils.constants import (
    APP_VERSION,
    GITHUB_REPO,
    ICONS_DIR,
    PROJECT_ROOT,
    SAVES_DIR,
    THEMES_DIR,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

INSTALLED_THEMES_DIR: Path = SAVES_DIR / "themes"
_MAX_THEME_BYTES = 256 * 1024
_DOWNLOAD_TIMEOUT = 15


@dataclass(frozen=True)
class ThemeInfo:
    """What the theme picker shows and what the code needs to know about a theme."""

    name: str
    title: str
    description: str
    base: str  # window color; the dim layer over a background image
    text: str  # main text color (swapped for the player's own text color)
    surface: str  # card color, for the picker's preview
    accent: str
    icon: str  # icon color on ordinary buttons
    icon_muted: str  # sidebar icons
    danger: str  # icons on the reset buttons
    light: bool = False  # dark text on a light window
    builtin: bool = True
    size_kb: int = 0
    on_accent: str = "#ffffff"  # text and icons on the filled accent buttons
    # Soft colored glow painted behind see-through panels (Glass, Clay):
    # (x, y, radius) as fractions of the window, then "#rrggbb" and alpha 0-255.
    backdrop: tuple[tuple[float, float, float, str, int], ...] = ()


THEMES: dict[str, ThemeInfo] = {
    "dark": ThemeInfo(
        "dark", "Phantom Dark", "Deep black with a crimson glow. The default.",
        base="#0b0c10", text="#ececf1", surface="#16171e", accent="#ff3d55",
        icon="#c9ccd6", icon_muted="#7d8290", danger="#ff6b7b",
    ),
    "light": ThemeInfo(
        "light", "Daylight", "Clean and bright for well-lit rooms.",
        base="#f3f4f8", text="#1b1c21", surface="#ffffff", accent="#e3263f",
        icon="#3b3e48", icon_muted="#6b6f7b", danger="#cc1f37", light=True,
    ),
    "glass": ThemeInfo(
        "glass", "Glass", "Frosted dark panels over a lime and teal glow.",
        base="#0d0f12", text="#f2f4f3", surface="#1c1f24", accent="#c8f169",
        icon="#e3e8e6", icon_muted="#a6adab", danger="#ff7b86",
        builtin=False, size_kb=22, on_accent="#10140c",
        backdrop=(
            (0.22, 0.88, 0.55, "#a3e635", 165),
            (0.88, 0.28, 0.50, "#2dd4bf", 135),
            (0.70, 0.98, 0.38, "#facc15", 95),
            (0.40, 0.05, 0.32, "#84cc16", 80),
        ),
    ),
    "clay": ThemeInfo(
        "clay", "Clay", "Soft, puffy white shapes on lavender. Made to be pressed.",
        base="#efecfa", text="#1e2145", surface="#ffffff", accent="#6c5ce7",
        icon="#4e4b73", icon_muted="#7d7a9e", danger="#d93a4a", light=True,
        builtin=False, size_kb=22,
        backdrop=(
            (0.15, 0.12, 0.42, "#b9a6ff", 230),
            (0.95, 0.30, 0.36, "#9ff0c8", 220),
            (0.85, 0.98, 0.40, "#ffcfa3", 230),
            (0.30, 0.95, 0.34, "#d4c8ff", 220),
        ),
    ),
}


def theme_info(name: str) -> ThemeInfo:
    return THEMES.get(name, THEMES["dark"])


def _installed_path(name: str) -> Path:
    return INSTALLED_THEMES_DIR / f"{name}.qss"


def is_installed(name: str) -> bool:
    info = THEMES.get(name)
    if info is None:
        return False
    return info.builtin or _installed_path(name).is_file()


def available_themes() -> list[str]:
    """Themes that can be used right now: built in, or downloaded."""
    return [name for name in THEMES if is_installed(name)]


# First line of a downloaded theme: the app version it was downloaded for.
# After an update the app fetches the new copy, which styles the new screens.
_VERSION_MARK = "/* DUDC theme for v{} */\n"


def outdated_themes() -> list[str]:
    """Downloaded themes that came with an older version of the app."""
    stale = []
    for name, info in THEMES.items():
        if info.builtin:
            continue
        try:
            with _installed_path(name).open(encoding="utf-8") as file:
                first_line = file.readline()
        except OSError:
            continue  # not installed
        if first_line != _VERSION_MARK.format(APP_VERSION):
            stale.append(name)
    return stale


def _theme_urls(name: str) -> list[str]:
    """This version's copy first, then the latest one."""
    base = f"https://raw.githubusercontent.com/{GITHUB_REPO}"
    return [f"{base}/v{APP_VERSION}/themes/{name}.qss", f"{base}/main/themes/{name}.qss"]


def _check_stylesheet(data: bytes) -> str:
    if not data or len(data) > _MAX_THEME_BYTES:
        raise ValueError("The theme file has the wrong size.")
    text = data.decode("utf-8")
    # A stylesheet can only load images with url(); themes may only use the
    # app's own icons.
    stripped = text.replace("url(@ICONS@", "")
    if "url(" in stripped:
        raise ValueError("The theme file refers to outside files.")
    if "QWidget" not in text:
        raise ValueError("That isn't a theme file.")
    return text


def install_theme(name: str) -> Path:
    """
    Download a catalog theme into ``saves/themes`` (call off the UI thread).

    Raises:
        ValueError: Unknown theme, or the download wasn't a valid theme.
        OSError: No connection, or the file couldn't be saved.
    """
    info = THEMES.get(name)
    if info is None or info.builtin:
        raise ValueError(f"'{name}' isn't a downloadable theme.")
    text = ""
    local = PROJECT_ROOT / "themes" / f"{name}.qss"
    if not getattr(sys, "frozen", False) and local.is_file():
        text = _check_stylesheet(local.read_bytes())  # running from source
    else:
        last_error: Exception | None = None
        for url in _theme_urls(name):
            try:
                with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT) as response:
                    text = _check_stylesheet(response.read(_MAX_THEME_BYTES + 1))
                break
            except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError) as exc:
                last_error = exc
        if not text:
            raise OSError(f"Couldn't download the {info.title} theme: {last_error}")
    INSTALLED_THEMES_DIR.mkdir(parents=True, exist_ok=True)
    target = _installed_path(name)
    partial = target.with_suffix(".part")
    # One line-ending style: "\r\n" written in text mode on Windows would
    # read back as blank lines, and the theme's rules wouldn't match.
    text = text.replace("\r\n", "\n")
    partial.write_text(_VERSION_MARK.format(APP_VERSION) + text, encoding="utf-8", newline="\n")
    os.replace(partial, target)
    logger.info("Installed theme '%s'", name)
    return target


def uninstall_theme(name: str) -> None:
    """Remove a downloaded theme (built-in themes can't be removed)."""
    info = THEMES.get(name)
    if info is None or info.builtin:
        return
    try:
        _installed_path(name).unlink()
        logger.info("Uninstalled theme '%s'", name)
    except FileNotFoundError:
        pass


def load_stylesheet(theme_name: str) -> str:
    """
    Load a theme's QSS text: built in, or downloaded. Falls back to "dark"
    if the theme is unknown or not installed.
    """
    if not is_installed(theme_name):
        if theme_name != "dark":
            logger.warning("Theme '%s' isn't available; using 'dark'", theme_name)
        theme_name = "dark"
    info = THEMES[theme_name]
    qss_path = THEMES_DIR / f"{theme_name}.qss" if info.builtin else _installed_path(theme_name)
    try:
        # @ICONS@ lets the stylesheets use images from assets/icons wherever
        # the app is installed.
        return qss_path.read_text(encoding="utf-8").replace("@ICONS@", ICONS_DIR.as_posix())
    except OSError:
        logger.exception("Failed to load theme file %s", qss_path)
        return ""


def active_theme(theme_name: str) -> str:
    """The theme that will actually be used for ``theme_name``."""
    return theme_name if is_installed(theme_name) else "dark"


# Kept for importers: each theme's window color.
THEME_BASE_COLORS: dict[str, str] = {name: info.base for name, info in THEMES.items()}


def customize_stylesheet(
    stylesheet: str,
    theme_name: str,
    text_color: str = "",
    counter_color: str = "",
    font_family: str = "",
    see_through: bool = False,
) -> str:
    """
    Apply the player's colors, font and background choice to a theme stylesheet.

    Args:
        stylesheet: The theme's QSS.
        theme_name: The theme it came from.
        text_color: Replaces the theme's main text color ("" keeps it).
        counter_color: Color of the big death number ("" keeps the theme's).
        font_family: Font for the whole window ("" keeps the theme's).
        see_through: Make plain widgets transparent so a background image painted
            behind them shows. Buttons, inputs and the counter card keep their
            own backgrounds.
    """
    info = theme_info(theme_name)
    if see_through:
        stylesheet = stylesheet.replace(
            f"QWidget {{\n    background-color: {info.base};",
            "QWidget {\n    background-color: transparent;",
            1,
        )
        stylesheet += "\nQMainWindow { background: transparent; }\n"
    # Appended rules use the theme's own selectors, so coming later makes them win.
    if text_color:
        stylesheet = stylesheet.replace(f"color: {info.text};", f"color: {text_color};")
        stylesheet += f"\nQLabel#TitleLabel, QLabel#PageTitle {{ color: {text_color}; }}\n"
    if counter_color:
        stylesheet += (
            f"\nQLabel#CounterLabel, QLabel#HomeCount {{ color: {counter_color}; }}\n"
        )
    if font_family:
        family = font_family.replace('"', "")
        stylesheet += f'\nQWidget {{ font-family: "{family}"; }}\n'
    return stylesheet


def apply_theme(
    widget: QWidget,
    theme_name: str,
    text_color: str = "",
    counter_color: str = "",
    font_family: str = "",
    see_through: bool = False,
) -> None:
    """
    Apply a theme's stylesheet to a widget (typically the top-level window).

    Args:
        widget: The widget to style. Stylesheets cascade to children.
        theme_name: A key of :data:`THEMES` (unavailable ones fall back to "dark").
        text_color: Optional custom text color (e.g. ``"#7fd1ff"``).
        counter_color: Optional custom color for the big death number.
        font_family: Optional font family for the whole window.
        see_through: Let a background image behind the widgets show.
    """
    theme_name = active_theme(theme_name)
    stylesheet = customize_stylesheet(
        load_stylesheet(theme_name),
        theme_name,
        text_color,
        counter_color,
        font_family,
        see_through,
    )
    if widget.styleSheet() == stylesheet:
        return  # restyling every widget is slow: skip it when nothing changed
    widget.setStyleSheet(stylesheet)
    logger.info("Applied theme '%s'", theme_name)
