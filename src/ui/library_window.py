"""
The setups library: ready-made auto-detect setups from other players.

Lists the online library (fetched in the background), applies one to the
selected game, imports a setup file, or saves the game's own setup to share.
"""

from __future__ import annotations

import threading
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.database.database import Database
from src.ui import icons
from src.utils import presets
from src.utils.constants import GITHUB_REPO
from src.utils.logger import get_logger

logger = get_logger(__name__)

_ROLE = Qt.ItemDataRole.UserRole
_MODE_NAMES = {"template": "death screen", "souls": "Souls preset", "health": "health bar",
               "log": "log file"}


class Fetcher(QObject):
    """Runs a library request on a worker thread; the result comes back as a signal."""

    done = Signal(object, str)  # result, error text

    def run(self, job) -> None:
        def work() -> None:
            try:
                self.done.emit(job(), "")
            except (OSError, presets.PresetError) as exc:
                self.done.emit(None, str(exc))

        threading.Thread(target=work, name="setups-library", daemon=True).start()


class LibraryDialog(QDialog):
    """
    Signals:
        applied: A setup was applied to the game (the main window reloads detection).
    """

    applied = Signal(str)  # the setup's game name

    def __init__(self, database: Database, game_id: int, game_name: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._database, self._game_id, self._game_name = database, game_id, game_name
        self._entries: list[presets.LibraryEntry] = []
        self.setWindowTitle("Setups Library")
        self.resize(560, 520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        intro = QLabel(
            f"Ready-made auto-detect setups from other players. Pick your game and "
            f"<b>Use for {game_name}</b>: deaths then count by themselves, no "
            "calibrating. Only reading the screen, as always."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search games…")
        self._search.textChanged.connect(self._fill)
        layout.addWidget(self._search)
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _item: self._use_selected())
        self._list.currentItemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self._list, 1)
        self._status = QLabel("Loading the library…")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._use_btn = QPushButton(f" Use for {game_name}")
        self._use_btn.setObjectName("AccentButton")
        icons.set_icon(self._use_btn, "download", icons.ACCENT, size=16)
        self._use_btn.clicked.connect(self._use_selected)
        import_btn = QPushButton(" Import File…")
        icons.set_icon(import_btn, "folder-open", size=16)
        import_btn.clicked.connect(self._import_file)
        share_btn = QPushButton(" Share My Setup…")
        icons.set_icon(share_btn, "save", size=16)
        share_btn.setToolTip(f"Save {game_name}'s setup as a file to send in or give a friend.")
        share_btn.clicked.connect(self._share)
        buttons = QHBoxLayout()
        buttons.addWidget(self._use_btn)
        buttons.addStretch()
        buttons.addWidget(import_btn)
        buttons.addWidget(share_btn)
        layout.addLayout(buttons)
        self._update_buttons()

        self._fetcher = Fetcher(self)
        self._fetcher.done.connect(self._on_list)
        self._fetcher.run(presets.fetch_library)

    # ---------------------------------------------------------------- the list
    def _on_list(self, entries, error: str) -> None:
        if error:
            self._status.setText(f"Couldn't load the library: {error}. Import File still works.")
            return
        self._entries = entries
        self._fill()
        detection = self._database.get_game_detection(self._game_id)
        exe = Path(detection["exe_path"] or "").name if detection is not None else ""
        name = self._game_name.casefold()
        for row in range(self._list.count()):
            entry = self._list.item(row).data(_ROLE)
            if (exe and entry.matches_exe(exe)) or entry.game.casefold() == name:
                self._list.setCurrentRow(row)  # this game's setup, chosen for you
                break

    def _fill(self) -> None:
        query = self._search.text().strip().casefold()
        self._list.clear()
        for entry in self._entries:
            if query and query not in entry.game.casefold():
                continue
            how = _MODE_NAMES.get(entry.mode, entry.mode)
            detail = f"{how}, {entry.screens} screen{'s' if entry.screens != 1 else ''}"
            if entry.author:
                detail += f", shared by {entry.author}"
            item = QListWidgetItem(f"{entry.game}    ·    {detail}")
            item.setData(_ROLE, entry)
            self._list.addItem(item)
        count = self._list.count()
        self._status.setText(
            f"{count} game{'s' if count != 1 else ''} in the library." if self._entries
            else "The library is empty for now."
        )
        self._update_buttons()

    def _update_buttons(self) -> None:
        self._use_btn.setEnabled(self._list.currentItem() is not None)

    # ---------------------------------------------------------------- actions
    def _use_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        entry: presets.LibraryEntry = item.data(_ROLE)
        self._status.setText(f"Downloading the {entry.game} setup…")
        self._use_btn.setEnabled(False)
        fetcher = Fetcher(self)
        fetcher.done.connect(lambda preset, error: self._apply(preset, error))
        fetcher.run(lambda: presets.fetch_preset(entry))

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a Setup", "", f"DUDC setups (*{presets.PRESET_SUFFIX});;All files (*)"
        )
        if not path:
            return
        try:
            self._apply(presets.read_preset(path), "")
        except (OSError, presets.PresetError) as exc:
            QMessageBox.warning(self, "Import a Setup", str(exc))

    def _apply(self, preset, error: str) -> None:
        self._update_buttons()
        if error or preset is None:
            self._status.setText(f"Couldn't get that setup: {error}")
            return
        own = sum(len(self._database.get_death_templates(self._game_id, kind))
                  for kind in ("death", "victory", "pause"))
        if own and QMessageBox.question(
            self, "Use This Setup?",
            f"{self._game_name} already has {own} saved screen{'s' if own != 1 else ''}. "
            f"Replace them with the {preset['game']} setup?",
        ) != QMessageBox.StandardButton.Yes:
            self._status.setText("Kept your own setup.")
            return
        presets.apply_preset(self._database, self._game_id, preset)
        logger.info("Applied the %s setup to game_id=%s", preset["game"], self._game_id)
        self.applied.emit(preset["game"])
        self.accept()

    def _share(self) -> None:
        try:
            preset = presets.export_preset(self._database, self._game_id)
        except presets.PresetError as exc:
            QMessageBox.information(self, "Share My Setup", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Share My Setup", presets.preset_file_name(preset),
            f"DUDC setups (*{presets.PRESET_SUFFIX})",
        )
        if not path:
            return
        presets.write_preset(path, preset)
        answer = QMessageBox.question(
            self, "Setup Saved",
            f"Saved to {Path(path).name}.\n\nAdd it to the library so others can use it? "
            "That opens a GitHub issue: attach the file there.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            title = urllib.parse.quote(f"Setup for the library: {preset['game']}")
            QDesktopServices.openUrl(
                QUrl(f"https://github.com/{GITHUB_REPO}/issues/new?title={title}"
                     "&labels=setup")
            )
