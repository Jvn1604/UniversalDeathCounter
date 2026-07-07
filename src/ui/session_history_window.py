"""Dialog for reviewing and deleting past play sessions for a game."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.database.database import Database
from src.utils.logger import get_logger

logger = get_logger(__name__)

_USER_ROLE = 256


class SessionHistoryWindow(QDialog):
    """Modal dialog listing every recorded session for one game."""

    def __init__(self, database: Database, game_id: int, parent=None) -> None:
        super().__init__(parent)
        self._database = database
        self._game_id = game_id

        game = database.get_game(game_id)
        game_name = game["name"] if game is not None else "Unknown Game"
        self.setWindowTitle(f"Session History — {game_name}")
        self.setMinimumSize(420, 420)
        self._build_ui()
        self._reload_sessions()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Each entry shows when a session started and its death count."))

        self._sessions_list = QListWidget()
        layout.addWidget(self._sessions_list)

        button_row = QHBoxLayout()
        delete_btn = QPushButton("Delete Selected Session")
        delete_btn.setObjectName("DangerButton")
        delete_btn.clicked.connect(self._delete_selected)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("AccentButton")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(delete_btn)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _reload_sessions(self) -> None:
        self._sessions_list.clear()
        sessions = self._database.get_sessions_with_counts(self._game_id)
        if not sessions:
            self._sessions_list.addItem(QListWidgetItem("No sessions recorded yet."))
            return
        for session in sessions:
            status = "Ended" if session["ended_at"] else "In Progress"
            label = f"Started {session['started_at']}  —  {session['deaths']} death(s)  [{status}]"
            item = QListWidgetItem(label)
            item.setData(_USER_ROLE, session["id"])
            self._sessions_list.addItem(item)

    def _delete_selected(self) -> None:
        item = self._sessions_list.currentItem()
        if item is None or item.data(_USER_ROLE) is None:
            return
        confirm = QMessageBox.question(
            self, "Delete Session", "Delete this session and its death events?"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._database.delete_session(item.data(_USER_ROLE))
        self._reload_sessions()
