"""
Settings dialog: theme, overlay appearance & behavior, streaming output,
hotkeys, tray, and updates.

Nothing is saved until Apply or Save. Looks (theme, colors, fonts,
backgrounds, the overlay) preview live while you change them: the dialog
sends ``preview_changed`` and the main window shows the unsaved values, then
goes back to the saved look if the dialog is cancelled.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QKeySequence
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
    QStyledItemDelegate,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.counter_manager import CounterSnapshot
from src.database.database import Database
from src.hotkeys.conflicts import ERROR, WARNING, Conflict, find_conflicts, has_errors
from src.hotkeys.gamepad import GamepadManager, combo_label, controllers_supported
from src.hotkeys.hotkey_manager import HotkeyManager, global_hotkeys_available
from src.overlay.overlay_window import OverlayWindow
from src.ui import icons
from src.ui.theme_picker import ThemeGallery
from src.utils import startup
from src.utils.backgrounds import IMAGE_FILTER, import_background
from src.utils.constants import (
    CONTROL_ACTIONS,
    DEFAULT_COUNTER_SOURCE,
    SETTING_BOSS_AUTO_ADVANCE,
    SETTING_BOSS_AUTO_SPLIT,
    SETTING_BOSS_DETECTION,
    SETTING_CHECK_UPDATES,
    SETTING_CONFIRM_CLOSE,
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
    SETTING_OVERLAY_SHOW_SKULL,
    SETTING_OVERLAY_SHOW_STATS,
    SETTING_OVERLAY_TEXT_COLOR,
    SETTING_OVERLAY_TEXT_OUTLINE,
    SETTING_THEME,
    SETTING_TIMER_COMPARISON,
    SETTING_TIMER_DIGITS,
    SETTING_TIMER_METHOD,
    SETTING_TIMER_PAUSE_BACKGROUND,
    SETTING_TIMER_PAUSE_LOADING,
    SETTING_TIMER_PAUSE_NOT_RESPONDING,
    SETTING_TIMER_PAUSE_ON_CLOSE,
    SETTING_TIMER_PAUSE_SCREENS,
    SETTING_UI_BG_DIM,
    SETTING_UI_BG_IMAGE,
    SETTING_UI_COUNTER_COLOR,
    SETTING_UI_FONT,
    SETTING_UI_TEXT_COLOR,
    pad_setting,
)
from src.utils.logger import get_logger
from src.utils.platform_info import IS_MAC, login_item_label

logger = get_logger(__name__)

_BG_MODES: tuple[tuple[str, str], ...] = (
    ("dark", "Card (solid color)"),
    ("chroma", "Green screen (for OBS Chroma Key)"),
    ("image", "Image"),
)
_COUNTER_SOURCE_LABELS: tuple[tuple[str, str], ...] = (
    ("session", "Deaths this session"),
    ("boss", "Deaths on this boss"),
    ("total", "All-time deaths"),
    ("run", "Deaths this speedrun run"),
)


def _readable_on(background: str) -> str:
    """Black or white, whichever reads better on ``background``."""
    return "#000000" if QColor(background).lightness() > 150 else "#ffffff"


class _ColorChoice(QWidget):
    """A color swatch button plus "Default"; :meth:`color` is "" for the default."""

    changed = Signal()

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
        if color != self._color:
            self._color = color
            self.changed.emit()
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


class _FontPreviewDelegate(QStyledItemDelegate):
    """
    Draws each font's name in that font, but only for the rows on screen.

    Giving every item its own font instead (Qt.FontRole) makes Qt load all
    installed fonts whenever the window restyles, which froze the app for
    seconds on each Settings change.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fonts: dict[str, QFont] = {}

    def initStyleOption(self, option, index) -> None:  # noqa: N802 - Qt override
        super().initStyleOption(option, index)
        family = index.data(Qt.ItemDataRole.UserRole)
        if family:
            font = self._fonts.get(family)
            if font is None:
                font = self._fonts[family] = QFont(family, option.font.pointSize())
            option.font = font


