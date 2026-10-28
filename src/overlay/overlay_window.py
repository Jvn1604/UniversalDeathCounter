"""
Transparent, always-on-top overlay window for OBS capture.

The overlay is a frameless, drag-movable widget showing the game name,
boss name, a large configurable counter, and a "Session • Total" stats
line. It supports three background modes:

* ``dark``   — semi-transparent card in the player's color (default near-black)
* ``chroma`` — solid chroma-key green (#00ff00) for OBS color-key filters
* ``image``  — the player's own picture, filling the card

Every visual aspect (colors, font, counter source, which lines are shown,
font size, opacity, corner roundness, text outline) is user-configurable
via Settings and applied live through :meth:`apply_display_settings`.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QScreen,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QLabel,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from src.core.counter_manager import CounterSnapshot
from src.utils.backgrounds import cover, load_background
from src.utils.constants import (
    ACCENT_COLOR,
    SETTING_OVERLAY_BG_IMAGE,
    SETTING_OVERLAY_BG_MODE,
    SETTING_OVERLAY_CARD_COLOR,
    SETTING_OVERLAY_CORNER_RADIUS,
    SETTING_OVERLAY_COUNTER_SOURCE,
    SETTING_OVERLAY_FONT,
    SETTING_OVERLAY_FONT_SIZE,
    SETTING_OVERLAY_OPACITY,
    SETTING_OVERLAY_SECONDARY_COLOR,
    SETTING_OVERLAY_SHOW_BOSS,
    SETTING_OVERLAY_SHOW_GAME,
    SETTING_OVERLAY_SHOW_STATS,
    SETTING_OVERLAY_TEXT_COLOR,
    SETTING_OVERLAY_TEXT_OUTLINE,
)
from src.utils.logger import get_logger
from src.utils.screens import fit_to_screens, place_in_corner

logger = get_logger(__name__)

CHROMA_GREEN = "#00ff00"
DEFAULT_CARD_COLOR = "#141416"
_CAPTIONS = {"session": "SESSION DEATHS", "boss": "BOSS DEATHS", "total": "ALL-TIME DEATHS"}
OVERLAY_WINDOW_TITLE = "DUDC Overlay"


class OverlayWindow(QWidget):
    """A movable, resizable, OBS-friendly death counter overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        # OBS's Window Capture list leaves out tool windows, so the overlay is a
        # normal window. Being owned by a never-shown window keeps it off the
        # taskbar and Alt-Tab anyway.
        owner = QWidget() if parent is None else None
        super().__init__(parent or owner)
        self._owner = owner
        self._drag_offset: QPoint | None = None
        # Frameless, so never shown on screen, but it's how the overlay is
        # listed in OBS's Window Capture picker.
        self.setWindowTitle(OVERLAY_WINDOW_TITLE)

        # Display configuration (updated via apply_display_settings)
        self._font_size = 24
        self._opacity = 0.85
        self._bg_mode = "dark"
        self._text_color = ACCENT_COLOR
        self._counter_source = "session"
        self._show_game = True
        self._show_boss = True
        self._show_stats = True
        self._font_family = ""
        self._card_color = QColor(DEFAULT_CARD_COLOR)
        self._secondary_color = ""  # "" = automatic for the background
        self._bg_image: QPixmap | None = None
        self._bg_scaled: QPixmap | None = None  # cache, rescaled only on resize
        self._corner_radius = 12
        self._text_outline = False

        self._last_snapshot: CounterSnapshot | None = None

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Translucent so the dark card's rounded corners and opacity show through.
        # Qt doesn't paint stylesheet backgrounds on translucent windows, so the
        # card / chroma green is drawn in paintEvent instead.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(220, 110)
        self.resize(280, 150)

        self._build_ui()
        self._restyle()

    # ----------------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)

        self._game_label = QLabel("No Game Selected")
        self._boss_label = QLabel("")
        self._death_label = QLabel("0")
        self._caption_label = QLabel("DEATHS")
        self._stats_label = QLabel("")

        layout.addWidget(self._game_label)
        layout.addWidget(self._boss_label)
        layout.addWidget(self._death_label)
        layout.addWidget(self._caption_label)
        layout.addWidget(self._stats_label)

        self._size_grip = QSizeGrip(self)
        layout.addWidget(self._size_grip, 0, Qt.AlignmentFlag.AlignRight)

    def _restyle(self) -> None:
        """Re-apply all label styles and the background for current config."""
        # Background itself is drawn in paintEvent; here only text styling.
        automatic = "#101113" if self._bg_mode == "chroma" else "#dddddd"
        secondary = self._secondary_color or automatic
        family = self._font_family.replace('"', "")
        font = f'font-family: "{family}";' if family else ""
        self.update()

        self._game_label.setStyleSheet(
            f"color: {secondary}; font-size: 13px; font-weight: 500; {font}"
        )
        self._boss_label.setStyleSheet(f"color: {secondary}; font-size: 12px; {font}")
        self._death_label.setStyleSheet(
            f"color: {self._text_color}; font-size: {self._font_size}px; font-weight: 800; "
            f"{font}"
        )
        self._caption_label.setStyleSheet(
            f"color: {secondary}; font-size: 10px; letter-spacing: 2px; {font}"
        )
        self._stats_label.setStyleSheet(f"color: {secondary}; font-size: 11px; {font}")

        # A soft shadow keeps text readable over busy images or game footage.
        for label in self._text_labels():
            if not self._text_outline:
                label.setGraphicsEffect(None)
            elif label.graphicsEffect() is None:
                label.setGraphicsEffect(self._make_outline(label))

        self._game_label.setVisible(self._show_game)
        self._boss_label.setVisible(self._show_boss)
        self._stats_label.setVisible(self._show_stats)

    def _text_labels(self) -> tuple[QLabel, ...]:
        return (
            self._game_label,
            self._boss_label,
            self._death_label,
            self._caption_label,
            self._stats_label,
        )

    @staticmethod
    def _make_outline(label: QLabel) -> QGraphicsDropShadowEffect:
        # Parented to the label: without a parent, Python frees it right away.
        effect = QGraphicsDropShadowEffect(label)
        effect.setBlurRadius(6)
        effect.setOffset(0, 0)
        effect.setColor(QColor(0, 0, 0, 230))
        return effect

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------
    def apply_display_settings(self, settings: dict[str, str]) -> None:
        """
        Apply overlay-related settings (from the settings table) live.

        Args:
            settings: Full settings dict from ``Database.get_all_settings``.
        """
        self._font_size = int(settings.get(SETTING_OVERLAY_FONT_SIZE, "24"))
        self._opacity = float(settings.get(SETTING_OVERLAY_OPACITY, "0.85"))
        self._bg_mode = settings.get(SETTING_OVERLAY_BG_MODE, "dark")
        self._text_color = settings.get(SETTING_OVERLAY_TEXT_COLOR, ACCENT_COLOR) or ACCENT_COLOR
        self._counter_source = settings.get(SETTING_OVERLAY_COUNTER_SOURCE, "session")
        self._show_game = settings.get(SETTING_OVERLAY_SHOW_GAME, "true") == "true"
        self._show_boss = settings.get(SETTING_OVERLAY_SHOW_BOSS, "true") == "true"
        self._show_stats = settings.get(SETTING_OVERLAY_SHOW_STATS, "true") == "true"
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
        self._restyle()
        if self._last_snapshot is not None:
            self.update_counters(self._last_snapshot)

    def update_counters(self, snapshot: CounterSnapshot) -> None:
        """
        Refresh the overlay's displayed text from a counter snapshot.

        Args:
            snapshot: The latest counter state.
        """
        self._last_snapshot = snapshot
        source_values = {
            "session": snapshot.session_deaths,
            "boss": snapshot.boss_deaths,
            "total": snapshot.total_deaths,
        }
        big_number = source_values.get(self._counter_source, snapshot.session_deaths)

        self._game_label.setText(snapshot.game_name or "No Game Selected")
        self._boss_label.setText(snapshot.boss_name or "")
        self._death_label.setText(str(big_number))
        self._caption_label.setText(_CAPTIONS.get(self._counter_source, "DEATHS"))
        self._stats_label.setText(
            f"Session {snapshot.session_deaths}  •  All-time {snapshot.total_deaths}"
        )

    def set_always_on_top(self, enabled: bool) -> None:
        """Toggle the always-on-top window flag and re-show the widget."""
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if self.isVisible():
            self.show()

    def toggle_visibility(self) -> None:
        """Show the overlay if hidden, hide it if shown."""
        self.setVisible(not self.isVisible())
        logger.info("Overlay visibility toggled to %s", self.isVisible())

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
            painter.setPen(QPen(QColor(255, 77, 77, 120), 1))
            painter.drawRoundedRect(card_rect, radius, radius)
        painter.end()
        super().paintEvent(event)

    # ----------------------------------------------------------------
    # Drag-to-move support (frameless windows have no title bar)
    # ----------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
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
        laptop undocked), the overlay is moved onto the primary display.
        """
        if not value:
            return
        try:
            x, y, w, h = (int(part) for part in value.split(","))
        except (ValueError, TypeError):
            logger.warning("Could not parse overlay geometry string: %s", value)
            return
        self.setGeometry(fit_to_screens(QRect(x, y, w, h), available_screen_rects()))

    def keep_on_screen(self) -> None:
        """Pull the overlay back onto a display if it ended up off every screen."""
        fitted = fit_to_screens(self.geometry(), available_screen_rects())
        if fitted != self.geometry():
            logger.info("Overlay was off-screen; moved to the primary display")
            self.setGeometry(fitted)

    def move_to_screen(self, screen: QScreen) -> None:
        """Place the overlay in the top-right corner of ``screen`` and show it."""
        self.setGeometry(place_in_corner(self.geometry(), screen.availableGeometry()))
        self.show()
        self.raise_()
        logger.info("Overlay moved to display %s", screen.name())


def available_screen_rects() -> list[QRect]:
    """Usable area of every connected display, primary first."""
    primary = QGuiApplication.primaryScreen()
    screens = sorted(QGuiApplication.screens(), key=lambda s: s is not primary)
    return [s.availableGeometry() for s in screens]
