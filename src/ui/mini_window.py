"""
Compact mini mode: the count and the main buttons in a tiny always-on-top
window, for players with one monitor.

It's a :class:`~src.overlay.capture_window.CaptureWindow`, so it drags,
stays on top, follows the overlay's Appearance settings, and can also be
captured in OBS. The buttons emit ``action_requested``; the main window does
the work.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.core.counter_manager import CounterSnapshot
from src.overlay.capture_window import CaptureWindow
from src.ui import icons
from src.utils.constants import DEFAULT_COUNTER_SOURCE

MINI_WINDOW_TITLE = "DUDC Mini"
_CAPTIONS = {
    "session": "THIS SESSION", "boss": "THIS BOSS", "total": "ALL-TIME", "run": "THIS RUN"
}


class MiniWindow(CaptureWindow):
    """
    Tiny always-on-top counter with +1 / Undo.

    Signals:
        action_requested: "increment", "undo" or "expand" (back to the full window).
    """

    action_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(MINI_WINDOW_TITLE, parent)
        self._counter_source = "session"
        self.setMinimumSize(190, 96)
        self.resize(230, 112)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(4)
        top = QHBoxLayout()
        self._title = QLabel("")
        self._expand = QPushButton()
        self._expand.setToolTip("Back to the full window")
        self._expand.setFixedSize(26, 22)
        self._expand.clicked.connect(lambda: self.action_requested.emit("expand"))
        top.addWidget(self._title, 1)
        top.addWidget(self._expand)
        layout.addLayout(top)

        body = QHBoxLayout()
        numbers = QVBoxLayout()
        numbers.setSpacing(0)
        self._count = QLabel("0")
        self._caption = QLabel(_CAPTIONS["session"])
        numbers.addWidget(self._count)
        numbers.addWidget(self._caption)
        body.addLayout(numbers, 1)
        self._plus = QPushButton("+1")
        self._plus.clicked.connect(lambda: self.action_requested.emit("increment"))
        self._undo = QPushButton()
        self._undo.setToolTip("Undo")
        self._undo.clicked.connect(lambda: self.action_requested.emit("undo"))
        for button in (self._plus, self._undo):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(38)
        self._plus.setMinimumWidth(56)
        self._expand.setIconSize(QSize(13, 13))
        self._undo.setIconSize(QSize(18, 18))
        body.addWidget(self._plus)
        body.addWidget(self._undo)
        layout.addLayout(body)
        self._restyle()

    def apply_display_settings(self, settings: dict[str, str]) -> None:
        """Use the overlay's Appearance settings (background, font, colors)."""
        self.apply_style_settings(settings)
        self._counter_source = settings.get("overlay_counter_source", DEFAULT_COUNTER_SOURCE)
        self._restyle()

    def _restyle(self) -> None:
        secondary, font = self.secondary_color(), self.font_css()
        self._title.setStyleSheet(f"color: {secondary}; font-size: 11px; {font}")
        self._count.setStyleSheet(
            f"color: {self._text_color}; font-size: 34px; font-weight: 800; {font}"
        )
        self._caption.setStyleSheet(
            f"color: {secondary}; font-size: 9px; letter-spacing: 2px; {font}"
        )
        # The window has no app stylesheet (it's owned by a hidden window), so
        # its buttons are styled here, translucent so any background shows.
        self.setStyleSheet(
            "QPushButton { background-color: rgba(255, 255, 255, 0.10);"
            f" color: {secondary}; border: 1px solid rgba(255, 255, 255, 0.18);"
            " border-radius: 9px; font-size: 15px; font-weight: 700; padding: 0 8px; }"
            "QPushButton:hover { border: 1px solid #ff3d55; }"
            "QPushButton:pressed { background-color: rgba(255, 61, 85, 0.35); }"
        )
        self._plus.setStyleSheet(
            "QPushButton { background-color: #ff3d55; color: #ffffff; border: none; }"
            "QPushButton:hover { background-color: #ff6477; }"
        )
        self._expand.setIcon(icons.icon("maximize-2", secondary, size=13))
        self._undo.setIcon(icons.icon("undo-2", secondary, size=18))
        self.apply_outline((self._title, self._count, self._caption))

    def update_counters(self, snapshot: CounterSnapshot) -> None:
        values = {
            "session": snapshot.session_deaths,
            "boss": snapshot.boss_deaths,
            "total": snapshot.total_deaths,
            "run": snapshot.run_deaths,
        }
        self._count.setText(str(values.get(self._counter_source, snapshot.session_deaths)))
        self._caption.setText(_CAPTIONS.get(self._counter_source, _CAPTIONS["session"]))
        title = snapshot.boss_name or snapshot.game_name or "No game"
        self._title.setText(title if len(title) <= 28 else title[:27] + "…")
