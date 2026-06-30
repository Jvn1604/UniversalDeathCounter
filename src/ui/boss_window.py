"""
Dialog for creating and deleting games and bosses.

Kept as a single dialog (rather than two) since the workflows are tightly
coupled: deleting a game cascades to its bosses, and you typically manage
both while setting up a new run.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
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


class BossWindow(QDialog):
    """Modal dialog for managing games and their bosses."""

    def __init__(self, database: Database, parent=None) -> None:
        super().__init__(parent)
        self._database = database
        self._selected_game_id: int | None = None

        self.setWindowTitle("Manage Games & Bosses")
        self.setMinimumSize(560, 420)
        self._build_ui()
        self._reload_games()

    # ----------------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        root_layout = QHBoxLayout(self)

        # --- Games column ---
        games_column = QVBoxLayout()
        games_column.addWidget(QLabel("Games"))
        self._games_list = QListWidget()
        self._games_list.currentItemChanged.connect(self._on_game_selected)
        games_column.addWidget(self._games_list)

        game_buttons = QHBoxLayout()
        add_game_btn = QPushButton("Create Game")
        add_game_btn.setObjectName("AccentButton")
        add_game_btn.clicked.connect(self._create_game)
        delete_game_btn = QPushButton("Delete Game")
        delete_game_btn.setObjectName("DangerButton")
        delete_game_btn.clicked.connect(self._delete_game)
        game_buttons.addWidget(add_game_btn)
        game_buttons.addWidget(delete_game_btn)
        games_column.addLayout(game_buttons)

        # --- Bosses column ---
        bosses_column = QVBoxLayout()
        bosses_column.addWidget(QLabel("Bosses"))
        self._bosses_list = QListWidget()
        bosses_column.addWidget(self._bosses_list)

        boss_buttons = QHBoxLayout()
        add_boss_btn = QPushButton("Create Boss")
        add_boss_btn.setObjectName("AccentButton")
        add_boss_btn.clicked.connect(self._create_boss)
        delete_boss_btn = QPushButton("Delete Boss")
        delete_boss_btn.setObjectName("DangerButton")
        delete_boss_btn.clicked.connect(self._delete_boss)
        boss_buttons.addWidget(add_boss_btn)
        boss_buttons.addWidget(delete_boss_btn)
        bosses_column.addLayout(boss_buttons)

        root_layout.addLayout(games_column)
        root_layout.addLayout(bosses_column)

    # ----------------------------------------------------------------
    # Data loading
    # ----------------------------------------------------------------
    def _reload_games(self) -> None:
        self._games_list.clear()
        for game in self._database.get_games():
            item = QListWidgetItem(game["name"])
            item.setData(256, game["id"])  # Qt.UserRole == 256
            self._games_list.addItem(item)

    def _reload_bosses(self) -> None:
        self._bosses_list.clear()
        if self._selected_game_id is None:
            return
        for boss in self._database.get_bosses(self._selected_game_id):
            item = QListWidgetItem(boss["name"])
            item.setData(256, boss["id"])
            self._bosses_list.addItem(item)

    # ----------------------------------------------------------------
    # Event handlers
    # ----------------------------------------------------------------
    def _on_game_selected(self, current: QListWidgetItem | None, _previous) -> None:
        self._selected_game_id = current.data(256) if current is not None else None
        self._reload_bosses()

    def _create_game(self) -> None:
        name, ok = QInputDialog.getText(self, "Create Game", "Game name:")
        if not ok or not name.strip():
            return
        try:
            self._database.create_game(name.strip())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not create game", str(exc))
            return
        self._reload_games()

    def _delete_game(self) -> None:
        item = self._games_list.currentItem()
        if item is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete Game",
            f"Delete '{item.text()}' and all of its bosses/history? This cannot be undone.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._database.delete_game(item.data(256))
        self._selected_game_id = None
        self._reload_games()
        self._reload_bosses()

    def _create_boss(self) -> None:
        if self._selected_game_id is None:
            QMessageBox.information(self, "Select a Game", "Select a game first.")
            return
        name, ok = QInputDialog.getText(self, "Create Boss", "Boss name:")
        if not ok or not name.strip():
            return
        try:
            self._database.create_boss(self._selected_game_id, name.strip())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not create boss", str(exc))
            return
        self._reload_bosses()

    def _delete_boss(self) -> None:
        item = self._bosses_list.currentItem()
        if item is None:
            return
        confirm = QMessageBox.question(
            self, "Delete Boss", f"Delete '{item.text()}' and its death history?"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._database.delete_boss(item.data(256))
        self._reload_bosses()