def _font_combo(default_label: str) -> QComboBox:
    """Installed font families, with ``default_label`` (value "") first."""
    combo = QComboBox()
    combo.addItem(default_label, userData="")
    for family in QFontDatabase.families():
        if not family.startswith("@"):  # vertical-text variants of CJK fonts
            combo.addItem(family, userData=family)
    combo.setItemDelegate(_FontPreviewDelegate(combo))
    combo.setMaxVisibleItems(16)
    return combo


def _select_data(combo: QComboBox, value: str) -> None:
    combo.setCurrentIndex(max(combo.findData(value), 0))


_BOSS_OPTIONS: tuple[tuple[str, str], ...] = (
    (SETTING_BOSS_DETECTION, "Detect boss kills from saved victory screens"),
    (SETTING_BOSS_AUTO_ADVANCE, "After a boss is defeated, select the next boss"),
    (SETTING_BOSS_AUTO_SPLIT, "After a boss is defeated, split the speedrun timer"),
)
_TIMER_COMPARISONS: tuple[tuple[str, str], ...] = (
    ("pb", "Personal Best"),
    ("previous", "Previous Run"),
    ("best", "Best Segments (sum of best)"),
)
_TIMER_PRECISIONS: tuple[tuple[int, str], ...] = (
    (0, "Seconds (1:23)"),
    (1, "Tenths (1:23.4)"),
    (2, "Hundredths (1:23.45)"),
    (3, "Milliseconds (1:23.456)"),
)
_TIMER_PAUSE_OPTIONS: tuple[tuple[str, str], ...] = (
    (SETTING_TIMER_PAUSE_ON_CLOSE, "Pause the timer if the game closes or crashes"),
    (
        SETTING_TIMER_PAUSE_NOT_RESPONDING,
        "Stop game time while the game is frozen (Not Responding)",
    ),
    (SETTING_TIMER_PAUSE_LOADING, "Stop game time on black loading screens"),
    (
        SETTING_TIMER_PAUSE_SCREENS,
        "Stop game time on pause, loading and cutscene screens you've marked",
    ),
    (
        SETTING_TIMER_PAUSE_BACKGROUND,
        "Stop game time while the game is minimized or in the background",
    ),
)


class _ImageChoice(QWidget):
    """Shows the chosen background image's name, with Choose… and Remove."""

    changed = Signal()

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
        if path != self._path:
            self._path = path
            self.changed.emit()
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


def _keyboard_note() -> str:
    """What's different about keyboard shortcuts on this computer, or ""."""
    if not global_hotkeys_available():
        return (
            "This desktop (Wayland) doesn't let apps hear keys while a game has focus, so "
            "keyboard shortcuts only work inside this window. Use a controller combo or "
            "the phone remote in-game, or log in with an X11 (Xorg) session."
        )
    if IS_MAC:
        return (
            "On a Mac, F-keys control brightness and volume unless you hold fn. To use "
            "F9 on its own, turn on \"Use F1, F2, etc. keys as standard function keys\" "
            "in System Settings → Keyboard."
        )
    return ""


