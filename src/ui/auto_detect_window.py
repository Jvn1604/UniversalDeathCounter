"""
Auto death detection dialogs.

* :class:`AutoDetectWindow` — per-game setup: pick the game's .exe, the
  detection method, calibration, and the cooldown between deaths.
* :class:`CalibrationDialog` — shows a screenshot of the death screen and
  lets the player drag a box around the death text (e.g. "YOU DIED").
* :class:`HealthBarDialog` — the same, for marking the health bar.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRubberBand,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.database.database import SCREEN_DEATH, SCREEN_PAUSE, SCREEN_VICTORY, Database
from src.detection.game_window import detection_available
from src.detection.log_watcher import compile_death_pattern, scan_log
from src.detection.matchers import SOULS_PRESET_EXES, DeathTemplate, HealthBar, Region
from src.utils.constants import (
    DETECTION_MODE_HEALTH,
    DETECTION_MODE_LOG,
    DETECTION_MODE_OFF,
    DETECTION_MODE_SOULS,
    DETECTION_MODE_TEMPLATE,
    OPTION_OBS_SOURCE,
    SETTING_DETECTION_COOLDOWN,
    SETTING_HOTKEY_CALIBRATE,
    SETTING_HOTKEY_INCREMENT,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_MODE_LABELS: tuple[tuple[str, str], ...] = (
    (DETECTION_MODE_OFF, "Off"),
    (DETECTION_MODE_TEMPLATE, "Calibrated death screen (any game)"),
    (DETECTION_MODE_SOULS, "Souls preset (red \"YOU DIED\" / 死 text)"),
    (DETECTION_MODE_HEALTH, "Health bar empties (games without a death screen)"),
    (DETECTION_MODE_LOG, "Game log file (e.g. Minecraft)"),
)
_MAX_PREVIEW = QSize(1100, 650)


# ----------------------------------------------------------------
# numpy <-> Qt image conversion
# ----------------------------------------------------------------
def frame_to_qimage(frame: np.ndarray) -> QImage:
    """Convert an ``(H, W, 3)`` RGB uint8 array to a QImage (deep copy)."""
    height, width = frame.shape[:2]
    data = np.ascontiguousarray(frame[..., :3])
    return QImage(data.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()


def qimage_to_frame(image: QImage) -> np.ndarray:
    """Convert any QImage to an ``(H, W, 3)`` RGB uint8 array."""
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height, stride = rgb.width(), rgb.height(), rgb.bytesPerLine()
    buffer = np.frombuffer(rgb.constBits(), dtype=np.uint8, count=stride * height)
    return buffer.reshape(height, stride)[:, : width * 3].reshape(height, width, 3).copy()


# ----------------------------------------------------------------
# Calibration
# ----------------------------------------------------------------
class _RegionSelector(QLabel):
    """Displays a screenshot and lets the user drag out a selection box."""

    selection_changed = Signal()

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._origin = QPoint()
        self._selection = QRect()

    def _clamp(self, point: QPoint) -> QPoint:
        return QPoint(
            min(max(point.x(), 0), self.width() - 1), min(max(point.y(), 0), self.height() - 1)
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._origin = self._clamp(event.position().toPoint())
        self._band.setGeometry(QRect(self._origin, QSize()))
        self._band.show()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        current = self._clamp(event.position().toPoint())
        self._band.setGeometry(QRect(self._origin, current).normalized())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._selection = self._band.geometry()
        self.selection_changed.emit()

    def selected_region(self) -> Region | None:
        """The selection as fractions of the image, or None if too small."""
        if self._selection.width() < 8 or self._selection.height() < 4:
            return None
        width, height = self.width(), self.height()
        return (
            self._selection.x() / width,
            self._selection.y() / height,
            self._selection.width() / width,
            self._selection.height() / height,
        )


class CalibrationDialog(QDialog):
    """
    Lets the player mark the death text on a screenshot.

    After ``exec()`` returns Accepted, :attr:`template` holds the result.
    Subclasses change the wording and override :meth:`_build_result`.
    """

    _TITLE = "Calibrate Death Screen"
    _INSTRUCTIONS = (
        "Drag a box tightly around the death text (e.g. \"YOU DIED\").\n"
        "Pick something that looks the same every time you die, and avoid "
        "parts that change, such as the game world behind it."
    )
    _SAVE_LABEL = "Save Calibration"

    def __init__(self, frame: np.ndarray, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self._TITLE)
        self._frame = frame
        self.template: DeathTemplate | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self._INSTRUCTIONS))
        pixmap = QPixmap.fromImage(frame_to_qimage(frame)).scaled(
            _MAX_PREVIEW,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._selector = _RegionSelector(pixmap)
        self._selector.selection_changed.connect(self._on_selection_changed)
        layout.addWidget(self._selector)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        self._save_button = QPushButton(self._SAVE_LABEL)
        self._save_button.setObjectName("AccentButton")
        self._save_button.setEnabled(False)
        self._save_button.clicked.connect(self._save)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self._save_button)
        layout.addLayout(buttons)

    def _on_selection_changed(self) -> None:
        self._save_button.setEnabled(self._selector.selected_region() is not None)

    def _build_result(self, region: Region) -> None:
        """Turn the selection into the dialog's result; raise ValueError if unusable."""
        self.template = DeathTemplate.from_frame(self._frame, region)

    def _save(self) -> None:
        region = self._selector.selected_region()
        if region is None:
            return
        try:
            self._build_result(region)
        except ValueError as exc:
            QMessageBox.warning(self, "Try Another Area", str(exc))
            return
        self.accept()


