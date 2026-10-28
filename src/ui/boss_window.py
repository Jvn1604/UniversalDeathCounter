"""
Dialog for creating, renaming, and deleting games and bosses, plus
one-click template setup and per-game session history management.

Kept as a single dialog since the workflows are tightly coupled: deleting
a game cascades to its bosses, and players typically manage both while
setting up a run.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
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
from src.ui.session_history_window import SessionHistoryWindow
from src.utils.game_templates import add_template_bosses, get_template, get_template_names
from src.utils.logger import get_logger

logger = get_logger(__name__)

_USER_ROLE = 256  # Qt.ItemDataRole.UserRole


def _plural(count: int, noun: str) -> str:
    """'1 death', '3 deaths', '2 bosses'."""
    if count == 1:
        return f"1 {noun}"
    return f"{count} {noun}es" if noun.endswith("s") else f"{count} {noun}s"


class BossWindow(QDialog):
    """Modal dialog for managing games and their bosses with full freedom."""

    def __init__(self, database: Database, parent=None) -> None:
        super().__init__(parent)
        self._database = database
        self._selected_game_id: int | None = None

        self.setWindowTitle("Manage Games & Bosses")
        self.setMinimumSize(640, 460)
        self._build_ui()
        self._reload_games()

    # ----------------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)

        columns_layout = QHBoxLayout()

        # --- Games column ---
        games_column = QVBoxLayout()
        games_column.addWidget(QLabel("Games"))
        self._games_list = QListWidget()
        self._games_list.currentItemChanged.connect(self._on_game_selected)
        self._games_list.itemDoubleClicked.connect(lambda _: self._rename_game())
        games_column.addWidget(self._games_list)

        game_buttons_row1 = QHBoxLayout()
        add_game_btn = QPushButton("Create Game")
        add_game_btn.setObjectName("AccentButton")
        add_game_btn.clicked.connect(self._create_game)
        rename_game_btn = QPushButton("Rename")
        rename_game_btn.clicked.connect(self._rename_game)
        game_buttons_row1.addWidget(add_game_btn)
        game_buttons_row1.addWidget(rename_game_btn)
        games_column.addLayout(game_buttons_row1)

        game_buttons_row2 = QHBoxLayout()
        history_btn = QPushButton("Session History")
        history_btn.clicked.connect(self._open_session_history)
        delete_game_btn = QPushButton("Delete Game")
        delete_game_btn.setObjectName("DangerButton")
        delete_game_btn.clicked.connect(self._delete_game)
        game_buttons_row2.addWidget(history_btn)
        game_buttons_row2.addWidget(delete_game_btn)
        games_column.addLayout(game_buttons_row2)

        # --- Quick-add template row ---
        template_row = QHBoxLayout()
        self._template_combo = QComboBox()
        self._template_combo.addItems(get_template_names())
        add_template_btn = QPushButton("Quick-Add Template")
        add_template_btn.clicked.connect(self._add_from_template)
        template_row.addWidget(self._template_combo)
        template_row.addWidget(add_template_btn)
        games_column.addLayout(template_row)

        # --- Bosses column ---
        bosses_column = QVBoxLayout()
        bosses_column.addWidget(QLabel("Bosses"))
        self._bosses_list = QListWidget()
        self._bosses_list.itemDoubleClicked.connect(lambda _: self._rename_boss())
        bosses_column.addWidget(self._bosses_list)

        boss_buttons = QHBoxLayout()
        add_boss_btn = QPushButton("Create Boss")
        add_boss_btn.setObjectName("AccentButton")
        add_boss_btn.clicked.connect(self._create_boss)
        rename_boss_btn = QPushButton("Rename")
        rename_boss_btn.clicked.connect(self._rename_boss)
        delete_boss_btn = QPushButton("Delete Boss")
        delete_boss_btn.setObjectName("DangerButton")
        delete_boss_btn.clicked.connect(self._delete_boss)
        boss_buttons.addWidget(add_boss_btn)
        boss_buttons.addWidget(rename_boss_btn)
        boss_buttons.addWidget(delete_boss_btn)
        bosses_column.addLayout(boss_buttons)

        defeated_row = QHBoxLayout()
        defeated_btn = QPushButton("Toggle Defeated ✓")
        defeated_btn.clicked.connect(self._toggle_defeated)
        defeated_row.addWidget(defeated_btn)
        bosses_column.addLayout(defeated_row)

        columns_layout.addLayout(games_column)
        columns_layout.addLayout(bosses_column)
        root_layout.addLayout(columns_layout)

        hint = QLabel("Tip: double-click any Game or Boss to rename it.")
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        root_layout.addWidget(hint)

    # ----------------------------------------------------------------
    # Data loading
    # ----------------------------------------------------------------
    def _reload_games(self) -> None:
        self._games_list.clear()
        for game in self._database.get_games():
            item = QListWidgetItem(game["name"])
            item.setData(_USER_ROLE, game["id"])
            self._games_list.addItem(item)

    def _reload_bosses(self) -> None:
        self._bosses_list.clear()
        if self._selected_game_id is None:
            return
        for boss in self._database.get_bosses(self._selected_game_id):
            prefix = "✓ " if boss["defeated"] else ""
            suffix = (
                f"  ({boss['deaths_at_defeat']} deaths to victory)" if boss["defeated"] else ""
            )
            item = QListWidgetItem(f"{prefix}{boss['name']}{suffix}")
            item.setData(_USER_ROLE, boss["id"])
            self._bosses_list.addItem(item)

    def _toggle_defeated(self) -> None:
        item = self._bosses_list.currentItem()
        if item is None:
            return
        boss_id = item.data(_USER_ROLE)
        boss = self._database.get_boss(boss_id)
        if boss is None:
            return
        self._database.set_boss_defeated(boss_id, not bool(boss["defeated"]))
        self._reload_bosses()

    # ----------------------------------------------------------------
    # Event handlers — Games
    # ----------------------------------------------------------------
    def _on_game_selected(self, current: QListWidgetItem | None, _previous) -> None:
        self._selected_game_id = current.data(_USER_ROLE) if current is not None else None
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

    def _rename_game(self) -> None:
        item = self._games_list.currentItem()
        if item is None:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Game", "New name:", text=item.text())
        if not ok or not new_name.strip():
            return
        try:
            self._database.rename_game(item.data(_USER_ROLE), new_name.strip())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not rename game", str(exc))
            return
        self._reload_games()

    def _delete_game(self) -> None:
        item = self._games_list.currentItem()
        if item is None:
            return
        game_id = item.data(_USER_ROLE)
        confirm = QMessageBox.warning(
            self,
            "Delete Game",
            f"Delete '{item.text()}'?\n\n{self._what_goes(game_id)}\n\n"
            "This can't be undone. Export a backup first (⋮ at the top → Export Backup) "
            "if you might want them back.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._database.delete_game(game_id)
        self._selected_game_id = None
        self._reload_games()
        self._reload_bosses()

    def _what_goes(self, game_id: int) -> str:
        """What deleting a game removes, in numbers (e.g. "This removes 412 deaths, …")."""
        db = self._database
        counts = (
            (db.get_total_deaths(game_id), "death"),
            (len(db.get_bosses(game_id)), "boss"),
            (db.get_total_sessions(game_id), "session"),
            (db.count_speedrun_attempts(game_id), "speedrun attempt"),
        )
        parts = [_plural(count, noun) for count, noun in counts if count]
        if not parts:
            return "It has no deaths, bosses or runs yet."
        listed = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
        return f"This permanently removes {listed}."

    def _add_from_template(self) -> None:
        template = get_template(self._template_combo.currentText())
        if template is None:
            return
        existing_names = {g["name"] for g in self._database.get_games()}
        game_name = template.name
        if game_name in existing_names:
            confirm = QMessageBox.question(
                self,
                "Game Already Exists",
                f"'{game_name}' already exists. Add its bosses to the existing game anyway?",
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        _game_id, added = add_template_bosses(self._database, template)

        self._reload_games()
        QMessageBox.information(
            self, "Template Added", f"Added '{game_name}' with {added} new boss(es)."
        )

    def _open_session_history(self) -> None:
        if self._selected_game_id is None:
            QMessageBox.information(self, "Select a Game", "Select a game first.")
            return
        dialog = SessionHistoryWindow(self._database, self._selected_game_id, parent=self)
        dialog.exec()

    # ----------------------------------------------------------------
    # Event handlers — Bosses
    # ----------------------------------------------------------------
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

    def _rename_boss(self) -> None:
        item = self._bosses_list.currentItem()
        if item is None:
            return
        boss = self._database.get_boss(item.data(_USER_ROLE))
        if boss is None:
            return
        new_name, ok = QInputDialog.getText(
            self, "Rename Boss", "New name:", text=boss["name"]
        )
        if not ok or not new_name.strip():
            return
        try:
            self._database.rename_boss(item.data(_USER_ROLE), new_name.strip())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not rename boss", str(exc))
            return
        self._reload_bosses()

    def _delete_boss(self) -> None:
        item = self._bosses_list.currentItem()
        if item is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete Boss",
            f"Delete '{item.text()}'?\n\nIts deaths stay in the game's totals, "
            "counted as \"No boss\".",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._database.delete_boss(item.data(_USER_ROLE))
        self._reload_bosses()
