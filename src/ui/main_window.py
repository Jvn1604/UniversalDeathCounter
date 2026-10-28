"""
Main application window.

Wires together the database (per active profile), core managers, hotkeys,
overlay, system tray, deaths.txt stream output, update checker, and theme
system into the primary user-facing UI.
"""

from __future__ import annotations

import dataclasses
import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPixmap,
    QScreen,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.core.counter_manager import CounterManager, CounterSnapshot
from src.core.session_manager import SessionManager
from src.core.speedrun import (
    AHEAD,
    BEHIND,
    FINISHED,
    GOLD,
    IDLE,
    RUNNING,
    SpeedrunController,
    SpeedrunTimer,
    format_time,
)
from src.core.statistics import StatisticsService
from src.database.database import SCREEN_DEATH, SCREEN_PAUSE, SCREEN_VICTORY, Database
from src.detection.death_watcher import (
    ACTIVITY_BACKGROUND,
    ACTIVITY_CLOSED,
    ACTIVITY_LOADING,
    ACTIVITY_NOT_RESPONDING,
    ACTIVITY_PAUSE_SCREEN,
    DeathWatcher,
    WatchConfig,
)
from src.detection.game_window import (
    capture_game_frame,
    detection_available,
    exe_display_name,
    running_exe_paths,
)
from src.detection.log_watcher import LogWatchConfig, LogWatcher, compile_death_pattern
from src.detection.matchers import (
    SOULS_PRESET_EXES,
    DeathTemplate,
    HealthBarMatcher,
    build_matcher,
    build_screen_matcher,
)
from src.hotkeys.gamepad import GamepadManager, combo_label
from src.hotkeys.hotkey_manager import HotkeyManager
from src.overlay.overlay_window import OverlayWindow, available_screen_rects
from src.themes.theme_manager import THEME_BASE_COLORS, apply_theme
from src.ui.about_window import AboutWindow
from src.ui.auto_detect_window import (
    AutoDetectWindow,
    CalibrationDialog,
    DeathScreenDialog,
    HealthBarDialog,
    first_death_hint,
)
from src.ui.boss_window import BossWindow
from src.ui.death_log_window import DeathLogWindow
from src.ui.obs_guide_window import ObsGuideWindow
from src.ui.settings_window import SettingsWindow
from src.ui.statistics_window import StatisticsWindow
from src.ui.timer_window import RunHistoryDialog, SplitsDialog, TimerWindow
from src.ui.widgets import (
    StatTile,
    StatusPill,
    card,
    field,
    glow,
    nav_button,
    page_header,
    row,
    section_title,
)
from src.utils.backgrounds import cover, load_background
from src.utils.constants import (
    APP_BRAND,
    APP_NAME,
    APP_SHORT_NAME,
    APP_SUBTITLE,
    APP_VERSION,
    CONTROL_ACTIONS,
    DETECTION_MODE_HEALTH,
    DETECTION_MODE_LOG,
    DETECTION_MODE_OFF,
    DETECTION_MODE_SOULS,
    DETECTION_MODE_TEMPLATE,
    ICONS_DIR,
    SAVES_DIR,
    SETTING_BOSS_AUTO_ADVANCE,
    SETTING_BOSS_AUTO_SPLIT,
    SETTING_BOSS_DETECTION,
    SETTING_CHECK_UPDATES,
    SETTING_DEATHS_TXT_ENABLED,
    SETTING_DEATHS_TXT_PATH,
    SETTING_DEATHS_TXT_TEMPLATE,
    SETTING_DETECTION_COOLDOWN,
    SETTING_HOTKEY_CALIBRATE,
    SETTING_HOTKEY_UNDO,
    SETTING_LAST_BOSS_ID,
    SETTING_LAST_GAME_ID,
    SETTING_MAIN_WINDOW_GEOMETRY,
    SETTING_MINIMIZE_TO_TRAY,
    SETTING_OVERLAY_ALWAYS_ON_TOP,
    SETTING_OVERLAY_BG_MODE,
    SETTING_OVERLAY_COUNTER_SOURCE,
    SETTING_OVERLAY_GEOMETRY,
    SETTING_THEME,
    SETTING_TIMER_AUTOSAVE,
    SETTING_TIMER_COMPARISON,
    SETTING_TIMER_DIGITS,
    SETTING_TIMER_GEOMETRY,
    SETTING_TIMER_METHOD,
    SETTING_TIMER_PAUSE_BACKGROUND,
    SETTING_TIMER_PAUSE_LOADING,
    SETTING_TIMER_PAUSE_NOT_RESPONDING,
    SETTING_TIMER_PAUSE_ON_CLOSE,
    SETTING_TIMER_PAUSE_SCREENS,
    SETTING_TIMER_VISIBLE,
    SETTING_UI_BG_DIM,
    SETTING_UI_BG_IMAGE,
    SETTING_UI_COUNTER_COLOR,
    SETTING_UI_FONT,
    SETTING_UI_TEXT_COLOR,
    pad_setting,
)
from src.utils.exporters import write_csv_summary
from src.utils.logger import get_logger
from src.utils.profiles import DEFAULT_PROFILE_NAME, ProfileManager
from src.utils.screens import display_name, fit_to_screens, screen_index_at
from src.utils.stream_writer import render_template, write_deaths_file
from src.utils.update_checker import UpdateChecker

logger = get_logger(__name__)

# Last entry of the Game dropdown, which opens the add-game-from-.exe flow.
_ADD_GAME_SENTINEL = "__add_game_from_exe__"
_ADD_GAME_LABEL = "+ Add game from .exe…"
_GAME_LAUNCH_POLL_MS = 3000
_AUTOSAVE_MS = 10_000  # a run in progress is saved this often (crash recovery)
# What makes the speedrun timer's game time stop: (reason shown, setting).
_GAME_TIME_PAUSES = {
    ACTIVITY_LOADING: ("Loading", SETTING_TIMER_PAUSE_LOADING),
    ACTIVITY_PAUSE_SCREEN: ("Game paused", SETTING_TIMER_PAUSE_SCREENS),
    ACTIVITY_NOT_RESPONDING: ("Game not responding", SETTING_TIMER_PAUSE_NOT_RESPONDING),
    ACTIVITY_BACKGROUND: ("Game in background", SETTING_TIMER_PAUSE_BACKGROUND),
}
# Sidebar pages, in stack order.
_PAGE_HOME, _PAGE_TIMER, _PAGE_STATS, _PAGE_DETECTION = range(4)
_TIMER_STATUS_COLORS = {AHEAD: "#3ad07a", BEHIND: "#ff5c5c", GOLD: "#ffd24a"}
_MODE_NAMES = {
    DETECTION_MODE_OFF: "Off",
    DETECTION_MODE_TEMPLATE: "Death screen",
    DETECTION_MODE_SOULS: "Souls preset",
    DETECTION_MODE_HEALTH: "Health bar",
    DETECTION_MODE_LOG: "Log file",
}
# Caption under the big number, by the "Big number shows" setting.
_COUNTER_CAPTIONS = {
    "session": "DEATHS THIS SESSION",
    "boss": "DEATHS ON THIS BOSS",
    "total": "ALL-TIME DEATHS",
}