class PauseScreenDialog(CalibrationDialog):
    """Marks a pause / loading / cutscene screen for the speedrun timer's game time."""

    _TITLE = "Mark Pause or Loading Screen"
    _INSTRUCTIONS = (
        "Drag a box around something that only shows on this screen, like the "
        '"PAUSED" text, the loading icon, or a cutscene\'s black bars.\n'
        "While it's on screen, the speedrun timer's game time stops."
    )
    _SAVE_LABEL = "Save Screen"


class VictoryScreenDialog(CalibrationDialog):
    """Marks a boss-kill banner, so defeating a boss is detected."""

    _TITLE = "Mark Boss Victory Screen"
    _INSTRUCTIONS = (
        'Drag a box tightly around the victory text (e.g. "GREAT ENEMY FELLED" or '
        '"VICTORY ACHIEVED").\n'
        "Box only the words, so other banners in the same style don't count."
    )
    _SAVE_LABEL = "Save Victory Screen"


class HealthBarDialog(CalibrationDialog):
    """
    Lets the player mark their health bar on a full-health screenshot.

    After ``exec()`` returns Accepted, :attr:`health_bar` holds the result.
    """

    _TITLE = "Mark Your Health Bar"
    _INSTRUCTIONS = (
        "Drag a box around your health bar. Use a screenshot taken at full health, "
        "so the whole bar is filled.\n"
        "Box only the bar itself, not the portrait, numbers or icons next to it."
    )
    _SAVE_LABEL = "Save Health Bar"

    def __init__(self, frame: np.ndarray, parent: QWidget | None = None) -> None:
        self.health_bar: HealthBar | None = None
        super().__init__(frame, parent)

    def _build_result(self, region: Region) -> None:
        self.health_bar = HealthBar.from_frame(self._frame, region)


def first_death_hint(hotkey: str) -> str:
    """How to teach the app a game's death screen, for info messages."""
    return (
        "Detection starts once the app knows this game's death screen. The next time "
        f"you die, either press {hotkey} while the death screen shows, or click "
        "Capture Screen on the Detection page afterwards and pick it from the last few "
        "seconds."
    )


