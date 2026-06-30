"""
Main application window.

Wires together the database, core managers (counter/session/statistics),
hotkeys, overlay, and theme system into the primary user-facing UI.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.counter_manager import CounterManager, CounterSnapshot
from src.core.session_manager import SessionManager
from src.core.statistics import StatisticsService
from src.database.database import Database
from src.hotkeys.hotkey_manager import HotkeyManager
from src.overlay.overlay_window import OverlayWindow
from src.themes.theme_manager import apply_theme
from src.ui.about_window import AboutWindow
from src.ui.boss_window import BossWindow
from src.ui.settings_window import SettingsWindow
from src.utils.constants import (
    APP_NAME,
    ICONS_DIR,
    SETTING_HOTKEY_DECREMENT,
    SETTING_HOTKEY_INCREMENT,
    SETTING_HOTKEY_TOGGLE_OVERLAY,
    SETTING_HOTKEY_UNDO,
    SETTING_OVERLAY_ALWAYS_ON_TOP,
    SETTING_OVERLAY_FONT_SIZE,
    SETTING_OVERLAY_GEOMETRY,
    SETTING_OVERLAY_OPACITY,
    SETTING_THEME,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    """The application's primary window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(480, 420)

        icon_path = ICONS_DIR / "app_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # --- Core wiring ---
        self._database = Database()
        self._session_manager = SessionManager(self._database)
        self._counter_manager = CounterManager(self._database, self._session_manager)
        self._statistics_service = StatisticsService(self._database)
        self._overlay = OverlayWindow()

        self._build_menu()
        self._build_ui()
        self._setup_hotkeys()
        self._apply_saved_settings()
        self._reload_games()

    # ----------------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------------
    def _build_menu(self) -> None:
        menu_bar: QMenuBar = self.menuBar()

        manage_menu = menu_bar.addMenu("&Manage")
        manage_action = manage_menu.addAction("Games && Bosses…")
        manage_action.triggered.connect(self._open_boss_window)

        view_menu = menu_bar.addMenu("&View")
        self._overlay_action = view_menu.addAction("Toggle Overlay")
        self._overlay_action.triggered.connect(self._toggle_overlay)

        stats_action = view_menu.addAction("Show Statistics")
        stats_action.triggered.connect(self._show_statistics)

        settings_menu = menu_bar.addMenu("&Settings")
        settings_action = settings_menu.addAction("Preferences…")
        settings_action.triggered.connect(self._open_settings_window)

        help_menu = menu_bar.addMenu("&Help")
        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self._open_about_window)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(16)

        title_label = QLabel(APP_NAME)
        title_label.setObjectName("TitleLabel")
        root_layout.addWidget(title_label)

        # --- Selectors ---
        selector_layout = QHBoxLayout()
        self._game_combo = QComboBox()
        self._game_combo.currentIndexChanged.connect(self._on_game_changed)
        self._boss_combo = QComboBox()
        self._boss_combo.currentIndexChanged.connect(self._on_boss_changed)
        selector_layout.addWidget(self._labeled("Game", self._game_combo))
        selector_layout.addWidget(self._labeled("Boss", self._boss_combo))
        root_layout.addLayout(selector_layout)

        # --- Counter card ---
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._counter_label = QLabel("0")
        self._counter_label.setObjectName("CounterLabel")
        self._counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._sub_counter_label = QLabel("Session: 0   |   Total: 0")
        self._sub_counter_label.setObjectName("SubCounterLabel")
        self._sub_counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card_layout.addWidget(self._counter_label)
        card_layout.addWidget(self._sub_counter_label)
        root_layout.addWidget(card)

        # --- Primary action buttons ---
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

        # --- Reset buttons ---
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
    # Hotkeys
    # ----------------------------------------------------------------
    def _setup_hotkeys(self) -> None:
        settings = self._database.get_all_settings()
        self._hotkey_manager = HotkeyManager(
            increment_key=settings.get(SETTING_HOTKEY_INCREMENT, "f9"),
            decrement_key=settings.get(SETTING_HOTKEY_DECREMENT, "f10"),
            undo_key=settings.get(SETTING_HOTKEY_UNDO, "f11"),
            toggle_overlay_key=settings.get(SETTING_HOTKEY_TOGGLE_OVERLAY, "f12"),
            parent=self,
        )
        self._hotkey_manager.increment_triggered.connect(self._on_increment)
        self._hotkey_manager.decrement_triggered.connect(self._on_decrement)
        self._hotkey_manager.undo_triggered.connect(self._on_undo)
        self._hotkey_manager.toggle_overlay_triggered.connect(self._toggle_overlay)
        self._hotkey_manager.start()

    def _apply_saved_settings(self) -> None:
        settings = self._database.get_all_settings()
        apply_theme(self, settings.get(SETTING_THEME, "dark"))
        self._overlay.set_font_size(int(settings.get(SETTING_OVERLAY_FONT_SIZE, "24")))
        self._overlay.set_opacity_level(float(settings.get(SETTING_OVERLAY_OPACITY, "0.85")))
        self._overlay.set_always_on_top(
            settings.get(SETTING_OVERLAY_ALWAYS_ON_TOP, "true") == "true"
        )
        self._overlay.restore_geometry_string(settings.get(SETTING_OVERLAY_GEOMETRY, ""))

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
            self._refresh_counters()

    def _reload_bosses(self, game_id: int | None) -> None:
        self._boss_combo.blockSignals(True)
        self._boss_combo.clear()
        self._boss_combo.addItem("(No Boss)", userData=None)
        if game_id is not None:
            for boss in self._database.get_bosses(game_id):
                self._boss_combo.addItem(boss["name"], userData=boss["id"])
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

    def _on_boss_changed(self, index: int) -> None:
        boss_id = self._boss_combo.itemData(index)
        boss_name = self._boss_combo.itemText(index) if index > 0 else None
        self._counter_manager.set_current_boss(boss_id, boss_name)
        self._refresh_counters()

    # ----------------------------------------------------------------
    # Counter actions
    # ----------------------------------------------------------------
    def _on_increment(self) -> None:
        snapshot = self._counter_manager.increment()
        self._apply_snapshot(snapshot)

    def _on_decrement(self) -> None:
        snapshot = self._counter_manager.decrement()
        self._apply_snapshot(snapshot)

    def _on_undo(self) -> None:
        snapshot = self._counter_manager.undo()
        self._apply_snapshot(snapshot)

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

    def _refresh_counters(self) -> None:
        self._apply_snapshot(self._counter_manager.get_snapshot())

    def _apply_snapshot(self, snapshot: CounterSnapshot) -> None:
        self._counter_label.setText(str(snapshot.session_deaths))
        self._sub_counter_label.setText(
            f"Session: {snapshot.session_deaths}   |   Total: {snapshot.total_deaths}"
        )
        self._overlay.update_counters(
            snapshot.game_name, snapshot.boss_name, snapshot.session_deaths
        )

    # ----------------------------------------------------------------
    # Window / dialog actions
    # ----------------------------------------------------------------
    def _open_boss_window(self) -> None:
        dialog = BossWindow(self._database, parent=self)
        dialog.exec()
        self._reload_games()

    def _open_settings_window(self) -> None:
        dialog = SettingsWindow(self._database, parent=self)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.exec()

    def _open_about_window(self) -> None:
        AboutWindow(parent=self).exec()

    def _on_settings_changed(self) -> None:
        self._apply_saved_settings()
        settings = self._database.get_all_settings()
        self._hotkey_manager.update_bindings(
            increment_key=settings.get(SETTING_HOTKEY_INCREMENT, "f9"),
            decrement_key=settings.get(SETTING_HOTKEY_DECREMENT, "f10"),
            undo_key=settings.get(SETTING_HOTKEY_UNDO, "f11"),
            toggle_overlay_key=settings.get(SETTING_HOTKEY_TOGGLE_OVERLAY, "f12"),
        )

    def _toggle_overlay(self) -> None:
        self._overlay.toggle_visibility()

    def _show_statistics(self) -> None:
        game_id = self._counter_manager.current_game_id
        global_stats = self._statistics_service.get_global_statistics()

        lines = [
            f"Total Deaths (All Games): {global_stats.total_deaths_all_games}",
            f"Most Played Game: {global_stats.most_played_game or 'N/A'} "
            f"({global_stats.most_played_game_sessions} sessions)",
            f"Total Play Sessions: {global_stats.total_play_sessions}",
        ]

        if game_id is not None:
            game_stats = self._statistics_service.get_game_statistics(game_id)
            lines += [
                "",
                f"-- {self._game_combo.currentText()} --",
                f"Total Deaths: {game_stats.total_deaths}",
                f"Most Deaths On: {game_stats.most_deaths_boss or 'N/A'} "
                f"({game_stats.most_deaths_count})",
                f"Least Deaths On: {game_stats.least_deaths_boss or 'N/A'} "
                f"({game_stats.least_deaths_count})",
                f"Average Deaths Per Boss: {game_stats.average_deaths_per_boss}",
                f"Total Runs: {game_stats.total_runs}",
            ]

        QMessageBox.information(self, "Statistics", "\n".join(lines))

    # ----------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        """Persist overlay geometry and clean up resources on exit."""
        self._database.set_setting(SETTING_OVERLAY_GEOMETRY, self._overlay.geometry_string())
        self._session_manager.end_current_session()
        self._hotkey_manager.stop()
        self._overlay.close()
        self._database.close()
        logger.info("Application closed cleanly")
        super().closeEvent(event)
