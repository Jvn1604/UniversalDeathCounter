"""
Settings dialog: theme, overlay appearance & behavior, streaming output,
hotkeys, tray, and updates.

All changes are persisted immediately to the `settings` table via
:class:`~src.database.database.Database`, consistent with the app's
"no manual save button" philosophy (the Save button here commits the
whole form at once).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QKeySequence
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
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.database.database import Database
from src.hotkeys.conflicts import ERROR, WARNING, Conflict, find_conflicts, has_errors
from src.hotkeys.gamepad import GamepadManager, combo_label
from src.hotkeys.hotkey_manager import HotkeyManager
from src.utils import startup
from src.utils.backgrounds import IMAGE_FILTER, import_background
from src.utils.constants import (
    AVAILABLE_THEMES,
    CONTROL_ACTIONS,
    SETTING_CHECK_UPDATES,
    SETTING_DEATHS_TXT_ENABLED,
    SETTING_DEATHS_TXT_PATH,
    SETTING_DEATHS_TXT_TEMPLATE,
    SETTING_MINIMIZE_TO_TRAY,
    SETTING_OVERLAY_ALWAYS_ON_TOP,
    SETTING_OVERLAY_BG_IMAGE,
    SETTING_OVERLAY_BG_MODE,
    SETTING_OVERLAY_CARD_COLOR,
    SETTING_OVERLAY_CORNER_RADIUS,
    SETTING_OVERLAY_COUNTER_SOURCE,
    SETTING_OVERLAY_FONT,
    SETTING_OVERLAY_FONT_SIZE,
    SETTING_OVERLAY_OPACITY,
    SETTING_OVERLAY_SECONDARY_COLOR,
    SETTING_OVERLAY_SHOW_BOSS,
    SETTING_OVERLAY_SHOW_GAME,
    SETTING_OVERLAY_SHOW_STATS,
    SETTING_OVERLAY_TEXT_COLOR,
    SETTING_OVERLAY_TEXT_OUTLINE,
    SETTING_THEME,
    SETTING_UI_BG_DIM,
    SETTING_UI_BG_IMAGE,
    SETTING_UI_COUNTER_COLOR,
    SETTING_UI_FONT,
    SETTING_UI_TEXT_COLOR,
    pad_setting,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_BG_MODES: tuple[tuple[str, str], ...] = (
    ("dark", "Card (solid color)"),
    ("chroma", "Green screen (for OBS Chroma Key)"),
    ("image", "Image"),
)
_COUNTER_SOURCES = ["session", "boss", "total"]


def _readable_on(background: str) -> str:
    """Black or white, whichever reads better on ``background``."""
    return "#000000" if QColor(background).lightness() > 150 else "#ffffff"


class _ColorChoice(QWidget):
    """A color swatch button plus "Default"; :meth:`color` is "" for the default."""

    def __init__(
        self, title: str, default_label: str = "Theme", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._default_label = default_label
        self._color = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self._button = QPushButton()
        self._button.setFixedWidth(90)
        self._button.clicked.connect(self._pick)
        reset = QPushButton("Reset")
        reset.setToolTip(f"Back to {default_label.lower()}")
        reset.clicked.connect(lambda: self.set_color(""))
        row.addWidget(self._button)
        row.addWidget(reset)
        row.addStretch()
        self.set_color("")

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color
        self._button.setText(color or self._default_label)
        self._button.setStyleSheet(
            f"background-color: {color}; color: {_readable_on(color)}; font-weight: 600;"
            if color
            else ""
        )

    def _pick(self) -> None:
        start = QColor(self._color or "#e8e8e8")
        chosen = QColorDialog.getColor(start, self, self._title)
        if chosen.isValid():
            self.set_color(chosen.name())


def _font_combo(default_label: str) -> QComboBox:
    """Installed font families, with ``default_label`` (value "") first."""
    combo = QComboBox()
    combo.addItem(default_label, userData="")
    for family in QFontDatabase.families():
        if not family.startswith("@"):  # vertical-text variants of CJK fonts
            combo.addItem(family, userData=family)
    combo.setMaxVisibleItems(20)
    return combo


def _select_data(combo: QComboBox, value: str) -> None:
    combo.setCurrentIndex(max(combo.findData(value), 0))


class _ImageChoice(QWidget):
    """Shows the chosen background image's name, with Choose… and Remove."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._path = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel()
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose)
        self._remove = QPushButton("Remove")
        self._remove.clicked.connect(lambda: self.set_path(""))
        row.addWidget(self._label, 1)
        row.addWidget(choose)
        row.addWidget(self._remove)
        self.set_path("")

    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        self._path = path
        self._label.setText(Path(path).name if path else "None")
        self._label.setToolTip(path)
        self._remove.setEnabled(bool(path))

    def _choose(self) -> None:
        source, _ = QFileDialog.getOpenFileName(self, self._title, "", IMAGE_FILTER)
        if not source:
            return
        try:
            self.set_path(str(import_background(Path(source))))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Couldn't Use That Image", str(exc))