class SettingsWindow(QDialog):
    """
    Modal dialog exposing all user-configurable settings.

    Signals:
        settings_changed: Emitted whenever settings are saved, so the
            main window can refresh theme/overlay/hotkeys/stream output live.
        preview_changed: Unsaved look settings to show now ({} = the saved look).
    """

    settings_changed = Signal()
    preview_changed = Signal(dict)
    TAB_GENERAL, TAB_APPEARANCE, TAB_OVERLAY, TAB_SPEEDRUN, TAB_CONTROLS = range(5)

    def __init__(
        self,
        database: Database,
        gamepad: GamepadManager | None = None,
        hotkeys: HotkeyManager | None = None,
        parent=None,
        tab: int = 0,
    ) -> None:
        super().__init__(parent)
        self._database = database
        self._gamepad = gamepad
        self._hotkeys = hotkeys  # probes whether keys are taken by other programs
        self._availability: dict[str, bool] = {}
        self._recording_action: str | None = None
        self._text_color = "#ff4d4d"
        self.previewed = False  # True once the main window showed unsaved looks
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)  # one restyle per burst of changes
        self._preview_timer.timeout.connect(self._send_preview)
        self.setWindowTitle("Settings")
        self.setMinimumSize(720, 620)  # all five tabs fit side by side
        self._build_ui()
        self._load_current_values()
        self._connect_preview()
        self._tabs.setCurrentIndex(tab)

    # ----------------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 14)
        tabs = self._tabs = QTabWidget()
        tabs.setDocumentMode(True)
        outer.addWidget(tabs)
        general_page = QWidget()
        layout = QVBoxLayout(general_page)
        for page, title, icon_name in (
            (general_page, "General", "settings"),
            (self._build_appearance_page(), "Appearance", "palette"),
            (self._build_overlay_page(), "Overlay", "layers"),
            (self._build_speedrun_page(), "Speedrun", "timer"),
            (self._build_controls_page(), "Controls", "gamepad-2"),
        ):
            tabs.addTab(page, icons.icon(icon_name, icons.color(icons.NORMAL), size=16), title)

        # --- General ---
        general_group = QGroupBox("General")
        general_form = QFormLayout(general_group)
        self._minimize_tray_check = QCheckBox("Minimize to system tray on close")
        general_form.addRow(self._minimize_tray_check)
        self._confirm_close_check = QCheckBox("Ask before closing (your progress is saved first)")
        general_form.addRow(self._confirm_close_check)
        self._start_with_windows_check = QCheckBox(login_item_label())
        if not startup.startup_supported():
            self._start_with_windows_check.setEnabled(False)
            self._start_with_windows_check.setToolTip(
                "Available in the installed app (not when running from source)."
            )
        general_form.addRow(self._start_with_windows_check)
        self._check_updates_check = QCheckBox("Check for updates on startup")
        general_form.addRow(self._check_updates_check)
        layout.addWidget(general_group)

        boss_group = QGroupBox("Boss kills")
        boss_layout = QVBoxLayout(boss_group)
        self._boss_checks: dict[str, QCheckBox] = {}
        for key, label in _BOSS_OPTIONS:
            check = QCheckBox(label)
            boss_layout.addWidget(check)
            self._boss_checks[key] = check
        boss_note = QLabel(
            "Teach a game its victory banner with Capture Screen (Detection page) after a boss "
            "fight. The Boss Defeated key (Controls) does the same by hand."
        )
        boss_note.setWordWrap(True)
        boss_note.setStyleSheet("color: #999999; font-size: 11px;")
        boss_layout.addWidget(boss_note)
        layout.addWidget(boss_group)

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
        hint = QLabel("Looks change live as you edit; nothing is kept until you save.")
        hint.setObjectName("Muted")
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("GhostButton")
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("Apply")
        apply_button.setToolTip("Save without closing Settings.")
        apply_button.clicked.connect(self._apply)
        save_button = QPushButton(" Save")
        save_button.setObjectName("AccentButton")
        icons.set_icon(save_button, "check", icons.ACCENT, size=16)
        save_button.setMinimumWidth(120)
        save_button.clicked.connect(self._save)
        buttons.addWidget(hint, 1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(apply_button)
        buttons.addWidget(save_button)
        outer.addLayout(buttons)

    def _build_appearance_page(self) -> QWidget:
        """Main window look: theme, colors, font, background image."""
        page = QWidget()
        layout = QVBoxLayout(page)

        theme_group = QGroupBox("Theme")
        theme_layout = QVBoxLayout(theme_group)
        self._gallery = ThemeGallery()
        theme_layout.addWidget(self._gallery)
        theme_note = QLabel(
            "Glass and Clay are downloaded when you pick them (a few KB) and can be "
            "uninstalled again. Click a theme to try it."
        )
        theme_note.setObjectName("Muted")
        theme_note.setWordWrap(True)
        theme_layout.addWidget(theme_note)
        layout.addWidget(theme_group)

        window_group = QGroupBox("Text and background")
        window_form = QFormLayout(window_group)
        self._ui_font_combo = _font_combo("Theme font (Segoe UI)")
        window_form.addRow("Font", self._ui_font_combo)
        self._ui_text_color = _ColorChoice("Text Color")
        window_form.addRow("Text color", self._ui_text_color)
        self._ui_counter_color = _ColorChoice("Death Number Color")
        window_form.addRow("Death number color", self._ui_counter_color)
        self._counter_source_combo = QComboBox()
        for value, label in _COUNTER_SOURCE_LABELS:
            self._counter_source_combo.addItem(label, userData=value)
        self._counter_source_combo.setToolTip("Used by this window, the overlay and mini mode.")
        window_form.addRow("Big number shows", self._counter_source_combo)
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
        layout.addStretch()
        return self._scrolling(page)

    def _build_overlay_page(self) -> QWidget:
        """The overlay (and timer / mini windows): background, text, what's shown."""
        page = QWidget()
        layout = QVBoxLayout(page)

        preview_group = QGroupBox("Preview")
        preview_layout = QHBoxLayout(preview_group)
        self._overlay_preview = OverlayWindow(parent=preview_group)
        self._overlay_preview.setWindowFlags(Qt.WindowType.Widget)  # inside the dialog
        self._overlay_preview.set_locked(True)
        self._overlay_preview._size_grip.hide()
        self._overlay_preview.setFixedSize(280, 150)
        self._overlay_preview.update_counters(
            CounterSnapshot("Elden Ring", "Margit, the Fell Omen", 12, 348, 27)
        )
        preview_tip = QLabel(
            "The real overlay changes too while you edit.\n\n"
            "Tip: right-click the overlay for quick options; double-click it to come here."
        )
        preview_tip.setObjectName("Muted")
        preview_tip.setWordWrap(True)
        preview_layout.addWidget(self._overlay_preview)
        preview_layout.addSpacing(10)
        preview_layout.addWidget(preview_tip, 1)
        layout.addWidget(preview_group)

        overlay_group = QGroupBox("Background")
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
        layout.addWidget(overlay_group)

        text_group = QGroupBox("Text")
        text_form = QFormLayout(text_group)
        self._overlay_font_combo = _font_combo("Default font")
        text_form.addRow("Font", self._overlay_font_combo)
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(10, 96)
        text_form.addRow("Number size", self._font_size_spin)
        color_row = QHBoxLayout()
        self._color_button = QPushButton()
        self._color_button.setFixedWidth(90)
        self._color_button.clicked.connect(self._pick_color)
        color_row.addWidget(self._color_button)
        color_row.addStretch()
        text_form.addRow("Number color", color_row)
        self._secondary_color = _ColorChoice("Overlay Text Color", default_label="Auto")
        text_form.addRow("Other text color", self._secondary_color)
        self._outline_check = QCheckBox("Shadow behind text (readable over images)")
        text_form.addRow(self._outline_check)
        layout.addWidget(text_group)

        show_group = QGroupBox("Show")
        show_layout = QVBoxLayout(show_group)
        self._show_game_check = QCheckBox("Game name")
        self._show_boss_check = QCheckBox("Boss name")
        self._show_stats_check = QCheckBox("Session • All-time line")
        self._show_skull_check = QCheckBox("Skull badge (it evolves every 10 deaths)")
        self._always_on_top_check = QCheckBox("Always on top of other windows")
        for check in (
            self._show_game_check,
            self._show_boss_check,
            self._show_stats_check,
            self._show_skull_check,
            self._always_on_top_check,
        ):
            show_layout.addWidget(check)
        layout.addWidget(show_group)
        layout.addStretch()
        return self._scrolling(page)

    @staticmethod
    def _scrolling(page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    # ----------------------------------------------------------------
    # Live preview
    # ----------------------------------------------------------------
    def _connect_preview(self) -> None:
        """Every look control previews on change (connected after loading the values)."""
        self._gallery.theme_changed.connect(self._schedule_preview)
        for combo in (
            self._ui_font_combo,
            self._counter_source_combo,
            self._bg_mode_combo,
            self._overlay_font_combo,
        ):
            combo.currentIndexChanged.connect(self._schedule_preview)
        for choice in (
            self._ui_text_color,
            self._ui_counter_color,
            self._card_color,
            self._secondary_color,
            self._ui_bg_image,
            self._overlay_image,
        ):
            choice.changed.connect(self._schedule_preview)
        self._ui_bg_dim.valueChanged.connect(self._schedule_preview)
        self._opacity_spin.valueChanged.connect(self._schedule_preview)
        self._radius_spin.valueChanged.connect(self._schedule_preview)
        self._font_size_spin.valueChanged.connect(self._schedule_preview)
        for check in (
            self._outline_check,
            self._show_game_check,
            self._show_boss_check,
            self._show_stats_check,
            self._show_skull_check,
        ):
            check.toggled.connect(self._schedule_preview)
        self._update_overlay_preview()

    def _schedule_preview(self, *_args) -> None:
        self._update_overlay_preview()
        self._preview_timer.start()

    def _send_preview(self) -> None:
        self.previewed = True
        self.preview_changed.emit(self._look_values())

    def _update_overlay_preview(self) -> None:
        settings = self._database.get_all_settings()
        settings.update(self._look_values())
        self._overlay_preview.apply_display_settings(settings)

    def _look_values(self) -> dict[str, str]:
        """The look settings as the form has them now (strings, like the settings table)."""

        def flag(check: QCheckBox) -> str:
            return "true" if check.isChecked() else "false"

        return {
            SETTING_THEME: self._gallery.theme(),
            SETTING_UI_TEXT_COLOR: self._ui_text_color.color(),
            SETTING_UI_COUNTER_COLOR: self._ui_counter_color.color(),
            SETTING_UI_FONT: self._ui_font_combo.currentData() or "",
            SETTING_UI_BG_IMAGE: self._ui_bg_image.path(),
            SETTING_UI_BG_DIM: str(self._ui_bg_dim.value()),
            SETTING_OVERLAY_CARD_COLOR: self._card_color.color(),
            SETTING_OVERLAY_BG_IMAGE: self._overlay_image.path(),
            SETTING_OVERLAY_CORNER_RADIUS: str(self._radius_spin.value()),
            SETTING_OVERLAY_FONT: self._overlay_font_combo.currentData() or "",
            SETTING_OVERLAY_SECONDARY_COLOR: self._secondary_color.color(),
            SETTING_OVERLAY_TEXT_OUTLINE: flag(self._outline_check),
            SETTING_OVERLAY_BG_MODE: self._bg_mode_combo.currentData(),
            SETTING_OVERLAY_COUNTER_SOURCE: self._counter_source_combo.currentData(),
            SETTING_OVERLAY_TEXT_COLOR: self._text_color,
            SETTING_OVERLAY_FONT_SIZE: str(self._font_size_spin.value()),
            SETTING_OVERLAY_OPACITY: str(self._opacity_spin.value()),
            SETTING_OVERLAY_SHOW_GAME: flag(self._show_game_check),
            SETTING_OVERLAY_SHOW_BOSS: flag(self._show_boss_check),
            SETTING_OVERLAY_SHOW_STATS: flag(self._show_stats_check),
            SETTING_OVERLAY_SHOW_SKULL: flag(self._show_skull_check),
        }

    def _build_speedrun_page(self) -> QWidget:
        """Speedrun timer: timing method, comparison, precision and auto-pause."""
        page = QWidget()
        layout = QVBoxLayout(page)

        timer_group = QGroupBox("Timer")
        timer_form = QFormLayout(timer_group)
        self._timer_method_combo = QComboBox()
        self._timer_method_combo.addItem("Real Time", userData="real")
        self._timer_method_combo.addItem("Game Time (without loads and pauses)", userData="game")
        timer_form.addRow("Timing method", self._timer_method_combo)
        self._timer_comparison_combo = QComboBox()
        for value, label in _TIMER_COMPARISONS:
            self._timer_comparison_combo.addItem(label, userData=value)
        timer_form.addRow("Compare against", self._timer_comparison_combo)
        self._timer_digits_combo = QComboBox()
        for digits, label in _TIMER_PRECISIONS:
            self._timer_digits_combo.addItem(label, userData=str(digits))
        timer_form.addRow("Precision", self._timer_digits_combo)
        layout.addWidget(timer_group)

        pause_group = QGroupBox("Automatic pausing")
        pause_layout = QVBoxLayout(pause_group)
        self._timer_pause_checks: dict[str, QCheckBox] = {}
        for key, label in _TIMER_PAUSE_OPTIONS:
            check = QCheckBox(label)
            pause_layout.addWidget(check)
            self._timer_pause_checks[key] = check
        note = QLabel(
            "Only the first one stops the whole timer. The others stop game time only; "
            "real time keeps running, as speedrun rules expect. Mark pause, loading and "
            "cutscene screens on the Detection page. Needs the game's .exe set."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #999999; font-size: 11px;")
        pause_layout.addWidget(note)
        layout.addWidget(pause_group)
        layout.addStretch()
        return page

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
        note = _keyboard_note()
        if note:
            note_label = QLabel(note)
            note_label.setObjectName("Muted")
            note_label.setWordWrap(True)
            layout.addWidget(note_label)

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
            clear_key = QPushButton()
            icons.set_icon(clear_key, "x", size=14)
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
            clear_pad = QPushButton()
            icons.set_icon(clear_pad, "x", size=14)
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
        if self._gamepad is None or not controllers_supported():
            text = "Controllers aren't supported on this system yet."
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
            self._schedule_preview()

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

        self._gallery.set_theme(settings.get(SETTING_THEME, "dark"))
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
        self._confirm_close_check.setChecked(
            settings.get(SETTING_CONFIRM_CLOSE, "true") == "true"
        )
        self._minimize_tray_check.setChecked(
            settings.get(SETTING_MINIMIZE_TO_TRAY, "false") == "true"
        )
        self._start_with_windows_check.setChecked(startup.is_enabled())
        self._check_updates_check.setChecked(
            settings.get(SETTING_CHECK_UPDATES, "true") == "true"
        )
        for key, check in self._boss_checks.items():
            check.setChecked(settings.get(key, "true") == "true")

        _select_data(self._bg_mode_combo, settings.get(SETTING_OVERLAY_BG_MODE, "dark"))
        _select_data(
            self._counter_source_combo,
            settings.get(SETTING_OVERLAY_COUNTER_SOURCE, DEFAULT_COUNTER_SOURCE),
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
        self._show_skull_check.setChecked(
            settings.get(SETTING_OVERLAY_SHOW_SKULL, "true") == "true"
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

        _select_data(self._timer_method_combo, settings.get(SETTING_TIMER_METHOD, "real"))
        _select_data(
            self._timer_comparison_combo, settings.get(SETTING_TIMER_COMPARISON, "pb")
        )
        _select_data(self._timer_digits_combo, settings.get(SETTING_TIMER_DIGITS, "2"))
        for key, check in self._timer_pause_checks.items():
            default = "false" if key == SETTING_TIMER_PAUSE_BACKGROUND else "true"
            check.setChecked(settings.get(key, default) == "true")

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
        for key, value in self._look_values().items():
            db.set_setting(key, value)
        db.set_setting(
            SETTING_MINIMIZE_TO_TRAY,
            "true" if self._minimize_tray_check.isChecked() else "false",
        )
        db.set_setting(
            SETTING_CONFIRM_CLOSE, "true" if self._confirm_close_check.isChecked() else "false"
        )
        if startup.startup_supported():
            try:
                startup.set_enabled(self._start_with_windows_check.isChecked())
            except OSError as exc:
                QMessageBox.warning(self, login_item_label(), f"Could not update: {exc}")
        db.set_setting(
            SETTING_CHECK_UPDATES,
            "true" if self._check_updates_check.isChecked() else "false",
        )
        for key, check in self._boss_checks.items():
            db.set_setting(key, "true" if check.isChecked() else "false")

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

        db.set_setting(SETTING_TIMER_METHOD, self._timer_method_combo.currentData())
        db.set_setting(SETTING_TIMER_COMPARISON, self._timer_comparison_combo.currentData())
        db.set_setting(SETTING_TIMER_DIGITS, self._timer_digits_combo.currentData())
        for key, check in self._timer_pause_checks.items():
            db.set_setting(key, "true" if check.isChecked() else "false")

        # An empty field means "unbound" for keyboard and controller alike.
        for action, _label, setting_key, _default in CONTROL_ACTIONS:
            db.set_setting(setting_key, self._key_edits[action].keySequence().toString().lower())
            db.set_setting(pad_setting(action), self._pad_values.get(action, ""))

        logger.info("Settings saved")
        self.settings_changed.emit()
        self.previewed = False  # what's shown is what's saved now
        return True

    def reject(self) -> None:  # noqa: D102 - stop a pending preview first
        self._preview_timer.stop()
        super().reject()
