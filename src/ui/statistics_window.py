"""
Statistics window: text summary plus interactive charts.

Uses Qt Charts (bundled with PySide6-Addons — no extra dependency like
matplotlib needed) to render three views of the event-sourced death data:

* Deaths per Boss   — bar chart
* Deaths over Time  — cumulative line chart by day
* Sessions          — per-session death counts, oldest to newest
"""

from __future__ import annotations

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QDateTimeAxis,
    QLineSeries,
    QValueAxis,
)
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QLabel, QTabWidget, QVBoxLayout

from src.core.statistics import StatisticsService
from src.database.database import Database
from src.utils.constants import ACCENT_COLOR
from src.utils.logger import get_logger

logger = get_logger(__name__)

_TEXT_COLOR = QColor("#e8e8e8")
_ACCENT = QColor(ACCENT_COLOR)
_MAX_BOSSES_IN_CHART = 12
_MAX_SESSIONS_IN_CHART = 20


class StatisticsWindow(QDialog):
    """Tabbed statistics dialog for the currently selected game."""

    def __init__(
        self,
        database: Database,
        statistics_service: StatisticsService,
        game_id: int | None,
        game_name: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._database = database
        self._stats = statistics_service
        self._game_id = game_id
        self._game_name = game_name

        self.setWindowTitle(f"Statistics — {game_name or 'All Games'}")
        self.setMinimumSize(640, 460)
        self._build_ui()

    # ----------------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_summary_tab(), "Summary")
        if self._game_id is not None:
            tabs.addTab(self._build_boss_chart_tab(), "Deaths per Boss")
            tabs.addTab(self._build_timeline_tab(), "Deaths over Time")
            tabs.addTab(self._build_sessions_tab(), "Sessions")
        layout.addWidget(tabs)

    def _build_summary_tab(self) -> QLabel:
        global_stats = self._stats.get_global_statistics()
        lines = [
            f"Total Deaths (All Games): {global_stats.total_deaths_all_games}",
            f"Most Played Game: {global_stats.most_played_game or 'N/A'} "
            f"({global_stats.most_played_game_sessions} sessions)",
            f"Total Play Sessions: {global_stats.total_play_sessions}",
        ]

        if self._game_id is not None:
            game_stats = self._stats.get_game_statistics(self._game_id)
            lines += [
                "",
                f"— {self._game_name} —",
                f"Total Deaths: {game_stats.total_deaths}",
                f"Most Deaths On: {game_stats.most_deaths_boss or 'N/A'} "
                f"({game_stats.most_deaths_count})",
                f"Least Deaths On: {game_stats.least_deaths_boss or 'N/A'} "
                f"({game_stats.least_deaths_count})",
                f"Average Deaths Per Boss: {game_stats.average_deaths_per_boss}",
                f"Total Runs: {game_stats.total_runs}",
            ]

            defeated = [
                boss
                for boss in self._database.get_bosses(self._game_id)
                if boss["defeated"]
            ]
            if defeated:
                lines.append("")
                lines.append("Victories (deaths until victory):")
                for boss in defeated:
                    lines.append(f"  ✓ {boss['name']} — {boss['deaths_at_defeat']} death(s)")

        label = QLabel("\n".join(lines))
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        label.setContentsMargins(16, 16, 16, 16)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    # ----------------------------------------------------------------
    # Charts
    # ----------------------------------------------------------------
    def _style_chart(self, chart: QChart) -> None:
        """Apply a dark, minimal look consistent with the app theme."""
        chart.setBackgroundBrush(Qt.BrushStyle.NoBrush)
        chart.setTitleBrush(_TEXT_COLOR)
        chart.legend().setVisible(False)

    def _make_view(self, chart: QChart) -> QChartView:
        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setStyleSheet("background: transparent;")
        return view

    def _build_boss_chart_tab(self) -> QChartView:
        totals = self._database.get_boss_death_totals(self._game_id)[:_MAX_BOSSES_IN_CHART]

        bar_set = QBarSet("Deaths")
        bar_set.setColor(_ACCENT)
        categories: list[str] = []
        max_value = 1
        for row in totals:
            bar_set.append(int(row["total"]))
            # Truncate long boss names so category labels stay readable.
            name = row["name"]
            categories.append(name if len(name) <= 14 else name[:12] + "…")
            max_value = max(max_value, int(row["total"]))

        series = QBarSeries()
        series.append(bar_set)

        chart = QChart()
        chart.setTitle("Deaths per Boss")
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories or ["No bosses"])
        axis_x.setLabelsColor(_TEXT_COLOR)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setRange(0, max_value * 1.1)
        axis_y.setLabelFormat("%d")
        axis_y.setLabelsColor(_TEXT_COLOR)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        self._style_chart(chart)
        return self._make_view(chart)

    def _build_timeline_tab(self) -> QChartView:
        daily = self._database.get_deaths_per_day(self._game_id)

        series = QLineSeries()
        series.setColor(_ACCENT)
        cumulative = 0
        max_value = 1
        for row in daily:
            cumulative += int(row["deaths"])
            max_value = max(max_value, cumulative)
            moment = QDateTime.fromString(f"{row['day']}T00:00:00", Qt.DateFormat.ISODate)
            series.append(float(moment.toMSecsSinceEpoch()), float(cumulative))

        chart = QChart()
        chart.setTitle("Cumulative Deaths over Time")
        chart.addSeries(series)

        axis_x = QDateTimeAxis()
        axis_x.setFormat("MMM d")
        axis_x.setLabelsColor(_TEXT_COLOR)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setRange(0, max_value * 1.1)
        axis_y.setLabelFormat("%d")
        axis_y.setLabelsColor(_TEXT_COLOR)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        self._style_chart(chart)
        return self._make_view(chart)

    def _build_sessions_tab(self) -> QChartView:
        sessions = self._database.get_sessions_with_counts(self._game_id)
        # Newest-first from the DB; show oldest → newest left to right.
        sessions = list(reversed(sessions))[-_MAX_SESSIONS_IN_CHART:]

        bar_set = QBarSet("Deaths")
        bar_set.setColor(_ACCENT)
        categories: list[str] = []
        max_value = 1
        for index, row in enumerate(sessions, start=1):
            deaths = int(row["deaths"])
            bar_set.append(deaths)
            categories.append(f"#{index}")
            max_value = max(max_value, deaths)

        series = QBarSeries()
        series.append(bar_set)

        chart = QChart()
        chart.setTitle("Deaths per Session (oldest → newest)")
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories or ["No sessions"])
        axis_x.setLabelsColor(_TEXT_COLOR)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setRange(0, max_value * 1.1)
        axis_y.setLabelFormat("%d")
        axis_y.setLabelsColor(_TEXT_COLOR)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        self._style_chart(chart)
        return self._make_view(chart)
