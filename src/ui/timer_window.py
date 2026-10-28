"""
Speedrun timer window and splits editor.

:class:`TimerWindow` is a second OBS-capturable window (same styling as the
overlay) showing the splits, the big timer and deaths this run. It repaints
on a ~30 fps timer only while a run is going, so an idle timer costs nothing.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent, QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QTableWidget,
    QTableWidgetItem,
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
    format_time,
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
            "skip", "reset", "edit_splits", "history" or "hide".
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
        # Why the clock isn't moving (Paused / Loading…) and the other clock.
        self._sub_label = QLabel()
        self._sub_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._sub_label)
        self._segment_label = QLabel()
        self._segment_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._segment_label)
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
        self._segment_label.setStyleSheet(f"color: {secondary}; font-size: 11px; {font}")
        self._sub_label.setStyleSheet(f"color: {secondary}; font-size: 11px; {font}")
        self.apply_outline(
            (
                self._title_label,
                self._attempts_label,
                self._time_label,
                self._sub_label,
                self._segment_label,
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
            ("Run History && Records…", "history"),
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
        sub = "   ".join(part for part in (view.paused_reason, view.other_time) if part)
        if self._sub_label.text() != sub:
            self._sub_label.setText(sub)
        static = (
            view.rows,
            view.attempts,
            view.deaths,
            view.pb,
            view.previous_segment,
            view.comparison,
        )
        if previous is None or static != (
            previous.rows,
            previous.attempts,
            previous.deaths,
            previous.pb,
            previous.previous_segment,
            previous.comparison,
        ):
            self._render_static(view)
        if view.state != RUNNING or not self.isVisible():
            self._tick.stop()  # the time isn't moving, or nobody can see it
        elif not self._tick.isActive():
            self._tick.start()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()  # catch up, and start ticking if a run is going

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        super().hideEvent(event)
        self._tick.stop()

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
        segment = "-"
        if view.previous_segment:
            color = _STATUS_COLORS.get(view.previous_segment_status, secondary)
            segment = (
                f'<span style="color: {color}; font-weight: 600;">'
                f"{view.previous_segment}</span>"
            )
        self._segment_label.setText(f"Previous segment {segment}   •   vs {view.comparison}")
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


def _local_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


class RunHistoryDialog(QDialog):
    """Every attempt for the current splits, plus personal records."""

    def __init__(
        self,
        database: Database,
        controller: SpeedrunController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._database = database
        self._controller = controller
        self.changed = False
        self.setWindowTitle(f"Run History & Records: {controller.game_name}")
        self.setMinimumSize(640, 480)

        layout = QVBoxLayout(self)
        self._records_label = QLabel()
        self._records_label.setTextFormat(Qt.TextFormat.RichText)
        self._records_label.setWordWrap(True)
        self._records_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._records_label)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["#", "Date", "Result", "Real time", "Game time", "Deaths"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Result takes the rest
        layout.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        self._delete_button = QPushButton("Delete Selected Run")
        self._delete_button.setObjectName("DangerButton")
        self._delete_button.clicked.connect(self._delete_selected)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(self._delete_button)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._populate()

    def _populate(self) -> None:
        controller = self._controller
        names = controller.timer.split_names
        runs = controller.runs
        records = controller.records()
        digits = controller.digits
        pb = records.pb

        lines = [f"<b>Attempts:</b> {records.attempts} &nbsp; <b>Finished:</b> {records.finished}"]
        if pb is not None:
            lines.append(
                f"<b>🏆 Personal best:</b> {format_time(pb.total(controller.method), digits)} "
                f"({pb.deaths} deaths, {_local_time(pb.started_at)})"
            )
        if records.fewest_deaths is not None and records.fewest_deaths is not pb:
            run = records.fewest_deaths
            lines.append(
                f"<b>💀 Fewest deaths:</b> {run.deaths} in "
                f"{format_time(run.total(controller.method), digits)} "
                f"({_local_time(run.started_at)})"
            )
        lines.append(f"<b>Sum of best:</b> {format_time(records.sum_of_best, digits)}")
        golds = ", ".join(
            f"{name} {format_time(best, digits)}"
            for name, best in records.best_segments
            if best is not None
        )
        if golds:
            lines.append(f"<b>Best segments:</b> {golds}")
        if controller.game_id is not None:
            lines += self._death_records(controller.game_id)
        self._records_label.setText("<br>".join(lines))

        self._table.setRowCount(len(runs))
        for row, (number, run) in enumerate(reversed(list(enumerate(runs, start=1)))):
            if run.finished:
                result = "Finished"
            else:  # the split it was on when reset
                reached = min(len(run.split_times), len(names) - 1)
                result = f"Reset at {names[reached]}"
            is_pb = pb is not None and run is pb
            cells = [
                str(number),
                _local_time(run.started_at),
                ("🏆 PB  " if is_pb else "") + result,
                format_time(_last(run.split_times), digits),
                format_time(_last(run.times("game")), digits),
                str(run.deaths),
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, run.run_id)
                self._table.setItem(row, column, item)
        self._delete_button.setEnabled(bool(runs) and not controller.running)

    def _death_records(self, game_id: int) -> list[str]:
        """Death-counter records: easiest boss victory and the roughest session."""
        lines: list[str] = []
        victories = [
            boss
            for boss in self._database.get_bosses(game_id)
            if boss["defeated"] and boss["deaths_at_defeat"] is not None
        ]
        if victories:
            best = min(victories, key=lambda boss: boss["deaths_at_defeat"])
            lines.append(
                f"<b>Fewest deaths to beat a boss:</b> {best['deaths_at_defeat']} "
                f"({best['name']})"
            )
        sessions = self._database.get_sessions_with_counts(game_id)
        if sessions:
            worst = max(sessions, key=lambda session: session["deaths"])
            if worst["deaths"] > 0:
                lines.append(
                    f"<b>Most deaths in a session:</b> {worst['deaths']} "
                    f"({_local_time(worst['started_at'])})"
                )
        return lines

    def _delete_selected(self) -> None:
        row = self._table.currentRow()
        item = self._table.item(row, 0) if row >= 0 else None
        run_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if run_id is None:
            return
        confirm = QMessageBox.question(
            self, "Delete Run", "Delete this run from the history? This can't be undone."
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._database.delete_speedrun_run(int(run_id))
        game_id = self._controller.game_id
        if game_id is not None:
            self._controller.set_runs(
                self._database.get_speedrun_runs(game_id, self._controller.timer.split_names)
            )
        self.changed = True
        self._populate()


def _last(times: list[int | None]) -> int | None:
    return next((t for t in reversed(times) if t is not None), None)
