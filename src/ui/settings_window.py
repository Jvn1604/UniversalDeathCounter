"""
Settings dialog: theme, overlay appearance & behavior, streaming output,
hotkeys, tray, and updates.

All changes are persisted immediately to the `settings` table via
:class:`~src.database.database.Database`, consistent with the app's
"no manual save button" philosophy (the Save button here commits the
whole form at once).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.database.database import Database
from src.utils.constants import (
    AVAILABLE_THEMES,
    SETTING_CHECK_UPDATES,
    SETTING_DEATHS_TXT_ENABLED,
    SETTING_DEATHS_TXT_PATH,
    SETTING_DEATHS_TXT_TEMPLATE,
    SETTING_HOTKEY_DECREMENT,
    SETTING_HOTKEY_INCREMENT,
    SETTING_HOTKEY_TOGGLE_OVERLAY,
    SETTING_HOTKEY_UNDO,
    SETTING_MINIMIZE_TO_TRAY,
    SETTING_OVERLAY_ALWAYS_ON_TOP,
    SETTING_OVERLAY_BG_MODE,
    SETTING_OVERLAY_COUNTER_SOURCE,
    SETTING_OVERLAY_FONT_SIZE,
    SETTING_OVERLAY_OPACITY,
    SETTING_OVERLAY_SHOW_BOSS,
    SETTING_OVERLAY_SHOW_GAME,
    SETTING_OVERLAY_SHOW_STATS,
    SETTING_OVERLAY_TEXT_COLOR,
    SETTING_THEME,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_BG_MODES = ["dark", "chroma"]
_COUNTER_SOURCES = ["session", "boss", "total"]


class SettingsWindow(QDialog):
    """
    Modal dialog exposing all user-configurable settings.

    Signals:
        settings_changed: Emitted whenever settings are saved, so the
            main window can refresh theme/overlay/hotkeys/stream output live.
    """

    settings_changed = Signal()

    def __init__(self, database: Database, parent=None) -> None:
        super().__init__(parent)
        self._database = database
        self._text_color = "#ff4d4d"
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        self._build_ui()
        self._load_current_values()

    # ----------------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- General ---
        general_group = QGroupBox("General")
        general_form = QFormLayout(general_group)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(AVAILABLE_THEMES)
        general_form.addRow("Theme", self._theme_combo)
        self._minimize_tray_check = QCheckBox("Minimize to system tray on close")
        general_form.addRow(self._minimize_tray_check)
        self._check_updates_check = QCheckBox("Check for updates on startup")
        general_form.addRow(self._check_updates_check)
        layout.addWidget(general_group)

        # --- Overlay ---
        overlay_group = QGroupBox("Overlay")
        overlay_form = QFormLayout(overlay_group)

        self._bg_mode_combo = QComboBox()
        self._bg_mode_combo.addItems(_BG_MODES)
        overlay_form.addRow("Background", self._bg_mode_combo)

        self._counter_source_combo = QComboBox()
        self._counter_source_combo.addItems(_COUNTER_SOURCES)
        overlay_form.addRow("Big number shows", self._counter_source_combo)

        color_row = QHBoxLayout()
        self._color_button = QPushButton()
        self._color_button.setFixedWidth(80)
        self._color_button.clicked.connect(self._pick_color)
        color_row.addWidget(self._color_button)
        color_row.addStretch()
        overlay_form.addRow("Counter color", color_row)

        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(10, 96)
        overlay_form.addRow("Font size", self._font_size_spin)

        self._opacity_spin = QDoubleSpinBox()
        self._opacity_spin.setRange(0.1, 1.0)
        self._opacity_spin.setSingleStep(0.05)
        overlay_form.addRow("Opacity (dark mode)", self._opacity_spin)

        self._show_game_check = QCheckBox("Show game name")
        overlay_form.addRow(self._show_game_check)
        self._show_boss_check = QCheckBox("Show boss name")
        overlay_form.addRow(self._show_boss_check)
        self._show_stats_check = QCheckBox("Show Session • Total line")
        overlay_form.addRow(self._show_stats_check)

        self._always_on_top_check = QCheckBox("Always on top")
        overlay_form.addRow(self._always_on_top_check)
        layout.addWidget(overlay_group)

        # --- Streaming (deaths.txt) ---
        stream_group = QGroupBox("Streaming — deaths.txt for OBS Text Source")
        stream_form = QFormLayout(stream_group)

        self._deaths_txt_check = QCheckBox("Write deaths.txt on every change")
        stream_form.addRow(self._deaths_txt_check)

        path_row = QHBoxLayout()
        self._deaths_txt_path = QLineEdit()
        self._deaths_txt_path.setPlaceholderText("(default: saves/deaths.txt)")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_deaths_txt)
        path_row.addWidget(self._deaths_txt_path)
        path_row.addWidget(browse_btn)
        stream_form.addRow("File path", path_row)

        self._deaths_txt_template = QLineEdit()
        self._deaths_txt_template.setPlaceholderText("{game} - {boss}: {deaths}")
        self._deaths_txt_template.setToolTip(
            "Placeholders: {game} {boss} {deaths} {session} {boss_deaths} {total}"
        )
        stream_form.addRow("Template", self._deaths_txt_template)
        layout.addWidget(stream_group)

        # --- Hotkeys ---
        hotkey_group = QGroupBox("Global Hotkeys")
        hotkey_form = QFormLayout(hotkey_group)
        self._hotkey_increment = QKeySequenceEdit()
        hotkey_form.addRow("+1 Death", self._hotkey_increment)
        self._hotkey_decrement = QKeySequenceEdit()
        hotkey_form.addRow("-1 Death", self._hotkey_decrement)
        self._hotkey_undo = QKeySequenceEdit()
        hotkey_form.addRow("Undo", self._hotkey_undo)
        self._hotkey_toggle_overlay = QKeySequenceEdit()
        hotkey_form.addRow("Toggle Overlay", self._hotkey_toggle_overlay)
        layout.addWidget(hotkey_group)

        save_button = QPushButton("Save")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(self._save)
        layout.addWidget(save_button)

    def _update_color_button(self) -> None:
        self._color_button.setText(self._text_color)
        self._color_button.setStyleSheet(
            f"background-color: {self._text_color}; color: #ffffff; font-weight: 600;"
        )

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._text_color), self, "Overlay Counter Color")
        if color.isValid():
            self._text_color = color.name()
            self._update_color_button()

    def _browse_deaths_txt(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "deaths.txt Location", "deaths.txt", "Text Files (*.txt)"
        )
        if path:
            self._deaths_txt_path.setText(path)

    # ----------------------------------------------------------------
    # Data binding
    # ----------------------------------------------------------------
    def _load_current_values(self) -> None:
        settings = self._database.get_all_settings()

        self._theme_combo.setCurrentText(settings.get(SETTING_THEME, "dark"))
        self._minimize_tray_check.setChecked(
            settings.get(SETTING_MINIMIZE_TO_TRAY, "false") == "true"
        )
        self._check_updates_check.setChecked(
            settings.get(SETTING_CHECK_UPDATES, "true") == "true"
        )

        self._bg_mode_combo.setCurrentText(settings.get(SETTING_OVERLAY_BG_MODE, "dark"))
        self._counter_source_combo.setCurrentText(
            settings.get(SETTING_OVERLAY_COUNTER_SOURCE, "session")
        )
        self._text_color = settings.get(SETTING_OVERLAY_TEXT_COLOR, "#ff4d4d") or "#ff4d4d"
        self._update_color_button()
        self._font_size_spin.setValue(int(settings.get(SETTING_OVERLAY_FONT_SIZE, "24")))
        self._opacity_spin.setValue(float(settings.get(SETTING_OVERLAY_OPACITY, "0.85")))
        self._show_game_check.setChecked(settings.get(SETTING_OVERLAY_SHOW_GAME, "true") == "true")
        self._show_boss_check.setChecked(settings.get(SETTING_OVERLAY_SHOW_BOSS, "true") == "true")
        self._show_stats_check.setChecked(
            settings.get(SETTING_OVERLAY_SHOW_STATS, "true") == "true"
        )
        self._always_on_top_check.setChecked(
            settings.get(SETTING_OVERLAY_ALWAYS_ON_TOP, "true") == "true"
        )

        self._deaths_txt_check.setChecked(
            settings.get(SETTING_DEATHS_TXT_ENABLED, "false") == "true"
        )
        self._deaths_txt_path.setText(settings.get(SETTING_DEATHS_TXT_PATH, ""))
        self._deaths_txt_template.setText(
            settings.get(SETTING_DEATHS_TXT_TEMPLATE, "{game} - {boss}: {deaths}")
        )

        self._hotkey_increment.setKeySequence(settings.get(SETTING_HOTKEY_INCREMENT, "F9"))
        self._hotkey_decrement.setKeySequence(settings.get(SETTING_HOTKEY_DECREMENT, "F10"))
        self._hotkey_undo.setKeySequence(settings.get(SETTING_HOTKEY_UNDO, "F11"))
        self._hotkey_toggle_overlay.setKeySequence(
            settings.get(SETTING_HOTKEY_TOGGLE_OVERLAY, "F12")
        )

    def _save(self) -> None:
        db = self._database
        db.set_setting(SETTING_THEME, self._theme_combo.currentText())
        db.set_setting(
            SETTING_MINIMIZE_TO_TRAY,
            "true" if self._minimize_tray_check.isChecked() else "false",
        )
        db.set_setting(
            SETTING_CHECK_UPDATES,
            "true" if self._check_updates_check.isChecked() else "false",
        )

        db.set_setting(SETTING_OVERLAY_BG_MODE, self._bg_mode_combo.currentText())
        db.set_setting(SETTING_OVERLAY_COUNTER_SOURCE, self._counter_source_combo.currentText())
        db.set_setting(SETTING_OVERLAY_TEXT_COLOR, self._text_color)
        db.set_setting(SETTING_OVERLAY_FONT_SIZE, self._font_size_spin.value())
        db.set_setting(SETTING_OVERLAY_OPACITY, self._opacity_spin.value())
        db.set_setting(
            SETTING_OVERLAY_SHOW_GAME,
            "true" if self._show_game_check.isChecked() else "false",
        )
        db.set_setting(
            SETTING_OVERLAY_SHOW_BOSS,
            "true" if self._show_boss_check.isChecked() else "false",
        )
        db.set_setting(
            SETTING_OVERLAY_SHOW_STATS,
            "true" if self._show_stats_check.isChecked() else "false",
        )
        db.set_setting(
            SETTING_OVERLAY_ALWAYS_ON_TOP,
            "true" if self._always_on_top_check.isChecked() else "false",
        )

        db.set_setting(
            SETTING_DEATHS_TXT_ENABLED,
            "true" if self._deaths_txt_check.isChecked() else "false",
        )
        db.set_setting(SETTING_DEATHS_TXT_PATH, self._deaths_txt_path.text().strip())
        template = self._deaths_txt_template.text().strip() or "{game} - {boss}: {deaths}"
        db.set_setting(SETTING_DEATHS_TXT_TEMPLATE, template)

        for setting_key, edit in (
            (SETTING_HOTKEY_INCREMENT, self._hotkey_increment),
            (SETTING_HOTKEY_DECREMENT, self._hotkey_decrement),
            (SETTING_HOTKEY_UNDO, self._hotkey_undo),
            (SETTING_HOTKEY_TOGGLE_OVERLAY, self._hotkey_toggle_overlay),
        ):
            sequence_text = edit.keySequence().toString().lower()
            if sequence_text:
                db.set_setting(setting_key, sequence_text)

        logger.info("Settings saved")
        self.settings_changed.emit()
        self.accept()
