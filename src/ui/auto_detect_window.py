"""
Auto death detection dialogs.

* :class:`AutoDetectWindow` — per-game setup: pick the game's .exe, the
  detection method, calibration, and the cooldown between deaths.
* :class:`CalibrationDialog` — shows a screenshot of the death screen and
  lets the player drag a box around the death text (e.g. "YOU DIED").
"""

from __future__ import annotations

import time
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

from src.database.database import Database
from src.detection.game_window import detection_available
from src.detection.matchers import SOULS_PRESET_EXES, DeathTemplate, Region
from src.utils.constants import (
    DETECTION_MODE_OFF,
    DETECTION_MODE_SOULS,
    DETECTION_MODE_TEMPLATE,
    SETTING_DETECTION_COOLDOWN,
    SETTING_HOTKEY_CALIBRATE,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_MODE_LABELS: tuple[tuple[str, str], ...] = (
    (DETECTION_MODE_OFF, "Off"),
    (DETECTION_MODE_TEMPLATE, "Calibrated death screen (any game)"),
    (DETECTION_MODE_SOULS, "Souls preset (red \"YOU DIED\" / 死 text)"),
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
    """

    def __init__(self, frame: np.ndarray, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calibrate Death Screen")
        self._frame = frame
        self.template: DeathTemplate | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Drag a box tightly around the death text (e.g. \"YOU DIED\").\n"
                "Pick something that looks the same every time you die, and avoid "
                "parts that change, such as the game world behind it."
            )
        )
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
        self._save_button = QPushButton("Save Calibration")
        self._save_button.setObjectName("AccentButton")
        self._save_button.setEnabled(False)
        self._save_button.clicked.connect(self._save)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self._save_button)
        layout.addLayout(buttons)

    def _on_selection_changed(self) -> None:
        self._save_button.setEnabled(self._selector.selected_region() is not None)

    def _save(self) -> None:
        region = self._selector.selected_region()
        if region is None:
            return
        try:
            self.template = DeathTemplate.from_frame(self._frame, region)
        except ValueError as exc:
            QMessageBox.warning(self, "Try Another Area", str(exc))
            return
        self.accept()


def first_death_hint(hotkey: str) -> str:
    """How to teach the app a game's death screen, for info messages."""
    return (
        "Detection starts once the app knows this game's death screen. The next time "
        f"you die, either press {hotkey} while the death screen shows, or click "
        "📷 Death Screen on the main window afterwards and pick it from the last few "
        "seconds."
    )


class DeathScreenDialog(QDialog):
    """
    Add a death screen after the fact ("that death wasn't counted").

    Offers the watcher's recent frames as thumbnails (newest first), a
    screenshot file, or the clipboard (e.g. after Win+Shift+S). Once the
    player marks the death text, :attr:`template` holds the result and
    :attr:`count_death` says whether to also add +1.
    """

    def __init__(
        self, recent_frames: list[tuple[float, np.ndarray]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a Death Screen")
        self.setMinimumWidth(640)
        self.template: DeathTemplate | None = None
        self.count_death = False
        self._frames = list(reversed(recent_frames))  # newest first

        layout = QVBoxLayout(self)
        if self._frames:
            layout.addWidget(QLabel("Pick the frame that shows the death screen:"))
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

    def _calibrate(self, frame: np.ndarray) -> None:
        dialog = CalibrationDialog(frame, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.template is not None:
            self.template = dialog.template
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
        self, database: Database, game_id: int, game_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._database = database
        self._game_id = game_id
        self.setWindowTitle(f"Auto Death Detection: {game_name}")
        self.setMinimumWidth(520)
        self._build_ui()
        self._load_current_values()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        if not detection_available():
            warning = QLabel("Auto-detection needs Windows, so it is unavailable here.")
            warning.setStyleSheet("color: #ff4d4d; font-weight: 600;")
            layout.addWidget(warning)

        intro = QLabel(
            "The app watches the game's window and counts a death whenever the death "
            "screen appears. It only reads the screen, so it is safe with anti-cheat. "
            "Run the game in borderless or windowed mode for reliable capture."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        exe_row = QHBoxLayout()
        self._exe_edit = QLineEdit()
        self._exe_edit.setReadOnly(True)
        self._exe_edit.setPlaceholderText("Select the game's .exe")
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_exe)
        exe_row.addWidget(self._exe_edit)
        exe_row.addWidget(browse_button)
        form.addRow("Game executable", exe_row)

        self._mode_combo = QComboBox()
        for mode, label in _MODE_LABELS:
            self._mode_combo.addItem(label, userData=mode)
        form.addRow("Detection method", self._mode_combo)

        calibration_row = QHBoxLayout()
        self._calibration_label = QLabel()
        screenshot_button = QPushButton("Add from Screenshot…")
        screenshot_button.clicked.connect(self._calibrate_from_file)
        self._clear_button = QPushButton("Clear")
        self._clear_button.clicked.connect(self._clear_templates)
        calibration_row.addWidget(self._calibration_label)
        calibration_row.addStretch()
        calibration_row.addWidget(screenshot_button)
        calibration_row.addWidget(self._clear_button)
        form.addRow("Death screens", calibration_row)

        hotkey = self._database.get_setting(SETTING_HOTKEY_CALIBRATE, "f8").upper()
        hint = QLabel(
            f"Press {hotkey} in-game while the death screen is showing, or after a death "
            "click 📷 Death Screen on the main window and pick the frame. Add more than "
            "one if some deaths are missed: any saved death screen counts."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #999999; font-size: 11px;")
        form.addRow("", hint)

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

    def _load_current_values(self) -> None:
        row = self._database.get_game_detection(self._game_id)
        if row is not None:
            self._exe_edit.setText(row["exe_path"] or "")
            index = self._mode_combo.findData(row["mode"])
            self._mode_combo.setCurrentIndex(max(index, 0))
        self._update_calibration_label()
        self._cooldown_spin.setValue(
            int(self._database.get_setting(SETTING_DETECTION_COOLDOWN, "8") or 8)
        )

    def _has_template(self) -> bool:
        return bool(self._database.get_death_templates(self._game_id))

    def _update_calibration_label(self) -> None:
        count = len(self._database.get_death_templates(self._game_id))
        self._calibration_label.setText(
            "None saved" if count == 0 else f"{count} saved ✓"
        )
        self._clear_button.setEnabled(count > 0)

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

    def _calibrate_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Death Screen Screenshot", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "Could Not Open", "That file is not a readable image.")
            return
        dialog = CalibrationDialog(qimage_to_frame(image), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.template is None:
            return
        self._database.add_death_template(
            self._game_id, dialog.template.region_json(), dialog.template.patch_bytes()
        )
        if self._mode_combo.currentData() == DETECTION_MODE_OFF:
            self._mode_combo.setCurrentIndex(self._mode_combo.findData(DETECTION_MODE_TEMPLATE))
        self._update_calibration_label()

    def _save(self) -> None:
        mode = self._mode_combo.currentData()
        exe_path = self._exe_edit.text().strip() or None
        if mode != DETECTION_MODE_OFF and exe_path is None:
            QMessageBox.warning(self, "Select the Game", "Select the game's .exe first.")
            return
        if mode == DETECTION_MODE_TEMPLATE and not self._has_template():
            hotkey = self._database.get_setting(SETTING_HOTKEY_CALIBRATE, "f8").upper()
            QMessageBox.information(self, "Teach It Your Death Screen", first_death_hint(hotkey))
        self._database.set_game_detection(self._game_id, exe_path, mode)
        self._database.set_setting(SETTING_DETECTION_COOLDOWN, self._cooldown_spin.value())
        self.accept()
