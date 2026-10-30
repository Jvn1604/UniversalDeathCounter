"""
Main application window.

Wires together the database (per active profile), core managers, hotkeys,
overlay, system tray, deaths.txt stream output, update checker, and theme
system into the primary user-facing UI.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDesktopServices,
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
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
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
    RunRecord,
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
    list_windows,
    request_capture_permission,
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
from src.detection.obs_client import DEFAULT_HOST as OBS_DEFAULT_HOST
from src.detection.obs_client import DEFAULT_PORT as OBS_DEFAULT_PORT
from src.detection.obs_client import ObsClient, ObsError
from src.hotkeys.gamepad import GamepadManager, combo_label
from src.hotkeys.hotkey_manager import HotkeyManager
from src.overlay.overlay_window import OverlayWindow, available_screen_rects
from src.themes.theme_manager import active_theme, apply_theme, outdated_themes, theme_info
from src.ui import dashboard, icons
from src.ui.about_window import AboutWindow
from src.ui.auto_detect_window import (
    AutoDetectWindow,
    CalibrationDialog,
    DeathScreenDialog,
    HealthBarDialog,
    first_death_hint,
)
from src.ui.boss_window import BossWindow
from src.ui.dashboard import BossRanking, ProgressRing, SkullBadge, StartBanner, WeekChart
from src.ui.death_log_window import DeathLogWindow
from src.ui.guide_dialog import (
    ACTION_ADD_EXE,
    ACTION_BOSSES,
    ACTION_CONSOLE,
    ACTION_CONTROLS,
    ACTION_DETECTION,
    ACTION_HOME,
    ACTION_OBS,
    ACTION_OVERLAY,
    ACTION_TEMPLATE,
    ACTION_TIMER,
    STEPS,
    GuideDialog,
)
from src.ui.mini_window import MiniWindow
from src.ui.obs_guide_window import ObsGuideWindow
from src.ui.session_history_window import SessionHistoryWindow
from src.ui.settings_window import SettingsWindow
from src.ui.statistics_window import StatisticsWindow
from src.ui.theme_picker import ThemeDownload
from src.ui.timer_window import RunHistoryDialog, SplitsDialog, TimerWindow
from src.ui.widgets import (
    ActionButton,
    AutoHideLabel,
    CreditCard,
    HeroCard,
    NavToggle,
    StatTile,
    StatusPill,
    UpdateCard,
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
    CREATOR_CHANNEL_URL,
    CREATOR_NAME,
    DEFAULT_COUNTER_SOURCE,
    DETECTION_MODE_HEALTH,
    DETECTION_MODE_LOG,
    DETECTION_MODE_OFF,
    DETECTION_MODE_SOULS,
    DETECTION_MODE_TEMPLATE,
    ICONS_DIR,
    OPTION_OBS_SOURCE,
    OPTION_WINDOW_TITLE,
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
    SETTING_MINI_GEOMETRY,
    SETTING_MINIMIZE_TO_TRAY,
    SETTING_OBS_HOST,
    SETTING_OBS_PASSWORD,
    SETTING_OBS_PORT,
    SETTING_OVERLAY_ALWAYS_ON_TOP,
    SETTING_OVERLAY_BG_IMAGE,
    SETTING_OVERLAY_BG_MODE,
    SETTING_OVERLAY_COUNTER_SOURCE,
    SETTING_OVERLAY_EVER_SHOWN,
    SETTING_OVERLAY_FONT_SIZE,
    SETTING_OVERLAY_GEOMETRY,
    SETTING_OVERLAY_LOCKED,
    SETTING_OVERLAY_SHOW_SKULL,
    SETTING_PHONE_REMOTE,
    SETTING_PHONE_REMOTE_KEY,
    SETTING_QUICK_START_HIDDEN,
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
    SETTING_WELCOME_SHOWN,
    pad_setting,
)
from src.utils.exporters import write_csv_summary
from src.utils.game_templates import add_template_bosses, get_template
from src.utils.logger import get_logger
from src.utils.phone_remote import ACTIONS as PHONE_ACTIONS
from src.utils.phone_remote import PhoneRemote, new_key
from src.utils.platform_info import program_file_filter
from src.utils.profiles import DEFAULT_PROFILE_NAME, ProfileManager
from src.utils.screens import display_name, fit_to_screens, screen_index_at
from src.utils.stream_writer import render_template, write_deaths_file
from src.utils.update_checker import UpdateChecker
from src.utils.updater import (
    INSTALLER_NAME,
    UpdateError,
    download_installer,
    is_installed_copy,
    launch_installer,
)

logger = get_logger(__name__)

# Last entry of the Game dropdown, which opens the add-game-from-.exe flow.
_ADD_GAME_SENTINEL = "__add_game_from_exe__"
_ADD_GAME_LABEL = "+ Add game from .exe…"
_GAME_LAUNCH_POLL_MS = 3000
_AUTOSAVE_MS = 10_000  # a run in progress is saved this often (crash recovery)
_UPDATE_RECHECK_MS = 6 * 60 * 60 * 1000  # while open, look for a new version this often
# What makes the speedrun timer's game time stop: (reason shown, setting).
_GAME_TIME_PAUSES = {
    ACTIVITY_LOADING: ("Loading", SETTING_TIMER_PAUSE_LOADING),
    ACTIVITY_PAUSE_SCREEN: ("Game paused", SETTING_TIMER_PAUSE_SCREENS),
    ACTIVITY_NOT_RESPONDING: ("Game not responding", SETTING_TIMER_PAUSE_NOT_RESPONDING),
    ACTIVITY_BACKGROUND: ("Game in background", SETTING_TIMER_PAUSE_BACKGROUND),
}
# Timer keys besides Start/Split are only registered while a run is going:
# a registered hotkey is swallowed system-wide, and these default to number-
# pad digits, which would otherwise stop typing in every other app.
_RUN_ONLY_ACTIONS = ("timer_pause", "timer_reset", "timer_undo", "timer_skip")
# Timer page buttons: (label, icon).
_TIMER_BUTTONS = {
    "split": ("Start / Split", "flag"),
    "pause": ("Pause", "pause"),
    "undo": ("Undo", "undo-2"),
    "skip": ("Skip", "skip-forward"),
    "reset": ("Reset", "rotate-ccw"),
}


class _UpdateDownload(QObject):
    """Downloads the update installer on a worker thread and reports back by signal."""

    progress = Signal(int, int)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, size: int, destination: Path) -> None:
        super().__init__()
        self._url, self._size, self._destination = url, size, destination
        self.cancelled = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="UpdateDownload", daemon=True).start()

    def _run(self) -> None:
        try:
            path = download_installer(
                self._url, self._destination, self._size, self.progress.emit, self.cancelled
            )
        except UpdateError as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(str(path))


# Sidebar pages, in stack order: (name, icon).
_PAGE_HOME, _PAGE_TIMER, _PAGE_STATS, _PAGE_DETECTION, _PAGE_CONSOLE = range(5)
_PAGES = (
    ("Home", "house"),
    ("Timer", "timer"),
    ("Stats", "chart-column"),
    ("Detection", "scan-eye"),
    ("Console", "gamepad-2"),
)
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
    "run": "DEATHS THIS RUN",
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
        self._overlay.menu_requested.connect(self._overlay_context_menu)
        self._overlay.settings_requested.connect(self._open_overlay_settings)
        self._mini = MiniWindow()
        self._phone_remote = PhoneRemote(self)
        self._phone_remote.action_requested.connect(self._on_phone_action)
        self._phone_remote.phone_seen.connect(self._on_phone_seen)
        self._mini.action_requested.connect(self._on_mini_action)
        self._timer_window = TimerWindow()
        self._timer_window.action_requested.connect(self._on_timer_window_action)
        self._speedrun: SpeedrunController | None = None
        self._death_watcher = DeathWatcher(parent=self)
        self._log_watcher = LogWatcher(parent=self)
        self._detection_paused = False  # not persisted: every launch starts active
        self._quitting = False
        self._closed = False  # cleanup ran; a second close must not touch the database
        self._run_keys_active = False  # see _RUN_ONLY_ACTIONS
        self._update_page_url = ""
        self._update_version = ""
        # True once this session has written a crash-recovery snapshot. Until
        # then a snapshot in the settings belongs to a crashed earlier run,
        # waiting for the recovery prompt, and must not be cleared.
        self._autosave_written = False
        self._menu_icons: list[tuple[QAction, str]] = []  # re-tinted with the theme
        self._guide: GuideDialog | None = None
        # Home's charts and the guide's checklist: refreshed once after a burst of changes.
        self._home_refresh = QTimer(self)
        self._home_refresh.setSingleShot(True)
        self._home_refresh.setInterval(150)
        self._home_refresh.timeout.connect(self._refresh_home)
        self._overlay.visibility_changed.connect(self._on_overlay_visibility)

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
        self._refresh_downloaded_themes()
        if self._database.get_setting(SETTING_PHONE_REMOTE, "false") == "true":
            self._set_phone_remote(True)

    def _update_window_title(self) -> None:
        profile = self._profile_manager.active_profile
        suffix = "" if profile == DEFAULT_PROFILE_NAME else f"  [{profile}]"
        self.setWindowTitle(f"{APP_NAME}{suffix}")

    # ----------------------------------------------------------------
    # Menu
    # ----------------------------------------------------------------
    def _build_menu(self) -> None:
        """
        The top bar's menus: profiles, and the "more" menu (backups, about, quit).

        Everything else has one home: pages in the sidebar, the overlay and
        tools under Tools, the timer window and splits on the Timer page.
        """
        self._profile_menu = QMenu(self)
        self._rebuild_profile_menu()
        menu = self._more_menu = QMenu(self)
        self._menu_action(menu, "save", "Export Backup…", self._export_backup)
        self._menu_action(menu, "upload", "Import Backup…", self._import_backup)
        menu.addSeparator()
        self._menu_action(menu, "info", "About", self._open_about_window)
        menu.addSeparator()
        self._menu_action(menu, "trash-2", "Clear All Data…", self._clear_all_data)
        self._menu_action(menu, "power", "Quit", self._quit_app)

    def _menu_action(
        self, menu: QMenu, icon_name: str, text: str, handler: Callable[[], object]
    ) -> QAction:
        """A menu entry with a themed icon."""
        action = menu.addAction(icons.icon(icon_name, icons.color(icons.NORMAL), size=16), text)
        action.triggered.connect(lambda _=False: handler())
        self._menu_icons.append((action, icon_name))
        return action

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
            action = self._profile_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == active)
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
            self._build_console_page,
        ):
            page = builder()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        layout.setContentsMargins(18, 10, 14, 10)
        layout.setSpacing(8)
        logo_label = QLabel()
        logo = QPixmap(str(ICONS_DIR / "app_icon_128.png"))
        if not logo.isNull():
            logo.setDevicePixelRatio(logo.width() / 40)
            logo_label.setPixmap(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title_label = QLabel(APP_BRAND)
        title_label.setObjectName("TitleLabel")
        subtitle_label = QLabel(APP_SUBTITLE.upper())
        subtitle_label.setObjectName("Subtitle")
        titles.addWidget(title_label)
        titles.addWidget(subtitle_label)
        layout.addWidget(logo_label)
        layout.addSpacing(4)
        layout.addLayout(titles)
        layout.addSpacing(14)
        self._page_badge = QLabel()
        self._page_badge.setObjectName("PageBadge")
        layout.addWidget(self._page_badge)
        layout.addStretch(1)

        self._profile_combo = QComboBox()
        self._profile_combo.setToolTip("Profile: each one keeps its own games and counts.")
        self._profile_combo.setMinimumWidth(150)
        self._profile_combo.activated.connect(
            lambda index: self._switch_profile(self._profile_combo.itemText(index))
        )
        profile_button = self._top_button("users", "Profiles: switch, add or delete")
        profile_button.setMenu(self._profile_menu)
        help_button = self._top_button("circle-help", "Guide: how everything works")
        help_button.clicked.connect(lambda: self.maybe_show_welcome(force=True))
        more_button = self._top_button("ellipsis-vertical", "Backups, About, Quit")
        more_button.setMenu(self._more_menu)
        layout.addWidget(self._profile_combo)
        layout.addWidget(profile_button)
        layout.addSpacing(4)
        layout.addWidget(help_button)
        layout.addWidget(more_button)
        return bar

    @staticmethod
    def _top_button(icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("TopIconButton")
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(button, icon_name, size=19)
        return button

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(214)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 8, 0, 12)
        layout.setSpacing(1)
        menu_title = QLabel("MENU")
        menu_title.setObjectName("NavSection")
        layout.addWidget(menu_title)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        for index, (text, icon_name) in enumerate(_PAGES):
            button = nav_button(text, icon_name)
            button.clicked.connect(lambda _=False, i=index: self._show_page(i))
            self._nav_group.addButton(button, index)
            self._nav_buttons.append(button)
            layout.addWidget(button)

        tools_title = QLabel("TOOLS")
        tools_title.setObjectName("NavSection")
        layout.addWidget(tools_title)
        self._overlay_nav = NavToggle("Overlay", "layers")
        self._overlay_nav.setToolTip(
            "Show or hide the overlay for OBS. Right-click the overlay for its options."
        )
        self._overlay_nav.clicked.connect(self._toggle_overlay)
        self._overlay.visibility_changed.connect(self._overlay_nav.set_on)
        layout.addWidget(self._overlay_nav)
        for text, icon_name, handler, tip in (
            ("Mini Mode", "picture-in-picture-2", self._toggle_mini_mode,
             "A tiny always-on-top counter instead of this window"),
            ("OBS Setup", "radio", self._open_obs_guide, "Put the counter on your stream"),
            ("Settings", "settings", self._open_settings_window,
             "Look, themes, overlay, timer and controls"),
        ):
            button = nav_button(text, icon_name, checkable=False)
            button.setToolTip(tip)
            button.clicked.connect(handler)
            layout.addWidget(button)
        layout.addStretch()

        self._update_card = UpdateCard(APP_VERSION)
        self._update_btn = self._update_card.button
        self._update_btn.clicked.connect(self._start_update)
        self._update_card.check_requested.connect(self._check_updates)
        update_row = QHBoxLayout()
        update_row.setContentsMargins(12, 0, 12, 8)
        update_row.addWidget(self._update_card)
        layout.addLayout(update_row)

        credit = self._credit = CreditCard(
            QPixmap(str(ICONS_DIR / "channel_logo.png")), CREATOR_NAME, CREATOR_CHANNEL_URL
        )
        credit_row = QHBoxLayout()
        credit_row.setContentsMargins(12, 0, 12, 0)
        credit_row.addWidget(credit)
        credit_row.setContentsMargins(12, 0, 12, 4)
        layout.addLayout(credit_row)
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

        greeting = QHBoxLayout()
        greeting_titles = QVBoxLayout()
        greeting_titles.setSpacing(2)
        self._greeting = QLabel()
        self._greeting.setObjectName("PageTitle")
        self._greeting_line = QLabel()
        self._greeting_line.setObjectName("PageSubtitle")
        greeting_titles.addWidget(self._greeting)
        greeting_titles.addWidget(self._greeting_line)
        self._date_chip = QLabel()
        self._date_chip.setObjectName("DateChip")
        greeting.addLayout(greeting_titles, 1)
        greeting.addWidget(self._date_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(greeting)
        self._start_banner = StartBanner()
        self._start_banner.clicked.connect(lambda: self.maybe_show_welcome(force=True))
        self._start_banner.dismissed.connect(self._hide_start_banner)
        self._start_banner.hide()
        layout.addWidget(self._start_banner)

        self._game_combo = QComboBox()
        self._game_combo.setPlaceholderText("Add a game: pick its .exe")
        self._game_combo.currentIndexChanged.connect(self._on_game_changed)
        self._boss_combo = QComboBox()
        self._boss_combo.currentIndexChanged.connect(self._on_boss_changed)
        for combo, handler in (
            (self._game_combo, self._game_context_menu),
            (self._boss_combo, self._boss_context_menu),
        ):
            combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            combo.customContextMenuRequested.connect(handler)
            combo.setToolTip("Right-click to rename")
            # Long boss names mustn't widen the page (the list still shows them in full).
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(10)
        self._prev_boss_btn = QPushButton()
        self._prev_boss_btn.clicked.connect(lambda: self._select_adjacent_boss(-1))
        self._next_boss_btn = QPushButton()
        self._next_boss_btn.clicked.connect(lambda: self._select_adjacent_boss(+1))
        self._defeated_btn = QPushButton()
        self._defeated_btn.setToolTip("Boss defeated: mark it ✓ and move to the next boss")
        self._defeated_btn.clicked.connect(lambda: self._defeat_current_boss(detected=False))
        for button, icon_name in (
            (self._prev_boss_btn, "chevron-left"),
            (self._next_boss_btn, "chevron-right"),
            (self._defeated_btn, "trophy"),
        ):
            button.setObjectName("IconButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            icons.set_icon(button, icon_name)
        manage_button = QPushButton(" Games && Bosses")
        manage_button.setObjectName("GhostButton")
        manage_button.setToolTip("Add, rename and delete games and bosses; boss lists")
        icons.set_icon(manage_button, "library", size=17)
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

        hero = HeroCard(watermark="")
        hero_row = QHBoxLayout(hero)
        hero_row.setContentsMargins(24, 18, 22, 18)
        hero_row.setSpacing(24)
        self._skull_badge = SkullBadge()
        hero_row.addWidget(self._skull_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        hero_layout = QVBoxLayout()
        hero_layout.setSpacing(0)
        hero_row.addLayout(hero_layout, 1)
        self._counter_label = QLabel("0")
        self._counter_label.setObjectName("CounterLabel")
        self._counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # The caption doubles as the switch for what the big number counts.
        self._counter_caption = QPushButton(_COUNTER_CAPTIONS[DEFAULT_COUNTER_SOURCE])
        self._counter_caption.setObjectName("CounterCaption")
        self._counter_caption.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # icon after
        self._counter_caption.setCursor(Qt.CursorShape.PointingHandCursor)
        self._counter_caption.setToolTip(
            "Choose what the big number counts (here, on the overlay and in mini mode)."
        )
        icons.set_icon(self._counter_caption, "chevron-down", size=14)
        self._counter_caption.clicked.connect(self._show_counter_source_menu)
        hero_layout.addWidget(self._counter_label)
        hero_layout.addWidget(self._counter_caption, 0, Qt.AlignmentFlag.AlignHCenter)
        # Empty state: one obvious first step instead of a lonely 0.
        self._first_game_btn = QPushButton(" Add Your First Game")
        self._first_game_btn.setObjectName("AccentButton")
        self._first_game_btn.setMinimumHeight(44)
        icons.set_icon(self._first_game_btn, "plus", icons.ACCENT)
        self._first_game_btn.clicked.connect(lambda: self.maybe_show_welcome(force=True))
        self._first_game_btn.hide()
        hero_layout.addSpacing(10)
        hero_layout.addWidget(self._first_game_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        hero_layout.addSpacing(14)
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

        # Keys come from _update_hotkey_labels().
        self._plus_btn = ActionButton("+1 Death", "skull", icons.ACCENT)
        self._plus_btn.setObjectName("AccentButton")
        self._plus_btn.setMinimumHeight(58)
        self._plus_btn.clicked.connect(self._on_increment)
        self._minus_btn = ActionButton("−1 Death", "")
        self._minus_btn.clicked.connect(self._on_decrement)
        self._undo_btn = ActionButton("Undo", "undo-2")
        self._undo_btn.clicked.connect(self._on_undo)
        self._sessions_btn = ActionButton("Sessions", "history")
        self._sessions_btn.setToolTip("Continue a past session of this game")
        self._sessions_btn.clicked.connect(self._continue_past_session)
        for button in (self._minus_btn, self._undo_btn, self._sessions_btn):
            button.setMinimumHeight(58)
        layout.addLayout(
            row(
                self._plus_btn, self._minus_btn, self._undo_btn, self._sessions_btn,
                stretch=(2, 1, 1, 1),
            )
        )

        week, week_layout = card(margins=16)
        week_layout.setSpacing(4)
        week_top = QHBoxLayout()
        week_top.addWidget(section_title("This week"))
        week_top.addStretch()
        self._week_delta = QLabel()
        self._week_delta.setObjectName("DeltaChip")
        week_top.addWidget(self._week_delta)
        week_layout.addLayout(week_top)
        self._week_total = QLabel()
        self._week_total.setObjectName("InsightValue")
        week_layout.addWidget(self._week_total)
        self._week_chart = WeekChart()
        week_layout.addWidget(self._week_chart, 1)

        bosses, bosses_layout = card(margins=16)
        bosses_layout.addWidget(section_title("Boss progress"))
        boss_body = QHBoxLayout()
        boss_body.setSpacing(18)
        self._boss_ring = ProgressRing()
        self._toughest = BossRanking()
        boss_body.addWidget(self._boss_ring, 0, Qt.AlignmentFlag.AlignVCenter)
        boss_body.addWidget(self._toughest, 1)
        bosses_layout.addLayout(boss_body, 1)
        insights = QHBoxLayout()
        insights.setSpacing(16)
        insights.addWidget(week, 3)
        insights.addWidget(bosses, 2)
        layout.addLayout(insights)

        status, status_layout = card(margins=14)
        self._detect_status_label = StatusPill("Auto-detect off")
        self._detect_last_label = AutoHideLabel()
        self._detect_last_label.setObjectName("Muted")
        self._detect_last_label.setWordWrap(True)
        self._detect_last_label.hide()
        self._pause_btn = QPushButton(" Pause")
        icons.set_icon(self._pause_btn, "pause", size=16)
        self._pause_btn.clicked.connect(self._toggle_detection_pause)
        open_detection = QPushButton("Detection ")
        open_detection.setObjectName("GhostButton")
        open_detection.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # icon after text
        open_detection.setToolTip("Set up detection, or pick a missed death screen")
        icons.set_icon(open_detection, "chevron-right", size=16)
        open_detection.clicked.connect(lambda: self._show_page(_PAGE_DETECTION))
        status_layout.setSpacing(8)
        status_top = QHBoxLayout()
        status_top.setSpacing(10)
        status_top.addWidget(section_title("Auto-detect"))
        status_top.addWidget(self._detect_status_label, 1)
        status_top.addWidget(self._pause_btn)
        status_top.addWidget(open_detection)
        status_layout.addLayout(status_top)
        status_layout.addWidget(self._detect_last_label)
        layout.addWidget(status)

        set_count_btn = QPushButton(" Set Exact Count")
        set_count_btn.setObjectName("GhostButton")
        icons.set_icon(set_count_btn, "pencil", size=16)
        set_count_btn.clicked.connect(self._on_set_count)
        reset_session_btn = QPushButton(" Reset Session")
        reset_session_btn.setObjectName("DangerButton")
        icons.set_icon(reset_session_btn, "rotate-ccw", icons.DANGER, size=16)
        reset_session_btn.clicked.connect(self._on_reset_session)
        reset_total_btn = QPushButton(" Reset Total")
        reset_total_btn.setObjectName("DangerButton")
        icons.set_icon(reset_total_btn, "trash-2", icons.DANGER, size=16)
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

        # Keys come from _update_hotkey_labels().
        self._timer_buttons: dict[str, ActionButton] = {}
        for action, (text, icon_name) in _TIMER_BUTTONS.items():
            split = action == "split"
            role = icons.ACCENT if split else icons.DANGER if action == "reset" else icons.NORMAL
            button = ActionButton(text, icon_name, role)
            if split:
                button.setObjectName("AccentButton")
            elif action == "reset":
                button.setObjectName("DangerButton")
            button.clicked.connect(lambda _=False, a=action: self._timer_action(a))
            self._timer_buttons[action] = button
        self._timer_buttons["split"].setMinimumHeight(58)
        layout.addWidget(self._timer_buttons["split"])
        layout.addLayout(
            row(*(self._timer_buttons[a] for a in ("pause", "undo", "skip", "reset")))
        )

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

        self._timer_window_btn = NavToggle("Timer Window", "app-window", object_name="")
        self._timer_window_btn.setToolTip(
            "The timer's own window: what you capture in OBS. Right-click it for options."
        )
        self._timer_window_btn.clicked.connect(self._toggle_timer_window)
        self._timer_window.visibility_changed.connect(self._timer_window_btn.set_on)
        splits_button = QPushButton(" Edit Splits")
        icons.set_icon(splits_button, "list-ordered", size=16)
        splits_button.clicked.connect(self._open_splits_dialog)
        history_button = QPushButton(" Run History && Records")
        icons.set_icon(history_button, "history", size=16)
        history_button.clicked.connect(self._open_run_history)
        layout.addLayout(row(self._timer_window_btn, splits_button, history_button))
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
        for text, icon_name, handler in (
            (" Graphs", "chart-column", self._show_statistics),
            (" Death Log", "scroll-text", self._open_death_log),
            (" Export CSV", "file-down", self._export_csv),
        ):
            button = QPushButton(text)
            icons.set_icon(button, icon_name, size=16)
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

        setup_button = QPushButton(" Set Up Detection")
        setup_button.setObjectName("AccentButton")
        icons.set_icon(setup_button, "wand-sparkles", icons.ACCENT, size=16)
        setup_button.clicked.connect(self._open_auto_detect_window)
        capture_button = QPushButton(" Capture Screen")
        icons.set_icon(capture_button, "camera", size=16)
        capture_button.setToolTip(
            "A death wasn't counted, or teach a boss victory banner: pick the screen "
            "from the last few seconds (or a screenshot)."
        )
        capture_button.clicked.connect(self._open_death_screen_dialog)
        self._pause_btn_detect = QPushButton(" Pause")
        icons.set_icon(self._pause_btn_detect, "pause", size=16)
        self._pause_btn_detect.clicked.connect(self._toggle_detection_pause)
        for button in (setup_button, capture_button, self._pause_btn_detect):
            button.setMinimumHeight(42)
        layout.addLayout(row(setup_button, capture_button, self._pause_btn_detect))

        tips, tips_layout = card(margins=18)
        tips_layout.addWidget(section_title("How it learns"))
        tip = QLabel(
            "• <b>Death screen</b>: press the calibrate key (F8) on it, or pick it "
            "afterwards with Capture Screen.<br>"
            "• <b>Boss victory</b>: after a boss, Capture Screen → \"A boss victory "
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

    # Console ----------------------------------------------------------
    def _build_console_page(self) -> QWidget:
        page, layout = self._page_layout()
        layout.addWidget(
            page_header(
                "Console",
                "Playing on PlayStation or Xbox? Count from your phone, and let auto-detect "
                "watch your capture card or Remote Play on this PC.",
            )
        )

        phone, phone_layout = card(margins=18)
        phone_top = QHBoxLayout()
        phone_top.addWidget(section_title("1 · Phone remote"))
        phone_top.addStretch()
        self._phone_toggle = NavToggle("Phone Remote", "smartphone", object_name="")
        self._phone_toggle.setMinimumWidth(190)
        self._phone_toggle.setToolTip("Turn the phone page on or off")
        self._phone_toggle.clicked.connect(
            lambda: self._set_phone_remote(not self._phone_remote.running)
        )
        phone_top.addWidget(self._phone_toggle)
        phone_layout.addLayout(phone_top)
        phone_intro = QLabel(
            "Your controller talks to the console, so the PC's hotkeys can't hear it. "
            "Switch this on and open the link on your phone (same Wi-Fi): big +1, Undo, "
            "boss and timer buttons, no app to install."
        )
        phone_intro.setObjectName("Muted")
        phone_intro.setWordWrap(True)
        phone_layout.addWidget(phone_intro)
        self._phone_link = QLabel()
        self._phone_link.setObjectName("PhoneLink")
        self._phone_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._phone_link.setWordWrap(True)
        copy_link = QPushButton(" Copy Link")
        icons.set_icon(copy_link, "copy", size=16)
        copy_link.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self._phone_remote.url())
        )
        new_link = QPushButton(" New Link")
        new_link.setObjectName("GhostButton")
        new_link.setToolTip("Make a new link: phones with the old one stop working")
        icons.set_icon(new_link, "refresh-cw", size=16)
        new_link.clicked.connect(self._new_phone_link)
        self._phone_link_box = QWidget()
        self._phone_link_box.setObjectName("PhoneLinkBox")
        self._phone_link_box.setStyleSheet("QWidget#PhoneLinkBox { background: transparent; }")
        link_layout = QVBoxLayout(self._phone_link_box)
        link_layout.setContentsMargins(0, 4, 0, 0)
        link_layout.setSpacing(8)
        link_layout.addWidget(self._phone_link)
        link_buttons = QHBoxLayout()
        link_buttons.addWidget(copy_link)
        link_buttons.addWidget(new_link)
        link_buttons.addStretch()
        link_layout.addLayout(link_buttons)
        self._phone_status = QLabel()
        self._phone_status.setObjectName("Muted")
        self._phone_status.setWordWrap(True)
        link_layout.addWidget(self._phone_status)
        phone_layout.addWidget(self._phone_link_box)
        layout.addWidget(phone)

        capture, capture_layout = card(margins=18)
        capture_layout.addWidget(section_title("2 · Auto-detect from a window"))
        capture_intro = QLabel(
            "Show the game on this PC, then pick its window below: <b>PS Remote Play</b>, "
            "the <b>Xbox app</b>, your capture card's app (e.g. Elgato 4K Capture Utility), "
            "or in <b>OBS</b>: right-click the capture card source → Windowed Projector. "
            "Deaths, boss kills and timer pauses are then read from that window."
        )
        capture_intro.setObjectName("Muted")
        capture_intro.setWordWrap(True)
        capture_intro.setTextFormat(Qt.TextFormat.RichText)
        capture_layout.addWidget(capture_intro)
        self._console_source = QLabel()
        self._console_source.setWordWrap(True)
        self._console_source.setTextFormat(Qt.TextFormat.RichText)
        capture_layout.addWidget(self._console_source)
        self._window_combo = QComboBox()
        self._window_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._window_combo.setMinimumContentsLength(20)
        refresh_windows = QPushButton()
        refresh_windows.setObjectName("IconButton")
        refresh_windows.setToolTip("Look for windows again")
        icons.set_icon(refresh_windows, "refresh-cw", size=16)
        refresh_windows.clicked.connect(self._refresh_console_page)
        capture_layout.addLayout(row(self._window_combo, refresh_windows, stretch=(1, 0)))
        use_window = QPushButton(" Use This Window")
        use_window.setObjectName("AccentButton")
        icons.set_icon(use_window, "monitor-play", icons.ACCENT, size=16)
        use_window.clicked.connect(self._use_console_window)
        self._stop_window_btn = QPushButton(" Stop Using It")
        self._stop_window_btn.setObjectName("GhostButton")
        icons.set_icon(self._stop_window_btn, "x", size=16)
        self._stop_window_btn.clicked.connect(self._stop_console_window)
        setup = QPushButton(" Set Up Detection")
        icons.set_icon(setup, "wand-sparkles", size=16)
        setup.clicked.connect(self._open_auto_detect_window)
        capture_layout.addLayout(row(use_window, setup, self._stop_window_btn))
        keep_visible = QLabel(
            "Keep that window open and visible (another screen is ideal): detection reads "
            "what's on screen, so a minimized or covered window can't be read."
        )
        keep_visible.setObjectName("Muted")
        keep_visible.setWordWrap(True)
        capture_layout.addWidget(keep_visible)
        layout.addWidget(capture)

        obs, obs_layout = card(margins=18)
        obs_layout.addWidget(section_title("3 · Or read the capture card from OBS"))
        obs_intro = QLabel(
            "Best with a capture card: nothing to keep visible, and OBS keeps the card. "
            "In OBS: <b>Tools → WebSocket Server Settings</b> → tick <b>Enable WebSocket "
            "server</b>, then <b>Show Connect Info</b> for the port and password."
        )
        obs_intro.setObjectName("Muted")
        obs_intro.setWordWrap(True)
        obs_intro.setTextFormat(Qt.TextFormat.RichText)
        obs_layout.addWidget(obs_intro)
        host, port, password = self._obs_settings()
        self._obs_host = QLineEdit(host)
        self._obs_port = QSpinBox()
        self._obs_port.setRange(1, 65535)
        self._obs_port.setValue(port)
        self._obs_password = QLineEdit(password)
        self._obs_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._obs_password.setPlaceholderText("Leave empty if OBS has no password")
        connect_obs = QPushButton(" Connect")
        icons.set_icon(connect_obs, "radio", size=16)
        connect_obs.clicked.connect(self._connect_obs)
        obs_layout.addLayout(
            row(
                field("Address", self._obs_host),
                field("Port", self._obs_port),
                field("Password", self._obs_password),
                stretch=(2, 1, 3),
            )
        )
        self._obs_status = AutoHideLabel()
        self._obs_status.setObjectName("Muted")
        self._obs_status.hide()
        self._obs_status.setWordWrap(True)
        self._obs_source_combo = QComboBox()
        self._obs_source_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._obs_source_combo.setMinimumContentsLength(16)
        self._obs_source_combo.setPlaceholderText("Connect to list OBS's sources")
        use_source = QPushButton(" Use This Source")
        use_source.setObjectName("AccentButton")
        icons.set_icon(use_source, "monitor-play", icons.ACCENT, size=16)
        use_source.clicked.connect(self._use_obs_source)
        obs_layout.addLayout(row(connect_obs, self._obs_source_combo, use_source,
                                 stretch=(0, 1, 0)))
        obs_layout.addWidget(self._obs_status)
        layout.addWidget(obs)
        layout.addStretch()
        self._set_phone_ui()
        return page

    def _refresh_console_page(self) -> None:
        """List the windows that could be watched, and what the game uses now."""
        windows = list_windows()
        current = self._window_combo.currentData()
        self._window_combo.clear()
        for window in windows:
            self._window_combo.addItem(window.label, userData=(window.exe_path, window.title))
        if not windows:
            self._window_combo.addItem("No windows found: start Remote Play or your capture app")
        index = self._window_combo.findData(current) if current else -1
        self._window_combo.setCurrentIndex(max(index, 0))

        game_id = self._counter_manager.current_game_id
        title = self._capture_window_title(game_id) if game_id is not None else ""
        source = self._obs_source(game_id) if game_id is not None else ""
        row_ = self._database.get_game_detection(game_id) if game_id is not None else None
        if game_id is None:
            text = "Select or add your game on the Home page first."
        elif source:
            text = (
                f"<b>{escape(self._game_combo.currentText())}</b> reads "
                f"<b>{escape(source)}</b> from OBS."
            )
        elif title and row_ is not None and row_["exe_path"]:
            text = (
                f"<b>{escape(self._game_combo.currentText())}</b> is watching "
                f"<b>{escape(title)}</b> ({escape(Path(row_['exe_path']).name)})."
            )
        else:
            text = (
                f"<b>{escape(self._game_combo.currentText())}</b>: no window picked yet."
            )
        self._console_source.setText(text)
        self._stop_window_btn.setVisible(bool(title or source))

    def _use_console_window(self) -> None:
        game_id = self._counter_manager.current_game_id
        choice = self._window_combo.currentData()
        if game_id is None:
            QMessageBox.information(self, "Select a Game", "Select or add your game first.")
            return
        if not choice:
            return
        exe_path, title = choice
        row_ = self._database.get_game_detection(game_id)
        mode = row_["mode"] if row_ is not None else DETECTION_MODE_OFF
        if mode in (DETECTION_MODE_OFF, DETECTION_MODE_LOG):
            mode = DETECTION_MODE_TEMPLATE  # a console game's screen, not a log file
        self._database.set_game_detection(game_id, exe_path, mode)
        self._database.update_detection_options(
            game_id, **{OPTION_WINDOW_TITLE: title, OPTION_OBS_SOURCE: None}
        )
        self._configure_detection()
        self._refresh_console_page()
        self._explain_next_step(f"Auto-detect now watches \"{title}\".")

    def _explain_next_step(self, done: str) -> None:
        hotkey = self._database.get_setting(SETTING_HOTKEY_CALIBRATE, "f8").upper()
        QMessageBox.information(
            self,
            "Ready",
            f"{done}\n\nNext, teach it the death screen: when you die, click Capture Screen "
            f"on the Detection page and pick it (or press {hotkey} on the PC). Souls games "
            "can use the Souls preset in Set Up Detection.",
        )

    def _save_obs_settings(self) -> None:
        self._database.set_setting(SETTING_OBS_HOST, self._obs_host.text().strip())
        self._database.set_setting(SETTING_OBS_PORT, self._obs_port.value())
        self._database.set_setting(SETTING_OBS_PASSWORD, self._obs_password.text())

    def _connect_obs(self) -> None:
        """Log in to OBS and list its sources (capture devices first)."""
        self._save_obs_settings()
        self._obs_status.setText("Connecting…")
        QGuiApplication.processEvents()
        client = ObsClient(*self._obs_settings(), timeout=2.0)
        try:
            sources = client.video_sources()
        except ObsError as exc:
            self._obs_status.setText(f"⚠ {exc}")
            return
        finally:
            client.close()
        current = self._obs_source(self._counter_manager.current_game_id or -1)
        self._obs_source_combo.clear()
        self._obs_source_combo.addItems(sources)
        # A combo with placeholder text stays unselected unless told otherwise.
        self._obs_source_combo.setCurrentIndex(sources.index(current) if current in sources else 0)
        self._obs_status.setText(
            f"Connected to OBS ✓  Pick the source that shows your console "
            f"({len(sources)} found)." if sources else "Connected, but OBS has no sources yet."
        )
        self._configure_detection()  # a game already using OBS picks up new settings

    def _use_obs_source(self) -> None:
        game_id = self._counter_manager.current_game_id
        source = self._obs_source_combo.currentText()
        if game_id is None:
            QMessageBox.information(self, "Select a Game", "Select or add your game first.")
            return
        if not source:
            QMessageBox.information(self, "Connect First", "Connect to OBS, then pick a source.")
            return
        self._save_obs_settings()
        row_ = self._database.get_game_detection(game_id)
        mode = row_["mode"] if row_ is not None else DETECTION_MODE_OFF
        if mode in (DETECTION_MODE_OFF, DETECTION_MODE_LOG):
            mode = DETECTION_MODE_TEMPLATE
        self._database.set_game_detection(game_id, None, mode)
        self._database.update_detection_options(
            game_id, **{OPTION_OBS_SOURCE: source, OPTION_WINDOW_TITLE: None}
        )
        self._configure_detection()
        self._refresh_console_page()
        self._explain_next_step(f"Auto-detect now reads \"{source}\" from OBS.")

    def _stop_console_window(self) -> None:
        game_id = self._counter_manager.current_game_id
        if game_id is None:
            return
        row_ = self._database.get_game_detection(game_id)
        mode = row_["mode"] if row_ is not None else DETECTION_MODE_OFF
        self._database.set_game_detection(game_id, None, mode)
        self._database.update_detection_options(
            game_id, **{OPTION_WINDOW_TITLE: None, OPTION_OBS_SOURCE: None}
        )
        self._configure_detection()
        self._refresh_console_page()

    # Phone remote ------------------------------------------------------
    def _set_phone_remote(self, on: bool) -> None:
        if on:
            key = self._database.get_setting(SETTING_PHONE_REMOTE_KEY, "")
            if not key:
                key = new_key()
                self._database.set_setting(SETTING_PHONE_REMOTE_KEY, key)
            try:
                self._phone_remote.start(key)
            except OSError as exc:
                QMessageBox.warning(
                    self, "Phone Remote", f"Couldn't start the phone page: {exc}"
                )
                on = False
            self._refresh_counters()  # the page shows the current count right away
        else:
            self._phone_remote.stop()
        self._database.set_setting(SETTING_PHONE_REMOTE, "true" if on else "false")
        self._set_phone_ui()

    def _new_phone_link(self) -> None:
        self._database.set_setting(SETTING_PHONE_REMOTE_KEY, new_key())
        if self._phone_remote.running:
            self._set_phone_remote(True)

    def _set_phone_ui(self) -> None:
        on = self._phone_remote.running
        self._phone_toggle.set_on(on)
        self._phone_link_box.setVisible(on)
        if on:
            self._phone_link.setText(self._phone_remote.url())
            self._phone_status.setText(
                "Open it in your phone's browser and add it to the home screen. "
                "If Windows asks whether this app may use the network, allow private networks."
            )

    def _on_phone_seen(self) -> None:
        self._phone_status.setText(f"Phone connected ✓  (last seen {datetime.now():%H:%M})")

    def _on_phone_action(self, action: str) -> None:
        if action in PHONE_ACTIONS:  # the server already refuses anything else
            self._action_handlers[action]()

    # Page switching and refresh --------------------------------------
    def _show_page(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._nav_buttons[index].setChecked(True)
        self._page_badge.setText(_PAGES[index][0])

    def _on_page_changed(self, index: int) -> None:
        if index == _PAGE_TIMER:
            self._refresh_timer_page()
        else:
            self._page_timer.stop()
        if index == _PAGE_HOME:
            self._refresh_home()
        elif index == _PAGE_STATS:
            self._refresh_stats_page()
        elif index == _PAGE_DETECTION:
            self._refresh_detection_page()
        elif index == _PAGE_CONSOLE:
            self._refresh_console_page()

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
        defeated_action = menu.addAction("Boss Defeated")
        defeated_action.triggered.connect(lambda: self._defeat_current_boss(detected=False))
        pause_action = menu.addAction("Pause / Resume Auto-Detect")
        pause_action.triggered.connect(self._toggle_detection_pause)
        menu.addSeparator()
        split_action = menu.addAction("Timer: Start / Split")
        split_action.triggered.connect(lambda: self._timer_action("split"))
        timer_window_action = menu.addAction("Show / Hide Timer Window")
        timer_window_action.triggered.connect(self._toggle_timer_window)
        mini_action = menu.addAction("Mini Mode")
        mini_action.triggered.connect(self._toggle_mini_mode)
        menu.addSeparator()
        overlay_action = menu.addAction("Overlay")
        overlay_action.setCheckable(True)
        overlay_action.triggered.connect(lambda _=False: self._toggle_overlay())
        self._overlay.visibility_changed.connect(overlay_action.setChecked)
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
            self.bring_to_front()

    def bring_to_front(self) -> None:
        """Show the window (from the tray, too) and give it focus."""
        if self.isMinimized():
            self.showNormal()
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

    def _registered_bindings(self) -> dict[str, str]:
        """The keyboard combos to register now: run-only timer keys only during a run."""
        bindings = self._hotkey_bindings()
        if not self._run_keys_active:
            for action in _RUN_ONLY_ACTIONS:
                bindings[f"{action}_key"] = ""
        return bindings

    def _sync_run_hotkeys(self) -> None:
        """Register the run-only timer keys while a run is going (or just finished)."""
        controller = self._speedrun
        active = controller is not None and controller.timer.state != IDLE
        if active != self._run_keys_active:
            self._run_keys_active = active
            self._hotkey_manager.update_bindings(**self._registered_bindings())

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
            (self._undo_btn, "undo", "Undo the last change"),
        ):
            button.set_key(key(action))
            button.setToolTip(tooltip(action, text))
        self._pause_btn.setToolTip(
            tooltip("pause_detection", "Pause/resume auto-detection (cutscenes, co-op…)")
        )
        self._prev_boss_btn.setToolTip(tooltip("prev_boss", "Previous boss"))
        self._next_boss_btn.setToolTip(tooltip("next_boss", "Next boss not yet defeated"))
        self._defeated_btn.setToolTip(
            tooltip("boss_defeated", "Boss defeated: mark it ✓ and move to the next boss")
        )
        for action, button in self._timer_buttons.items():
            button.set_key(key(f"timer_{action}"))
            what = _TIMER_BUTTONS[action][0]
            if f"timer_{action}" in _RUN_ONLY_ACTIONS:
                what += "\nThe key works in-game while a run is going."
            button.setToolTip(tooltip(f"timer_{action}", what))

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
        self._hotkey_manager = HotkeyManager(**self._registered_bindings(), parent=self)
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
            "isn't supported. Pick a different key in Settings → Controls."
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
            status = "Auto-detect can't run here"
        elif not row["exe_path"] and not self._obs_source(game_id):
            status = "Auto-detect off"
        else:
            screen_config = self._screen_watch_config(game_id, mode, row["exe_path"])
            if row["exe_path"]:
                request_capture_permission()  # macOS asks once for Screen Recording
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
        if screen_config is not None and game_id is not None:
            host, port, password = self._obs_settings()
            screen_config = dataclasses.replace(
                screen_config,
                window_title=self._capture_window_title(game_id),
                obs_source=self._obs_source(game_id),
                obs_host=host,
                obs_port=port,
                obs_password=password,
            )
        cooldown = float(self._database.get_setting(SETTING_DETECTION_COOLDOWN, "8") or 8)
        self._death_watcher.configure(screen_config, cooldown_seconds=cooldown)
        self._log_watcher.configure(log_config)
        if status is not None:
            self._detect_status_label.setText(status)
        if self._pages.currentIndex() == _PAGE_DETECTION:
            self._refresh_detection_page()

    def _capture_window_title(self, game_id: int) -> str:
        """Console games: the title of the window to watch ("" = the game's own window)."""
        title = self._database.get_detection_options(game_id).get(OPTION_WINDOW_TITLE, "")
        return title if isinstance(title, str) else ""

    def _obs_source(self, game_id: int) -> str:
        """Console games with a capture card: the OBS source to read ("" = none)."""
        source = self._database.get_detection_options(game_id).get(OPTION_OBS_SOURCE, "")
        return source if isinstance(source, str) else ""

    def _obs_settings(self) -> tuple[str, int, str]:
        settings = self._database.get_all_settings()
        try:
            port = int(settings.get(SETTING_OBS_PORT, "") or OBS_DEFAULT_PORT)
        except ValueError:
            port = OBS_DEFAULT_PORT
        host = settings.get(SETTING_OBS_HOST, "").strip() or OBS_DEFAULT_HOST
        return host, port, settings.get(SETTING_OBS_PASSWORD, "")

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
            message + (" Wrong? Unmark it in Games & Bosses on the Home page." if detected else "")
        )
        self._notify(message, 6000)
        self._configure_detection()  # watch for the next boss's victory instead

    def _screen_watch_config(self, game_id: int, mode: str, exe_path: str) -> WatchConfig:
        templates = [
            (t["region"], t["template"]) for t in self._database.get_death_templates(game_id)
        ]
        # A None matcher still watches the window, buffering recent frames so
        # the player can pick their first death screen with Capture Screen.
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
            button.setText(" Resume" if self._detection_paused else " Pause")
            icons.set_icon(button, "play" if self._detection_paused else "pause", size=16)
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
        """
        A game launched: continue its session after a short break (or when the
        app itself just restarted, e.g. for an update), else start a fresh one.
        """
        self._session_manager.continue_or_start(game_id)
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
        source = self._obs_source(game_id)
        if source:
            client = ObsClient(*self._obs_settings())
            try:
                frame = client.screenshot(source)
            except ObsError as exc:
                QMessageBox.warning(self, "Couldn't Read OBS", str(exc))
                return
            finally:
                client.close()
        else:
            frame = capture_game_frame(exe_path, self._capture_window_title(game_id))
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
            self, "Select the Game", "", program_file_filter()
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
        """Startup and profile switch: the look, plus where the windows were."""
        settings = self._database.get_all_settings()
        self._apply_appearance(settings)
        self._timer_window.restore_geometry_string(settings.get(SETTING_TIMER_GEOMETRY, ""))
        self._timer_window.setVisible(settings.get(SETTING_TIMER_VISIBLE, "false") == "true")
        self._overlay.restore_geometry_string(settings.get(SETTING_OVERLAY_GEOMETRY, ""))

    def _apply_appearance(self, settings: dict[str, str]) -> None:
        """Theme, colors, fonts and backgrounds of every window (also the Settings preview)."""
        theme = active_theme(settings.get(SETTING_THEME, "dark"))
        info = theme_info(theme)
        image = load_background(settings.get(SETTING_UI_BG_IMAGE, ""))
        dim = QColor(info.base)
        try:
            dim.setAlphaF(min(max(int(settings.get(SETTING_UI_BG_DIM, "60")), 0), 90) / 100)
        except ValueError:
            dim.setAlphaF(0.6)
        self._background.set_background(image, dim)
        icons.set_colors(
            {
                icons.NORMAL: info.icon,
                icons.NAV: info.icon_muted,
                "nav_active": info.text if info.light else "#ffffff",
                icons.DANGER: info.danger,
            }
        )
        dashboard.set_colors(
            settings.get(SETTING_UI_TEXT_COLOR, "") or info.text,
            info.icon_muted,
            settings.get(SETTING_UI_COUNTER_COLOR, "") or info.accent,
            info.light,
        )
        apply_theme(
            self,
            theme,
            text_color=settings.get(SETTING_UI_TEXT_COLOR, ""),
            counter_color=settings.get(SETTING_UI_COUNTER_COLOR, ""),
            font_family=settings.get(SETTING_UI_FONT, ""),
            see_through=image is not None,
        )
        self._refresh_theme_icons(settings.get(SETTING_UI_COUNTER_COLOR, "") or info.accent)
        self._overlay.apply_display_settings(settings)
        self._timer_window.apply_display_settings(settings)
        self._mini.apply_display_settings(settings)
        self._overlay.set_always_on_top(
            settings.get(SETTING_OVERLAY_ALWAYS_ON_TOP, "true") == "true"
        )
        self._overlay.set_locked(settings.get(SETTING_OVERLAY_LOCKED, "false") == "true")

    def _refresh_theme_icons(self, glow_color: str) -> None:
        icons.refresh_icons(self)
        for button in self.findChildren(ActionButton):
            button.refresh_icon()
        for action, icon_name in self._menu_icons:
            action.setIcon(icons.icon(icon_name, icons.color(icons.NORMAL), size=16))
        self._credit.refresh_icon()
        self._update_card.refresh_icon()
        self._skull_badge.refresh_art()
        self._start_banner.refresh_icon()
        self._week_chart.update()
        self._boss_ring.update()
        glow(self._counter_label, glow_color, radius=48)

    def _preview_appearance(self, values: dict[str, str]) -> None:
        """Show unsaved Settings changes ({} = back to the saved look)."""
        settings = self._database.get_all_settings()
        settings.update(values)
        self._apply_appearance(settings)

    def _refresh_downloaded_themes(self) -> None:
        """After an app update, fetch this version's copy of downloaded themes (quietly)."""
        self._theme_downloads = []
        for name in outdated_themes():
            download = ThemeDownload(name)
            download.finished.connect(self._on_theme_refreshed)
            self._theme_downloads.append(download)
            download.start()

    def _on_theme_refreshed(self, name: str, error: str) -> None:
        if error:
            logger.info("Couldn't refresh theme '%s': %s", name, error)
        elif self._database.get_setting(SETTING_THEME, "dark") == name:
            self._apply_saved_settings()

    def _maybe_check_updates(self) -> None:
        """Check now and every few hours (if enabled); the sidebar card shows the result."""
        checker = self._update_checker = UpdateChecker(self)
        checker.update_available.connect(self._on_update_available)
        checker.up_to_date.connect(lambda _latest: self._update_card.set_state("current"))
        checker.check_failed.connect(lambda: self._update_card.set_state("failed"))
        self._update_recheck = QTimer(self)
        self._update_recheck.setInterval(_UPDATE_RECHECK_MS)
        self._update_recheck.timeout.connect(self._check_updates)
        if self._database.get_setting(SETTING_CHECK_UPDATES, "true") == "true":
            self._check_updates()
            self._update_recheck.start()

    def _check_updates(self) -> None:
        if self._update_card.state() in ("checking", "available"):
            return  # one at a time; a found update stays until it's installed
        self._update_card.set_state("checking")
        self._update_checker.check_async()

    def _on_update_available(self, latest: str, url: str) -> None:
        announced = latest == self._update_version
        self._update_version, self._update_page_url = latest, url
        self._update_card.set_state("available", latest)
        if self._tray is not None and not announced:
            self._tray.showMessage(
                APP_BRAND,
                f"Version {latest} is available. Click \"Update\" at the bottom of the sidebar.",
                QSystemTrayIcon.MessageIcon.Information,
                8000,
            )

    def _start_update(self) -> None:
        """Download the new installer, run it silently and quit (installed copies)."""
        checker = getattr(self, "_update_checker", None)
        url = checker.installer_url if checker is not None else ""
        size = checker.installer_size if checker is not None else 0
        if not is_installed_copy() or not url:
            # Portable or source copies can't replace themselves: open the release.
            QDesktopServices.openUrl(QUrl(self._update_page_url))
            return
        confirm = QMessageBox.question(
            self,
            "Update",
            f"Download and install {self._update_version} now?\n\n"
            f"{APP_SHORT_NAME} closes, updates and opens again in a moment. Your games, "
            "deaths and settings are kept.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        progress = QProgressDialog("Downloading the update…", "Cancel", 0, 100, self)
        progress.setWindowTitle("Update")
        progress.setMinimumDuration(0)
        destination = Path(tempfile.gettempdir()) / "DUDC-update" / INSTALLER_NAME
        download = self._update_download = _UpdateDownload(url, size, destination)
        download.progress.connect(
            lambda done, total: progress.setValue(int(done * 100 / max(total, 1)))
        )
        progress.canceled.connect(download.cancelled.set)

        def failed(message: str) -> None:
            progress.close()
            if not download.cancelled.is_set():
                QMessageBox.warning(self, "Update Failed", message)

        def succeeded(path: str) -> None:
            progress.close()
            try:
                launch_installer(Path(path))
            except OSError as exc:
                QMessageBox.warning(self, "Update Failed", f"Couldn't start the installer: {exc}")
                return
            self._quit_app()  # the installer replaces the files and reopens the app

        download.failed.connect(failed)
        download.succeeded.connect(succeeded)
        download.start()

    # ----------------------------------------------------------------
    # Welcome guide, mini mode, quick renames
    # ----------------------------------------------------------------
    def _guide_keys(self) -> dict[str, str]:
        bindings = self._hotkey_bindings()
        return {
            action: QKeySequence(bindings.get(f"{action}_key", "")).toString(
                QKeySequence.SequenceFormat.NativeText
            )
            for action in (
                "increment",
                "decrement",
                "undo",
                "calibrate",
                "toggle_overlay",
                "timer_split",
                "timer_pause",
                "timer_reset",
            )
        }

    def maybe_show_welcome(self, force: bool = False) -> None:
        """The Quick Start guide: on a fresh install once, or on request."""
        if not force and (
            self._database.get_games()
            or self._database.get_setting(SETTING_WELCOME_SHOWN, "") == "true"
        ):
            return
        if self._guide is None:
            guide = self._guide = GuideDialog(self._guide_keys(), parent=self)
            guide.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            guide.again_check.setChecked(
                self._database.get_setting(SETTING_WELCOME_SHOWN, "") == "false"
            )
            guide.action_requested.connect(self._on_guide_action)
            guide.finished.connect(self._on_guide_closed)
        self._guide.set_status(self._quick_start_status())
        self._guide.show()
        self._guide.raise_()
        self._guide.activateWindow()

    def _on_guide_closed(self, _result: int) -> None:
        if self._guide is not None:
            shown = "false" if self._guide.again_check.isChecked() else "true"
            self._database.set_setting(SETTING_WELCOME_SHOWN, shown)
        self._guide = None

    def _on_guide_action(self, action: str) -> None:
        """A guide button: do it here, where the real flows live."""
        pages = {
            ACTION_HOME: _PAGE_HOME,
            ACTION_DETECTION: _PAGE_DETECTION,
            ACTION_CONSOLE: _PAGE_CONSOLE,
            ACTION_TIMER: _PAGE_TIMER,
        }
        if action == ACTION_ADD_EXE:
            self._add_game_from_exe()
        elif action.startswith(ACTION_TEMPLATE):
            self._add_template_game(action[len(ACTION_TEMPLATE):])
        elif action in pages:
            self._show_page(pages[action])
            self.showNormal()
            self.raise_()
            self.activateWindow()
        elif action == ACTION_BOSSES:
            self._open_boss_window()
        elif action == ACTION_OVERLAY:
            if not self._overlay.isVisible():
                self._toggle_overlay()
        elif action == ACTION_OBS:
            self._open_obs_guide()
        elif action == ACTION_CONTROLS:
            self._open_settings_window(SettingsWindow.TAB_CONTROLS)
        self._home_refresh.start()

    def _quick_start_status(self) -> dict[str, bool]:
        """Which Quick Start steps the player has done (cheap: a few small queries)."""
        db = self._database
        game_id = self._counter_manager.current_game_id
        detect = False
        if game_id is not None:
            row_ = db.get_game_detection(game_id)
            mode = row_["mode"] if row_ is not None else DETECTION_MODE_OFF
            source = bool(row_ is not None and row_["exe_path"]) or bool(self._obs_source(game_id))
            if mode == DETECTION_MODE_LOG:
                detect = True
            elif mode == DETECTION_MODE_TEMPLATE:
                detect = source and bool(db.get_death_templates(game_id, SCREEN_DEATH))
            elif mode != DETECTION_MODE_OFF:
                detect = source
        return {
            "game": game_id is not None or bool(db.get_games()),
            "death": db.get_total_deaths() > 0,
            "bosses": game_id is not None and self._boss_combo.count() > 1,
            "detect": detect,
            "stream": self._overlay.isVisible()
            or db.get_setting(SETTING_OVERLAY_EVER_SHOWN, "false") == "true"
            or db.get_setting(SETTING_DEATHS_TXT_ENABLED, "false") == "true",
        }

    def _on_overlay_visibility(self, visible: bool) -> None:
        if visible and self._database.get_setting(SETTING_OVERLAY_EVER_SHOWN, "") != "true":
            self._database.set_setting(SETTING_OVERLAY_EVER_SHOWN, "true")
            self._home_refresh.start()

    def _hide_start_banner(self) -> None:
        self._database.set_setting(SETTING_QUICK_START_HIDDEN, "true")
        self._start_banner.hide()

    def _refresh_home(self) -> None:
        """The guide's checklist, the banner, and (while Home shows) the greeting and charts."""
        status = self._quick_start_status()
        if self._guide is not None:
            self._guide.set_status(status)
        remaining = [title for key, title in STEPS if not status[key]]
        hidden = self._database.get_setting(SETTING_QUICK_START_HIDDEN, "false") == "true"
        if remaining and not hidden:
            self._start_banner.set_progress(len(STEPS) - len(remaining), len(STEPS), remaining[0])
        self._start_banner.setVisible(bool(remaining) and not hidden)
        if self._pages.currentIndex() != _PAGE_HOME:
            return

        db = self._database
        game_id = self._counter_manager.current_game_id
        now = datetime.now()
        hello = (
            "Late-night grind" if now.hour < 5
            else "Good morning" if now.hour < 12
            else "Good afternoon" if now.hour < 18
            else "Good evening"
        )
        profile = self._profile_manager.active_profile
        self._greeting.setText(f"{hello}, {profile}" if profile != "Default" else hello)
        self._date_chip.setText(f"{now:%a %d %b}")
        today = date.today()
        per_day = (
            {row_["day"]: row_["deaths"] for row_ in db.get_deaths_per_day(game_id)}
            if game_id is not None
            else {}
        )
        today_deaths = per_day.get(today.isoformat(), 0)
        if game_id is None:
            line = "Add a game and let's start counting."
        elif today_deaths <= 0:
            line = "No deaths yet today. Clean run so far."
        elif today_deaths < 10:
            line = f"{today_deaths} death{'s' if today_deaths != 1 else ''} today. Warming up."
        elif today_deaths < 30:
            line = f"{today_deaths} deaths today. You're learning the fight."
        else:
            line = f"{today_deaths} deaths today. Persistence is a skill too."
        self._greeting_line.setText(line)

        days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
        week = [(day.strftime("%a"), per_day.get(day.isoformat(), 0), day == today) for day in days]
        self._week_chart.set_days(week)
        this_week = sum(max(count, 0) for _, count, _ in week)
        last_week = sum(
            max(per_day.get((today - timedelta(days=offset)).isoformat(), 0), 0)
            for offset in range(7, 14)
        )
        self._week_total.setText(f"{this_week} death{'s' if this_week != 1 else ''}")
        change = this_week - last_week
        self._week_delta.setVisible(bool(this_week or last_week))
        self._week_delta.setText(f"{change:+d} vs last week" if change else "Same as last week")
        tone = "up" if change > 0 else "down" if change < 0 else "flat"
        self._week_delta.setProperty("tone", tone)
        self._week_delta.style().unpolish(self._week_delta)
        self._week_delta.style().polish(self._week_delta)

        bosses = db.get_bosses(game_id) if game_id is not None else []
        beaten = sum(1 for boss in bosses if boss["defeated"])
        self._boss_ring.set_values(beaten, len(bosses))
        totals = (
            [(row_["name"], row_["total"]) for row_ in db.get_boss_death_totals(game_id)
             if row_["total"] > 0]
            if bosses
            else []
        )
        self._toughest.set_rows(
            totals,
            "No bosses yet: add them with Games & Bosses to track every fight."
            if not bosses
            else "No boss deaths yet. Pick the boss you're fighting above.",
        )

    def _add_template_game(self, name: str) -> None:
        template = get_template(name)
        if template is None:
            return
        game_id, _added = add_template_bosses(self._database, template)
        self._reload_games(select_game_id=game_id)
        if self._boss_combo.count() > 1:
            self._boss_combo.setCurrentIndex(1)  # the first boss, in story order

    def _toggle_mini_mode(self) -> None:
        if self._mini.isVisible():
            self._exit_mini_mode()
        else:
            self._enter_mini_mode()

    def _enter_mini_mode(self) -> None:
        """Swap the full window for the small always-on-top one."""
        saved = self._database.get_setting(SETTING_MINI_GEOMETRY, "")
        if saved:
            self._mini.restore_geometry_string(saved)
        else:
            corner = self.frameGeometry().topRight()
            self._mini.move(corner.x() - self._mini.width(), corner.y() + 40)
            self._mini.keep_on_screen()
        self._refresh_counters()
        self._mini.show()
        self._mini.raise_()
        self.hide()

    def _exit_mini_mode(self) -> None:
        self._database.set_setting(SETTING_MINI_GEOMETRY, self._mini.geometry_string())
        self._mini.hide()
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_mini_action(self, action: str) -> None:
        if action == "increment":
            self._on_increment()
        elif action == "undo":
            self._on_undo()
        elif action == "expand":
            self._exit_mini_mode()

    def _game_context_menu(self, position) -> None:
        game_id = self._counter_manager.current_game_id
        if game_id is None:
            return
        menu = QMenu(self)
        menu.addAction("Rename Game…", self._rename_current_game)
        menu.addAction("Games && Bosses…", self._open_boss_window)
        menu.exec(self._game_combo.mapToGlobal(position))

    def _boss_context_menu(self, position) -> None:
        boss_id = self._counter_manager.current_boss_id
        menu = QMenu(self)
        if boss_id is not None:
            boss = self._database.get_boss(boss_id)
            menu.addAction("Rename Boss…", self._rename_current_boss)
            if boss is not None and boss["defeated"]:
                menu.addAction("Mark Not Defeated", lambda: self._set_boss_defeated(False))
            else:
                menu.addAction("Mark Defeated ✓", lambda: self._set_boss_defeated(True))
            menu.addSeparator()
        menu.addAction("Games && Bosses…", self._open_boss_window)
        menu.exec(self._boss_combo.mapToGlobal(position))

    def _rename_current_game(self) -> None:
        game_id = self._counter_manager.current_game_id
        if game_id is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Game", "New name:", text=self._game_combo.currentText()
        )
        if not ok or not name.strip() or name.strip() == self._game_combo.currentText():
            return
        try:
            self._database.rename_game(game_id, name.strip())
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Could Not Rename", f"{exc}\n\nIs the name already used?")
            return
        self._reload_games(select_game_id=game_id)

    def _rename_current_boss(self) -> None:
        boss_id = self._counter_manager.current_boss_id
        boss = self._database.get_boss(boss_id) if boss_id is not None else None
        if boss is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Boss", "New name:", text=boss["name"])
        if not ok or not name.strip() or name.strip() == boss["name"]:
            return
        try:
            self._database.rename_boss(boss_id, name.strip())
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Could Not Rename", f"{exc}\n\nIs the name already used?")
            return
        self._reload_bosses(self._counter_manager.current_game_id)

    def _set_boss_defeated(self, defeated: bool) -> None:
        boss_id = self._counter_manager.current_boss_id
        if boss_id is None:
            return
        self._database.set_boss_defeated(boss_id, defeated)
        self._reload_bosses(self._counter_manager.current_game_id)
        self._configure_detection()  # victory watching follows defeated state

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
            self._first_game_btn.hide()
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
            self._first_game_btn.show()

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

    def _show_counter_source_menu(self) -> None:
        current = self._database.get_setting(SETTING_OVERLAY_COUNTER_SOURCE, DEFAULT_COUNTER_SOURCE)
        menu = QMenu(self)
        group = QActionGroup(menu)
        for value, text in (
            ("total", "All-time deaths in this game"),
            ("session", "Deaths this session"),
            ("boss", "Deaths on this boss"),
            ("run", "Deaths this speedrun run"),
        ):
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(value == current)
            group.addAction(action)
            action.triggered.connect(
                lambda _=False, v=value: self._set_overlay_setting(
                    SETTING_OVERLAY_COUNTER_SOURCE, v
                )
            )
        caption = self._counter_caption
        menu.exec(caption.mapToGlobal(caption.rect().bottomLeft()))

    def _continue_past_session(self) -> None:
        """Pick an earlier session of this game and keep counting in it."""
        game_id = self._counter_manager.current_game_id
        if game_id is None:
            return
        sessions = self._session_manager
        dialog = SessionHistoryWindow(
            self._database, game_id, parent=self, can_continue=True,
            current_session_id=sessions.current_session_id,
        )
        dialog.exec()
        if dialog.continue_session_id is None:
            return
        sessions.continue_session(game_id, dialog.continue_session_id)
        self._refresh_counters()
        deaths = sessions.get_session_deaths()
        self._notify(f"Continuing that session: {deaths} death{'' if deaths == 1 else 's'} so far.")

    def _refresh_counters(self) -> None:
        self._apply_snapshot(self._counter_manager.get_snapshot())

    def _run_deaths(self) -> int:
        """Deaths in the speedrun in progress (0 when no run is going)."""
        controller = self._speedrun
        if controller is None or controller.game_id != self._counter_manager.current_game_id:
            return 0
        return controller.timer.deaths if controller.timer.state != IDLE else 0

    def _apply_snapshot(self, snapshot: CounterSnapshot) -> None:
        snapshot.run_deaths = self._run_deaths()
        source = self._database.get_setting(SETTING_OVERLAY_COUNTER_SOURCE, DEFAULT_COUNTER_SOURCE)
        big_numbers = {
            "session": snapshot.session_deaths,
            "boss": snapshot.boss_deaths,
            "total": snapshot.total_deaths,
            "run": snapshot.run_deaths,
        }
        self._counter_label.setText(str(big_numbers.get(source, snapshot.session_deaths)))
        self._skull_badge.set_count(big_numbers.get(source, snapshot.session_deaths))
        self._home_refresh.start()
        self._counter_caption.setText(
            _COUNTER_CAPTIONS.get(source, _COUNTER_CAPTIONS[DEFAULT_COUNTER_SOURCE])
        )
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
        self._mini.update_counters(snapshot)
        self._phone_remote.set_state(
            game=snapshot.game_name or "",
            boss=snapshot.boss_name or "",
            count=big_numbers.get(source, snapshot.session_deaths),
            caption=f"{_COUNTER_CAPTIONS.get(source, '').title()}  ·  "
            f"all-time {snapshot.total_deaths}",
            detection=self._detect_status_label.text(),
        )
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
        source = self._database.get_setting(SETTING_OVERLAY_COUNTER_SOURCE, DEFAULT_COUNTER_SOURCE)
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

    def _open_settings_window(self, tab: int = 0) -> None:
        dialog = SettingsWindow(
            self._database,
            gamepad=self._gamepad_manager,
            hotkeys=self._hotkey_manager,
            parent=self,
            tab=tab,
        )
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.preview_changed.connect(self._preview_appearance)
        if dialog.exec() != SettingsWindow.DialogCode.Accepted and dialog.previewed:
            self._preview_appearance({})  # cancelled: back to what's saved

    def _open_overlay_settings(self) -> None:
        self._open_settings_window(tab=SettingsWindow.TAB_OVERLAY)

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
        self._apply_appearance(self._database.get_all_settings())
        self._overlay.keep_on_screen()
        self._overlay.show()
        self._overlay.raise_()

    def _enable_deaths_txt(self) -> None:
        """Turn on deaths.txt output and write it immediately so OBS can find it."""
        self._database.set_setting(SETTING_DEATHS_TXT_ENABLED, "true")
        self._refresh_counters()

    def _on_settings_changed(self) -> None:
        self._apply_appearance(self._database.get_all_settings())
        if self._speedrun is not None:
            self._apply_timer_options(self._speedrun)
            self._timer_window.set_controller(self._speedrun)
        self._configure_detection()
        self._on_settings_changed_hotkeys()
        self._refresh_counters()

    def _on_settings_changed_hotkeys(self) -> None:
        bindings = self._hotkey_bindings()
        pads = self._pad_bindings()
        self._hotkey_manager.update_bindings(**self._registered_bindings())
        self._gamepad_manager.update_bindings(pads)
        self._update_hotkey_labels(bindings, pads)

    def _toggle_overlay(self) -> None:
        self._overlay.toggle_visibility()
        if self._overlay.isVisible():
            self._overlay.keep_on_screen()

    def _overlay_context_menu(self, position: QPoint) -> None:
        """The overlay's right-click menu: count, change its look, place it."""
        settings = self._database.get_all_settings()
        menu = QMenu(self)
        self._menu_icons_before = len(self._menu_icons)
        self._menu_action(menu, "skull", "+1 Death", self._on_increment)
        self._menu_action(menu, "minus", "−1 Death", self._on_decrement)
        self._menu_action(menu, "undo-2", "Undo", self._on_undo)
        self._menu_action(
            menu, "trophy", "Boss Defeated", lambda: self._defeat_current_boss(detected=False)
        )
        menu.addSeparator()

        def choices(title: str, key: str, options, current: str) -> None:
            submenu = menu.addMenu(title)
            group = QActionGroup(submenu)
            for value, label, enabled in options:
                action = submenu.addAction(label)
                action.setCheckable(True)
                action.setChecked(value == current)
                action.setEnabled(enabled)
                group.addAction(action)
                action.triggered.connect(
                    lambda _=False, v=value: self._set_overlay_setting(key, v)
                )

        choices(
            "Big Number Shows",
            SETTING_OVERLAY_COUNTER_SOURCE,
            (("total", "All-Time", True), ("session", "This Session", True),
             ("boss", "This Boss", True), ("run", "This Speedrun Run", True)),
            settings.get(SETTING_OVERLAY_COUNTER_SOURCE, DEFAULT_COUNTER_SOURCE),
        )
        has_image = bool(settings.get(SETTING_OVERLAY_BG_IMAGE, ""))
        choices(
            "Background",
            SETTING_OVERLAY_BG_MODE,
            (("dark", "Card", True), ("chroma", "Green Screen (Chroma Key)", True),
             ("image", "Image" if has_image else "Image (choose one in Settings)", has_image)),
            settings.get(SETTING_OVERLAY_BG_MODE, "dark"),
        )
        try:
            size = int(settings.get(SETTING_OVERLAY_FONT_SIZE, "24"))
        except ValueError:
            size = 24
        size_menu = menu.addMenu("Number Size")
        for label, step in (("Bigger", +4), ("Smaller", -4)):
            action = size_menu.addAction(label)
            new_size = min(max(size + step, 10), 96)
            action.setEnabled(new_size != size)
            action.triggered.connect(
                lambda _=False, v=new_size: self._set_overlay_setting(SETTING_OVERLAY_FONT_SIZE, v)
            )
        menu.addSeparator()
        for key, label, default in (
            (SETTING_OVERLAY_SHOW_SKULL, "Skull Badge", "true"),
            (SETTING_OVERLAY_LOCKED, "Lock Position", "false"),
            (SETTING_OVERLAY_ALWAYS_ON_TOP, "Always on Top", "true"),
        ):
            action = menu.addAction(label)
            action.setCheckable(True)
            on = settings.get(key, default) == "true"
            action.setChecked(on)
            action.triggered.connect(
                lambda _=False, k=key, v=on: self._set_overlay_setting(k, "false" if v else "true")
            )
        self._add_display_menu(menu)
        menu.addSeparator()
        self._menu_action(menu, "settings", "Overlay Settings…", self._open_overlay_settings)
        self._menu_action(menu, "eye-off", "Hide Overlay", self._toggle_overlay)
        menu.exec(position)
        del self._menu_icons[self._menu_icons_before:]  # this menu is gone

    def _set_overlay_setting(self, key: str, value: object) -> None:
        self._database.set_setting(key, value)
        self._apply_appearance(self._database.get_all_settings())
        self._refresh_counters()  # "Big number shows" also changes this window

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
        self._sync_run_hotkeys()

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
            or not (row["exe_path"] or self._obs_source(game_id))
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
        self._sync_run_hotkeys()

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
        self._sync_run_hotkeys()
        self._refresh_counters()  # "Deaths this run" starts or ends with the run

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
        dialog = RunHistoryDialog(self._database, self._speedrun, parent=self)
        dialog.exec()
        if dialog.continue_run is not None:
            self._continue_saved_run(self._speedrun.game_id, dialog.continue_run)
            return
        self._timer_window.set_controller(self._speedrun)  # history may have changed

    def _continue_saved_run(self, game_id: int, run: RunRecord) -> None:
        """Carry on a reset attempt: paused at its time, with its splits and deaths."""
        if self._speedrun is not None and self._speedrun.running:
            return
        timer = SpeedrunTimer.restore(run.resume_data())
        if run.run_id is not None:
            # It's an attempt in progress again; it's saved anew when it ends.
            self._database.delete_speedrun_run(run.run_id)
        self._resume_recovered_run(game_id, timer)
        self._autosave()
        self._refresh_timer_page()
        self._refresh_counters()
        pause_key = self._hotkey_bindings().get("timer_pause_key", "").upper() or "Pause"
        self._notify(
            f"Run continued at {format_time(timer.elapsed_ms())}: press {pause_key} to go on."
        )

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
        self._mini.keep_on_screen()

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
        self._database.set_setting(SETTING_MINI_GEOMETRY, self._mini.geometry_string())
        self._database.set_setting(
            SETTING_MAIN_WINDOW_GEOMETRY, bytes(self.saveGeometry().toBase64()).decode("ascii")
        )
        self._session_manager.end_current_session()
        self._hotkey_manager.stop()
        self._gamepad_manager.stop()
        self._phone_remote.stop()
        self._autosave_timer.stop()
        self._recovery_timer.stop()
        self._game_launch_timer.stop()  # it reads the database being closed
        self._page_timer.stop()
        self._death_watcher.stop()
        self._log_watcher.stop()
        self._overlay.close()
        self._timer_window.close()
        self._mini.close()
        if self._tray is not None:
            self._tray.hide()
        self._database.close()
        self._closed = True
        logger.info("Application closed cleanly")
        super().closeEvent(event)