class _BackgroundHost(QWidget):
    """Central widget that paints an optional background image under everything."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QPixmap | None = None
        self._scaled: QPixmap | None = None  # cache: rescaled only on resize
        self._dim = QColor(0, 0, 0, 0)

    def set_background(self, image: QPixmap | None, dim_color: QColor) -> None:
        """Show ``image`` (None for none) under a ``dim_color`` layer that keeps text readable."""
        self._image, self._scaled, self._dim = image, None, dim_color
        self.update()

    def has_image(self) -> bool:
        return self._image is not None

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        if self._image is not None:
            if self._scaled is None or self._scaled.size() != self.size():
                self._scaled = cover(self._image, self.size())
            painter = QPainter(self)
            painter.drawPixmap(0, 0, self._scaled)
            painter.fillRect(self.rect(), self._dim)
            painter.end()
        super().paintEvent(event)


class MainWindow(QMainWindow):
    """The application's primary window."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(820, 600)
        self.resize(1000, 700)

        icon_path = ICONS_DIR / "app_icon.ico"  # multi-size: crisp in title bar and tray
        self._app_icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        self.setWindowIcon(self._app_icon)

        # --- Profile + core wiring ---
        self._profile_manager = ProfileManager()
        self._database = Database(self._profile_manager.active_db_path())
        self._session_manager = SessionManager(self._database)
        self._counter_manager = CounterManager(self._database, self._session_manager)
        self._statistics_service = StatisticsService(self._database)
        self._overlay = OverlayWindow()
        self._timer_window = TimerWindow()
        self._timer_window.action_requested.connect(self._on_timer_window_action)
        self._speedrun: SpeedrunController | None = None
        self._death_watcher = DeathWatcher(parent=self)
        self._log_watcher = LogWatcher(parent=self)
        self._detection_paused = False  # not persisted: every launch starts active
        self._quitting = False
        self._closed = False  # cleanup ran; a second close must not touch the database
        # True once this session has written a crash-recovery snapshot. Until
        # then a snapshot in the settings belongs to a crashed earlier run,
        # waiting for the recovery prompt, and must not be cleared.
        self._autosave_written = False

        self._update_window_title()
        self._build_menu()
        self._build_ui()
        self._rebuild_profile_menu()  # again, now that the header's profile box exists
        self._detect_status_label.add_mirror(self._detect_status_label_mirror)
        self._build_tray()
        self._setup_hotkeys()
        self._setup_death_watcher()
        self._apply_saved_settings()
        self._restore_main_geometry()
        QGuiApplication.instance().screenRemoved.connect(self._on_screen_removed)
        self._reload_games()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(_AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()
        # Once the window is up; a QTimer (not singleShot) so closing can cancel it.
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setSingleShot(True)
        self._recovery_timer.timeout.connect(self._offer_run_recovery)
        self._recovery_timer.start(0)
        self._maybe_check_updates()

    def _update_window_title(self) -> None:
        profile = self._profile_manager.active_profile
        suffix = "" if profile == DEFAULT_PROFILE_NAME else f"  [{profile}]"
        self.setWindowTitle(f"{APP_NAME}{suffix}")

    # ----------------------------------------------------------------
    # Menu
    # ----------------------------------------------------------------
    def _build_menu(self) -> None:
        menu_bar: QMenuBar = self.menuBar()
        menu_bar.clear()

        file_menu = menu_bar.addMenu("&File")
        export_action = file_menu.addAction("Export Backup (JSON)…")
        export_action.triggered.connect(self._export_backup)
        import_action = file_menu.addAction("Import Backup (JSON)…")
        import_action.triggered.connect(self._import_backup)
        csv_action = file_menu.addAction("Export CSV Summary…")
        csv_action.triggered.connect(self._export_csv)
        file_menu.addSeparator()
        clear_action = file_menu.addAction("Clear All Data…")
        clear_action.triggered.connect(self._clear_all_data)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.triggered.connect(self._quit_app)

        self._profile_menu = menu_bar.addMenu("&Profile")
        self._rebuild_profile_menu()

        manage_menu = menu_bar.addMenu("&Manage")
        manage_action = manage_menu.addAction("Games && Bosses…")
        manage_action.triggered.connect(self._open_boss_window)
        detect_action = manage_menu.addAction("Auto Death Detection…")
        detect_action.triggered.connect(self._open_auto_detect_window)
        splits_action = manage_menu.addAction("Speedrun Splits…")
        splits_action.triggered.connect(self._open_splits_dialog)

        view_menu = menu_bar.addMenu("&View")
        overlay_action = view_menu.addAction("Toggle Overlay")
        overlay_action.triggered.connect(self._toggle_overlay)
        self._add_display_menu(view_menu)
        timer_action = view_menu.addAction("Speedrun Timer")
        timer_action.triggered.connect(self._toggle_timer_window)
        history_action = view_menu.addAction("Run History && Records…")
        history_action.triggered.connect(self._open_run_history)
        stats_action = view_menu.addAction("Statistics && Graphs…")
        stats_action.triggered.connect(self._show_statistics)
        log_action = view_menu.addAction("Death Log…")
        log_action.triggered.connect(self._open_death_log)

        settings_menu = menu_bar.addMenu("&Settings")
        settings_action = settings_menu.addAction("Preferences…")
        settings_action.triggered.connect(self._open_settings_window)

        help_menu = menu_bar.addMenu("&Help")
        obs_action = help_menu.addAction("Set Up OBS Overlay…")
        obs_action.triggered.connect(self._open_obs_guide)
        help_menu.addSeparator()
        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self._open_about_window)

    def _rebuild_profile_menu(self) -> None:
        self._profile_menu.clear()
        active = self._profile_manager.active_profile
        combo = getattr(self, "_profile_combo", None)  # built after the menu
        if combo is not None:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self._profile_manager.list_profiles())
            combo.setCurrentText(active)
            combo.blockSignals(False)
        for name in self._profile_manager.list_profiles():
            action = self._profile_menu.addAction(f"{'● ' if name == active else '   '}{name}")
            action.triggered.connect(lambda _=False, n=name: self._switch_profile(n))
        self._profile_menu.addSeparator()
        new_action = self._profile_menu.addAction("New Profile…")
        new_action.triggered.connect(self._create_profile)
        delete_action = self._profile_menu.addAction("Delete Profile…")
        delete_action.triggered.connect(self._delete_profile)

    # ----------------------------------------------------------------
    # Central UI
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        """Top bar, sidebar navigation, and a stack of pages (Home, Timer, Stats, Detection)."""
        central = self._background = _BackgroundHost()
        self.setCentralWidget(central)
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._build_top_bar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._pages = QStackedWidget()
        body.addWidget(self._build_sidebar())
        body.addWidget(self._pages, 1)
        shell.addLayout(body, 1)

        for builder in (
            self._build_home_page,
            self._build_timer_page,
            self._build_stats_page,
            self._build_detection_page,
        ):
            page = builder()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self._pages.addWidget(scroll)
        self._pages.currentChanged.connect(self._on_page_changed)
        self._page_timer = QTimer(self)  # live Timer page while it's showing
        self._page_timer.timeout.connect(self._refresh_timer_page)
        self._show_page(_PAGE_HOME)

    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(12)
        logo_label = QLabel()
        logo = QPixmap(str(ICONS_DIR / "app_icon_48.png"))
        if not logo.isNull():
            logo_label.setPixmap(
                logo.scaled(
                    36,
                    36,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title_label = QLabel(APP_BRAND)
        title_label.setObjectName("TitleLabel")
        subtitle_label = QLabel(APP_SUBTITLE.upper())
        subtitle_label.setObjectName("Subtitle")
        titles.addWidget(title_label)
        titles.addWidget(subtitle_label)
        layout.addWidget(logo_label)
        layout.addLayout(titles, 1)

        profile_caption = QLabel("PROFILE")
        profile_caption.setObjectName("FieldLabel")
        self._profile_combo = QComboBox()
        self._profile_combo.setToolTip("Each profile keeps its own games and counts.")
        self._profile_combo.setMinimumWidth(150)
        self._profile_combo.activated.connect(
            lambda index: self._switch_profile(self._profile_combo.itemText(index))
        )
        settings_button = QPushButton("≡")
        settings_button.setObjectName("IconButton")
        settings_button.setToolTip("Settings")
        settings_button.clicked.connect(self._open_settings_window)
        layout.addWidget(profile_caption)
        layout.addWidget(self._profile_combo)
        layout.addWidget(settings_button)
        return bar

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(176)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 14, 0, 10)
        layout.setSpacing(2)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        for index, text in enumerate(
            ("⌂   Home", "◷   Timer", "▤   Stats", "◎   Detection")
        ):
            button = nav_button(text)
            button.clicked.connect(lambda _=False, i=index: self._show_page(i))
            self._nav_group.addButton(button, index)
            self._nav_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch()
        for text, handler in (
            ("▣   Overlay", self._toggle_overlay),
            ("◉   OBS Setup", self._open_obs_guide),
            ("≡   Settings", self._open_settings_window),
        ):
            button = nav_button(text, checkable=False)
            button.clicked.connect(handler)
            layout.addWidget(button)
        footer = QLabel(f"{APP_SHORT_NAME} v{APP_VERSION}")
        footer.setObjectName("NavFooter")
        layout.addWidget(footer)
        return sidebar

    @staticmethod
    def _page_layout() -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(16)
        return page, layout

    # Home -------------------------------------------------------------
    def _build_home_page(self) -> QWidget:
        page, layout = self._page_layout()

        self._game_combo = QComboBox()
        self._game_combo.setPlaceholderText("Add a game: pick its .exe")
        self._game_combo.currentIndexChanged.connect(self._on_game_changed)
        self._boss_combo = QComboBox()
        self._boss_combo.currentIndexChanged.connect(self._on_boss_changed)
        self._prev_boss_btn = QPushButton("◀")
        self._prev_boss_btn.clicked.connect(lambda: self._select_adjacent_boss(-1))
        self._next_boss_btn = QPushButton("▶")
        self._next_boss_btn.clicked.connect(lambda: self._select_adjacent_boss(+1))
        self._defeated_btn = QPushButton("✓")
        self._defeated_btn.setToolTip("Boss defeated: mark it ✓ and move to the next boss")
        self._defeated_btn.clicked.connect(lambda: self._defeat_current_boss(detected=False))
        for button in (self._prev_boss_btn, self._next_boss_btn, self._defeated_btn):
            button.setObjectName("IconButton")
        manage_button = QPushButton("Manage…")
        manage_button.setObjectName("GhostButton")
        manage_button.setToolTip("Games & bosses: add, rename, boss lists, defeated…")
        manage_button.clicked.connect(self._open_boss_window)

        boss_row = QWidget()
        boss_layout = QHBoxLayout(boss_row)
        boss_layout.setContentsMargins(0, 0, 0, 0)
        boss_layout.setSpacing(6)
        boss_layout.addWidget(self._boss_combo, 1)
        for button in (self._prev_boss_btn, self._next_boss_btn, self._defeated_btn):
            boss_layout.addWidget(button)
        selectors = QHBoxLayout()
        selectors.setSpacing(14)
        selectors.addWidget(field("Game", self._game_combo), 2)
        selectors.addWidget(field("Boss", boss_row), 3)
        selectors.addWidget(manage_button, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(selectors)

        hero, hero_layout = card("HeroCard", margins=18)
        hero_layout.setSpacing(2)
        self._counter_label = QLabel("0")
        self._counter_label.setObjectName("CounterLabel")
        self._counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glow(self._counter_label)
        self._counter_caption = QLabel(_COUNTER_CAPTIONS["session"])
        self._counter_caption.setObjectName("CounterCaption")
        self._counter_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(self._counter_label)
        hero_layout.addWidget(self._counter_caption)
        hero_layout.addSpacing(8)
        self._tile_session = StatTile("This session")
        self._tile_boss = StatTile("This boss")
        self._tile_total = StatTile("All-time")
        self._tile_session.setToolTip(
            "Deaths since the game was started or the session was reset."
        )
        self._tile_total.setToolTip("Every death in this game, with or without a boss selected.")
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        for tile in (self._tile_session, self._tile_boss, self._tile_total):
            tiles.addWidget(tile, 1)
        hero_layout.addLayout(tiles)
        layout.addWidget(hero)

        # Labels get the current hotkeys from _update_hotkey_labels().
        self._plus_btn = QPushButton()
        self._plus_btn.setObjectName("AccentButton")
        self._plus_btn.clicked.connect(self._on_increment)
        self._minus_btn = QPushButton()
        self._minus_btn.clicked.connect(self._on_decrement)
        self._undo_btn = QPushButton()
        self._undo_btn.clicked.connect(self._on_undo)
        for button in (self._plus_btn, self._minus_btn, self._undo_btn):
            button.setProperty("big", True)
            button.setMinimumHeight(48)
            button.setStyleSheet("font-size: 15px; border-radius: 12px;")
        layout.addLayout(row(self._plus_btn, self._minus_btn, self._undo_btn, stretch=(2, 1, 1)))

        status, status_layout = card(margins=14)
        self._detect_status_label = StatusPill("Auto-detect off")
        self._detect_last_label = QLabel("")
        self._detect_last_label.setObjectName("Muted")
        self._detect_last_label.setWordWrap(True)
        self._pause_btn = QPushButton("❚❚ Pause")
        self._pause_btn.clicked.connect(self._toggle_detection_pause)
        capture_button = QPushButton("📷 Capture Screen…")
        capture_button.setToolTip(
            "A death wasn't counted, or teach a boss victory banner: pick the screen "
            "from the last few seconds (or a screenshot)."
        )
        capture_button.clicked.connect(self._open_death_screen_dialog)
        status_layout.setSpacing(8)
        status_top = QHBoxLayout()
        status_top.setSpacing(10)
        status_top.addWidget(section_title("Auto-detect"))
        status_top.addWidget(self._detect_status_label, 1)
        status_top.addWidget(self._pause_btn)
        status_top.addWidget(capture_button)
        status_layout.addLayout(status_top)
        status_layout.addWidget(self._detect_last_label)
        layout.addWidget(status)

        set_count_btn = QPushButton("Set Exact Count…")
        set_count_btn.setObjectName("GhostButton")
        set_count_btn.clicked.connect(self._on_set_count)
        reset_session_btn = QPushButton("Reset Session")
        reset_session_btn.setObjectName("DangerButton")
        reset_session_btn.clicked.connect(self._on_reset_session)
        reset_total_btn = QPushButton("Reset Total")
        reset_total_btn.setObjectName("DangerButton")
        reset_total_btn.clicked.connect(self._on_reset_total)
        footer = QHBoxLayout()
        footer.addWidget(set_count_btn)
        footer.addStretch()
        footer.addWidget(reset_session_btn)
        footer.addWidget(reset_total_btn)
        layout.addLayout(footer)
        layout.addStretch()
        return page

    # Timer ------------------------------------------------------------
    def _build_timer_page(self) -> QWidget:
        page, layout = self._page_layout()
        layout.addWidget(
            page_header(
                "Speedrun Timer",
                "Splits, personal best and game time. The hotkeys work while you play.",
            )
        )
        hero, hero_layout = card("HeroCard", margins=22)
        self._timer_page_time = QLabel("0:00.00")
        self._timer_page_time.setObjectName("TimerValue")
        self._timer_page_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._timer_page_info = QLabel("")
        self._timer_page_info.setObjectName("Muted")
        self._timer_page_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._timer_page_split = QLabel("")
        self._timer_page_split.setObjectName("CounterCaption")
        self._timer_page_split.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(self._timer_page_split)
        hero_layout.addWidget(self._timer_page_time)
        hero_layout.addWidget(self._timer_page_info)
        layout.addWidget(hero)

        split_button = QPushButton("▶  Start / Split")
        split_button.setObjectName("AccentButton")
        buttons = [split_button]
        for text in ("❚❚  Pause", "↶  Undo", "⤼  Skip"):
            buttons.append(QPushButton(text))
        reset_button = QPushButton("⟲  Reset")
        reset_button.setObjectName("DangerButton")
        buttons.append(reset_button)
        for button, action in zip(
            buttons, ("split", "pause", "undo", "skip", "reset"), strict=True
        ):
            button.setMinimumHeight(44)
            button.clicked.connect(lambda _=False, a=action: self._timer_action(a))
        layout.addLayout(row(*buttons, stretch=(2, 1, 1, 1, 1)))

        self._timer_tiles = {
            "pb": StatTile("Personal best"),
            "sob": StatTile("Sum of best"),
            "attempts": StatTile("Attempts"),
            "deaths": StatTile("Deaths this run"),
        }
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        for tile in self._timer_tiles.values():
            tiles.addWidget(tile, 1)
        layout.addLayout(tiles)

        window_button = QPushButton("Show / Hide Timer Window")
        window_button.setToolTip("The timer window is what you capture in OBS.")
        window_button.clicked.connect(self._toggle_timer_window)
        splits_button = QPushButton("Edit Splits…")
        splits_button.clicked.connect(self._open_splits_dialog)
        history_button = QPushButton("Run History && Records…")
        history_button.clicked.connect(self._open_run_history)
        layout.addLayout(row(window_button, splits_button, history_button))
        hint = QLabel(
            "Timing method, comparison, precision and auto-pause are in "
            "Settings → Speedrun. Splits can come from your boss list."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        return page

    # Stats ------------------------------------------------------------
    def _build_stats_page(self) -> QWidget:
        page, layout = self._page_layout()
        layout.addWidget(page_header("Stats", "How it's going in the selected game."))
        self._stat_tiles = {
            "total": StatTile("All-time deaths"),
            "today": StatTile("Deaths today"),
            "sessions": StatTile("Sessions"),
            "bosses": StatTile("Bosses defeated"),
            "worst": StatTile("Most deaths on"),
            "everything": StatTile("All games"),
        }
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, tile in enumerate(self._stat_tiles.values()):
            grid.addWidget(tile, index // 3, index % 3)
        layout.addLayout(grid)

        layout.addWidget(section_title("Recent deaths"))
        self._recent_list = QListWidget()
        self._recent_list.setMinimumHeight(180)
        layout.addWidget(self._recent_list, 1)

        buttons = []
        for text, handler in (
            ("Graphs…", self._show_statistics),
            ("Death Log…", self._open_death_log),
            ("Run History && Records…", self._open_run_history),
            ("Export CSV…", self._export_csv),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            buttons.append(button)
        layout.addLayout(row(*buttons))
        return page

    # Detection --------------------------------------------------------
    def _build_detection_page(self) -> QWidget:
        page, layout = self._page_layout()
        layout.addWidget(
            page_header(
                "Detection",
                "Deaths, boss kills and loads are read from the screen or a log file: "
                "nothing is injected, so it's safe with anti-cheat.",
            )
        )
        status, status_layout = card(margins=18)
        pill = StatusPill()
        self._detect_status_label_mirror = pill
        status_layout.addWidget(section_title("Status"))
        status_layout.addWidget(pill)
        self._detect_page_info = QLabel("")
        self._detect_page_info.setObjectName("Muted")
        # Short fixed lines: word-wrapped rich text inside a scroll area gets
        # squeezed by Qt's height-for-width layout, cutting the card off.
        self._detect_page_info.setTextFormat(Qt.TextFormat.RichText)
        status_layout.addWidget(self._detect_page_info)
        layout.addWidget(status)

        setup_button = QPushButton("Set Up Detection…")
        setup_button.setObjectName("AccentButton")
        setup_button.clicked.connect(self._open_auto_detect_window)
        capture_button = QPushButton("📷 Capture Screen…")
        capture_button.clicked.connect(self._open_death_screen_dialog)
        self._pause_btn_detect = QPushButton("❚❚ Pause")
        self._pause_btn_detect.clicked.connect(self._toggle_detection_pause)
        layout.addLayout(row(setup_button, capture_button, self._pause_btn_detect))

        tips, tips_layout = card(margins=18)
        tips_layout.addWidget(section_title("How it learns"))
        tip = QLabel(
            "• <b>Death screen</b>: press the calibrate key (F8) on it, or pick it "
            "afterwards with 📷 Capture Screen.<br>"
            "• <b>Boss victory</b>: after a boss, 📷 Capture Screen → \"A boss victory "
            "screen\". Kills then mark the boss defeated and can split the timer.<br>"
            "• <b>No death screen?</b> Use the health bar or the game's log file in "
            "Set Up Detection.<br>"
            "• <b>Speedruns</b>: mark pause and loading screens there too, so game time "
            "leaves them out."
        )
        tip.setWordWrap(True)
        tip.setTextFormat(Qt.TextFormat.RichText)
        tips_layout.addWidget(tip)
        layout.addWidget(tips)
        layout.addStretch()
        return page

    # Page switching and refresh --------------------------------------
    def _show_page(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._nav_buttons[index].setChecked(True)

    def _on_page_changed(self, index: int) -> None:
        if index == _PAGE_TIMER:
            self._refresh_timer_page()
        else:
            self._page_timer.stop()
        if index == _PAGE_STATS:
            self._refresh_stats_page()
        elif index == _PAGE_DETECTION:
            self._refresh_detection_page()

    def _refresh_timer_page(self) -> None:
        """Mirror the timer onto its page (ticks only while the page shows a running run)."""
        if self._pages.currentIndex() != _PAGE_TIMER:
            self._page_timer.stop()
            return
        controller = self._speedrun
        if controller is None or controller.game_id is None:
            self._timer_page_time.setText("0:00.00")
            self._timer_page_split.setText("SELECT A GAME")
            self._timer_page_info.setText("")
            self._page_timer.stop()
            return
        view = controller.view(max_rows=len(controller.timer.split_names))
        color = _TIMER_STATUS_COLORS.get(view.time_status, "")
        self._timer_page_time.setStyleSheet(f"color: {color};" if color else "")
        self._timer_page_time.setText(view.time)
        current = next((r.name for r in view.rows if r.current), "")
        if view.state == IDLE:
            first = controller.timer.split_names[0]
            self._timer_page_split.setText(f"READY  ·  FIRST SPLIT: {first.upper()}")
        elif view.state == FINISHED:
            self._timer_page_split.setText("FINISHED")
        else:
            self._timer_page_split.setText(f"NOW: {current.upper()}" if current else "")
        info = [part for part in (view.paused_reason, view.other_time) if part]
        if view.previous_segment:
            info.append(f"Previous segment {view.previous_segment}")
        info.append(f"vs {view.comparison}")
        self._timer_page_info.setText("   ·   ".join(info))
        self._timer_tiles["pb"].set_value(view.pb)
        self._timer_tiles["sob"].set_value(view.sum_of_best)
        self._timer_tiles["attempts"].set_value(str(view.attempts))
        self._timer_tiles["deaths"].set_value(str(view.deaths))
        # Fast while the clock moves, slow otherwise (to catch hotkeys and auto-pause).
        interval = 50 if view.state == RUNNING else 500
        if not self._page_timer.isActive() or self._page_timer.interval() != interval:
            self._page_timer.start(interval)

    def _refresh_stats_page(self) -> None:
        game_id = self._counter_manager.current_game_id
        db = self._database
        tiles = self._stat_tiles
        tiles["everything"].set_value(str(db.get_total_deaths()))
        self._recent_list.clear()
        if game_id is None:
            for key in ("total", "today", "sessions", "bosses", "worst"):
                tiles[key].set_value("–")
            return
        tiles["total"].set_value(str(db.get_total_deaths(game_id)))
        today = datetime.now().date().isoformat()  # local, like the per-day query
        per_day = {row["day"]: row["deaths"] for row in db.get_deaths_per_day(game_id)}
        tiles["today"].set_value(str(per_day.get(today, 0)))
        tiles["sessions"].set_value(str(db.get_total_sessions(game_id)))
        bosses = db.get_bosses(game_id)
        beaten = sum(1 for boss in bosses if boss["defeated"])
        tiles["bosses"].set_value(f"{beaten} / {len(bosses)}" if bosses else "–")
        totals = [row for row in db.get_boss_death_totals(game_id) if row["total"] > 0]
        if totals:
            worst = max(totals, key=lambda row: row["total"])
            tiles["worst"].set_value(f"{worst['total']}", tooltip=worst["name"])
            tiles["worst"].caption.setText(f"MOST DEATHS: {worst['name'].upper()[:22]}")
        else:
            tiles["worst"].set_value("–")
            tiles["worst"].caption.setText("MOST DEATHS ON")
        for event in db.get_recent_events(game_id, limit=40):
            if event["delta"] <= 0:
                continue
            when = datetime.fromisoformat(event["timestamp"]).astimezone()
            where = event["boss_name"] or "No boss"
            text = f"✝  {when:%a %H:%M}   ·   {where}"
            if event["note"]:
                text += f"   ·   {event['note']}"
            self._recent_list.addItem(text)
            if self._recent_list.count() >= 15:
                break
        if self._recent_list.count() == 0:
            self._recent_list.addItem("No deaths yet. Go get 'em.")

    def _refresh_detection_page(self) -> None:
        game_id = self._counter_manager.current_game_id
        if game_id is None:
            self._detect_page_info.setText("Select or add a game first.")
            return
        row_ = self._database.get_game_detection(game_id)
        mode = row_["mode"] if row_ is not None else DETECTION_MODE_OFF
        exe = Path(row_["exe_path"]).name if row_ is not None and row_["exe_path"] else "not set"
        counts = {
            kind: len(self._database.get_death_templates(game_id, kind))
            for kind in (SCREEN_DEATH, SCREEN_VICTORY, SCREEN_PAUSE)
        }
        self._detect_page_info.setText(
            f"<b>Method:</b> {_MODE_NAMES.get(mode, mode)} &nbsp; · &nbsp; "
            f"<b>Game:</b> {exe}<br>"
            f"<b>Saved screens:</b> {counts[SCREEN_DEATH]} death · "
            f"{counts[SCREEN_VICTORY]} boss victory · {counts[SCREEN_PAUSE]} pause/loading"
        )

    @staticmethod
    def _labeled(label_text: str, widget: QWidget) -> QWidget:
        """Wrap a widget with a small label above it."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(label_text)
        label.setStyleSheet("color: #999999; font-size: 11px; font-weight: 600;")
        layout.addWidget(label)
        layout.addWidget(widget)
        return container

    # ----------------------------------------------------------------
    # System tray
    # ----------------------------------------------------------------
    def _build_tray(self) -> None:
        self._tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("System tray unavailable on this platform")
            return

        self._tray = QSystemTrayIcon(self._app_icon, self)
        self._tray.setToolTip(APP_NAME)

        menu = QMenu()
        show_action = menu.addAction("Show / Hide Window")
        show_action.triggered.connect(self._toggle_main_window)
        menu.addSeparator()
        plus_action = menu.addAction("+1 Death")
        plus_action.triggered.connect(self._on_increment)
        minus_action = menu.addAction("-1 Death")
        minus_action.triggered.connect(self._on_decrement)
        undo_action = menu.addAction("Undo")
        undo_action.triggered.connect(self._on_undo)
        overlay_action = menu.addAction("Toggle Overlay")
        overlay_action.triggered.connect(self._toggle_overlay)
        self._add_display_menu(menu)
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit_app)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_main_window()

    def _toggle_main_window(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    # ----------------------------------------------------------------
    # Hotkeys / settings
    # ----------------------------------------------------------------
    def _hotkey_bindings(self) -> dict[str, str]:
        """Keyboard combos from settings, as HotkeyManager keyword args ("" = unbound)."""
        settings = self._database.get_all_settings()
        return {
            f"{action}_key": settings.get(setting_key, default)
            for action, _label, setting_key, default in CONTROL_ACTIONS
        }

    def _pad_bindings(self) -> dict[str, str]:
        """Controller combos from settings, keyed by action ("" = unbound)."""
        settings = self._database.get_all_settings()
        return {
            action: settings.get(pad_setting(action), "")
            for action, _label, _setting, _default in CONTROL_ACTIONS
        }

    def _update_hotkey_labels(self, bindings: dict[str, str], pads: dict[str, str]) -> None:
        """Keyboard key on each button; keyboard + controller bindings in its tooltip."""

        def key(action: str) -> str:
            return QKeySequence(bindings[f"{action}_key"]).toString(
                QKeySequence.SequenceFormat.NativeText
            )

        def tooltip(action: str, what: str) -> str:
            lines = [what]
            if key(action):
                lines.append(f"Keyboard: {key(action)}")
            if pads.get(action):
                lines.append(f"Controller: {combo_label(pads[action])}")
            return "\n".join(lines)

        for button, action, text in (
            (self._plus_btn, "increment", "+1 Death"),
            (self._minus_btn, "decrement", "-1 Death"),
            (self._undo_btn, "undo", "Undo"),
        ):
            button.setText(f"{text}  ({key(action)})" if key(action) else text)
            button.setToolTip(tooltip(action, text))
        self._pause_btn.setToolTip(
            tooltip("pause_detection", "Pause/resume auto-detection (cutscenes, co-op…)")
        )
        self._prev_boss_btn.setToolTip(tooltip("prev_boss", "Previous boss"))
        self._next_boss_btn.setToolTip(tooltip("next_boss", "Next boss not yet defeated"))

    def _setup_hotkeys(self) -> None:
        self._action_handlers = {
            "increment": self._on_increment,
            "decrement": self._on_decrement,
            "undo": self._on_undo,
            "toggle_overlay": self._toggle_overlay,
            "calibrate": self._on_calibrate_hotkey,
            "pause_detection": self._toggle_detection_pause,
            "prev_boss": lambda: self._select_adjacent_boss(-1),
            "next_boss": lambda: self._select_adjacent_boss(+1),
            "boss_defeated": lambda: self._defeat_current_boss(detected=False),
            "timer_split": lambda: self._timer_action("split"),
            "timer_pause": lambda: self._timer_action("pause"),
            "timer_reset": lambda: self._timer_action("reset"),
            "timer_undo": lambda: self._timer_action("undo"),
            "timer_skip": lambda: self._timer_action("skip"),
        }
        bindings = self._hotkey_bindings()
        self._hotkey_manager = HotkeyManager(**bindings, parent=self)
        self._hotkey_manager.action_triggered.connect(
            lambda action: self._action_handlers[action]()
        )
        self._hotkey_manager.registration_failed.connect(self._on_hotkeys_failed)
        self._hotkey_manager.start()

        pads = self._pad_bindings()
        self._gamepad_manager = GamepadManager(pads, parent=self)
        self._gamepad_manager.action_triggered.connect(
            lambda action: self._action_handlers[action]()
        )
        self._gamepad_manager.start()
        self._update_hotkey_labels(bindings, pads)

    def _on_hotkeys_failed(self, failures: list) -> None:
        labels = {action: label for action, label, _key, _default in CONTROL_ACTIONS}
        keys = ", ".join(
            f"{key.upper()} ({labels.get(action, action)})" for action, key in failures
        )
        message = (
            f"Hotkey unavailable: {keys}. Another program is already using it, or the key "
            "isn't supported. Pick a different key in Settings → Preferences."
        )
        if self._tray is not None:
            self._tray.showMessage(
                APP_NAME, message, QSystemTrayIcon.MessageIcon.Warning, 10000
            )
        else:
            QMessageBox.warning(self, "Hotkey Unavailable", message)

    # ----------------------------------------------------------------
    # Auto death detection
    # ----------------------------------------------------------------
    def _setup_death_watcher(self) -> None:
        self._death_watcher.status_changed.connect(self._detect_status_label.setText)
        self._death_watcher.death_detected.connect(self._on_death_detected)
        self._death_watcher.activity_changed.connect(self._on_game_activity)
        self._death_watcher.boss_defeated.connect(self._on_boss_victory_detected)
        self._log_watcher.status_changed.connect(self._detect_status_label.setText)
        self._log_watcher.death_detected.connect(self._on_death_detected)
        self._death_watcher.start()
        # Switch to a configured game automatically when its exe starts.
        self._running_game_ids: set[int] = set()
        self._game_launch_timer = QTimer(self)
        self._game_launch_timer.setInterval(_GAME_LAUNCH_POLL_MS)
        self._game_launch_timer.timeout.connect(self._check_game_launches)
        if detection_available():
            self._game_launch_timer.start()

    def _configure_detection(self) -> None:
        """Point the screen and log watchers at the current game's detection config."""
        game_id = self._counter_manager.current_game_id
        row = self._database.get_game_detection(game_id) if game_id is not None else None
        mode = row["mode"] if row is not None else DETECTION_MODE_OFF
        screen_config: WatchConfig | None = None
        log_config: LogWatchConfig | None = None
        status: str | None = None  # shown when neither watcher reports its own
        if game_id is None or mode == DETECTION_MODE_OFF:
            status = "Auto-detect off"
        elif self._detection_paused:
            status = "Auto-detect paused"
        elif mode == DETECTION_MODE_LOG:
            log_config, status = self._log_watch_config(game_id)
        elif not detection_available():
            status = "Auto-detect needs Windows"
        elif not row["exe_path"]:
            status = "Auto-detect off"
        else:
            screen_config = self._screen_watch_config(game_id, mode, row["exe_path"])
        if self._timer_needs_watching(game_id, row):
            # A run is going: also watch for loads, pauses and crashes, even
            # if death detection itself is off or uses the log file.
            if screen_config is None:
                screen_config = WatchConfig(
                    game_id=game_id,
                    exe_path=row["exe_path"],
                    matcher=None,
                    setup_hint="watching loads and pauses for the timer",
                )
            pause_screens = [
                (t["region"], t["template"])
                for t in self._database.get_death_templates(game_id, SCREEN_PAUSE)
            ]
            screen_config = dataclasses.replace(
                screen_config,
                watch_activity=True,
                pause_matcher=build_screen_matcher(pause_screens),
            )
        victory = self._victory_matcher(game_id, row)
        if victory is not None:
            if screen_config is None:
                screen_config = WatchConfig(
                    game_id=game_id,
                    exe_path=row["exe_path"],
                    matcher=None,
                    setup_hint="watching for the boss victory screen",
                )
            screen_config = dataclasses.replace(screen_config, victory_matcher=victory)
        cooldown = float(self._database.get_setting(SETTING_DETECTION_COOLDOWN, "8") or 8)
        self._death_watcher.configure(screen_config, cooldown_seconds=cooldown)
        self._log_watcher.configure(log_config)
        if status is not None:
            self._detect_status_label.setText(status)
        if self._pages.currentIndex() == _PAGE_DETECTION:
            self._refresh_detection_page()

    def _victory_matcher(self, game_id: int | None, row):
        """The saved victory screens to watch for, while an undefeated boss is selected."""
        boss_id = self._counter_manager.current_boss_id
        if (
            game_id is None
            or boss_id is None
            or row is None
            or not row["exe_path"]
            or self._detection_paused
            or not detection_available()
            or self._database.get_setting(SETTING_BOSS_DETECTION, "true") != "true"
        ):
            return None
        boss = self._database.get_boss(boss_id)
        if boss is None or boss["defeated"]:
            return None
        screens = self._database.get_death_templates(game_id, SCREEN_VICTORY)
        return build_screen_matcher([(t["region"], t["template"]) for t in screens])

    def _on_boss_victory_detected(self, game_id: int) -> None:
        if game_id == self._counter_manager.current_game_id:
            self._defeat_current_boss(detected=True)

    def _defeat_current_boss(self, detected: bool) -> None:
        """
        Mark the selected boss defeated (saving its deaths until victory), then
        optionally split a running speedrun and select the next boss.
        """
        game_id = self._counter_manager.current_game_id
        boss_id = self._counter_manager.current_boss_id
        if game_id is None or boss_id is None:
            if not detected:
                self._notify("Select the boss you're fighting first.")
            return
        boss = self._database.get_boss(boss_id)
        if boss is None or boss["defeated"]:
            return
        self._database.set_boss_defeated(boss_id, True)
        deaths = self._database.get_boss_deaths(boss_id)
        settings = self._database.get_all_settings()

        split = (
            settings.get(SETTING_BOSS_AUTO_SPLIT, "true") == "true"
            and self._speedrun is not None
            and self._speedrun.game_id == game_id
            and self._speedrun.timer.state == RUNNING
        )
        if split:
            self._timer_action("split")

        self._reload_bosses(game_id)  # show the ✓, still on this boss
        if settings.get(SETTING_BOSS_AUTO_ADVANCE, "true") == "true":
            self._select_adjacent_boss(+1)

        plural = "" if deaths == 1 else "s"
        message = f"⚔ {boss['name']} defeated after {deaths} death{plural}!"
        if split:
            message += " Split recorded."
        self._detect_last_label.setText(
            message + (" Wrong? Unmark it in Manage → Games & Bosses." if detected else "")
        )
        self._notify(message, 6000)
        self._configure_detection()  # watch for the next boss's victory instead

    def _screen_watch_config(self, game_id: int, mode: str, exe_path: str) -> WatchConfig:
        templates = [
            (t["region"], t["template"]) for t in self._database.get_death_templates(game_id)
        ]
        # A None matcher still watches the window, buffering recent frames so
        # the player can pick their first death screen with 📷 Capture Screen.
        matcher = build_matcher(mode, templates, self._database.get_detection_options(game_id))
        if mode != DETECTION_MODE_HEALTH:
            return WatchConfig(game_id=game_id, exe_path=exe_path, matcher=matcher)
        hotkey = self._database.get_setting(SETTING_HOTKEY_CALIBRATE, "f8").upper()
        return WatchConfig(
            game_id=game_id,
            exe_path=exe_path,
            matcher=matcher,
            required_frames=HealthBarMatcher.REQUIRED_FRAMES,
            setup_hint=f"at full health, press {hotkey} to mark your health bar",
        )

    def _log_watch_config(self, game_id: int) -> tuple[LogWatchConfig | None, str | None]:
        """The log watcher's config, or ``(None, status)`` explaining what's missing."""
        options = self._database.get_detection_options(game_id)
        log_path = str(options.get("log_path") or "")
        if not log_path:
            return None, "Log detection: choose the game's log file in Auto-Detect…"
        try:
            pattern = compile_death_pattern(str(options.get("log_pattern") or ""))
        except ValueError:
            return None, "Log detection: set the death text in Auto-Detect…"
        return LogWatchConfig(game_id=game_id, log_path=log_path, pattern=pattern), None

    def _toggle_detection_pause(self) -> None:
        self._detection_paused = not self._detection_paused
        for button in (self._pause_btn, self._pause_btn_detect):
            button.setText("▶ Resume" if self._detection_paused else "❚❚ Pause")
        self._configure_detection()
        if self._tray is not None:  # the hotkey is usually pressed in-game
            self._tray.showMessage(
                APP_BRAND,
                "Auto-detect paused" if self._detection_paused else "Auto-detect resumed",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def _check_game_launches(self) -> None:
        """
        Follow configured games starting and stopping (polled every few seconds).

        A game launching gets selected (unless the current game is running)
        and starts a fresh session; the current game exiting ends its session,
        so "Session" deaths always mean this play session.
        """
        configs = {
            row["exe_path"]: row["game_id"] for row in self._database.get_all_game_detections()
        }
        running = {configs[path] for path in running_exe_paths(list(configs))}
        newly_started = running - self._running_game_ids
        stopped = self._running_game_ids - running
        self._running_game_ids = running
        current = self._counter_manager.current_game_id

        if current in stopped:
            self._session_manager.end_current_session()
            self._refresh_counters()
        if not newly_started:
            return
        if current not in running:
            index = self._game_combo.findData(min(newly_started))
            if index >= 0:
                self._game_combo.setCurrentIndex(index)
                if self._tray is not None:
                    self._tray.showMessage(
                        APP_BRAND,
                        f"{self._game_combo.itemText(index)} started: now counting its deaths.",
                        QSystemTrayIcon.MessageIcon.Information,
                        4000,
                    )
            current = self._counter_manager.current_game_id
        if current in newly_started:
            self._start_play_session(current)

    def _start_play_session(self, game_id: int) -> None:
        """Begin a new session for a game launch, reusing a still-empty one."""
        sessions = self._session_manager
        if sessions.current_game_id == game_id and sessions.get_session_deaths() == 0:
            return  # e.g. the app was just opened on this game: no empty duplicate
        sessions.start_new_session(game_id)
        self._refresh_counters()

    def _save_death_template(self, game_id: int, template: DeathTemplate) -> None:
        """Store a new death screen and turn detection on for the game if needed."""
        self._database.add_death_template(game_id, template.region_json(), template.patch_bytes())
        row = self._database.get_game_detection(game_id)
        exe_path = row["exe_path"] if row is not None else None
        if row is None or row["mode"] == DETECTION_MODE_OFF:
            self._database.set_game_detection(game_id, exe_path, DETECTION_MODE_TEMPLATE)
        self._configure_detection()
        if not exe_path:
            QMessageBox.information(
                self, "Select the Game", "Death screen saved. Now pick the game's .exe."
            )
            self._open_auto_detect_window()

    def _on_death_detected(self, game_id: int) -> None:
        if game_id != self._counter_manager.current_game_id:
            return  # game switched while the frame was being processed
        self._on_increment()
        undo_key = self._database.get_setting(SETTING_HOTKEY_UNDO, "f11").upper()
        self._detect_last_label.setText(
            f"Death auto-counted at {datetime.now():%H:%M:%S} ({undo_key} to undo)"
        )

    def _on_calibrate_hotkey(self) -> None:
        game_id = self._counter_manager.current_game_id
        if game_id is None or not detection_available():
            return
        row = self._database.get_game_detection(game_id)
        exe_path = row["exe_path"] if row is not None else None
        frame = capture_game_frame(exe_path)
        if frame is None:
            return
        self.show()
        self.raise_()
        self.activateWindow()
        if row is not None and row["mode"] == DETECTION_MODE_HEALTH:
            bar_dialog = HealthBarDialog(frame, parent=self)
            accepted = bar_dialog.exec() == HealthBarDialog.DialogCode.Accepted
            if accepted and bar_dialog.health_bar is not None:
                self._database.update_detection_options(
                    game_id, **bar_dialog.health_bar.to_options()
                )
                self._configure_detection()
            return
        dialog = CalibrationDialog(frame, parent=self)
        if dialog.exec() != CalibrationDialog.DialogCode.Accepted or dialog.template is None:
            return
        self._save_death_template(game_id, dialog.template)

    def _open_death_screen_dialog(self) -> None:
        game_id = self._counter_manager.current_game_id
        if game_id is None:
            QMessageBox.information(self, "Select a Game", "Select or add a game first.")
            return
        dialog = DeathScreenDialog(self._death_watcher.recent_frames(), parent=self)
        if dialog.exec() != DeathScreenDialog.DialogCode.Accepted or dialog.template is None:
            return
        if dialog.kind == SCREEN_VICTORY:
            template = dialog.template
            self._database.add_death_template(
                game_id, template.region_json(), template.patch_bytes(), SCREEN_VICTORY
            )
            if dialog.count_death:
                self._defeat_current_boss(detected=False)
            self._configure_detection()
            return
        self._save_death_template(game_id, dialog.template)
        if dialog.count_death:
            self._on_increment()

    def _add_game_from_exe(self) -> None:
        """Create (or reuse) a game from its .exe and set up detection in one go."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the Game's .exe", "", "Programs (*.exe)"
        )
        if not path:
            return
        path = str(Path(path))
        name, ok = QInputDialog.getText(
            self, "Add Game", "Game name:", text=exe_display_name(path)
        )
        if not ok or not name.strip():
            return
        existing = {g["name"].casefold(): g["id"] for g in self._database.get_games()}
        game_id = existing.get(name.strip().casefold())
        if game_id is None:
            game_id = self._database.create_game(name.strip())
        has_templates = bool(self._database.get_death_templates(game_id))
        preset = Path(path).name.lower() in SOULS_PRESET_EXES and not has_templates
        self._database.set_game_detection(
            game_id, path, DETECTION_MODE_SOULS if preset else DETECTION_MODE_TEMPLATE
        )
        self._reload_games(select_game_id=game_id)
        if not preset and not has_templates:
            hotkey = self._database.get_setting(SETTING_HOTKEY_CALIBRATE, "f8").upper()
            QMessageBox.information(self, "Teach It Your Death Screen", first_death_hint(hotkey))

    def _apply_saved_settings(self) -> None:
        settings = self._database.get_all_settings()
        theme = settings.get(SETTING_THEME, "dark")
        image = load_background(settings.get(SETTING_UI_BG_IMAGE, ""))
        dim = QColor(THEME_BASE_COLORS.get(theme, THEME_BASE_COLORS["dark"]))
        try:
            dim.setAlphaF(min(max(int(settings.get(SETTING_UI_BG_DIM, "60")), 0), 90) / 100)
        except ValueError:
            dim.setAlphaF(0.6)
        self._background.set_background(image, dim)
        apply_theme(
            self,
            theme,
            text_color=settings.get(SETTING_UI_TEXT_COLOR, ""),
            counter_color=settings.get(SETTING_UI_COUNTER_COLOR, ""),
            font_family=settings.get(SETTING_UI_FONT, ""),
            see_through=image is not None,
        )
        self._overlay.apply_display_settings(settings)
        self._timer_window.apply_display_settings(settings)
        self._timer_window.restore_geometry_string(settings.get(SETTING_TIMER_GEOMETRY, ""))
        self._timer_window.setVisible(settings.get(SETTING_TIMER_VISIBLE, "false") == "true")
        self._overlay.set_always_on_top(
            settings.get(SETTING_OVERLAY_ALWAYS_ON_TOP, "true") == "true"
        )
        self._overlay.restore_geometry_string(settings.get(SETTING_OVERLAY_GEOMETRY, ""))

    def _maybe_check_updates(self) -> None:
        if self._database.get_setting(SETTING_CHECK_UPDATES, "true") != "true":
            return
        self._update_checker = UpdateChecker(self)
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.check_async()

    def _on_update_available(self, latest: str, url: str) -> None:
        if self._tray is not None:
            self._tray.showMessage(
                APP_BRAND,
                f"Version {latest} is available! Get it at:\n{url}",
                QSystemTrayIcon.MessageIcon.Information,
                8000,
            )
        else:
            QMessageBox.information(
                self, "Update Available", f"Version {latest} is available:\n{url}"
            )

    # ----------------------------------------------------------------
    # Profiles
    # ----------------------------------------------------------------
    def _switch_profile(self, name: str) -> None:
        if name == self._profile_manager.active_profile:
            return
        # Persist current state, tear down, and rebuild on the new database.
        self._end_speedrun()
        self._database.set_setting(SETTING_OVERLAY_GEOMETRY, self._overlay.geometry_string())
        self._session_manager.end_current_session()
        self._database.close()

        self._profile_manager.set_active(name)
        self._database = Database(self._profile_manager.active_db_path())
        self._session_manager = SessionManager(self._database)
        self._counter_manager = CounterManager(self._database, self._session_manager)
        self._statistics_service = StatisticsService(self._database)

        self._update_window_title()
        self._rebuild_profile_menu()
        self._apply_saved_settings()
        self._on_settings_changed_hotkeys()
        self._reload_games()
        logger.info("Switched to profile '%s'", name)

    def _create_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if not ok or not name.strip():
            return
        try:
            self._profile_manager.create_profile(name.strip())
        except ValueError as exc:
            QMessageBox.warning(self, "Could not create profile", str(exc))
            return
        self._rebuild_profile_menu()
        switch = QMessageBox.question(
            self, "Switch Profile", f"Switch to '{name.strip()}' now?"
        )
        if switch == QMessageBox.StandardButton.Yes:
            self._switch_profile(name.strip())

    def _delete_profile(self) -> None:
        candidates = [
            n for n in self._profile_manager.list_profiles() if n != DEFAULT_PROFILE_NAME
        ]
        if not candidates:
            QMessageBox.information(
                self, "No Profiles", "There are no deletable profiles (Default is protected)."
            )
            return
        name, ok = QInputDialog.getItem(
            self, "Delete Profile", "Profile to delete:", candidates, 0, False
        )
        if not ok:
            return
        confirm = QMessageBox.warning(
            self,
            "Delete Profile",
            f"Delete profile '{name}' and its entire database? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        switching_away = name == self._profile_manager.active_profile
        if switching_away:
            self._switch_profile(DEFAULT_PROFILE_NAME)
        try:
            self._profile_manager.delete_profile(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not delete profile", str(exc))
        self._rebuild_profile_menu()

    # ----------------------------------------------------------------
    # Data loading
    # ----------------------------------------------------------------
    def _reload_games(self, select_game_id: int | None = None) -> None:
        self._game_combo.blockSignals(True)
        self._game_combo.clear()
        games = self._database.get_games()
        for game in games:
            self._game_combo.addItem(game["name"], userData=game["id"])
        if games:
            self._game_combo.insertSeparator(self._game_combo.count())
        self._game_combo.addItem(_ADD_GAME_LABEL, userData=_ADD_GAME_SENTINEL)
        self._game_combo.blockSignals(False)
        if games:
            if select_game_id is None:  # reopen on the game used last time
                select_game_id = self._saved_id(SETTING_LAST_GAME_ID)
            # findData(None) would match the separator, so only look up real ids.
            index = self._game_combo.findData(select_game_id) if select_game_id else -1
            index = max(index, 0)
            self._game_combo.blockSignals(True)
            self._game_combo.setCurrentIndex(index)
            self._game_combo.blockSignals(False)
            self._on_game_changed(index)
        else:
            self._game_combo.blockSignals(True)
            self._game_combo.setCurrentIndex(-1)  # shows the placeholder text
            self._game_combo.blockSignals(False)
            self._counter_manager.set_current_game(None, None)
            self._reload_bosses(None)
            self._refresh_counters()
            self._configure_detection()
            self._load_speedrun()  # drops a run of a game that was just deleted

    def _saved_id(self, setting_key: str) -> int | None:
        """Read an id stored in the settings table (empty/invalid -> None)."""
        value = self._database.get_setting(setting_key, "")
        return int(value) if value.isdigit() else None

    def _reload_bosses(self, game_id: int | None) -> None:
        self._boss_combo.blockSignals(True)
        self._boss_combo.clear()
        self._boss_combo.addItem("(No Boss)", userData=None)
        if game_id is not None:
            for boss in self._database.get_bosses(game_id):
                prefix = "✓ " if boss["defeated"] else ""
                self._boss_combo.addItem(f"{prefix}{boss['name']}", userData=boss["id"])
        # Re-select the last boss if it belongs to this game.
        last_boss = self._saved_id(SETTING_LAST_BOSS_ID)
        index = max(self._boss_combo.findData(last_boss), 0) if last_boss else 0
        self._boss_combo.setCurrentIndex(index)
        self._boss_combo.blockSignals(False)
        self._on_boss_changed(index)

    def _select_adjacent_boss(self, step: int) -> None:
        """Select the next (+1) or previous (-1) boss, skipping defeated ones."""
        combo = self._boss_combo
        index = combo.currentIndex() + step
        while 0 <= index < combo.count():
            boss_id = combo.itemData(index)
            boss = self._database.get_boss(boss_id) if boss_id is not None else None
            if boss is None or not boss["defeated"]:
                combo.setCurrentIndex(index)  # the overlay shows the new boss
                return
            index += step

    # ----------------------------------------------------------------
    # Selector event handlers
    # ----------------------------------------------------------------
    def _on_game_changed(self, index: int) -> None:
        if self._game_combo.itemData(index) == _ADD_GAME_SENTINEL:
            # Snap back to the previous game, then run the add flow (which
            # selects the new game itself if one is added).
            previous = self._game_combo.findData(self._counter_manager.current_game_id)
            self._game_combo.blockSignals(True)
            self._game_combo.setCurrentIndex(previous)
            self._game_combo.blockSignals(False)
            self._add_game_from_exe()
            return
        game_id = self._game_combo.itemData(index)
        game_name = self._game_combo.itemText(index) if index >= 0 else None
        self._counter_manager.set_current_game(game_id, game_name)
        self._reload_bosses(game_id)
        self._refresh_counters()
        self._detect_last_label.setText("")
        self._configure_detection()
        self._load_speedrun()

    def _on_boss_changed(self, index: int) -> None:
        boss_id = self._boss_combo.itemData(index)
        if index > 0 and boss_id is not None:
            boss = self._database.get_boss(boss_id)
            boss_name = boss["name"] if boss is not None else None
        else:
            boss_id, boss_name = None, None
            self._database.set_setting(SETTING_LAST_BOSS_ID, "")  # "(No Boss)" is a choice too
        self._counter_manager.set_current_boss(boss_id, boss_name)
        self._refresh_counters()
        self._configure_detection()  # victory watching follows the selected boss

    # ----------------------------------------------------------------
    # Counter actions
    # ----------------------------------------------------------------
    def _on_increment(self) -> None:
        self._apply_counted(self._counter_manager.increment)

    def _on_decrement(self) -> None:
        self._apply_counted(self._counter_manager.decrement)

    def _on_undo(self) -> None:
        self._apply_counted(self._counter_manager.undo)

    def _apply_counted(self, action: Callable[[], CounterSnapshot]) -> None:
        """Run a +1/-1/undo and pass the change on to a speedrun in progress."""
        before = self._counter_manager.get_snapshot().session_deaths
        snapshot = action()
        if self._speedrun is not None:
            self._speedrun.add_deaths(
                self._counter_manager.current_game_id, snapshot.session_deaths - before
            )
            if self._speedrun.running:
                self._autosave()
            self._timer_window.refresh()
        self._apply_snapshot(snapshot)

    def _on_reset_session(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Reset Session",
            "Start the session count over at 0?\n\n"
            "The all-time total and boss counts keep these deaths.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._apply_snapshot(self._counter_manager.reset_session())

    def _on_reset_total(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Reset Total",
            "Set this game's all-time total to 0?\n\n"
            "The session count and boss counts stay as they are.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._apply_snapshot(self._counter_manager.reset_total())

    def _on_set_count(self) -> None:
        if self._counter_manager.current_game_id is None:
            QMessageBox.information(self, "Select a Game", "Select a game first.")
            return
        snapshot = self._counter_manager.get_snapshot()
        choices = ["This session", "All-time total"]
        which, ok = QInputDialog.getItem(
            self, "Set Exact Count", "Which count?", choices, 0, False
        )
        if not ok:
            return
        is_session = which == choices[0]
        target, ok = QInputDialog.getInt(
            self,
            "Set Exact Count",
            f"New {which.lower()} death count:",
            value=snapshot.session_deaths if is_session else snapshot.total_deaths,
            minValue=0,
            maxValue=999_999,
        )
        if not ok:
            return
        if is_session:
            self._apply_snapshot(self._counter_manager.set_session_count(target))
        else:
            self._apply_snapshot(self._counter_manager.set_total_count(target))

    def _refresh_counters(self) -> None:
        self._apply_snapshot(self._counter_manager.get_snapshot())

    def _apply_snapshot(self, snapshot: CounterSnapshot) -> None:
        source = self._database.get_setting(SETTING_OVERLAY_COUNTER_SOURCE, "session")
        big_numbers = {
            "session": snapshot.session_deaths,
            "boss": snapshot.boss_deaths,
            "total": snapshot.total_deaths,
        }
        self._counter_label.setText(str(big_numbers.get(source, snapshot.session_deaths)))
        self._counter_caption.setText(_COUNTER_CAPTIONS.get(source, _COUNTER_CAPTIONS["session"]))
        self._tile_session.set_value(str(snapshot.session_deaths))
        boss = str(snapshot.boss_deaths) if snapshot.boss_name else "–"
        self._tile_boss.set_value(
            boss, tooltip=f"Deaths while {snapshot.boss_name} was selected (all sessions)."
            if snapshot.boss_name
            else "Select a boss to count deaths against it."
        )
        self._tile_total.set_value(str(snapshot.total_deaths))
        if self._pages.currentIndex() == _PAGE_STATS:
            self._refresh_stats_page()
        self._overlay.update_counters(snapshot)
        self._write_deaths_txt(snapshot)

    def _deaths_txt_path(self) -> Path:
        raw_path = self._database.get_setting(SETTING_DEATHS_TXT_PATH, "").strip()
        return Path(raw_path) if raw_path else SAVES_DIR / "deaths.txt"

    def _write_deaths_txt(self, snapshot: CounterSnapshot) -> None:
        if self._database.get_setting(SETTING_DEATHS_TXT_ENABLED, "false") != "true":
            return
        path = self._deaths_txt_path()
        template = self._database.get_setting(
            SETTING_DEATHS_TXT_TEMPLATE, "{game} - {boss}: {deaths}"
        )
        source = self._database.get_setting(SETTING_OVERLAY_COUNTER_SOURCE, "session")
        write_deaths_file(path, render_template(template, snapshot, source))

    # ----------------------------------------------------------------
    # File menu actions
    # ----------------------------------------------------------------
    def _export_backup(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Backup", "death_counter_backup.json", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            data = self._database.export_data()
            with open(path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
            QMessageBox.information(self, "Export Complete", f"Backup saved to:\n{path}")
        except OSError as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))

    def _import_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Backup", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as file:
                data = json.load(file)
            self._database.import_data(data, mode="merge")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Import Failed", str(exc))
            return
        self._reload_games()
        QMessageBox.information(self, "Import Complete", "Backup imported successfully.")

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV Summary", "death_counter_summary.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            row_count = write_csv_summary(self._database, Path(path))
            QMessageBox.information(
                self, "Export Complete", f"CSV summary saved ({row_count} rows):\n{path}"
            )
        except OSError as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))

    def _clear_all_data(self) -> None:
        confirm = QMessageBox.warning(
            self,
            "Clear All Data",
            "This will permanently delete every game, boss, session, and death event\n"
            "in the CURRENT profile.\n\n"
            "This cannot be undone. Consider exporting a backup first.\n\n"
            "Are you absolutely sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._database.clear_all_data()
        self._reload_games()

    # ----------------------------------------------------------------
    # Window / dialog actions
    # ----------------------------------------------------------------
    def _open_boss_window(self) -> None:
        dialog = BossWindow(self._database, parent=self)
        dialog.exec()
        self._reload_games()

    def _open_auto_detect_window(self) -> None:
        game_id = self._counter_manager.current_game_id
        if game_id is None:
            QMessageBox.information(self, "Select a Game", "Select a game first.")
            return
        dialog = AutoDetectWindow(
            self._database,
            game_id,
            self._game_combo.currentText(),
            recent_frames=self._death_watcher.recent_frames,
            parent=self,
        )
        dialog.exec()
        self._configure_detection()

    def _open_death_log(self) -> None:
        game_id = self._counter_manager.current_game_id
        if game_id is None:
            QMessageBox.information(self, "Select a Game", "Select a game first.")
            return
        dialog = DeathLogWindow(
            self._database, game_id, self._game_combo.currentText(), parent=self
        )
        dialog.exec()

    def _open_settings_window(self) -> None:
        dialog = SettingsWindow(
            self._database,
            gamepad=self._gamepad_manager,
            hotkeys=self._hotkey_manager,
            parent=self,
        )
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.exec()

    def _open_about_window(self) -> None:
        AboutWindow(parent=self).exec()

    def _open_obs_guide(self) -> None:
        key = self._hotkey_bindings()["toggle_overlay_key"]
        shown = QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
        ObsGuideWindow(
            overlay_hotkey=shown,
            deaths_txt_path=self._deaths_txt_path(),
            show_overlay_green=self._show_overlay_for_obs,
            enable_deaths_txt=self._enable_deaths_txt,
            parent=self,
        ).exec()

    def _show_overlay_for_obs(self) -> None:
        """Green-screen background (for OBS's Chroma Key) and make the overlay visible."""
        self._database.set_setting(SETTING_OVERLAY_BG_MODE, "chroma")
        self._apply_saved_settings()
        self._overlay.keep_on_screen()
        self._overlay.show()
        self._overlay.raise_()

    def _enable_deaths_txt(self) -> None:
        """Turn on deaths.txt output and write it immediately so OBS can find it."""
        self._database.set_setting(SETTING_DEATHS_TXT_ENABLED, "true")
        self._refresh_counters()

    def _on_settings_changed(self) -> None:
        self._apply_saved_settings()
        if self._speedrun is not None:
            self._apply_timer_options(self._speedrun)
            self._timer_window.set_controller(self._speedrun)
        self._configure_detection()
        self._on_settings_changed_hotkeys()
        self._refresh_counters()

    def _on_settings_changed_hotkeys(self) -> None:
        bindings = self._hotkey_bindings()
        pads = self._pad_bindings()
        self._hotkey_manager.update_bindings(**bindings)
        self._gamepad_manager.update_bindings(pads)
        self._update_hotkey_labels(bindings, pads)

    def _toggle_overlay(self) -> None:
        self._overlay.toggle_visibility()

    def _show_statistics(self) -> None:
        dialog = StatisticsWindow(
            self._database,
            self._statistics_service,
            self._counter_manager.current_game_id,
            self._game_combo.currentText(),
            parent=self,
        )
        dialog.exec()

    # ----------------------------------------------------------------
    # Speedrun timer
    # ----------------------------------------------------------------
    def _load_speedrun(self, force: bool = False) -> None:
        """
        Point the timer at the current game's splits and attempts.

        A run already going for this game is kept (re-selecting the game
        mustn't reset it), and so is one for another game, so switching
        games mid-run doesn't lose it. ``force`` reloads anyway (new splits).
        """
        game_id = self._counter_manager.current_game_id
        current = self._speedrun
        if current is not None and not force:
            orphaned = (
                current.game_id is not None
                and self._database.get_game(current.game_id) is None
            )
            if not orphaned and (current.game_id == game_id or current.running):
                return
        self._end_speedrun()
        names = self._database.get_speedrun_splits(game_id) if game_id else []
        controller = SpeedrunController(
            game_id=game_id,
            game_name=self._game_combo.currentText() if game_id else "",
            split_names=names,
            runs=[],
            attempts=self._database.count_speedrun_attempts(game_id) if game_id else 0,
            store=self._store_speedrun_run,
        )
        if game_id is not None:
            # Same split names as the controller resolved ("Finish" if none).
            controller.set_runs(
                self._database.get_speedrun_runs(game_id, controller.timer.split_names)
            )
        self._apply_timer_options(controller)
        self._speedrun = controller
        self._timer_window.set_controller(controller)

    def _apply_timer_options(self, controller: SpeedrunController) -> None:
        settings = self._database.get_all_settings()
        try:
            digits = int(settings.get(SETTING_TIMER_DIGITS, "2"))
        except ValueError:
            digits = 2
        controller.set_options(
            settings.get(SETTING_TIMER_METHOD, "real"),
            settings.get(SETTING_TIMER_COMPARISON, "pb"),
            digits,
        )

    def _end_speedrun(self) -> None:
        """Save the attempt in progress (if any), e.g. before closing or switching."""
        if self._speedrun is not None:
            self._speedrun.reset()
            self._speedrun = None
            self._timer_window.set_controller(None)
        self._clear_autosave()

    def _clear_autosave(self) -> None:
        """Drop this session's crash snapshot (the run was stored properly)."""
        if self._autosave_written:
            self._database.set_setting(SETTING_TIMER_AUTOSAVE, "")
            self._autosave_written = False

    def _store_speedrun_run(self, game_id: int, run) -> None:
        """Save an attempt, unless its game was deleted meanwhile."""
        if self._database.get_game(game_id) is None:
            logger.info("Not saving a run of deleted game id=%s", game_id)
            return
        self._database.add_speedrun_run(game_id, run)

    def _timer_needs_watching(self, game_id: int | None, row) -> bool:
        """Whether a run in progress needs the game window watched for auto-pause."""
        controller = self._speedrun
        if (
            controller is None
            or not controller.running
            or controller.game_id != game_id
            or row is None
            or not row["exe_path"]
            or not detection_available()
        ):
            return False
        settings = self._database.get_all_settings()
        keys = [key for _reason, key in _GAME_TIME_PAUSES.values()]
        keys.append(SETTING_TIMER_PAUSE_ON_CLOSE)
        return any(settings.get(key, "false") == "true" for key in keys)

    def _on_game_activity(self, game_id: int, activity: str) -> None:
        """Auto-pause the speedrun timer from what the game is doing."""
        controller = self._speedrun
        if controller is None or controller.game_id != game_id or not controller.running:
            return
        settings = self._database.get_all_settings()
        if activity == ACTIVITY_CLOSED:
            controller.set_game_paused("")
            if (
                settings.get(SETTING_TIMER_PAUSE_ON_CLOSE, "true") == "true"
                and controller.timer.state == RUNNING
            ):
                controller.timer.toggle_pause()
                self._notify(
                    "The game closed or crashed, so the timer is paused. "
                    "Resume it with the pause key when you're back in."
                )
        else:
            reason, key = _GAME_TIME_PAUSES.get(activity, ("", ""))
            enabled = bool(key) and settings.get(key, "false") == "true"
            controller.set_game_paused(reason if enabled else "")
        self._autosave()
        self._timer_window.refresh()

    def _notify(self, message: str, msecs: int = 5000) -> None:
        if self._tray is not None:
            self._tray.showMessage(
                APP_BRAND, message, QSystemTrayIcon.MessageIcon.Information, msecs
            )

    # Auto-save / crash recovery ------------------------------------------
    def _autosave(self) -> None:
        """Save a snapshot of the run in progress (cleared once it's stored)."""
        controller = self._speedrun
        if controller is not None and controller.timer.state != IDLE:
            data = {
                "game_id": controller.game_id,
                "game_name": controller.game_name,
                "saved_at": time.time(),
                **controller.timer.snapshot(),
            }
            self._database.set_setting(SETTING_TIMER_AUTOSAVE, json.dumps(data))
            self._autosave_written = True
        else:
            self._clear_autosave()

    def _offer_run_recovery(self) -> None:
        """After a crash, offer the run that was in progress back."""
        raw = self._database.get_setting(SETTING_TIMER_AUTOSAVE, "")
        if not raw:
            return
        try:
            data = json.loads(raw)
            game_id = int(data["game_id"])
            timer = SpeedrunTimer.restore(data)
        except (ValueError, KeyError, TypeError):
            logger.warning("Discarding an unreadable auto-saved run")
            self._database.set_setting(SETTING_TIMER_AUTOSAVE, "")
            return
        game = self._database.get_game(game_id)
        if game is None:
            self._database.set_setting(SETTING_TIMER_AUTOSAVE, "")
            return
        done = sum(1 for t in timer.split_times if t is not None)
        pause_key = self._hotkey_bindings().get("timer_pause_key", "").upper() or "Pause"
        box = QMessageBox(self)
        box.setWindowTitle("Recover Run")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            f"A {game['name']} run was still going when {APP_SHORT_NAME} last closed "
            "unexpectedly.\n\n"
            f"Time {format_time(timer.elapsed_ms())}   •   "
            f"Split {done + 1 if timer.state != FINISHED else done}/{len(timer.split_names)}   •   "
            f"Deaths {timer.deaths}\n\n"
            f"Resume brings it back paused at that time; press {pause_key} to go on."
        )
        resume = box.addButton("Resume Run", QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton("Save as Attempt", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is resume:
            self._resume_recovered_run(game_id, timer)
            return
        if clicked is keep:
            record = timer.reset()
            if record is not None:
                self._database.add_speedrun_run(game_id, record)
        self._database.set_setting(SETTING_TIMER_AUTOSAVE, "")
        if self._speedrun is not None and self._speedrun.game_id == game_id:
            self._load_speedrun(force=True)  # new attempt count / history

    def _resume_recovered_run(self, game_id: int, timer: SpeedrunTimer) -> None:
        index = self._game_combo.findData(game_id)
        if index >= 0 and self._game_combo.currentIndex() != index:
            self._game_combo.setCurrentIndex(index)  # loads that game's timer
        if self._speedrun is None or self._speedrun.game_id != game_id:
            self._load_speedrun(force=True)
        controller = self._speedrun
        if controller is None:
            return
        controller.set_runs(self._database.get_speedrun_runs(game_id, timer.split_names))
        controller.restore_timer(timer)
        if not self._timer_window.isVisible():
            self._toggle_timer_window()
        self._timer_window.refresh()
        self._configure_detection()

    def _timer_action(self, action: str) -> None:
        controller = self._speedrun
        if controller is None or controller.game_id is None:
            return
        timer = controller.timer
        handlers = {
            "split": controller.split,
            "pause": timer.toggle_pause,
            "reset": controller.reset,
            "undo": timer.undo_split,
            "skip": timer.skip_split,
        }
        was_running = controller.running
        handlers[action]()
        if action == "split" and controller.is_new_pb():
            total = format_time(controller.timer.elapsed_ms(controller.method), 2)
            self._notify(f"🏆 New personal best! {total}", 8000)
        if action == "reset" and controller.game_id != self._counter_manager.current_game_id:
            self._load_speedrun()  # the finished-with game's run is saved; follow the UI
        if action == "split" and not self._timer_window.isVisible():
            self._toggle_timer_window()  # starting a run shows the timer
        if controller.running != was_running:
            self._configure_detection()  # start/stop watching for loads and crashes
        self._autosave()
        self._timer_window.refresh()
        self._refresh_timer_page()

    def _on_timer_window_action(self, action: str) -> None:
        if action == "edit_splits":
            self._open_splits_dialog()
        elif action == "hide":
            self._toggle_timer_window()
        elif action == "history":
            self._open_run_history()
        else:
            self._timer_action(action)

    def _toggle_timer_window(self) -> None:
        self._timer_window.toggle_visibility()
        self._database.set_setting(
            SETTING_TIMER_VISIBLE, "true" if self._timer_window.isVisible() else "false"
        )

    def _open_run_history(self) -> None:
        if self._speedrun is None or self._speedrun.game_id is None:
            QMessageBox.information(self, "Select a Game", "Select a game first.")
            return
        RunHistoryDialog(self._database, self._speedrun, parent=self).exec()
        self._timer_window.set_controller(self._speedrun)  # history may have changed

    def _open_splits_dialog(self) -> None:
        game_id = self._counter_manager.current_game_id
        if game_id is None:
            QMessageBox.information(self, "Select a Game", "Select a game first.")
            return
        if self._speedrun is not None and self._speedrun.running:
            QMessageBox.information(
                self, "Run in Progress", "Reset the timer before editing the splits."
            )
            return
        dialog = SplitsDialog(
            self._database, game_id, self._game_combo.currentText(), parent=self
        )
        if dialog.exec() == SplitsDialog.DialogCode.Accepted or dialog.history_cleared:
            self._load_speedrun(force=True)

    # ----------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------
    def _quit_app(self) -> None:
        self._quitting = True
        self.close()

    # ----------------------------------------------------------------
    # Multiple displays
    # ----------------------------------------------------------------
    def _add_display_menu(self, parent_menu: QMenu) -> None:
        """'Move Overlay to Display ▸' submenu, rebuilt each time it opens."""
        menu = parent_menu.addMenu("Move Overlay to Display")
        menu.aboutToShow.connect(lambda m=menu: self._fill_display_menu(m))

    def _fill_display_menu(self, menu: QMenu) -> None:
        menu.clear()
        primary = QGuiApplication.primaryScreen()
        rects = [s.availableGeometry() for s in QGuiApplication.screens()]
        current = screen_index_at(self._overlay.geometry(), rects)
        for index, screen in enumerate(QGuiApplication.screens()):
            size = screen.geometry().size()
            action = menu.addAction(
                display_name(index, (size.width(), size.height()), screen is primary)
            )
            action.setCheckable(True)
            action.setChecked(index == current and self._overlay.isVisible())
            action.triggered.connect(lambda _=False, s=screen: self._move_overlay_to(s))

    def _move_overlay_to(self, screen: QScreen) -> None:
        self._overlay.move_to_screen(screen)
        self._database.set_setting(SETTING_OVERLAY_GEOMETRY, self._overlay.geometry_string())

    def _restore_main_geometry(self) -> None:
        saved = self._database.get_setting(SETTING_MAIN_WINDOW_GEOMETRY, "")
        if saved:
            self.restoreGeometry(QByteArray.fromBase64(saved.encode("ascii")))
        self._keep_windows_on_screen()

    def _keep_windows_on_screen(self) -> None:
        """After a display is unplugged, pull our windows back onto one that exists."""
        rects = available_screen_rects()
        fitted = fit_to_screens(self.frameGeometry(), rects)
        if fitted.topLeft() != self.frameGeometry().topLeft():
            self.move(fitted.topLeft())
        self._overlay.keep_on_screen()
        self._timer_window.keep_on_screen()

    def _on_screen_removed(self, _screen: QScreen) -> None:
        # Let Qt finish re-laying out the remaining displays first.
        QTimer.singleShot(500, self._keep_windows_on_screen)

    def closeEvent(self, event) -> None:  # noqa: N802
        """Minimize to tray if configured; otherwise clean up and exit."""
        if self._closed:  # e.g. Quit from the tray while already closing
            super().closeEvent(event)
            return
        minimize = (
            self._database.get_setting(SETTING_MINIMIZE_TO_TRAY, "false") == "true"
        )
        if minimize and not self._quitting and self._tray is not None:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                APP_BRAND,
                "Still running in the tray — hotkeys stay active. Right-click to quit.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            return

        self._end_speedrun()
        self._database.set_setting(SETTING_OVERLAY_GEOMETRY, self._overlay.geometry_string())
        self._database.set_setting(
            SETTING_MAIN_WINDOW_GEOMETRY, bytes(self.saveGeometry().toBase64()).decode("ascii")
        )
        self._session_manager.end_current_session()
        self._hotkey_manager.stop()
        self._gamepad_manager.stop()
        self._autosave_timer.stop()
        self._recovery_timer.stop()
        self._game_launch_timer.stop()  # it reads the database being closed
        self._page_timer.stop()
        self._death_watcher.stop()
        self._log_watcher.stop()
        self._overlay.close()
        self._timer_window.close()
        if self._tray is not None:
            self._tray.hide()
        self._database.close()
        self._closed = True
        logger.info("Application closed cleanly")
        super().closeEvent(event)
