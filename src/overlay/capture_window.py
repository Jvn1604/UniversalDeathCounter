"""
Base class for the frameless, always-on-top windows streamers capture in OBS
(the death-counter overlay and the speedrun timer).

It owns everything the two share:

* being listed in OBS's Window Capture picker while staying off the taskbar
* drag-to-move, a resize grip, and keeping the window on a connected display
* the background (``dark`` card, ``chroma`` green, ``image`` or
  ``transparent``) and the text
  styling (font, colors, shadow) from the overlay's Appearance settings
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QScreen,
    QShowEvent,
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QWidget

from src.utils.backgrounds import cover, load_background
from src.utils.constants import (
    ACCENT_COLOR,
    SETTING_OVERLAY_BG_IMAGE,
    SETTING_OVERLAY_BG_MODE,
    SETTING_OVERLAY_BORDER,
    SETTING_OVERLAY_CARD_COLOR,
    SETTING_OVERLAY_CORNER_RADIUS,
    SETTING_OVERLAY_FONT,
    SETTING_OVERLAY_OPACITY,
    SETTING_OVERLAY_SECONDARY_COLOR,
    SETTING_OVERLAY_TEXT_COLOR,
    SETTING_OVERLAY_TEXT_OUTLINE,
)
from src.utils.logger import get_logger
from src.utils.screens import fit_to_screens, place_in_corner

logger = get_logger(__name__)

CHROMA_GREEN = "#00ff00"
DEFAULT_CARD_COLOR = "#141416"


class CaptureWindow(QWidget):
    """
    A movable, resizable, OBS-capturable window with the overlay's styling.

    Signals:
        visibility_changed: True when shown, False when hidden (for ON/OFF tags).
    """

    visibility_changed = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        # OBS's Window Capture list leaves out tool windows, so this is a
        # normal window. Being owned by a never-shown window keeps it off the
        # taskbar and Alt-Tab anyway.
        owner = QWidget() if parent is None else None
        super().__init__(parent or owner)
        self._owner = owner
        self._drag_offset: QPoint | None = None
        self._locked = False  # "Lock position": no dragging
        # Frameless, so never shown on screen, but it's how the window is
        # listed in OBS's Window Capture picker.
        self.setWindowTitle(title)

        # Shared appearance (updated via apply_style_settings)
        self._opacity = 0.85
        self._bg_mode = "dark"
        self._text_color = ACCENT_COLOR
        self._font_family = ""
        self._card_color = QColor(DEFAULT_CARD_COLOR)
        self._secondary_color = ""  # "" = automatic for the background
        self._bg_image: QPixmap | None = None
        self._bg_scaled: QPixmap | None = None  # cache, rescaled only on resize
        self._corner_radius = 12
        self._text_outline = False
        self._border = True

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Translucent so the card's rounded corners and opacity show through.
        # Qt doesn't paint stylesheet backgrounds on translucent windows, so the
        # card / chroma green / image is drawn in paintEvent instead.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    # ----------------------------------------------------------------
    # Styling
    # ----------------------------------------------------------------
    def apply_style_settings(self, settings: dict[str, str]) -> None:
        """Read the shared overlay appearance settings (call before restyling)."""
        try:
            self._opacity = float(settings.get(SETTING_OVERLAY_OPACITY, "0.85"))
        except ValueError:
            self._opacity = 0.85
        self._bg_mode = settings.get(SETTING_OVERLAY_BG_MODE, "dark")
        self._text_color = settings.get(SETTING_OVERLAY_TEXT_COLOR, ACCENT_COLOR) or ACCENT_COLOR
        self._font_family = settings.get(SETTING_OVERLAY_FONT, "")
        card = QColor(settings.get(SETTING_OVERLAY_CARD_COLOR, "") or DEFAULT_CARD_COLOR)
        self._card_color = card if card.isValid() else QColor(DEFAULT_CARD_COLOR)
        self._secondary_color = settings.get(SETTING_OVERLAY_SECONDARY_COLOR, "")
        self._bg_image = load_background(settings.get(SETTING_OVERLAY_BG_IMAGE, ""))
        self._bg_scaled = None
        try:
            radius = int(settings.get(SETTING_OVERLAY_CORNER_RADIUS, "12"))
        except ValueError:
            radius = 12
        self._corner_radius = min(max(radius, 0), 60)
        self._text_outline = settings.get(SETTING_OVERLAY_TEXT_OUTLINE, "false") == "true"
        self._border = settings.get(SETTING_OVERLAY_BORDER, "true") == "true"
        self.update()

    def secondary_color(self) -> str:
        """Color for everything but the main number."""
        automatic = "#101113" if self._bg_mode == "chroma" else "#dddddd"
        return self._secondary_color or automatic

    def font_css(self) -> str:
        """``font-family`` declaration for label stylesheets ("" for the default font)."""
        family = self._font_family.replace('"', "")
        return f'font-family: "{family}";' if family else ""

    def apply_outline(self, labels: tuple[QLabel, ...]) -> None:
        """Add or remove the soft text shadow (readable over images or footage)."""
        for label in labels:
            if not self._text_outline:
                label.setGraphicsEffect(None)
            elif label.graphicsEffect() is None:
                label.setGraphicsEffect(_make_outline(label))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        """Draw the background: chroma green, the player's image, or the translucent card."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        opacity = max(0.0, min(1.0, self._opacity))
        card_rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._corner_radius
        if self._bg_mode == "chroma":
            # Solid keyable green, square corners so OBS's Chroma Key is clean.
            painter.fillRect(self.rect(), QColor(CHROMA_GREEN))
        elif self._bg_mode == "transparent":
            # Just the text. Alpha 1 instead of 0: fully clear pixels let
            # clicks fall through, and the window couldn't be dragged.
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        elif self._bg_mode == "image" and self._bg_image is not None:
            if self._bg_scaled is None or self._bg_scaled.size() != self.size():
                self._bg_scaled = cover(self._bg_image, QSize(self.width(), self.height()))
            path = QPainterPath()
            path.addRoundedRect(card_rect, radius, radius)
            painter.setClipPath(path)
            painter.setOpacity(opacity)
            painter.drawPixmap(0, 0, self._bg_scaled)
        else:
            color = QColor(self._card_color)
            color.setAlphaF(opacity)
            painter.setBrush(color)
            if self._border:
                painter.setPen(QPen(QColor(255, 77, 77, 120), 1))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(card_rect, radius, radius)
        painter.end()
        super().paintEvent(event)

    # ----------------------------------------------------------------
    # Visibility
    # ----------------------------------------------------------------
    def _set_flag(self, flag: Qt.WindowType, enabled: bool) -> None:
        """Change one window flag, keeping the window where it was and shown if it was."""
        if bool(self.windowFlags() & flag) == enabled:
            return  # changing flags re-creates the window: it would flicker
        # setWindowFlags hides the window, so remember first (checking
        # isVisible() afterwards is what made the overlay vanish).
        was_visible = self.isVisible()
        geometry = self.geometry()
        self.setWindowFlag(flag, enabled)
        self.setGeometry(geometry)
        if was_visible:
            self.show()

    def set_always_on_top(self, enabled: bool) -> None:
        """Toggle the always-on-top window flag; the window stays shown."""
        self._set_flag(Qt.WindowType.WindowStaysOnTopHint, enabled)

    def set_click_through(self, enabled: bool) -> None:
        """Clicks pass through to the game underneath (no dragging or menu meanwhile)."""
        self._set_flag(Qt.WindowType.WindowTransparentForInput, enabled)

    def set_locked(self, locked: bool) -> None:
        """Lock the window in place (a stray click can't drag it)."""
        self._locked = locked

    def is_locked(self) -> bool:
        return self._locked

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def toggle_visibility(self) -> None:
        """Show the window if hidden, hide it if shown."""
        self.setVisible(not self.isVisible())
        logger.info("%s visibility toggled to %s", self.windowTitle(), self.isVisible())

    # ----------------------------------------------------------------
    # Drag-to-move support (frameless windows have no title bar)
    # ----------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self._locked:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    # ----------------------------------------------------------------
    # Geometry persistence helpers
    # ----------------------------------------------------------------
    def geometry_string(self) -> str:
        """Serialize current geometry as 'x,y,w,h' for persistence."""
        g = self.geometry()
        return f"{g.x()},{g.y()},{g.width()},{g.height()}"

    def restore_geometry_string(self, value: str) -> None:
        """
        Restore geometry from a 'x,y,w,h' string, ignoring invalid input.

        If that spot is no longer on a connected display (monitor unplugged,
        laptop undocked), the window is moved onto the primary display.
        """
        if not value:
            return
        try:
            x, y, w, h = (int(part) for part in value.split(","))
        except (ValueError, TypeError):
            logger.warning("Could not parse window geometry string: %s", value)
            return
        self.setGeometry(fit_to_screens(QRect(x, y, w, h), available_screen_rects()))

    def keep_on_screen(self) -> None:
        """Pull the window back onto a display if it ended up off every screen."""
        fitted = fit_to_screens(self.geometry(), available_screen_rects())
        if fitted != self.geometry():
            logger.info("%s was off-screen; moved to the primary display", self.windowTitle())
            self.setGeometry(fitted)

    def move_to_screen(self, screen: QScreen) -> None:
        """Place the window in the top-right corner of ``screen`` and show it."""
        self.setGeometry(place_in_corner(self.geometry(), screen.availableGeometry()))
        self.show()
        self.raise_()
        logger.info("%s moved to display %s", self.windowTitle(), screen.name())


def _make_outline(label: QLabel) -> QGraphicsDropShadowEffect:
    # Parented to the label: without a parent, Python frees it right away.
    effect = QGraphicsDropShadowEffect(label)
    effect.setBlurRadius(6)
    effect.setOffset(0, 0)
    effect.setColor(QColor(0, 0, 0, 230))
    return effect


def available_screen_rects() -> list[QRect]:
    """Usable area of every connected display, primary first."""
    primary = QGuiApplication.primaryScreen()
    screens = sorted(QGuiApplication.screens(), key=lambda s: s is not primary)
    return [s.availableGeometry() for s in screens]
