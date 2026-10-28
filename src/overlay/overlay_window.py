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
via Settings and applied live through :meth:`apply_display_settings`. The
window behavior and background are shared with the speedrun timer through
:class:`~src.overlay.capture_window.CaptureWindow`.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QLabel, QSizeGrip, QVBoxLayout, QWidget

from src.core.counter_manager import CounterSnapshot
from src.overlay.capture_window import (
    CHROMA_GREEN,
    DEFAULT_CARD_COLOR,
    CaptureWindow,
    available_screen_rects,
)
from src.utils.constants import (
    SETTING_OVERLAY_COUNTER_SOURCE,
    SETTING_OVERLAY_FONT_SIZE,
    SETTING_OVERLAY_SHOW_BOSS,
    SETTING_OVERLAY_SHOW_GAME,
    SETTING_OVERLAY_SHOW_STATS,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Re-exported for existing importers.
__all__ = ["CHROMA_GREEN", "DEFAULT_CARD_COLOR", "OverlayWindow", "available_screen_rects"]

_CAPTIONS = {"session": "SESSION DEATHS", "boss": "BOSS DEATHS", "total": "ALL-TIME DEATHS"}
OVERLAY_WINDOW_TITLE = "DUDC Overlay"


class OverlayWindow(CaptureWindow):
    """
    A movable, resizable, OBS-friendly death counter overlay.

    Signals:
        menu_requested: Right-click at this screen position; the main window
            shows the overlay's menu (counting, look, position, settings).
            The menu is its own window, so OBS never captures it.
        settings_requested: Double-click: open the overlay's settings.
    """

    menu_requested = Signal(QPoint)
    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(OVERLAY_WINDOW_TITLE, parent)

        # Overlay-only configuration (updated via apply_display_settings)
        self._font_size = 24
        self._counter_source = "session"
        self._show_game = True
        self._show_boss = True
        self._show_stats = True

        self._last_snapshot: CounterSnapshot | None = None

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
        """Re-apply all label styles for the current config (background: paintEvent)."""
        secondary = self.secondary_color()
        font = self.font_css()
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
        self.apply_outline(
            (
                self._game_label,
                self._boss_label,
                self._death_label,
                self._caption_label,
                self._stats_label,
            )
        )

        self._game_label.setVisible(self._show_game)
        self._boss_label.setVisible(self._show_boss)
        self._stats_label.setVisible(self._show_stats)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        self.menu_requested.emit(event.globalPos())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.settings_requested.emit()
        super().mouseDoubleClickEvent(event)

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------
    def apply_display_settings(self, settings: dict[str, str]) -> None:
        """
        Apply overlay-related settings (from the settings table) live.

        Args:
            settings: Full settings dict from ``Database.get_all_settings``.
        """
        self.apply_style_settings(settings)
        self._font_size = int(settings.get(SETTING_OVERLAY_FONT_SIZE, "24"))
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
        self._caption_label.setText(_CAPTIONS.get(self._counter_source, "DEATHS"))
        self._stats_label.setText(
            f"Session {snapshot.session_deaths}  •  All-time {snapshot.total_deaths}"
        )
