"""
Speedrun timer window and splits editor.

:class:`TimerWindow` is a second OBS-capturable window (same styling as the
overlay) showing the splits, the big timer and deaths this run. It repaints
on a ~30 fps timer only while a run is going, so an idle timer costs nothing.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from src.core.speedrun import (
    AHEAD,
    BEHIND,
    GOLD,
    RUNNING,
    SpeedrunController,
    TimerView,
)
from src.database.database import Database
from src.overlay.capture_window import CaptureWindow
from src.utils.logger import get_logger

logger = get_logger(__name__)

TIMER_WINDOW_TITLE = "DUDC Timer"
_TICK_MS = 33  # ~30 fps while running
_MAX_ROWS = 8
_STATUS_COLORS = {AHEAD: "#3ad07a", BEHIND: "#ff5c5c", GOLD: "#ffd24a"}


class TimerWindow(CaptureWindow):
    """
    Frameless, always-on-top speedrun timer for streaming.

    Signals:
        action_requested: From the right-click menu: "split", "pause", "undo",
            "skip", "reset", "edit_splits" or "hide".
    """

    action_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(TIMER_WINDOW_TITLE, parent)
        self._controller: SpeedrunController | None = None
        self.setMinimumSize(240, 180)
        self.resize(300, 340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(4)
        self._title_label = QLabel()
        self._attempts_label = QLabel()
        header = QHBoxLayout()
        header.addWidget(self._title_label, 1)
        header.addWidget(self._attempts_label)
        layout.addLayout(header)

        self._rows: list[tuple[QLabel, QLabel, QLabel]] = []
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(0, 1)
        for row in range(_MAX_ROWS):
            labels = (QLabel(), QLabel(), QLabel())
            labels[1].setAlignment(Qt.AlignmentFlag.AlignRight)
            labels[2].setAlignment(Qt.AlignmentFlag.AlignRight)
            for column, label in enumerate(labels):
                grid.addWidget(label, row, column)
            self._rows.append(labels)
        layout.addLayout(grid)
        layout.addStretch()

        self._time_label = QLabel("0:00.00")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._time_label)
        self._footer_label = QLabel()
        self._footer_label.setWordWrap(True)
        layout.addWidget(self._footer_label)
        layout.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignRight)

        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self.refresh)
        self._last_view: TimerView | None = None
        self._restyle()

    # ----------------------------------------------------------------
    # Styling
    # ----------------------------------------------------------------
    def apply_display_settings(self, settings: dict[str, str]) -> None:
        """Use the overlay's Appearance settings (background, font, colors)."""
        self.apply_style_settings(settings)
        self._restyle()
        self._last_view = None  # force label colors to be re-applied
        self.refresh()

    def _restyle(self) -> None:
        secondary, font = self.secondary_color(), self.font_css()
        self._title_label.setStyleSheet(f"color: {secondary}; font-weight: 600; {font}")
        self._attempts_label.setStyleSheet(f"color: {secondary}; font-size: 11px; {font}")
        self._footer_label.setStyleSheet(f"color: {secondary}; font-size: 11px; {font}")
        self.apply_outline(
            (
                self._title_label,
                self._attempts_label,
                self._time_label,
                self._footer_label,
                *(label for row in self._rows for label in row),
            )
        )

    def _style_time(self, status: str) -> None:
        color = _STATUS_COLORS.get(status, self._text_color)
        self._time_label.setStyleSheet(
            f"color: {color}; font-size: 34px; font-weight: 800; {self.font_css()}"
        )

    # ----------------------------------------------------------------
    # Content
    # ----------------------------------------------------------------
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        """Right-click: the timer controls, for anyone not using hotkeys."""
        menu = QMenu(self)
        for label, action in (
            ("Start / Split", "split"),
            ("Pause / Resume", "pause"),
            ("Undo Split", "undo"),
            ("Skip Split", "skip"),
            ("Reset", "reset"),
            (None, ""),
            ("Edit Splits…", "edit_splits"),
            ("Hide Timer", "hide"),
        ):
            if label is None:
                menu.addSeparator()
                continue
            item = menu.addAction(label)
            item.triggered.connect(lambda _=False, a=action: self.action_requested.emit(a))
        menu.exec(event.globalPos())

    def set_controller(self, controller: SpeedrunController | None) -> None:
        self._controller = controller
        self._last_view = None
        self.refresh()

    def refresh(self) -> None:
        """Re-render from the controller; keeps ticking only while a run is going."""
        controller = self._controller
        if controller is None:
            self._tick.stop()
            return
        view = controller.view(_MAX_ROWS)
        previous, self._last_view = self._last_view, view
        if previous is None or previous.time_status != view.time_status:
            self._style_time(view.time_status)
        self._time_label.setText(view.time)
        if previous is None or (previous.rows, previous.attempts, previous.deaths, previous.pb) != (
            view.rows,
            view.attempts,
            view.deaths,
            view.pb,
        ):
            self._render_static(view)
        if view.state != RUNNING:
            self._tick.stop()  # paused, finished or idle: the time doesn't move
        elif not self._tick.isActive():
            self._tick.start()

    def _render_static(self, view: TimerView) -> None:
        """Everything but the big time, which changes every tick."""
        secondary, font = self.secondary_color(), self.font_css()
        self._title_label.setText(view.game_name or "No game selected")
        self._attempts_label.setText(f"#{view.attempts}" if view.attempts else "")
        for index, (name, delta, time) in enumerate(self._rows):
            if index >= len(view.rows):
                for label in (name, delta, time):
                    label.setText("")
                continue
            row = view.rows[index]
            weight = "700" if row.current else "400"
            name.setText(("▸ " if row.current else "") + row.name)
            name.setStyleSheet(f"color: {secondary}; font-weight: {weight}; {font}")
            delta.setText(row.delta)
            delta.setStyleSheet(
                f"color: {_STATUS_COLORS.get(row.delta_status, secondary)}; "
                f"font-weight: 600; {font}"
            )
            time.setText(row.time)
            time.setStyleSheet(f"color: {secondary}; {font}")
        deaths = f"Deaths {view.deaths}"
        if view.pb_deaths is not None:
            deaths += f" (PB run {view.pb_deaths})"
        self._footer_label.setText(
            f"{deaths}   •   PB {view.pb}   •   Sum of best {view.sum_of_best}"
        )


