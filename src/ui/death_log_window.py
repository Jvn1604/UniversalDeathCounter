"""
Death Log dialog: browse recent death events and attach notes to them.

Double-click any entry (or use the button) to add/edit a note like
"fell off cliff" or "phase 2 grab" — great for post-run review.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from src.database.database import Database
from src.utils.logger import get_logger

logger = get_logger(__name__)

_USER_ROLE = 256


class DeathLogWindow(QDialog):
    """Modal dialog listing recent death events for a game with notes."""

    def __init__(self, database: Database, game_id: int, game_name: str, parent=None) -> None:
        super().__init__(parent)
        self._database = database
        self._game_id = game_id

        self.setWindowTitle(f"Death Log — {game_name}")
        self.setMinimumSize(520, 440)
        self._build_ui()
        self._reload_events()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Double-click any death to add or edit a note."))

        self._events_list = QListWidget()
        self._events_list.itemDoubleClicked.connect(lambda _: self._edit_note())
        layout.addWidget(self._events_list)

        button_row = QHBoxLayout()
        note_btn = QPushButton("Add / Edit Note")
        note_btn.setObjectName("AccentButton")
        note_btn.clicked.connect(self._edit_note)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(note_btn)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _reload_events(self) -> None:
        self._events_list.clear()
        events = self._database.get_recent_events(self._game_id)
        if not events:
            self._events_list.addItem(QListWidgetItem("No deaths recorded yet."))
            return
        for event in events:
            sign = "+" if event["delta"] > 0 else ""
            boss = event["boss_name"] or "(no boss)"
            note = f"  —  📝 {event['note']}" if event["note"] else ""
            label = f"{event['timestamp']}   {sign}{event['delta']}   {boss}{note}"
            item = QListWidgetItem(label)
            item.setData(_USER_ROLE, event["id"])
            self._events_list.addItem(item)

    def _edit_note(self) -> None:
        item = self._events_list.currentItem()
        if item is None or item.data(_USER_ROLE) is None:
            return
        event_id = item.data(_USER_ROLE)
        events = {e["id"]: e for e in self._database.get_recent_events(self._game_id)}
        current_note = events.get(event_id)["note"] if event_id in events else ""
        note, ok = QInputDialog.getText(
            self, "Death Note", "Note for this death:", text=current_note or ""
        )
        if not ok:
            return
        self._database.set_event_note(event_id, note.strip())
        self._reload_events()