class SettingsWindow(QDialog):
    """
    Modal dialog exposing all user-configurable settings.

    Signals:
        settings_changed: Emitted whenever settings are saved, so the
            main window can refresh theme/overlay/hotkeys/stream output live.
    """

    settings_changed = Signal()

    def __init__(
        self,
        database: Database,
        gamepad: GamepadManager | None = None,
        hotkeys: HotkeyManager | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._database = database
        self._gamepad = gamepad
        self._hotkeys = hotkeys  # probes whether keys are taken by other programs
        self._availability: dict[str, bool] = {}
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
        tabs.addTab(self._build_appearance_page(), "Appearance")
        tabs.addTab(self._build_controls_page(), "Controls")

        # --- General ---
        general_group = QGroupBox("General")
        general_form = QFormLayout(general_group)
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

        buttons = QHBoxLayout()
        apply_button = QPushButton("Apply")
        apply_button.setToolTip("Save and see the changes without closing Settings.")
        apply_button.clicked.connect(self._apply)
        save_button = QPushButton("Save")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(self._save)
        buttons.addWidget(apply_button)
        buttons.addWidget(save_button, 1)
        outer.addLayout(buttons)

    def _build_appearance_page(self) -> QWidget:
        """Main-window and overlay looks: colors, fonts, background images."""
        page = QWidget()
        layout = QVBoxLayout(page)

        window_group = QGroupBox("Main window")
        window_form = QFormLayout(window_group)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(AVAILABLE_THEMES)
        window_form.addRow("Theme", self._theme_combo)
        self._ui_font_combo = _font_combo("Theme font (Segoe UI)")
        window_form.addRow("Font", self._ui_font_combo)
        self._ui_text_color = _ColorChoice("Text Color")
        window_form.addRow("Text color", self._ui_text_color)
        self._ui_counter_color = _ColorChoice("Death Number Color")
        window_form.addRow("Death number color", self._ui_counter_color)
        self._ui_bg_image = _ImageChoice("Main Window Background")
        window_form.addRow("Background image", self._ui_bg_image)
        dim_row = QWidget()
        dim_layout = QHBoxLayout(dim_row)
        dim_layout.setContentsMargins(0, 0, 0, 0)
        self._ui_bg_dim = QSlider(Qt.Orientation.Horizontal)
        self._ui_bg_dim.setRange(0, 90)
        self._ui_bg_dim.setToolTip(
            "How much of the theme color covers the image. Higher keeps text easier to read."
        )
        dim_value = QLabel()
        dim_value.setMinimumWidth(36)
        self._ui_bg_dim.valueChanged.connect(lambda v: dim_value.setText(f"{v}%"))
        dim_layout.addWidget(self._ui_bg_dim, 1)
        dim_layout.addWidget(dim_value)
        window_form.addRow("Image dimming", dim_row)
        layout.addWidget(window_group)

        overlay_group = QGroupBox("Overlay")
        overlay_form = QFormLayout(overlay_group)
        self._bg_mode_combo = QComboBox()
        for mode, label in _BG_MODES:
            self._bg_mode_combo.addItem(label, userData=mode)
        overlay_form.addRow("Background", self._bg_mode_combo)
        self._card_color = _ColorChoice("Overlay Card Color", default_label="Default")
        overlay_form.addRow("Card color", self._card_color)
        self._overlay_image = _ImageChoice("Overlay Background")
        overlay_form.addRow("Image", self._overlay_image)
        self._opacity_spin = QDoubleSpinBox()
        self._opacity_spin.setRange(0.1, 1.0)
        self._opacity_spin.setSingleStep(0.05)
        self._opacity_spin.setToolTip("Of the card or image. Green screen is always solid.")
        overlay_form.addRow("Opacity", self._opacity_spin)
        self._radius_spin = QSpinBox()
        self._radius_spin.setRange(0, 40)
        self._radius_spin.setSuffix(" px")
        overlay_form.addRow("Corner roundness", self._radius_spin)

        self._counter_source_combo = QComboBox()
        self._counter_source_combo.addItems(_COUNTER_SOURCES)
        self._counter_source_combo.setToolTip("Used by the main window and the overlay.")
        overlay_form.addRow("Big number shows", self._counter_source_combo)
        self._overlay_font_combo = _font_combo("Default font")
        overlay_form.addRow("Font", self._overlay_font_combo)
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(10, 96)
        overlay_form.addRow("Number size", self._font_size_spin)
        color_row = QHBoxLayout()
        self._color_button = QPushButton()
        self._color_button.setFixedWidth(80)
        self._color_button.clicked.connect(self._pick_color)
        color_row.addWidget(self._color_button)
        color_row.addStretch()
        overlay_form.addRow("Number color", color_row)
        self._secondary_color = _ColorChoice("Overlay Text Color", default_label="Auto")
        overlay_form.addRow("Other text color", self._secondary_color)
        self._outline_check = QCheckBox("Shadow behind text (readable over images)")
        overlay_form.addRow(self._outline_check)

        self._show_game_check = QCheckBox("Show game name")
        overlay_form.addRow(self._show_game_check)
        self._show_boss_check = QCheckBox("Show boss name")
        overlay_form.addRow(self._show_boss_check)
        self._show_stats_check = QCheckBox("Show Session • All-time line")
        overlay_form.addRow(self._show_stats_check)
        self._always_on_top_check = QCheckBox("Always on top")
        overlay_form.addRow(self._always_on_top_check)
        layout.addWidget(overlay_group)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

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
            key_edit.keySequenceChanged.connect(self._refresh_conflicts)
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
            pad_label.setWordWrap(True)  # long combos wrap instead of being cut off
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

        self._conflict_label = QLabel()
        self._conflict_label.setWordWrap(True)
        layout.addWidget(self._conflict_label)

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
        self._pad_labels[action].setToolTip(combo_label(combo))
        self._refresh_conflicts()

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

    def _key_available(self, key: str) -> bool:
        """Cached probe: is a keyboard combo free of other programs' hotkeys?"""
        if self._hotkeys is None:
            return True
        if key not in self._availability:
            self._availability[key] = self._hotkeys.key_available(key)
        return self._availability[key]

    def _current_conflicts(self) -> list[Conflict]:
        keys = {a: e.keySequence().toString().lower() for a, e in self._key_edits.items()}
        labels = {action: label for action, label, _s, _d in CONTROL_ACTIONS}
        return find_conflicts(keys, self._pad_values, labels, self._key_available)

    def _refresh_conflicts(self) -> None:
        """Highlight problem bindings and explain them under the table, live."""
        if not hasattr(self, "_conflict_label"):
            return  # still building the page
        conflicts = self._current_conflicts()
        worst: dict[tuple[str, str], str] = {}
        for c in conflicts:
            if worst.get((c.action, c.kind)) != ERROR:
                worst[(c.action, c.kind)] = c.severity
        colors = {ERROR: "#ff4d4d", WARNING: "#f0a030"}
        for action, edit in self._key_edits.items():
            severity = worst.get((action, "keyboard"))
            edit.setStyleSheet(f"border: 2px solid {colors[severity]};" if severity else "")
        for action, label in self._pad_labels.items():
            severity = worst.get((action, "controller"))
            label.setStyleSheet(f"color: {colors[severity]};" if severity else "")
        labels = {action: name for action, name, _s, _d in CONTROL_ACTIONS}
        lines = [
            f"{'⛔' if c.severity == ERROR else '⚠'} {labels[c.action]}: {c.message}"
            for c in conflicts
        ]
        self._conflict_label.setText("\n".join(lines) or "✓ No conflicts")
        self._conflict_label.setStyleSheet(
            "color: #ff4d4d;" if has_errors(conflicts)
            else "color: #f0a030;" if conflicts else "color: #43b581;"
        )

    def _update_color_button(self) -> None:
        self._color_button.setText(self._text_color)
        self._color_button.setStyleSheet(
            f"background-color: {self._text_color}; "
            f"color: {_readable_on(self._text_color)}; font-weight: 600;"
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
        self._ui_text_color.set_color(settings.get(SETTING_UI_TEXT_COLOR, ""))
        self._ui_counter_color.set_color(settings.get(SETTING_UI_COUNTER_COLOR, ""))
        _select_data(self._ui_font_combo, settings.get(SETTING_UI_FONT, ""))
        self._ui_bg_image.set_path(settings.get(SETTING_UI_BG_IMAGE, ""))
        self._ui_bg_dim.setValue(int(settings.get(SETTING_UI_BG_DIM, "60") or 60))
        self._card_color.set_color(settings.get(SETTING_OVERLAY_CARD_COLOR, ""))
        self._overlay_image.set_path(settings.get(SETTING_OVERLAY_BG_IMAGE, ""))
        self._radius_spin.setValue(int(settings.get(SETTING_OVERLAY_CORNER_RADIUS, "12") or 12))
        _select_data(self._overlay_font_combo, settings.get(SETTING_OVERLAY_FONT, ""))
        self._secondary_color.set_color(settings.get(SETTING_OVERLAY_SECONDARY_COLOR, ""))
        self._outline_check.setChecked(
            settings.get(SETTING_OVERLAY_TEXT_OUTLINE, "false") == "true"
        )
        self._minimize_tray_check.setChecked(
            settings.get(SETTING_MINIMIZE_TO_TRAY, "false") == "true"
        )
        self._start_with_windows_check.setChecked(startup.is_enabled())
        self._check_updates_check.setChecked(
            settings.get(SETTING_CHECK_UPDATES, "true") == "true"
        )

        _select_data(self._bg_mode_combo, settings.get(SETTING_OVERLAY_BG_MODE, "dark"))
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
        if self._apply():
            self.accept()

    def _apply(self) -> bool:
        """Save every setting and notify the main window; False if Controls has errors."""
        errors = [c for c in self._current_conflicts() if c.severity == ERROR]
        if errors:
            QMessageBox.warning(
                self, "Fix Controls First", "\n".join(c.message for c in errors)
            )
            return False
        db = self._database
        db.set_setting(SETTING_THEME, self._theme_combo.currentText())
        db.set_setting(SETTING_UI_TEXT_COLOR, self._ui_text_color.color())
        db.set_setting(SETTING_UI_COUNTER_COLOR, self._ui_counter_color.color())
        db.set_setting(SETTING_UI_FONT, self._ui_font_combo.currentData())
        db.set_setting(SETTING_UI_BG_IMAGE, self._ui_bg_image.path())
        db.set_setting(SETTING_UI_BG_DIM, self._ui_bg_dim.value())
        db.set_setting(SETTING_OVERLAY_CARD_COLOR, self._card_color.color())
        db.set_setting(SETTING_OVERLAY_BG_IMAGE, self._overlay_image.path())
        db.set_setting(SETTING_OVERLAY_CORNER_RADIUS, self._radius_spin.value())
        db.set_setting(SETTING_OVERLAY_FONT, self._overlay_font_combo.currentData())
        db.set_setting(SETTING_OVERLAY_SECONDARY_COLOR, self._secondary_color.color())
        db.set_setting(
            SETTING_OVERLAY_TEXT_OUTLINE, "true" if self._outline_check.isChecked() else "false"
        )
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

        db.set_setting(SETTING_OVERLAY_BG_MODE, self._bg_mode_combo.currentData())
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
        return True
