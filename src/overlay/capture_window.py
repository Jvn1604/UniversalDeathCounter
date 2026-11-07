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

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QEnterEvent,
    QGuiApplication,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QScreen,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QGraphicsEffect,
    QLabel,
    QWidget,
)

from src.utils.backgrounds import cover, load_background
from src.utils.constants import (
    ACCENT_COLOR,
    DEFAULT_TEXT_EDGE,
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
    geometry_changed = Signal()  # moved or resized while shown (to remember its place)

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
        self._text_outline = False  # any edge at all (the stream page's "shadow")
        self._text_edge = "false"  # "outline", "true" (soft shadow) or "false"
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

        # Resize grip in the bottom-right corner, only while the mouse is over
        # the window: it isn't part of the overlay, so it never shows on stream.
        self._size_grip = _HoverGrip(self)
        self._grip_on_hover = True

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
        edge = settings.get(SETTING_OVERLAY_TEXT_OUTLINE, DEFAULT_TEXT_EDGE)
        self._text_edge = edge if edge in ("outline", "true") else "false"
        self._text_outline = self._text_edge != "false"
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

    @property
    def text_edge(self) -> str:
        return self._text_edge

    def apply_outline(self, labels: tuple[QLabel, ...]) -> None:
        """Add or remove the text's edge: a black outline or a soft shadow."""
        for label in labels:
            effect = label.graphicsEffect()
            if self._text_edge == "outline":
                if not isinstance(effect, OutlineEffect):
                    label.setGraphicsEffect(OutlineEffect(label))
            elif self._text_edge == "true":
                if not isinstance(effect, QGraphicsDropShadowEffect):
                    label.setGraphicsEffect(_make_outline(label))
            else:
                label.setGraphicsEffect(None)

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
        if enabled:  # no hover comes any more to take the grip away
            self._size_grip.hide()
        self._set_flag(Qt.WindowType.WindowTransparentForInput, enabled)

    def set_locked(self, locked: bool) -> None:
        """Lock the window in place (a stray click can't drag it)."""
        self._locked = locked

    def is_locked(self) -> bool:
        return self._locked

    def set_resizable(self, enabled: bool) -> None:
        """Whether hovering shows the resize grip (off for in-dialog previews)."""
        self._grip_on_hover = enabled
        if not enabled:
            self._size_grip.hide()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        grip = self._size_grip
        grip.move(self.width() - grip.width(), self.height() - grip.height())
        super().resizeEvent(event)
        if self.isVisible():
            self.geometry_changed.emit()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        if self.isVisible():
            self.geometry_changed.emit()

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        if self._grip_on_hover:
            self._size_grip.raise_()
            self._size_grip.show()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        # Not while resizing: the cursor can leave the window mid-drag.
        if not QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self._size_grip.hide()
        super().leaveEvent(event)

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

    def restore_geometry_string(self, value: str) -> bool:
        """
        Restore geometry from a 'x,y,w,h' string, ignoring invalid input.

        If that spot is no longer on a connected display (monitor unplugged,
        laptop undocked, or not awake yet at startup), the window is moved onto
        the primary display. Returns whether it went exactly where asked.
        """
        if not value:
            return True
        try:
            x, y, w, h = (int(part) for part in value.split(","))
        except (ValueError, TypeError):
            logger.warning("Could not parse window geometry string: %s", value)
            return True
        wanted = QRect(x, y, w, h)
        fitted = fit_to_screens(wanted, available_screen_rects())
        self.setGeometry(fitted)
        return fitted == wanted

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


class _HoverGrip(QWidget):
    """
    The resize corner. Not a QSizeGrip: that one shows itself again whenever
    its window is shown, so it couldn't stay hidden until hovered.
    """

    SIZE = 14

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self._start: tuple[QPoint, QSize] | None = None  # manual resize fallback
        self.hide()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 150))
        # Six dots in a triangle, like a window's resize corner.
        for row in range(3):
            for col in range(row + 1):
                x = self.SIZE - 4 - (row - col) * 4
                y = self.SIZE - 4 - col * 4
                painter.drawEllipse(QRectF(x - 1, y - 1, 2.4, 2.4))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        handle = self.window().windowHandle()
        edges = Qt.Edge.RightEdge | Qt.Edge.BottomEdge
        if handle is None or not handle.startSystemResize(edges):
            self._start = (event.globalPosition().toPoint(), self.window().size())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._start is not None:
            origin, size = self._start
            delta = event.globalPosition().toPoint() - origin
            self.window().resize(size.width() + delta.x(), size.height() + delta.y())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._start = None
        window = self.window()
        # A resize can end with the cursor outside (no leave event comes then).
        if not window.rect().contains(window.mapFromGlobal(QCursor.pos())):
            self.hide()


class OutlineEffect(QGraphicsEffect):
    """
    A solid black edge around each letter, so light text stays readable on a
    bright game scene (a soft shadow washes out there). The text is drawn in
    black a little offset all the way round, then itself on top.
    """

    _DIRECTIONS = 12

    def __init__(self, label: QLabel) -> None:
        super().__init__(label)  # parented: Python would free it otherwise
        self._label = label

    def _width(self) -> float:
        font = self._label.font()
        size = font.pixelSize() if font.pixelSize() > 0 else font.pointSizeF() * 1.33
        return max(1.5, min(size * 0.06, 4.0))

    def boundingRectFor(self, rect: QRectF) -> QRectF:  # noqa: N802 - Qt override
        width = self._width() + 1
        return rect.adjusted(-width, -width, width, width)

    def draw(self, painter: QPainter) -> None:
        offset = QPoint()  # filled in with where the padded pixmap goes
        pixmap = self.sourcePixmap(
            Qt.CoordinateSystem.LogicalCoordinates, offset,
            QGraphicsEffect.PixmapPadMode.PadToEffectiveBoundingRect,
        )
        if pixmap.isNull():
            return
        edge = QPixmap(pixmap.size())
        edge.setDevicePixelRatio(pixmap.devicePixelRatio())
        edge.fill(Qt.GlobalColor.transparent)
        tint = QPainter(edge)
        tint.drawPixmap(0, 0, pixmap)
        tint.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        tint.fillRect(edge.rect(), QColor(0, 0, 0))
        tint.end()
        width = self._width()
        for step in range(self._DIRECTIONS):
            angle = 2 * math.pi * step / self._DIRECTIONS
            painter.drawPixmap(
                QPointF(offset.x() + width * math.cos(angle), offset.y() + width * math.sin(angle)),
                edge,
            )
        painter.drawPixmap(offset, pixmap)


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
