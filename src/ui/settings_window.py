"""
Settings dialog: theme, overlay appearance, hotkeys, autosave, startup.

All changes are persisted immediately to the `settings` table via
:class:`~src.database.database.Database`, consistent with the app's
"no manual save button" philosophy.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QKeySequenceEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.database.database import Database
from src.utils.constants import (
    AVAILABLE_THEMES,
    SETTING_AUTOSAVE,
    SETTING_HOTKEY_DECREMENT,
    SETTING_HOTKEY_INCREMENT,
    SETTING_HOTKEY_TOGGLE_OVERLAY,
    SETTING_HOTKEY_UNDO,
    SETTING_LAUNCH_ON_STARTUP,
    SETTING_OVERLAY_ALWAYS_ON_TOP,
    SETTING_OVERLAY_FONT_SIZE,
    SETTING_OVERLAY_OPACITY,
    SETTING_THEME,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SettingsWindow(QDialog):
    """
    Modal dialog exposing all user-configurable settings.

    Signals:
        settings_changed: Emitted whenever any setting is saved, so the
            main window can refresh theme/overlay/hotkeys live.
    """

    settings_changed = Signal()

    def __init__(self, database: Database, parent=None) -> None:
        super().__init__(parent)
        self._database = database
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        self._build_ui()
        self._load_current_values()

    # ----------------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(AVAILABLE_THEMES)
        form.addRow("Theme", self._theme_combo)

        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(10, 96)
        form.addRow("Overlay Font Size", self._font_size_spin)

        self._opacity_spin = QDoubleSpinBox()
        self._opacity_spin.setRange(0.1, 1.0)
        self._opacity_spin.setSingleStep(0.05)
        form.addRow("Overlay Opacity", self._opacity_spin)

        self._always_on_top_check = QCheckBox("Overlay Always On Top")
        form.addRow(self._always_on_top_check)

        self._autosave_check = QCheckBox("Autosave (recommended: always on)")
        self._autosave_check.setEnabled(False)  # Autosave is core behavior, always on.
        form.addRow(self._autosave_check)

        self._launch_on_startup_check = QCheckBox("Launch on Startup (coming soon)")
        self._launch_on_startup_check.setEnabled(False)  # Placeholder per spec.
        form.addRow(self._launch_on_startup_check)

        self._hotkey_increment = QKeySequenceEdit()
        form.addRow("Hotkey: +1 Death", self._hotkey_increment)

        self._hotkey_decrement = QKeySequenceEdit()
        form.addRow("Hotkey: -1 Death", self._hotkey_decrement)

        self._hotkey_undo = QKeySequenceEdit()
        form.addRow("Hotkey: Undo", self._hotkey_undo)

        self._hotkey_toggle_overlay = QKeySequenceEdit()
        form.addRow("Hotkey: Toggle Overlay", self._hotkey_toggle_overlay)

        layout.addLayout(form)

        save_button = QPushButton("Save")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(self._save)
        layout.addWidget(save_button)

    # ----------------------------------------------------------------
    # Data binding
    # ----------------------------------------------------------------
    def _load_current_values(self) -> None:
        settings = self._database.get_all_settings()

        self._theme_combo.setCurrentText(settings.get(SETTING_THEME, "dark"))
        self._font_size_spin.setValue(int(settings.get(SETTING_OVERLAY_FONT_SIZE, "24")))
        self._opacity_spin.setValue(float(settings.get(SETTING_OVERLAY_OPACITY, "0.85")))
        self._always_on_top_check.setChecked(
            settings.get(SETTING_OVERLAY_ALWAYS_ON_TOP, "true") == "true"
        )
        self._autosave_check.setChecked(settings.get(SETTING_AUTOSAVE, "true") == "true")
        self._launch_on_startup_check.setChecked(
            settings.get(SETTING_LAUNCH_ON_STARTUP, "false") == "true"
        )

        self._hotkey_increment.setKeySequence(settings.get(SETTING_HOTKEY_INCREMENT, "F9"))
        self._hotkey_decrement.setKeySequence(settings.get(SETTING_HOTKEY_DECREMENT, "F10"))
        self._hotkey_undo.setKeySequence(settings.get(SETTING_HOTKEY_UNDO, "F11"))
        self._hotkey_toggle_overlay.setKeySequence(
            settings.get(SETTING_HOTKEY_TOGGLE_OVERLAY, "F12")
        )

    def _save(self) -> None:
        self._database.set_setting(SETTING_THEME, self._theme_combo.currentText())
        self._database.set_setting(SETTING_OVERLAY_FONT_SIZE, self._font_size_spin.value())
        self._database.set_setting(SETTING_OVERLAY_OPACITY, self._opacity_spin.value())
        self._database.set_setting(
            SETTING_OVERLAY_ALWAYS_ON_TOP,
            "true" if self._always_on_top_check.isChecked() else "false",
        )

        for setting_key, edit in (
            (SETTING_HOTKEY_INCREMENT, self._hotkey_increment),
            (SETTING_HOTKEY_DECREMENT, self._hotkey_decrement),
            (SETTING_HOTKEY_UNDO, self._hotkey_undo),
            (SETTING_HOTKEY_TOGGLE_OVERLAY, self._hotkey_toggle_overlay),
        ):
            sequence_text = edit.keySequence().toString().lower()
            if sequence_text:
                self._database.set_setting(setting_key, sequence_text)

        logger.info("Settings saved")
        self.settings_changed.emit()
        self.accept()