class DeathScreenDialog(QDialog):
    """
    Add a death or boss-victory screen after the fact.

    Offers the watcher's recent frames as thumbnails (newest first), a
    screenshot file, or the clipboard (e.g. after Win+Shift+S). Once the
    player marks the text, :attr:`template` holds the result, :attr:`kind`
    says which kind of screen it is, and :attr:`count_death` whether to
    also add the missed +1 death / boss defeat now.
    """

    def __init__(
        self, recent_frames: list[tuple[float, np.ndarray]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Capture a Death or Victory Screen")
        self.setMinimumWidth(640)
        self.template: DeathTemplate | None = None
        self.kind = SCREEN_DEATH
        self.count_death = False
        self._frames = list(reversed(recent_frames))  # newest first

        layout = QVBoxLayout(self)
        self._kind_combo = QComboBox()
        self._kind_combo.addItem("A death screen (e.g. YOU DIED)", userData=SCREEN_DEATH)
        self._kind_combo.addItem(
            "A boss victory screen (e.g. GREAT ENEMY FELLED)", userData=SCREEN_VICTORY
        )
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("This shows:"))
        kind_row.addWidget(self._kind_combo, 1)
        layout.addLayout(kind_row)
        if self._frames:
            layout.addWidget(QLabel("Pick the frame that shows it:"))
            self._list = QListWidget()
            self._list.setViewMode(QListWidget.ViewMode.IconMode)
            self._list.setIconSize(QSize(240, 135))
            self._list.setFlow(QListWidget.Flow.LeftToRight)
            self._list.setWrapping(True)
            self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
            self._list.setMinimumHeight(330)
            now = time.monotonic()
            for timestamp, frame in self._frames:
                icon = QIcon(QPixmap.fromImage(frame_to_qimage(frame)).scaled(
                    240, 135, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                QListWidgetItem(icon, f"{max(0, round(now - timestamp))} s ago", self._list)
            self._list.itemDoubleClicked.connect(lambda _item: self._use_selected())
            layout.addWidget(self._list)
        else:
            empty = QLabel(
                "No recent frames: the game isn't being watched right now. Load or paste "
                "a screenshot of the death screen instead."
            )
            empty.setWordWrap(True)
            layout.addWidget(empty)

        self._count_check = QCheckBox("That death wasn't counted: add +1 death too")
        self._count_check.setChecked(bool(self._frames))
        layout.addWidget(self._count_check)

        buttons = QHBoxLayout()
        file_button = QPushButton("Load Screenshot File…")
        file_button.clicked.connect(self._use_file)
        paste_button = QPushButton("Paste from Clipboard")
        paste_button.clicked.connect(self._use_clipboard)
        buttons.addWidget(file_button)
        buttons.addWidget(paste_button)
        buttons.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        if self._frames:
            use_button = QPushButton("Use Selected Frame")
            use_button.setObjectName("AccentButton")
            use_button.clicked.connect(self._use_selected)
            buttons.addWidget(use_button)
        layout.addLayout(buttons)

    def _on_kind_changed(self) -> None:
        if self._kind_combo.currentData() == SCREEN_VICTORY:
            self._count_check.setText("Also mark the selected boss defeated now")
        else:
            self._count_check.setText("That death wasn't counted: add +1 death too")

    def _calibrate(self, frame: np.ndarray) -> None:
        kind = self._kind_combo.currentData()
        dialog_class = VictoryScreenDialog if kind == SCREEN_VICTORY else CalibrationDialog
        dialog = dialog_class(frame, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.template is not None:
            self.template = dialog.template
            self.kind = kind
            self.count_death = self._count_check.isChecked()
            self.accept()

    def _use_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            QMessageBox.information(self, "Pick a Frame", "Click the frame with the death screen.")
            return
        self._calibrate(self._frames[row][1])

    def _use_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Death Screen Screenshot", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "Could Not Open", "That file is not a readable image.")
            return
        self._calibrate(qimage_to_frame(image))

    def _use_clipboard(self) -> None:
        image = QApplication.clipboard().image()
        if image.isNull():
            QMessageBox.information(
                self,
                "Clipboard Is Empty",
                "Copy a screenshot of the death screen first (e.g. Win+Shift+S).",
            )
            return
        self._calibrate(qimage_to_frame(image))


# ----------------------------------------------------------------
# Per-game setup
# ----------------------------------------------------------------
class AutoDetectWindow(QDialog):
    """Configure automatic death detection for one game."""

    def __init__(
        self,
        database: Database,
        game_id: int,
        game_name: str,
        recent_frames: Callable[[], list[tuple[float, np.ndarray]]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._database = database
        self._game_id = game_id
        self._recent_frames = recent_frames
        self.setWindowTitle(f"Auto Death Detection: {game_name}")
        self.setMinimumWidth(560)
        self._build_ui()
        self._load_current_values()

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #999999; font-size: 11px;")
        return label

    @staticmethod
    def _row(*widgets: QWidget, stretch_after: int | None = None) -> QWidget:
        """Pack widgets into one form-row field (a QWidget, so the row can be hidden)."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        for index, widget in enumerate(widgets):
            row.addWidget(widget)
            if index == stretch_after:
                row.addStretch()
        return container

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        if not detection_available():
            warning = QLabel(
                "Screen-based detection needs Windows, so only log-file detection works here."
            )
            warning.setStyleSheet("color: #ff4d4d; font-weight: 600;")
            layout.addWidget(warning)

        intro = QLabel(
            "The app counts a death when the death screen appears, when your health bar "
            "empties, or when the game writes a death to its log file. It only reads the "
            "screen or files, so it is safe with anti-cheat. Run the game in borderless or "
            "windowed mode for reliable capture."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = self._form = QFormLayout()
        self._exe_edit = QLineEdit()
        self._exe_edit.setReadOnly(True)
        self._exe_edit.setPlaceholderText("Select the game's .exe")
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_exe)
        form.addRow("Game executable", self._row(self._exe_edit, browse_button))

        self._mode_combo = QComboBox()
        for mode, label in _MODE_LABELS:
            self._mode_combo.addItem(label, userData=mode)
        self._mode_combo.currentIndexChanged.connect(self._update_visible_rows)
        form.addRow("Detection method", self._mode_combo)

        # Death screens: template and Souls modes (and extras for health-bar mode).
        self._calibration_label = QLabel()
        screenshot_button = QPushButton("Add from Screenshot…")
        screenshot_button.clicked.connect(self._calibrate_from_file)
        self._clear_button = QPushButton("Clear")
        self._clear_button.clicked.connect(self._clear_templates)
        self._screens_row = self._row(
            self._calibration_label, screenshot_button, self._clear_button, stretch_after=0
        )
        form.addRow("Death screens", self._screens_row)
        hotkey = self._database.get_setting(SETTING_HOTKEY_CALIBRATE, "f8").upper()
        self._screens_hint = self._hint(
            f"Press {hotkey} in-game while the death screen is showing, or after a death "
            "click Capture Screen on the Detection page and pick the frame. Add more than "
            "one if some deaths are missed: any saved death screen counts."
        )
        form.addRow("", self._screens_hint)

        # Health bar.
        self._health_label = QLabel()
        self._health_frame_button = QPushButton("Use Last Game Frame")
        self._health_frame_button.setToolTip(
            "Mark the bar on the most recent capture of the game window."
        )
        self._health_frame_button.clicked.connect(self._health_from_recent_frame)
        health_file_button = QPushButton("From Screenshot…")
        health_file_button.clicked.connect(self._health_from_file)
        self._health_row = self._row(
            self._health_label, self._health_frame_button, health_file_button, stretch_after=0
        )
        form.addRow("Health bar", self._health_row)
        increment = self._database.get_setting(SETTING_HOTKEY_INCREMENT, "f9").upper()
        self._health_hint = self._hint(
            f"At full health, press {hotkey} in-game and box the health bar. A death counts "
            "when the bar empties after your health was below about 60%, so opening a menu "
            "at high health never counts. One-hit kills from high health are missed: press "
            f"{increment} for those."
        )
        form.addRow("", self._health_hint)

        # Log file.
        self._log_edit = QLineEdit()
        self._log_edit.setPlaceholderText(r"e.g. %APPDATA%\.minecraft\logs\latest.log")
        log_browse_button = QPushButton("Browse…")
        log_browse_button.clicked.connect(self._browse_log)
        self._log_row = self._row(self._log_edit, log_browse_button)
        form.addRow("Log file", self._log_row)
        self._pattern_edit = QLineEdit()
        self._pattern_edit.setPlaceholderText("e.g. Steve was slain|Steve died|Steve fell")
        test_button = QPushButton("Test")
        test_button.setToolTip("Count matching lines near the end of the log file.")
        test_button.clicked.connect(self._test_pattern)
        self._pattern_row = self._row(self._pattern_edit, test_button)
        form.addRow("Death text", self._pattern_row)
        self._log_hint = self._hint(
            "Each new line in the log that contains this text counts as one death. Use | "
            "between alternatives (it's a case-insensitive regular expression). In "
            "multiplayer, include your player name so other players' deaths don't count."
        )
        form.addRow("", self._log_hint)

        # Speedrun timer: screens that stop game time (any detection method).
        self._pause_label = QLabel()
        pause_frame_button = QPushButton("Last Game Frame")
        pause_frame_button.setToolTip(
            "Pause the game (or wait on a loading screen), then click this."
        )
        pause_frame_button.clicked.connect(self._pause_from_recent_frame)
        pause_file_button = QPushButton("From Screenshot…")
        pause_file_button.clicked.connect(self._pause_from_file)
        self._pause_clear_button = QPushButton("Clear")
        self._pause_clear_button.clicked.connect(self._clear_pause_screens)
        form.addRow(
            "Timer pause screens",
            self._row(
                self._pause_label,
                pause_frame_button,
                pause_file_button,
                self._pause_clear_button,
                stretch_after=0,
            ),
        )
        form.addRow(
            "",
            self._hint(
                "For the speedrun timer: game time stops while a saved pause menu, "
                "loading or cutscene screen shows. Black loading screens, crashes and "
                "freezes are recognized without this (Settings → Speedrun)."
            ),
        )

        # Boss kills: victory banners (any detection method).
        self._victory_label = QLabel()
        victory_file_button = QPushButton("From Screenshot…")
        victory_file_button.clicked.connect(self._victory_from_file)
        self._victory_clear_button = QPushButton("Clear")
        self._victory_clear_button.clicked.connect(self._clear_victory_screens)
        form.addRow(
            "Boss victory screens",
            self._row(
                self._victory_label,
                victory_file_button,
                self._victory_clear_button,
                stretch_after=0,
            ),
        )
        form.addRow(
            "",
            self._hint(
                "After beating a boss, click Capture Screen on the Detection page, pick "
                "the frame with the victory banner and choose \"A boss victory screen\". "
                "From then on, beating the selected boss marks it defeated, moves to the "
                "next boss and can split the timer (Settings → General)."
            ),
        )

        self._cooldown_spin = QSpinBox()
        self._cooldown_spin.setRange(3, 120)
        self._cooldown_spin.setSuffix(" s")
        self._cooldown_spin.setToolTip("Ignore new death screens for this long after a death.")
        form.addRow("Min. time between deaths", self._cooldown_spin)
        layout.addLayout(form)

        save_button = QPushButton("Save")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(self._save)
        layout.addWidget(save_button)

    def _update_visible_rows(self) -> None:
        mode = self._mode_combo.currentData()
        screen_modes = (DETECTION_MODE_TEMPLATE, DETECTION_MODE_SOULS, DETECTION_MODE_HEALTH)
        visible = {
            self._screens_row: mode in screen_modes,
            self._screens_hint: mode in (DETECTION_MODE_TEMPLATE, DETECTION_MODE_SOULS),
            self._health_row: mode == DETECTION_MODE_HEALTH,
            self._health_hint: mode == DETECTION_MODE_HEALTH,
            self._log_row: mode == DETECTION_MODE_LOG,
            self._pattern_row: mode == DETECTION_MODE_LOG,
            self._log_hint: mode == DETECTION_MODE_LOG,
            self._cooldown_spin: mode in screen_modes,
        }
        for widget, show in visible.items():
            self._form.setRowVisible(widget, show)
        self._exe_edit.setPlaceholderText(
            "Optional: auto-selects this game when it starts"
            if mode == DETECTION_MODE_LOG
            else "Select the game's .exe"
        )
        self.adjustSize()

    def _load_current_values(self) -> None:
        row = self._database.get_game_detection(self._game_id)
        if row is not None:
            self._exe_edit.setText(row["exe_path"] or "")
            index = self._mode_combo.findData(row["mode"])
            self._mode_combo.setCurrentIndex(max(index, 0))
        options = self._database.get_detection_options(self._game_id)
        self._log_edit.setText(str(options.get("log_path") or ""))
        self._pattern_edit.setText(str(options.get("log_pattern") or ""))
        self._update_calibration_label()
        self._update_health_label()
        self._update_pause_label()
        self._update_victory_label()
        self._health_frame_button.setEnabled(bool(self._recent_frames and self._recent_frames()))
        self._cooldown_spin.setValue(
            int(self._database.get_setting(SETTING_DETECTION_COOLDOWN, "8") or 8)
        )
        self._update_visible_rows()

    def _has_template(self) -> bool:
        return bool(self._database.get_death_templates(self._game_id))

    def _health_bar(self) -> HealthBar | None:
        return HealthBar.from_options(self._database.get_detection_options(self._game_id))

    def _update_calibration_label(self) -> None:
        count = len(self._database.get_death_templates(self._game_id))
        self._calibration_label.setText(
            "None saved" if count == 0 else f"{count} saved ✓"
        )
        self._clear_button.setEnabled(count > 0)

    def _update_pause_label(self) -> None:
        count = len(self._database.get_death_templates(self._game_id, SCREEN_PAUSE))
        self._pause_label.setText("None saved" if count == 0 else f"{count} saved ✓")
        self._pause_clear_button.setEnabled(count > 0)

    def _mark_pause_screen(self, frame: np.ndarray) -> None:
        dialog = PauseScreenDialog(frame, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.template is None:
            return
        self._database.add_death_template(
            self._game_id,
            dialog.template.region_json(),
            dialog.template.patch_bytes(),
            SCREEN_PAUSE,
        )
        self._update_pause_label()

    def _pause_from_recent_frame(self) -> None:
        frames = self._recent_frames() if self._recent_frames else []
        if not frames:
            QMessageBox.information(
                self,
                "No Game Frame Yet",
                "Start the game (or a speedrun) first, then try again.",
            )
            return
        self._mark_pause_screen(frames[-1][1])

    def _pause_from_file(self) -> None:
        frame = self._open_image(self, "Pause or Loading Screen Screenshot")
        if frame is not None:
            self._mark_pause_screen(frame)

    def _clear_pause_screens(self) -> None:
        confirm = QMessageBox.question(
            self, "Clear Pause Screens", "Delete all saved pause/loading screens for this game?"
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._database.clear_death_templates(self._game_id, SCREEN_PAUSE)
            self._update_pause_label()

    def _update_victory_label(self) -> None:
        count = len(self._database.get_death_templates(self._game_id, SCREEN_VICTORY))
        self._victory_label.setText("None saved" if count == 0 else f"{count} saved ✓")
        self._victory_clear_button.setEnabled(count > 0)

    def _victory_from_file(self) -> None:
        frame = self._open_image(self, "Boss Victory Screenshot")
        if frame is None:
            return
        dialog = VictoryScreenDialog(frame, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.template is None:
            return
        self._database.add_death_template(
            self._game_id,
            dialog.template.region_json(),
            dialog.template.patch_bytes(),
            SCREEN_VICTORY,
        )
        self._update_victory_label()

    def _clear_victory_screens(self) -> None:
        confirm = QMessageBox.question(
            self, "Clear Victory Screens", "Delete all saved boss victory screens for this game?"
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._database.clear_death_templates(self._game_id, SCREEN_VICTORY)
            self._update_victory_label()

    def _update_health_label(self) -> None:
        bar = self._health_bar()
        if bar is None:
            self._health_label.setText("Not set")
            self._health_label.setStyleSheet("")
            return
        r, g, b = bar.color
        self._health_label.setText("■ Set ✓")
        self._health_label.setStyleSheet(f"color: rgb({r}, {g}, {b}); font-weight: 600;")

    def _clear_templates(self) -> None:
        confirm = QMessageBox.question(
            self, "Clear Death Screens", "Delete all saved death screens for this game?"
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._database.clear_death_templates(self._game_id)
            self._update_calibration_label()

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Game Executable", self._exe_edit.text(), "Programs (*.exe)"
        )
        if not path:
            return
        self._exe_edit.setText(str(Path(path)))
        if self._mode_combo.currentData() == DETECTION_MODE_OFF:
            preset = Path(path).name.lower() in SOULS_PRESET_EXES and not self._has_template()
            mode = DETECTION_MODE_SOULS if preset else DETECTION_MODE_TEMPLATE
            self._mode_combo.setCurrentIndex(self._mode_combo.findData(mode))

    @staticmethod
    def _open_image(parent: QWidget, title: str) -> np.ndarray | None:
        path, _ = QFileDialog.getOpenFileName(
            parent, title, "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return None
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(parent, "Could Not Open", "That file is not a readable image.")
            return None
        return qimage_to_frame(image)

    def _calibrate_from_file(self) -> None:
        frame = self._open_image(self, "Death Screen Screenshot")
        if frame is None:
            return
        dialog = CalibrationDialog(frame, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.template is None:
            return
        self._database.add_death_template(
            self._game_id, dialog.template.region_json(), dialog.template.patch_bytes()
        )
        if self._mode_combo.currentData() == DETECTION_MODE_OFF:
            self._mode_combo.setCurrentIndex(self._mode_combo.findData(DETECTION_MODE_TEMPLATE))
        self._update_calibration_label()

    def _mark_health_bar(self, frame: np.ndarray) -> None:
        dialog = HealthBarDialog(frame, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.health_bar is None:
            return
        self._database.update_detection_options(self._game_id, **dialog.health_bar.to_options())
        self._update_health_label()

    def _health_from_recent_frame(self) -> None:
        frames = self._recent_frames() if self._recent_frames else []
        if not frames:
            QMessageBox.information(
                self, "No Game Frame Yet", "Start the game first, then try again."
            )
            return
        self._mark_health_bar(frames[-1][1])

    def _health_from_file(self) -> None:
        frame = self._open_image(self, "Full-Health Screenshot")
        if frame is not None:
            self._mark_health_bar(frame)

    def _browse_log(self) -> None:
        start = os.path.expandvars(self._log_edit.text().strip())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the Game's Log File", start, "Log files (*.log *.txt);;All files (*)"
        )
        if path:
            self._log_edit.setText(str(Path(path)))

    def _log_path(self) -> Path | None:
        text = self._log_edit.text().strip()
        return Path(os.path.expandvars(text)) if text else None

    def _test_pattern(self) -> None:
        path = self._log_path()
        if path is None or not path.is_file():
            QMessageBox.warning(self, "Log File Not Found", "Choose an existing log file first.")
            return
        try:
            pattern = compile_death_pattern(self._pattern_edit.text())
            count, last = scan_log(path, pattern)
        except ValueError as exc:
            QMessageBox.warning(self, "Check the Death Text", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Can't Read the Log", str(exc))
            return
        if count == 0:
            QMessageBox.information(
                self,
                "No Matches",
                "No lines near the end of the log match. Die once in-game, then test again, "
                "or copy the exact wording from the log.",
            )
        else:
            QMessageBox.information(
                self, "Matches Found", f"{count} matching line(s). The latest:\n\n{last[:300]}"
            )

    def _console_source(self) -> bool:
        """Console games read OBS (set on the Console page) and need no .exe."""
        options = self._database.get_detection_options(self._game_id)
        return bool(options.get(OPTION_OBS_SOURCE))

    def _save(self) -> None:
        mode = self._mode_combo.currentData()
        exe_path = self._exe_edit.text().strip() or None
        if mode == DETECTION_MODE_LOG:
            log_path = self._log_path()
            if log_path is None:
                QMessageBox.warning(self, "Choose the Log File", "Choose the game's log file.")
                return
            try:
                compile_death_pattern(self._pattern_edit.text())
            except ValueError as exc:
                QMessageBox.warning(self, "Check the Death Text", str(exc))
                return
            self._database.update_detection_options(
                self._game_id, log_path=str(log_path), log_pattern=self._pattern_edit.text()
            )
        elif mode != DETECTION_MODE_OFF and exe_path is None and not self._console_source():
            QMessageBox.warning(self, "Select the Game", "Select the game's .exe first.")
            return
        hotkey = self._database.get_setting(SETTING_HOTKEY_CALIBRATE, "f8").upper()
        if mode == DETECTION_MODE_TEMPLATE and not self._has_template():
            QMessageBox.information(self, "Teach It Your Death Screen", first_death_hint(hotkey))
        if mode == DETECTION_MODE_HEALTH and self._health_bar() is None:
            QMessageBox.information(
                self,
                "Mark Your Health Bar",
                f"Start the game, and at full health press {hotkey} and box your health bar. "
                "Deaths are counted from then on.",
            )
        self._database.set_game_detection(self._game_id, exe_path, mode)
        self._database.set_setting(SETTING_DETECTION_COOLDOWN, self._cooldown_spin.value())
        self.accept()
