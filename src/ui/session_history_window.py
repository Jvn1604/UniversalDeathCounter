"""Dialog for reviewing, continuing and deleting past play sessions for a game."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
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

_USER_ROLE = Qt.ItemDataRole.UserRole


def _when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%a %d %b, %H:%M")
    except ValueError:
        return iso


def _length(started: str, ended: str | None) -> str:
    try:
        seconds = (datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds()
    except (TypeError, ValueError):
        return ""
    minutes = max(0, int(seconds // 60))
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def session_label(session, current_id: int | None = None) -> str:
    """One line per session: when, how long, how many deaths."""
    deaths = session["deaths"]
    parts = [_when(session["started_at"])]
    if session["id"] == current_id:
        parts.append("now")
    elif session["ended_at"]:
        parts.append(_length(session["started_at"], session["ended_at"]))
    parts.append(f"{deaths} death{'' if deaths == 1 else 's'}")
    return "   ·   ".join(part for part in parts if part)


class SessionHistoryWindow(QDialog):
    """
    Modal dialog listing every recorded session for one game.

    With ``can_continue``, a **Continue This Session** button closes the
    dialog with :attr:`continue_session_id` set; the main window then makes
    that session the active one again.
    """

    def __init__(
        self,
        database: Database,
        game_id: int,
        parent=None,
        can_continue: bool = False,
        current_session_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._database = database
        self._game_id = game_id
        self._can_continue = can_continue
        self._current_session_id = current_session_id
        self.continue_session_id: int | None = None

        game = database.get_game(game_id)
        game_name = game["name"] if game is not None else "Unknown Game"
        self.setWindowTitle(f"Sessions: {game_name}")
        self.setMinimumSize(460, 440)
        self._build_ui()
        self._reload_sessions()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        intro = (
            "Pick a session to keep counting in it: its deaths come back as this "
            "session's count. Newest first."
            if self._can_continue
            else "Every session of this game, newest first."
        )
        hint = QLabel(intro)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._sessions_list = QListWidget()
        self._sessions_list.currentItemChanged.connect(self._update_buttons)
        self._sessions_list.itemDoubleClicked.connect(self._continue_selected)
        layout.addWidget(self._sessions_list)

        button_row = QHBoxLayout()
        self._delete_btn = QPushButton("Delete Selected Session")
        self._delete_btn.setObjectName("DangerButton")
        self._delete_btn.clicked.connect(self._delete_selected)
        button_row.addWidget(self._delete_btn)
        button_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        button_row.addWidget(close_btn)
        self._continue_btn = QPushButton("Continue This Session")
        self._continue_btn.setObjectName("AccentButton")
        self._continue_btn.clicked.connect(self._continue_selected)
        self._continue_btn.setVisible(self._can_continue)
        button_row.addWidget(self._continue_btn)
        layout.addLayout(button_row)

    def _reload_sessions(self) -> None:
        self._sessions_list.clear()
        sessions = self._database.get_sessions_with_counts(self._game_id)
        if not sessions:
            self._sessions_list.addItem(QListWidgetItem("No sessions recorded yet."))
        for session in sessions:
            item = QListWidgetItem(session_label(session, self._current_session_id))
            item.setData(_USER_ROLE, session["id"])
            self._sessions_list.addItem(item)
        if sessions:
            self._sessions_list.setCurrentRow(0)
        self._update_buttons()

    def _selected_id(self) -> int | None:
        item = self._sessions_list.currentItem()
        return item.data(_USER_ROLE) if item is not None else None

    def _update_buttons(self, *_args) -> None:
        selected = self._selected_id()
        self._delete_btn.setEnabled(selected is not None and selected != self._current_session_id)
        self._continue_btn.setEnabled(
            selected is not None and selected != self._current_session_id
        )

    def _continue_selected(self, *_args) -> None:
        selected = self._selected_id()
        if not self._can_continue or selected is None or selected == self._current_session_id:
            return
        self.continue_session_id = int(selected)
        self.accept()

    def _delete_selected(self) -> None:
        selected = self._selected_id()
        if selected is None or selected == self._current_session_id:
            return
        confirm = QMessageBox.question(
            self, "Delete Session", "Delete this session and its death events?"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._database.delete_session(selected)
        self._reload_sessions()
