"""
The notification bell (top bar): what the app wanted to tell you, kept.

Toasts and tray messages vanish after a few seconds, often while you're in
the game. The ones that matter (an update, a key another program took,
auto-detect pausing, a failed save...) also go to the bell: a red badge counts
the unread ones, and clicking it lists them, newest first, each with a button
that goes where it can be fixed. Kept in memory only (the last 50).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.ui import icons
from src.ui.widgets import drawable

MAX_KEPT = 50
_REPEAT_SECONDS = 600  # the same message again within this long: one entry


@dataclass
class Notification:
    text: str
    icon: str = "info"
    action_label: str = ""
    action: Callable[[], None] | None = None
    at: float = field(default_factory=time.time)
    read: bool = False


def ago(seconds: float) -> str:
    """``"just now"``, ``"5 min ago"``, ``"2 h ago"``, ``"3 days ago"``."""
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days = int(seconds // 86400)
    return f"{days} day{'' if days == 1 else 's'} ago"


class NotificationBell(QPushButton):
    """The bell button with its unread badge; :meth:`add` files a notification."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TopIconButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(self, "bell", size=19)
        self.items: list[Notification] = []
        self._badge = QLabel(self)
        self._badge.setObjectName("BellBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setStyleSheet(
            "QLabel#BellBadge { background-color: #ff3d55; color: #ffffff; border-radius: 8px;"
            " font-size: 10px; font-weight: 800; padding: 0 4px; }"
        )
        self._badge.hide()
        self._panel: NotificationPanel | None = None
        self.clicked.connect(self.open_panel)
        self._refresh()

    # ---------------------------------------------------------------- model
    def add(
        self,
        text: str,
        icon: str = "info",
        action_label: str = "",
        action: Callable[[], None] | None = None,
    ) -> Notification:
        """File a notification (the same one again soon just moves to the top, unread)."""
        now = time.time()
        for item in self.items:
            if item.text == text and now - item.at < _REPEAT_SECONDS:
                self.items.remove(item)
                item.at, item.read = now, False
                item.action_label, item.action = action_label, action
                self.items.insert(0, item)
                self._refresh()
                return item
        item = Notification(text, icon, action_label, action, now)
        self.items.insert(0, item)
        del self.items[MAX_KEPT:]
        self._refresh()
        return item

    def unread(self) -> int:
        return sum(1 for item in self.items if not item.read)

    def mark_all_read(self) -> None:
        for item in self.items:
            item.read = True
        self._refresh()

    def clear(self) -> None:
        self.items.clear()
        self._refresh()

    def _refresh(self) -> None:
        count = self.unread()
        self._badge.setVisible(count > 0)
        self._badge.setText("9+" if count > 9 else str(count))
        self._badge.adjustSize()
        self._badge.resize(max(16, self._badge.width()), 16)
        self._badge.move(self.width() - self._badge.width() - 1, 1)
        self.setToolTip(
            f"Notifications: {count} new" if count else "Notifications"
        )
        self.changed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._refresh()

    # ---------------------------------------------------------------- panel
    def open_panel(self) -> None:
        panel = self._panel = NotificationPanel(self)
        panel.adjustSize()
        corner = self.mapToGlobal(QPoint(self.width(), self.height() + 6))
        panel.move(corner.x() - panel.width(), corner.y())
        panel.show()
        self.mark_all_read()  # seen now (the panel still marks which were new)


class NotificationPanel(QFrame):
    """The list under the bell (a popup: a click elsewhere closes it)."""

    def __init__(self, bell: NotificationBell) -> None:
        # The window's, not the bell's: the top bar makes everything in it transparent.
        super().__init__(bell.window(), Qt.WindowType.Popup)
        self.setObjectName("NotificationPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # A popup is a window of its own: paint the theme's background on it.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(380)
        self._bell = bell
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("Notifications")
        title.setStyleSheet("font-size: 15px; font-weight: 800;")
        clear = QPushButton("Clear All")
        clear.setObjectName("GhostButton")
        clear.setVisible(bool(bell.items))
        clear.clicked.connect(self._clear)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(clear)
        layout.addLayout(top)

        if not bell.items:
            empty = QLabel("Nothing new. Updates, keys another program took, auto-detect "
                           "pausing and failed saves show up here.")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            layout.addWidget(empty)
            return

        rows = QWidget()
        rows_layout = QVBoxLayout(rows)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(6)
        now = time.time()
        for item in bell.items:
            rows_layout.addWidget(self._row(item, now))
        rows_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(rows)
        scroll.setFixedHeight(min(420, max(90, rows.sizeHint().height() + 4)))
        layout.addWidget(scroll)

    def _row(self, item: Notification, now: float) -> QWidget:
        row = QFrame()
        row.setObjectName("NotificationRow")
        if not item.read:
            row.setProperty("unread", True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.pixmap(item.icon, "#ff3d55" if not item.read else "#8a8f9c", 18))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        text = QLabel(drawable(item.text))
        text.setWordWrap(True)
        when = QLabel(ago(now - item.at) + ("  ·  new" if not item.read else ""))
        when.setObjectName("Muted")
        when.setStyleSheet("font-size: 11px;")
        texts.addWidget(text)
        texts.addWidget(when)
        layout.addLayout(texts, 1)
        if item.action is not None and item.action_label:
            button = QPushButton(item.action_label)
            button.setObjectName("GhostButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, act=item.action: self._run(act))
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _run(self, action: Callable[[], None]) -> None:
        self.close()
        action()

    def _clear(self) -> None:
        self._bell.clear()
        self.close()