class SplitsDialog(QDialog):
    """Edit a game's split names; also clears its attempt history."""

    def __init__(
        self, database: Database, game_id: int, game_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._database = database
        self._game_id = game_id
        self.history_cleared = False
        self.setWindowTitle(f"Splits: {game_name}")
        self.setMinimumSize(380, 420)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "One split per checkpoint, in order (usually each boss). Double-click to "
            "rename. The last split ends the run. Changing the splits starts a fresh "
            "PB, since times only compare against runs with the same splits."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        body = QHBoxLayout()
        self._list = QListWidget()
        body.addWidget(self._list, 1)
        side = QVBoxLayout()
        for text, handler in (
            ("Add", self._add),
            ("Remove", self._remove),
            ("Move Up", lambda: self._move(-1)),
            ("Move Down", lambda: self._move(+1)),
            ("Use Boss List", self._use_bosses),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            side.addWidget(button)
        side.addStretch()
        clear = QPushButton("Clear History…")
        clear.setObjectName("DangerButton")
        clear.setToolTip("Delete every attempt for this game: PB, golds and attempt count.")
        clear.clicked.connect(self._clear_history)
        side.addWidget(clear)
        body.addLayout(side)
        layout.addLayout(body)

        save = QPushButton("Save")
        save.setObjectName("AccentButton")
        save.clicked.connect(self._save)
        layout.addWidget(save)

        for name in database.get_speedrun_splits(game_id):
            self._append(name)

    def _append(self, name: str) -> QListWidgetItem:
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._list.addItem(item)
        return item

    def names(self) -> list[str]:
        names = (self._list.item(i).text().strip() for i in range(self._list.count()))
        return [name for name in names if name]

    def _add(self) -> None:
        item = self._append(f"Split {self._list.count() + 1}")
        self._list.setCurrentItem(item)
        self._list.editItem(item)

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)

    def _move(self, step: int) -> None:
        row = self._list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self._list.count():
            return
        item = self._list.takeItem(row)
        self._list.insertItem(target, item)
        self._list.setCurrentRow(target)

    def _use_bosses(self) -> None:
        bosses = [boss["name"] for boss in self._database.get_bosses(self._game_id)]
        if not bosses:
            QMessageBox.information(self, "No Bosses", "This game has no bosses yet.")
            return
        self._list.clear()
        for name in bosses:
            self._append(name)

    def _clear_history(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Clear History",
            "Delete every attempt for this game? Your PB, golds and attempt count "
            "start over. This can't be undone.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._database.clear_speedrun_runs(self._game_id)
            self.history_cleared = True

    def _save(self) -> None:
        self._database.set_speedrun_splits(self._game_id, self.names())
        self.accept()
