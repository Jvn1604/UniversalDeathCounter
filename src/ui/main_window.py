"""
Main application window.

Wires together the database (per active profile), core managers, hotkeys,
overlay, system tray, deaths.txt stream output, update checker, and theme
system into the primary user-facing UI.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QPixmap, QScreen
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.core.counter_manager import CounterManager, CounterSnapshot
from src.core.session_manager import SessionManager
from src.core.statistics import StatisticsService
from src.database.database import Database
from src.detection.death_watcher import DeathWatcher, WatchConfig
from src.detection.game_window import (
    capture_game_frame,
    detection_available,
    exe_display_name,
    running_exe_paths,
)
from src.detection.matchers import SOULS_PRESET_EXES, DeathTemplate, build_matcher
from src.hotkeys.gamepad import GamepadManager, combo_label
from src.hotkeys.hotkey_manager import HotkeyManager
from src.overlay.overlay_window import OverlayWindow, available_screen_rects
from src.themes.theme_manager import apply_theme
from src.ui.about_window import AboutWindow
from src.ui.auto_detect_window import (
    AutoDetectWindow,
    CalibrationDialog,
    DeathScreenDialog,
    first_death_hint,
)
from src.ui.boss_window import BossWindow
from src.ui.death_log_window import DeathLogWindow
from src.ui.obs_guide_window import ObsGuideWindow
from src.ui.settings_window import SettingsWindow
from src.ui.statistics_window import StatisticsWindow
from src.utils.constants import (
    APP_BRAND,
    APP_NAME,
    APP_SUBTITLE,
    CONTROL_ACTIONS,
    DETECTION_MODE_OFF,
    DETECTION_MODE_SOULS,
    DETECTION_MODE_TEMPLATE,
    ICONS_DIR,
    SAVES_DIR,
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


class MainWindow(QMainWindow):
    """The application's primary window."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(480, 460)

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
        self._death_watcher = DeathWatcher(parent=self)
        self._detection_paused = False  # not persisted: every launch starts active
        self._quitting = False

        self._update_window_title()
        self._build_menu()
        self._build_ui()
        self._build_tray()
        self._setup_hotkeys()
        self._setup_death_watcher()
        self._apply_saved_settings()
        self._restore_main_geometry()
        QGuiApplication.instance().screenRemoved.connect(self._on_screen_removed)
        self._reload_games()
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

        view_menu = menu_bar.addMenu("&View")
        overlay_action = view_menu.addAction("Toggle Overlay")
        overlay_action.triggered.connect(self._toggle_overlay)
        self._add_display_menu(view_menu)
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
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)
        logo_label = QLabel()
        logo = QPixmap(str(ICONS_DIR / "app_icon_48.png"))
        if not logo.isNull():
            logo_label.setPixmap(logo)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(0)
        title_label = QLabel(APP_BRAND)
        title_label.setObjectName("TitleLabel")
        subtitle_label = QLabel(APP_SUBTITLE)
        subtitle_label.setStyleSheet("color: #b56cff; font-size: 12px; font-weight: 600;")
        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        header.addWidget(logo_label)
        header.addLayout(title_layout, 1)
        root_layout.addLayout(header)

        selector_layout = QHBoxLayout()
        self._game_combo = QComboBox()
        self._game_combo.setPlaceholderText("Add a game: pick its .exe")
        self._game_combo.currentIndexChanged.connect(self._on_game_changed)
        self._boss_combo = QComboBox()
        self._boss_combo.currentIndexChanged.connect(self._on_boss_changed)
        selector_layout.addWidget(self._labeled("Game", self._game_combo))
        selector_layout.addWidget(self._labeled("Boss", self._boss_combo))
        root_layout.addLayout(selector_layout)

        detect_layout = QHBoxLayout()
        detect_text_layout = QVBoxLayout()
        detect_text_layout.setSpacing(2)
        self._detect_status_label = QLabel("Auto-detect off")
        self._detect_status_label.setWordWrap(True)
        self._detect_last_label = QLabel("")
        self._detect_last_label.setStyleSheet("color: #999999; font-size: 11px;")
        detect_text_layout.addWidget(self._detect_status_label)
        detect_text_layout.addWidget(self._detect_last_label)
        death_screen_button = QPushButton("📷 Death Screen…")
        death_screen_button.setToolTip(
            "A death wasn't counted? Pick the death screen from the last few seconds "
            "(or a screenshot) so the app recognizes it next time."
        )
        death_screen_button.clicked.connect(self._open_death_screen_dialog)
        detect_button = QPushButton("Auto-Detect…")
        detect_button.clicked.connect(self._open_auto_detect_window)
        self._pause_btn = QPushButton("⏸ Pause")
        self._pause_btn.clicked.connect(self._toggle_detection_pause)
        detect_layout.addLayout(detect_text_layout, 1)
        detect_layout.addWidget(self._pause_btn)
        detect_layout.addWidget(death_screen_button)
        detect_layout.addWidget(detect_button)
        root_layout.addLayout(detect_layout)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._counter_label = QLabel("0")
        self._counter_label.setObjectName("CounterLabel")
        self._counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._sub_counter_label = QLabel("Session: 0   |   Boss: 0   |   Total: 0")
        self._sub_counter_label.setObjectName("SubCounterLabel")
        self._sub_counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        set_count_btn = QPushButton("Set Exact Count…")
        set_count_btn.clicked.connect(self._on_set_count)

        card_layout.addWidget(self._counter_label)
        card_layout.addWidget(self._sub_counter_label)
        card_layout.addWidget(set_count_btn)
        root_layout.addWidget(card)

        action_layout = QHBoxLayout()
        # Labels get the current hotkeys from _update_hotkey_labels().
        self._plus_btn = QPushButton()
        self._plus_btn.setObjectName("AccentButton")
        self._plus_btn.clicked.connect(self._on_increment)
        self._minus_btn = QPushButton()
        self._minus_btn.clicked.connect(self._on_decrement)
        self._undo_btn = QPushButton()
        self._undo_btn.clicked.connect(self._on_undo)
        action_layout.addWidget(self._plus_btn)
        action_layout.addWidget(self._minus_btn)
        action_layout.addWidget(self._undo_btn)
        root_layout.addLayout(action_layout)

        reset_layout = QGridLayout()
        reset_session_btn = QPushButton("Reset Session")
        reset_session_btn.setObjectName("DangerButton")
        reset_session_btn.clicked.connect(self._on_reset_session)
        reset_total_btn = QPushButton("Reset Total")
        reset_total_btn.setObjectName("DangerButton")
        reset_total_btn.clicked.connect(self._on_reset_total)
        reset_layout.addWidget(reset_session_btn, 0, 0)
        reset_layout.addWidget(reset_total_btn, 0, 1)
        root_layout.addLayout(reset_layout)

        root_layout.addStretch()

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

    def _setup_hotkeys(self) -> None:
        self._action_handlers = {
            "increment": self._on_increment,
            "decrement": self._on_decrement,
            "undo": self._on_undo,
            "toggle_overlay": self._toggle_overlay,
            "calibrate": self._on_calibrate_hotkey,
            "pause_detection": self._toggle_detection_pause,
        }
        bindings = self._hotkey_bindings()
        self._hotkey_manager = HotkeyManager(**bindings, parent=self)
        self._hotkey_manager.increment_triggered.connect(self._on_increment)
        self._hotkey_manager.decrement_triggered.connect(self._on_decrement)
        self._hotkey_manager.undo_triggered.connect(self._on_undo)
        self._hotkey_manager.toggle_overlay_triggered.connect(self._toggle_overlay)
        self._hotkey_manager.calibrate_triggered.connect(self._on_calibrate_hotkey)
        self._hotkey_manager.pause_detection_triggered.connect(self._toggle_detection_pause)
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
        labels = {
            "increment": "+1 Death",
            "decrement": "-1 Death",
            "undo": "Undo",
            "toggle_overlay": "Toggle Overlay",
            "calibrate": "Calibrate Death Screen",
            "pause_detection": "Pause Auto-Detect",
        }
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
        self._death_watcher.start()
        # Switch to a configured game automatically when its exe starts.
        self._running_game_ids: set[int] = set()
        self._game_launch_timer = QTimer(self)
        self._game_launch_timer.setInterval(_GAME_LAUNCH_POLL_MS)
        self._game_launch_timer.timeout.connect(self._check_game_launches)
        if detection_available():
            self._game_launch_timer.start()

    def _configure_detection(self) -> None:
        """Point the watcher at the current game's detection config, if any."""
        game_id = self._counter_manager.current_game_id
        row = self._database.get_game_detection(game_id) if game_id is not None else None
        if (
            game_id is None
            or row is None
            or not row["exe_path"]
            or row["mode"] == DETECTION_MODE_OFF
            or not detection_available()
        ):
            self._death_watcher.configure(None)
            self._detect_status_label.setText(
                "Auto-detect needs Windows" if not detection_available() else "Auto-detect off"
            )
            return
        if self._detection_paused:
            self._death_watcher.configure(None)
            self._detect_status_label.setText("Auto-detect paused")
            return
        templates = [
            (t["region"], t["template"]) for t in self._database.get_death_templates(game_id)
        ]
        # A None matcher still watches the window, buffering recent frames so
        # the player can pick their first death screen with 📷 Death Screen.
        matcher = build_matcher(row["mode"], templates)
        cooldown = float(self._database.get_setting(SETTING_DETECTION_COOLDOWN, "8") or 8)
        self._death_watcher.configure(
            WatchConfig(game_id=game_id, exe_path=row["exe_path"], matcher=matcher),
            cooldown_seconds=cooldown,
        )

    def _toggle_detection_pause(self) -> None:
        self._detection_paused = not self._detection_paused
        self._pause_btn.setText("▶ Resume" if self._detection_paused else "⏸ Pause")
        self._configure_detection()
        if self._tray is not None:  # the hotkey is usually pressed in-game
            self._tray.showMessage(
                APP_BRAND,
    APP_NAME,
    APP_SUBTITLE,
    CONTROL_ACTIONS,
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
    APP_NAME,
    APP_SUBTITLE,
    CONTROL_ACTIONS,
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
        apply_theme(self, settings.get(SETTING_THEME, "dark"))
        self._overlay.apply_display_settings(settings)
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
    APP_NAME,
    APP_SUBTITLE,
    CONTROL_ACTIONS,
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

    # ----------------------------------------------------------------
    # Counter actions
    # ----------------------------------------------------------------
    def _on_increment(self) -> None:
        self._apply_snapshot(self._counter_manager.increment())

    def _on_decrement(self) -> None:
        self._apply_snapshot(self._counter_manager.decrement())

    def _on_undo(self) -> None:
        self._apply_snapshot(self._counter_manager.undo())

    def _on_reset_session(self) -> None:
        confirm = QMessageBox.question(self, "Reset Session", "Reset the current session count?")
        if confirm == QMessageBox.StandardButton.Yes:
            self._apply_snapshot(self._counter_manager.reset_session())

    def _on_reset_total(self) -> None:
        confirm = QMessageBox.question(
            self, "Reset Total", "Reset the TOTAL death count for this game? This cannot be undone."
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._apply_snapshot(self._counter_manager.reset_total())

    def _on_set_count(self) -> None:
        if self._counter_manager.current_game_id is None:
            QMessageBox.information(self, "Select a Game", "Select a game first.")
            return
        snapshot = self._counter_manager.get_snapshot()
        target, ok = QInputDialog.getInt(
            self,
            "Set Exact Session Count",
            "New session death count:",
            value=snapshot.session_deaths,
            minValue=0,
            maxValue=999_999,
        )
        if not ok:
            return
        self._apply_snapshot(self._counter_manager.set_session_count(target))

    def _refresh_counters(self) -> None:
        self._apply_snapshot(self._counter_manager.get_snapshot())

    def _apply_snapshot(self, snapshot: CounterSnapshot) -> None:
        self._counter_label.setText(str(snapshot.session_deaths))
        self._sub_counter_label.setText(
            f"Session: {snapshot.session_deaths}   |   "
            f"Boss: {snapshot.boss_deaths}   |   Total: {snapshot.total_deaths}"
        )
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
            self._database, game_id, self._game_combo.currentText(), parent=self
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

    def _on_screen_removed(self, _screen: QScreen) -> None:
        # Let Qt finish re-laying out the remaining displays first.
        QTimer.singleShot(500, self._keep_windows_on_screen)

    def closeEvent(self, event) -> None:  # noqa: N802
        """Minimize to tray if configured; otherwise clean up and exit."""
        minimize = (
            self._database.get_setting(SETTING_MINIMIZE_TO_TRAY, "false") == "true"
        )
        if minimize and not self._quitting and self._tray is not None:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                APP_BRAND,
    APP_NAME,
    APP_SUBTITLE,
    CONTROL_ACTIONS,
                "Still running in the tray — hotkeys stay active. Right-click to quit.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            return

        self._database.set_setting(SETTING_OVERLAY_GEOMETRY, self._overlay.geometry_string())
        self._database.set_setting(
            SETTING_MAIN_WINDOW_GEOMETRY, bytes(self.saveGeometry().toBase64()).decode("ascii")
        )
        self._session_manager.end_current_session()
        self._hotkey_manager.stop()
        self._gamepad_manager.stop()
        self._death_watcher.stop()
        self._overlay.close()
        if self._tray is not None:
            self._tray.hide()
        self._database.close()
        logger.info("Application closed cleanly")
        super().closeEvent(event)
