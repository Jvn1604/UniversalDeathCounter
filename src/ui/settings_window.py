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
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.database.database import Database
from src.hotkeys.gamepad import GamepadManager, combo_label
from src.utils import startup
from src.utils.constants import (
    AVAILABLE_THEMES,
    CONTROL_ACTIONS,
    SETTING_CHECK_UPDATES,
    SETTING_DEATHS_TXT_ENABLED,
    SETTING_DEATHS_TXT_PATH,
    SETTING_DEATHS_TXT_TEMPLATE,
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
    pad_setting,
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

    def __init__(
        self, database: Database, gamepad: GamepadManager | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self._database = database
        self._gamepad = gamepad
        self._recording_action: str | None = None
        self._text_color = "#ff4d4d"
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        self._build_ui()
        self._load_current_values()

    # ----------------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        general_page = QWidget()
        layout = QVBoxLayout(general_page)
        tabs.addTab(general_page, "General")
        tabs.addTab(self._build_controls_page(), "Controls")

        # --- General ---
        general_group = QGroupBox("General")
        general_form = QFormLayout(general_group)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(AVAILABLE_THEMES)
        general_form.addRow("Theme", self._theme_combo)
        self._minimize_tray_check = QCheckBox("Minimize to system tray on close")
        general_form.addRow(self._minimize_tray_check)
        self._start_with_windows_check = QCheckBox("Start with Windows")
        if not startup.startup_supported():
            self._start_with_windows_check.setEnabled(False)
            self._start_with_windows_check.setToolTip(
                "Available in the installed app (not when running from source)."
            )
        general_form.addRow(self._start_with_windows_check)
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

        layout.addStretch()

        save_button = QPushButton("Save")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(self._save)
        outer.addWidget(save_button)

    def _build_controls_page(self) -> QWidget:
        """Keyboard + controller binding per action, with record/clear buttons."""
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "Click a keyboard field and press keys, or click Record and press a controller "
            "button combo (hold them, then release). Works with Xbox, PlayStation and most "
            "other controllers. Controller presses also reach the game, so a combo such as "
            "View/Share + D-pad Up is safest."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        grid = QGridLayout()
        for column, title in enumerate(("Action", "Keyboard", "", "Controller", "", "")):
            header = QLabel(title)
            header.setStyleSheet("font-weight: 600;")
            grid.addWidget(header, 0, column)

        self._key_edits: dict[str, QKeySequenceEdit] = {}
        self._pad_labels: dict[str, QLabel] = {}
        self._record_buttons: dict[str, QPushButton] = {}
        self._pad_values: dict[str, str] = {}
        for row, (action, label, _setting, _default) in enumerate(CONTROL_ACTIONS, start=1):
            grid.addWidget(QLabel(label), row, 0)

            key_edit = QKeySequenceEdit()
            key_edit.setMaximumSequenceLength(1)
            self._key_edits[action] = key_edit
            grid.addWidget(key_edit, row, 1)
            clear_key = QPushButton("✕")
            clear_key.setToolTip("Clear keyboard binding")
            clear_key.setFixedWidth(36)
            clear_key.setStyleSheet("padding: 0;")
            clear_key.clicked.connect(key_edit.clear)
            grid.addWidget(clear_key, row, 2)

            pad_label = QLabel()
            pad_label.setMinimumWidth(170)
            self._pad_labels[action] = pad_label
            grid.addWidget(pad_label, row, 3)
            record = QPushButton("Record")
            record.clicked.connect(lambda _=False, a=action: self._start_recording(a))
            self._record_buttons[action] = record
            grid.addWidget(record, row, 4)
            clear_pad = QPushButton("✕")
            clear_pad.setToolTip("Clear controller binding")
            clear_pad.setFixedWidth(36)
            clear_pad.setStyleSheet("padding: 0;")
            clear_pad.clicked.connect(lambda _=False, a=action: self._set_pad(a, ""))
            grid.addWidget(clear_pad, row, 5)
        layout.addLayout(grid)

        bottom = QHBoxLayout()
        self._pad_status = QLabel()
        self._pad_status.setStyleSheet("color: #999999; font-size: 11px;")
        reset = QPushButton("Reset to Defaults")
        reset.clicked.connect(self._reset_controls)
        bottom.addWidget(self._pad_status, 1)
        bottom.addWidget(reset)
        layout.addLayout(bottom)
        layout.addStretch()

        if self._gamepad is not None:
            self._gamepad.combo_recorded.connect(self._on_combo_recorded)
            self._gamepad.connection_changed.connect(self._update_pad_status)
        self._update_pad_status()
        return page

    # ----------------------------------------------------------------
    # Controller binding helpers
    # ----------------------------------------------------------------
    def _update_pad_status(self, _connected: bool | None = None) -> None:
        if self._gamepad is None:
            text = "Controller support is unavailable on this system."
        elif self._gamepad.connected:
            text = "Controller connected ✓"
        else:
            text = "No controller detected: connect one to record combos."
        self._pad_status.setText(text)

    def _set_pad(self, action: str, combo: str) -> None:
        self._pad_values[action] = combo
        self._pad_labels[action].setText(combo_label(combo) or "Not set")

    def _start_recording(self, action: str) -> None:
        if self._gamepad is None or not self._gamepad.connected:
            QMessageBox.information(
                self, "No Controller", "Connect a controller first, then click Record."
            )
            return
        self._recording_action = action
        for name, button in self._record_buttons.items():
            button.setEnabled(name == action)
        self._record_buttons[action].setText("Press…")
        self._pad_labels[action].setText("Hold the buttons, then release")
        self._gamepad.start_recording()

    def _on_combo_recorded(self, combo: str) -> None:
        action = self._recording_action
        if action is None:
            return
        self._recording_action = None
        self._set_pad(action, combo)
        for button in self._record_buttons.values():
            button.setEnabled(True)
            button.setText("Record")

    def _reset_controls(self) -> None:
        for action, _label, _setting, default in CONTROL_ACTIONS:
            self._key_edits[action].setKeySequence(QKeySequence(default))
            self._set_pad(action, "")

    def done(self, result: int) -> None:  # noqa: D102 - stop recording on close
        if self._gamepad is not None:
            self._gamepad.cancel_recording()
            try:
                self._gamepad.combo_recorded.disconnect(self._on_combo_recorded)
                self._gamepad.connection_changed.disconnect(self._update_pad_status)
            except (RuntimeError, TypeError):
                pass
        super().done(result)

    def _validate_controls(self) -> str | None:
        """Return an error message if two actions share a binding."""
        keys: dict[str, str] = {}
        pads: dict[str, str] = {}
        labels = {action: label for action, label, _s, _d in CONTROL_ACTIONS}
        for action, edit in self._key_edits.items():
            key = edit.keySequence().toString().lower()
            if key and key in keys:
                return f"{labels[keys[key]]} and {labels[action]} both use {key.upper()}."
            if key:
                keys[key] = action
        for action, combo in self._pad_values.items():
            if combo and combo in pads:
                return (
                    f"{labels[pads[combo]]} and {labels[action]} both use "
                    f"{combo_label(combo)}."
                )
            if combo:
                pads[combo] = action
        return None

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
        self._start_with_windows_check.setChecked(startup.is_enabled())
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

        for action, _label, setting_key, default in CONTROL_ACTIONS:
            self._key_edits[action].setKeySequence(
                QKeySequence(settings.get(setting_key, default))
            )
            self._set_pad(action, settings.get(pad_setting(action), ""))

    def _save(self) -> None:
        problem = self._validate_controls()
        if problem:
            QMessageBox.warning(self, "Duplicate Binding", problem)
            return
        db = self._database
        db.set_setting(SETTING_THEME, self._theme_combo.currentText())
        db.set_setting(
            SETTING_MINIMIZE_TO_TRAY,
            "true" if self._minimize_tray_check.isChecked() else "false",
        )
        if startup.startup_supported():
            try:
                startup.set_enabled(self._start_with_windows_check.isChecked())
            except OSError as exc:
                QMessageBox.warning(self, "Start with Windows", f"Could not update: {exc}")
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

        # An empty field means "unbound" for keyboard and controller alike.
        for action, _label, setting_key, _default in CONTROL_ACTIONS:
            db.set_setting(setting_key, self._key_edits[action].keySequence().toString().lower())
            db.set_setting(pad_setting(action), self._pad_values.get(action, ""))

        logger.info("Settings saved")
        self.settings_changed.emit()
        self.accept()
