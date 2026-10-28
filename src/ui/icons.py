"""
Line icons for buttons and the sidebar (Lucide, ISC licence).

The icons ship as white 64 px PNGs (``assets/icons/ui``, made by
``packaging/make_ui_icons.py``) and are tinted here, so one file serves every
theme and color. A button remembers its icon name and role, and
:func:`refresh_icons` re-tints all of them when the theme changes.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractButton, QWidget

from src.utils.constants import ICONS_DIR

UI_ICONS_DIR = ICONS_DIR / "ui"

# Roles: which color a button's icon takes in the current theme.
NORMAL = "normal"  # ordinary buttons
ACCENT = "accent"  # on the filled accent buttons (always white)
DANGER = "danger"
NAV = "nav"  # sidebar: muted, bright when selected

_ICON_PROPERTY = "dudcIcon"
_ROLE_PROPERTY = "dudcIconRole"
_cache: dict[tuple[str, str, int], QPixmap] = {}
# Colors per role, set from the theme by refresh_icons().
_colors: dict[str, str] = {
    NORMAL: "#c9ccd6",
    ACCENT: "#ffffff",
    DANGER: "#ff5c6c",
    NAV: "#8a8f9c",
    "nav_active": "#ffffff",
}


def pixmap(name: str, color: str, size: int = 18, ratio: float = 2.0) -> QPixmap:
    """The icon ``name`` tinted ``color``, ``size`` logical pixels square."""
    pixels = max(1, round(size * ratio))
    key = (name, color, pixels)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    source = QPixmap(str(UI_ICONS_DIR / f"{name}.png"))
    tinted = QPixmap(pixels, pixels)
    tinted.fill(Qt.GlobalColor.transparent)
    if not source.isNull():
        painter = QPainter(tinted)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(tinted.rect(), source)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), QColor(color))
        painter.end()
    tinted.setDevicePixelRatio(ratio)
    _cache[key] = tinted
    return tinted


def icon(name: str, color: str, on_color: str = "", size: int = 18) -> QIcon:
    """A QIcon; ``on_color`` tints the checked state (sidebar pages)."""
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(pixmap(name, on_color or color, size), QIcon.Mode.Normal, QIcon.State.On)
    result.addPixmap(pixmap(name, on_color or color, size), QIcon.Mode.Active, QIcon.State.On)
    return result


def set_icon(button: QAbstractButton, name: str, role: str = NORMAL, size: int = 18) -> None:
    """Give ``button`` an icon that follows the theme."""
    button.setProperty(_ICON_PROPERTY, name)
    button.setProperty(_ROLE_PROPERTY, role)
    button.setIconSize(QSize(size, size))
    _apply(button)


def _apply(button: QAbstractButton) -> None:
    name = button.property(_ICON_PROPERTY)
    if not name:
        return
    role = button.property(_ROLE_PROPERTY) or NORMAL
    size = button.iconSize().width()
    if role == NAV:
        button.setIcon(icon(name, _colors[NAV], _colors["nav_active"], size))
    else:
        button.setIcon(icon(name, _colors.get(role, _colors[NORMAL]), size=size))


def set_colors(colors: dict[str, str]) -> None:
    """Theme colors for the roles (missing ones keep their current color)."""
    _colors.update({role: color for role, color in colors.items() if color})


def color(role: str) -> str:
    return _colors.get(role, _colors[NORMAL])


def refresh_icons(root: QWidget) -> None:
    """Re-tint every themed icon under ``root`` (after a theme change)."""
    for button in root.findChildren(QAbstractButton):
        _apply(button)
