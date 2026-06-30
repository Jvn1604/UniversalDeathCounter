"""
Transparent, always-on-top overlay window for OBS Window Capture.

The overlay is a frameless, click-through-free (but drag-movable) widget
that shows only Game name, Boss name, and Death count. It is intentionally
minimal so it composites cleanly over gameplay footage in OBS.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizeGrip, QVBoxLayout, QWidget

from src.utils.constants import ACCENT_COLOR
from src.utils.logger import get_logger

logger = get_logger(__name__)


class OverlayWindow(QWidget):
    """A movable, resizable, transparent always-on-top death counter overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self._font_size = 24
        self._opacity = 0.85

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(220, 110)
        self.resize(280, 140)

        self._build_ui()

    # ----------------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)

        self._game_label = QLabel("No Game Selected")
        self._game_label.setStyleSheet("color: #dddddd; font-size: 13px; font-weight: 500;")

        self._boss_label = QLabel("")
        self._boss_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")

        self._death_label = QLabel("0")
        self._death_label.setStyleSheet(
            f"color: {ACCENT_COLOR}; font-size: 36px; font-weight: 800;"
        )

        caption = QLabel("DEATHS")
        caption.setStyleSheet("color: #888888; font-size: 10px; letter-spacing: 2px;")

        layout.addWidget(self._game_label)
        layout.addWidget(self._boss_label)
        layout.addWidget(self._death_label)
        layout.addWidget(caption)

        self._size_grip = QSizeGrip(self)
        layout.addWidget(self._size_grip, 0, Qt.AlignmentFlag.AlignRight)

        self._apply_background()

    def _apply_background(self) -> None:
        alpha = max(0, min(255, int(self._opacity * 255)))
        self.setStyleSheet(
            f"OverlayWindow {{ background-color: rgba(20, 20, 22, {alpha}); "
            f"border-radius: 12px; border: 1px solid rgba(255, 77, 77, 120); }}"
        )

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------
    def update_counters(self, game_name: str | None, boss_name: str | None, deaths: int) -> None:
        """
        Refresh the overlay's displayed text.

        Args:
            game_name: Currently selected game name, or ``None``.
            boss_name: Currently selected boss name, or ``None``.
            deaths: The death count to display (typically session deaths).
        """
        self._game_label.setText(game_name or "No Game Selected")
        self._boss_label.setText(boss_name or "")
        self._death_label.setText(str(deaths))

    def set_font_size(self, size: int) -> None:
        """Update the death counter's font size."""
        self._font_size = size
        self._death_label.setStyleSheet(
            f"color: {ACCENT_COLOR}; font-size: {size}px; font-weight: 800;"
        )

    def set_opacity_level(self, opacity: float) -> None:
        """Update the overlay background's opacity (0.0 - 1.0)."""
        self._opacity = max(0.0, min(1.0, opacity))
        self._apply_background()

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

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)

    # ----------------------------------------------------------------
    # Geometry persistence helpers (used by app.py with Database settings)
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
