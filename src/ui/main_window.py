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

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
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
from src.detection.game_window import capture_game_frame, detection_available
from src.detection.matchers import build_matcher
from src.hotkeys.hotkey_manager import HotkeyManager
from src.overlay.overlay_window import OverlayWindow
from src.themes.theme_manager import apply_theme
from src.ui.about_window import AboutWindow
from src.ui.auto_detect_window import AutoDetectWindow, CalibrationDialog
from src.ui.boss_window import BossWindow
from src.ui.death_log_window import DeathLogWindow
from src.ui.settings_window import SettingsWindow
from src.ui.statistics_window import StatisticsWindow
from src.utils.constants import (
    APP_NAME,
    DEFAULT_HOTKEY_TOGGLE_OVERLAY,
    DETECTION_MODE_TEMPLATE,
    ICONS_DIR,
    SAVES_DIR,
    SETTING_CHECK_UPDATES,
    SETTING_DEATHS_TXT_ENABLED,
    SETTING_DEATHS_TXT_PATH,
    SETTING_DEATHS_TXT_TEMPLATE,
    SETTING_DETECTION_COOLDOWN,
    SETTING_HOTKEY_CALIBRATE,
    SETTING_HOTKEY_DECREMENT,
    SETTING_HOTKEY_INCREMENT,
    SETTING_HOTKEY_TOGGLE_OVERLAY,
    SETTING_HOTKEY_UNDO,
    SETTING_MINIMIZE_TO_TRAY,
    SETTING_OVERLAY_ALWAYS_ON_TOP,
    SETTING_OVERLAY_COUNTER_SOURCE,
    SETTING_OVERLAY_GEOMETRY,
    SETTING_THEME,
)
from src.utils.exporters import write_csv_summary
from src.utils.logger import get_logger
from src.utils.profiles import DEFAULT_PROFILE_NAME, ProfileManager
from src.utils.stream_writer import render_template, write_deaths_file
from src.utils.update_checker import UpdateChecker

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    """The application's primary window."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(480, 460)

        icon_path = ICONS_DIR / "app_icon.png"
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
        self._quitting = False

        self._update_window_title()
        self._build_menu()
        self._build_ui()
        self._build_tray()
        self._setup_hotkeys()
        self._setup_death_watcher()
        self._apply_saved_settings()
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
        stats_action = view_menu.addAction("Statistics && Graphs…")
        stats_action.triggered.connect(self._show_statistics)
        log_action = view_menu.addAction("Death Log…")
        log_action.triggered.connect(self._open_death_log)

        settings_menu = menu_bar.addMenu("&Settings")
        settings_action = settings_menu.addAction("Preferences…")
        settings_action.triggered.connect(self._open_settings_window)

        help_menu = menu_bar.addMenu("&Help")
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

        title_label = QLabel(APP_NAME)
        title_label.setObjectName("TitleLabel")
        root_layout.addWidget(title_label)

        selector_layout = QHBoxLayout()
        self._game_combo = QComboBox()
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
        detect_button = QPushButton("Auto-Detect…")
        detect_button.clicked.connect(self._open_auto_detect_window)
        detect_layout.addLayout(detect_text_layout, 1)
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
        plus_btn = QPushButton("+1 Death  (F9)")
        plus_btn.setObjectName("AccentButton")
        plus_btn.clicked.connect(self._on_increment)
        minus_btn = QPushButton("-1 Death  (F10)")
        minus_btn.clicked.connect(self._on_decrement)
        undo_btn = QPushButton("Undo  (F11)")
        undo_btn.clicked.connect(self._on_undo)
        action_layout.addWidget(plus_btn)
        action_layout.addWidget(minus_btn)
        action_layout.addWidget(undo_btn)
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
    def _setup_hotkeys(self) -> None:
        settings = self._database.get_all_settings()
        self._hotkey_manager = HotkeyManager(
            increment_key=settings.get(SETTING_HOTKEY_INCREMENT, "f9"),
            decrement_key=settings.get(SETTING_HOTKEY_DECREMENT, "f10"),
            undo_key=settings.get(SETTING_HOTKEY_UNDO, "f11"),
            toggle_overlay_key=settings.get(
                SETTING_HOTKEY_TOGGLE_OVERLAY, DEFAULT_HOTKEY_TOGGLE_OVERLAY
            ),
            calibrate_key=settings.get(SETTING_HOTKEY_CALIBRATE, "f8"),
            parent=self,
        )
        self._hotkey_manager.increment_triggered.connect(self._on_increment)
        self._hotkey_manager.decrement_triggered.connect(self._on_decrement)
        self._hotkey_manager.undo_triggered.connect(self._on_undo)
        self._hotkey_manager.toggle_overlay_triggered.connect(self._toggle_overlay)
        self._hotkey_manager.calibrate_triggered.connect(self._on_calibrate_hotkey)
        self._hotkey_manager.registration_failed.connect(self._on_hotkeys_failed)
        self._hotkey_manager.start()

    def _on_hotkeys_failed(self, failures: list) -> None:
        labels = {
            "increment": "+1 Death",
            "decrement": "-1 Death",
            "undo": "Undo",
            "toggle_overlay": "Toggle Overlay",
            "calibrate": "Calibrate Death Screen",
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

    def _configure_detection(self) -> None:
        """Point the watcher at the current game's detection config, if any."""
        game_id = self._counter_manager.current_game_id
        row = self._database.get_game_detection(game_id) if game_id is not None else None
        matcher = (
            build_matcher(row["mode"], row["region"], row["template"]) if row is not None else None
        )
        if game_id is None or row is None or not row["exe_path"] or matcher is None:
            self._death_watcher.configure(None)
            if not detection_available():
                status = "Auto-detect needs Windows"
            elif row is not None and row["mode"] == DETECTION_MODE_TEMPLATE and matcher is None:
                hotkey = self._database.get_setting(SETTING_HOTKEY_CALIBRATE, "f8").upper()
                status = f"Auto-detect: press {hotkey} on the death screen to calibrate"
            else:
                status = "Auto-detect off"
            self._detect_status_label.setText(status)
            return
        cooldown = float(self._database.get_setting(SETTING_DETECTION_COOLDOWN, "8") or 8)
        self._death_watcher.configure(
            WatchConfig(game_id=game_id, exe_path=row["exe_path"], matcher=matcher),
            cooldown_seconds=cooldown,
        )

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
        self._database.set_game_death_template(
            game_id, dialog.template.region_json(), dialog.template.patch_bytes()
        )
        self._database.set_game_detection(game_id, exe_path, DETECTION_MODE_TEMPLATE)
        self._configure_detection()
        if not exe_path:
            self._open_auto_detect_window()

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
                APP_NAME,
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
    def _reload_games(self) -> None:
        self._game_combo.blockSignals(True)
        self._game_combo.clear()
        games = self._database.get_games()
        for game in games:
            self._game_combo.addItem(game["name"], userData=game["id"])
        self._game_combo.blockSignals(False)
        if games:
            self._game_combo.setCurrentIndex(0)
            self._on_game_changed(0)
        else:
            self._counter_manager.set_current_game(None, None)
            self._reload_bosses(None)
            self._refresh_counters()
            self._configure_detection()

    def _reload_bosses(self, game_id: int | None) -> None:
        self._boss_combo.blockSignals(True)
        self._boss_combo.clear()
        self._boss_combo.addItem("(No Boss)", userData=None)
        if game_id is not None:
            for boss in self._database.get_bosses(game_id):
                prefix = "✓ " if boss["defeated"] else ""
                self._boss_combo.addItem(f"{prefix}{boss['name']}", userData=boss["id"])
        self._boss_combo.blockSignals(False)
        self._on_boss_changed(0)

    # ----------------------------------------------------------------
    # Selector event handlers
    # ----------------------------------------------------------------
    def _on_game_changed(self, index: int) -> None:
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
            boss_name = None
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

    def _write_deaths_txt(self, snapshot: CounterSnapshot) -> None:
        if self._database.get_setting(SETTING_DEATHS_TXT_ENABLED, "false") != "true":
            return
        raw_path = self._database.get_setting(SETTING_DEATHS_TXT_PATH, "").strip()
        path = Path(raw_path) if raw_path else SAVES_DIR / "deaths.txt"
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
        dialog = SettingsWindow(self._database, parent=self)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.exec()

    def _open_about_window(self) -> None:
        AboutWindow(parent=self).exec()

    def _on_settings_changed(self) -> None:
        self._apply_saved_settings()
        self._on_settings_changed_hotkeys()
        self._refresh_counters()

    def _on_settings_changed_hotkeys(self) -> None:
        settings = self._database.get_all_settings()
        self._hotkey_manager.update_bindings(
            increment_key=settings.get(SETTING_HOTKEY_INCREMENT, "f9"),
            decrement_key=settings.get(SETTING_HOTKEY_DECREMENT, "f10"),
            undo_key=settings.get(SETTING_HOTKEY_UNDO, "f11"),
            toggle_overlay_key=settings.get(
                SETTING_HOTKEY_TOGGLE_OVERLAY, DEFAULT_HOTKEY_TOGGLE_OVERLAY
            ),
            calibrate_key=settings.get(SETTING_HOTKEY_CALIBRATE, "f8"),
        )

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

    def closeEvent(self, event) -> None:  # noqa: N802
        """Minimize to tray if configured; otherwise clean up and exit."""
        minimize = (
            self._database.get_setting(SETTING_MINIMIZE_TO_TRAY, "false") == "true"
        )
        if minimize and not self._quitting and self._tray is not None:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                APP_NAME,
                "Still running in the tray — hotkeys stay active. Right-click to quit.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            return

        self._database.set_setting(SETTING_OVERLAY_GEOMETRY, self._overlay.geometry_string())
        self._session_manager.end_current_session()
        self._hotkey_manager.stop()
        self._death_watcher.stop()
        self._overlay.close()
        if self._tray is not None:
            self._tray.hide()
        self._database.close()
        logger.info("Application closed cleanly")
        super().closeEvent(event)
