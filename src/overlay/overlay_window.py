"""
Transparent, always-on-top overlay window for OBS capture.

The overlay is a frameless, drag-movable widget showing the game name,
boss name, a large configurable counter, and a "Session • Total" stats
line. It supports two background modes:

* ``dark``   — semi-transparent dark card (for OBS Window Capture)
* ``chroma`` — solid chroma-key green (#00ff00) for OBS color-key filters

Every visual aspect (text color, counter source, which lines are shown,
font size, opacity) is user-configurable via Settings and applied live
through :meth:`apply_display_settings`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QSizeGrip, QVBoxLayout, QWidget

from src.core.counter_manager import CounterSnapshot
from src.utils.constants import (
    ACCENT_COLOR,
    SETTING_OVERLAY_BG_MODE,
    SETTING_OVERLAY_COUNTER_SOURCE,
    SETTING_OVERLAY_FONT_SIZE,
    SETTING_OVERLAY_OPACITY,
    SETTING_OVERLAY_SHOW_BOSS,
    SETTING_OVERLAY_SHOW_GAME,
    SETTING_OVERLAY_SHOW_STATS,
    SETTING_OVERLAY_TEXT_COLOR,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

CHROMA_GREEN = "#00ff00"


class OverlayWindow(QWidget):
    """A movable, resizable, OBS-friendly death counter overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None

        # Display configuration (updated via apply_display_settings)
        self._font_size = 24
        self._opacity = 0.85
        self._bg_mode = "dark"
        self._text_color = ACCENT_COLOR
        self._counter_source = "session"
        self._show_game = True
        self._show_boss = True
        self._show_stats = True

        self._last_snapshot: CounterSnapshot | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
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
        if self._bg_mode == "chroma":
            # Solid keyable green, square corners so the key is clean.
            self.setStyleSheet(
                f"OverlayWindow {{ background-color: {CHROMA_GREEN}; border-radius: 0px; }}"
            )
            secondary = "#101113"  # dark text reads best over pure green
        else:
            alpha = max(0, min(255, int(self._opacity * 255)))
            self.setStyleSheet(
                f"OverlayWindow {{ background-color: rgba(20, 20, 22, {alpha}); "
                f"border-radius: 12px; border: 1px solid rgba(255, 77, 77, 120); }}"
            )
            secondary = "#dddddd"

        self._game_label.setStyleSheet(f"color: {secondary}; font-size: 13px; font-weight: 500;")
        self._boss_label.setStyleSheet(f"color: {secondary}; font-size: 12px;")
        self._death_label.setStyleSheet(
            f"color: {self._text_color}; font-size: {self._font_size}px; font-weight: 800;"
        )
        self._caption_label.setStyleSheet(
            f"color: {secondary}; font-size: 10px; letter-spacing: 2px;"
        )
        self._stats_label.setStyleSheet(f"color: {secondary}; font-size: 11px;")

        self._game_label.setVisible(self._show_game)
        self._boss_label.setVisible(self._show_boss)
        self._stats_label.setVisible(self._show_stats)

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
        self._stats_label.setText(
            f"Session {snapshot.session_deaths}  •  Total {snapshot.total_deaths}"
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
        """Restore geometry from a 'x,y,w,h' string, ignoring invalid input."""
        if not value:
            return
        try:
            x, y, w, h = (int(part) for part in value.split(","))
            self.setGeometry(x, y, w, h)
        except (ValueError, TypeError):
            logger.warning("Could not parse overlay geometry string: %s", value)
