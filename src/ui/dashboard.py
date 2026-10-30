"""
The Home page's dashboard pieces: the skull badge, the week chart, the boss
ring and the "getting started" banner.

The charts are painted directly (no chart library): a handful of rounded
rectangles and arcs, repainted only when their numbers change. Colors come
from the theme through :func:`set_colors`, like the icons.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.ui import icons
from src.ui.skulls import TIERS, next_tier, skull_pixmap, tier_index

_colors = {"text": "#ececf1", "muted": "#7d8290", "accent": "#ff3d55", "track": "#262833"}


def set_colors(text: str, muted: str, accent: str, light: bool) -> None:
    """Theme colors for everything painted here (call before refreshing)."""
    track = QColor(text)
    track.setAlphaF(0.10 if light else 0.08)
    _colors.update(
        text=text, muted=muted, accent=accent, track=track.name(QColor.NameFormat.HexArgb)
    )


def color(name: str) -> str:
    return _colors[name]


class SkullBadge(QWidget):
    """The evolving skull, its rank, and how far it is to the next one."""

    SIZE = 112

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._count = 0
        self._shown: QPixmap | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._art = QLabel()
        self._art.setFixedSize(self.SIZE, self.SIZE)
        self._name = QLabel()
        self._name.setObjectName("TierName")
        self._name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bar = QProgressBar()
        self._bar.setObjectName("TierProgress")
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 1000)
        self._bar.setFixedHeight(6)
        self._hint = QLabel()
        self._hint.setObjectName("TierHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._art, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._name)
        layout.addWidget(self._bar)
        layout.addWidget(self._hint)
        self.setFixedWidth(150)
        self.set_count(0)

    def set_count(self, count: int) -> None:
        self._count = count
        tier = TIERS[tier_index(count)]
        self._name.setText(tier.name)
        upcoming, progress = next_tier(count)
        self._bar.setValue(round(progress * 1000))
        if upcoming is None:
            self._hint.setText("Final form")
            self.setToolTip(f"{tier.name}: the last skull. Legendary.")
        else:
            left = upcoming.deaths - max(count, 0)
            self._hint.setText(f"{left} more to {upcoming.name}")
            self.setToolTip(
                f"Your skull evolves as deaths pile up: {tier.name} now, "
                f"{upcoming.name} at {upcoming.deaths}."
            )
        self.refresh_art()

    def refresh_art(self) -> None:
        """Redraw in the theme's colors (cached per tier and color)."""
        art = skull_pixmap(
            self._count, self.SIZE, _colors["text"], _colors["accent"], self.devicePixelRatioF()
        )
        if art is not self._shown:  # a new tier or theme, not every death
            self._shown = art
            self._art.setPixmap(art)


class WeekChart(QWidget):
    """Seven rounded bars, one per day; today's is lit."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._days: list[tuple[str, int, bool]] = []
        self.setMinimumHeight(132)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_days(self, days: list[tuple[str, int, bool]]) -> None:
        """(label, deaths, is today) for each day, oldest first."""
        if days != self._days:
            self._days = days
            self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, 150)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._days:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        label_height, value_height = 18, 16
        top = value_height + 2
        chart_height = self.height() - top - label_height - 4
        slot = self.width() / len(self._days)
        bar_width = min(slot * 0.56, 34)
        peak = max(1, max(count for _, count, _ in self._days))
        muted, accent = QColor(_colors["muted"]), QColor(_colors["accent"])
        for index, (label, count, today) in enumerate(self._days):
            x = index * slot + (slot - bar_width) / 2
            track = QRectF(x, top, bar_width, chart_height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(_colors["track"]))
            painter.drawRoundedRect(track, 7, 7)
            height = max(count, 0) / peak * chart_height
            if height > 0:
                bar = QRectF(x, top + chart_height - height, bar_width, height)
                fill = QColor(accent)
                if not today:
                    fill.setAlphaF(0.55)
                painter.setBrush(fill)
                painter.drawRoundedRect(bar, 7, 7)
            if count > 0 and (today or count == peak):
                painter.setPen(QColor(_colors["text"]))
                painter.drawText(
                    QRectF(x - 10, top + chart_height - height - value_height - 2,
                           bar_width + 20, value_height),
                    Qt.AlignmentFlag.AlignCenter, str(count),
                )
            painter.setPen(QColor(_colors["text"]) if today else muted)
            painter.drawText(
                QRectF(index * slot, top + chart_height + 4, slot, label_height),
                Qt.AlignmentFlag.AlignCenter, label,
            )
        painter.end()


class ProgressRing(QWidget):
    """A ring that fills as bosses fall, with "3/12" in the middle."""

    def __init__(self, diameter: int = 112, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._done = 0
        self._total = 0
        self.setFixedSize(diameter, diameter)

    def set_values(self, done: int, total: int) -> None:
        if (done, total) != (self._done, self._total):
            self._done, self._total = done, total
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        thickness = 11
        area = QRectF(self.rect()).adjusted(thickness, thickness, -thickness, -thickness)
        pen = QPen(QColor(_colors["track"]), thickness)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(area, 0, 360 * 16)
        if self._total and self._done:
            pen.setColor(QColor(_colors["accent"]))
            painter.setPen(pen)
            painter.drawArc(area, 90 * 16, -round(360 * 16 * self._done / self._total))
        font = QFont(self.font())
        font.setPixelSize(22)
        font.setWeight(QFont.Weight.Black)
        painter.setFont(font)
        painter.setPen(QColor(_colors["text"]))
        number = QRectF(
            area.x(), area.y() + area.height() * 0.18, area.width(), area.height() * 0.42
        )
        painter.drawText(number, Qt.AlignmentFlag.AlignCenter,
                         f"{self._done}/{self._total}" if self._total else "–")
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        painter.setFont(font)
        painter.setPen(QColor(_colors["muted"]))
        caption = QRectF(area.x(), number.bottom(), area.width(), area.height() * 0.22)
        painter.drawText(caption, Qt.AlignmentFlag.AlignCenter, "BEATEN")
        painter.end()


class BossRanking(QWidget):
    """The bosses that killed you most: name, count, and a bar for each."""

    ROWS = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, int]] = []
        self._empty = ""
        self.setMinimumHeight(self.ROWS * 34 + 20)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_rows(self, rows: list[tuple[str, int]], empty: str = "") -> None:
        """Up to three (boss, deaths) rows, worst first; ``empty`` shows when there are none."""
        rows = rows[: self.ROWS]
        if (rows, empty) != (self._rows, self._empty):
            self._rows, self._empty = rows, empty
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        painter.setFont(font)
        painter.setPen(QColor(_colors["muted"]))
        width = self.width()
        painter.drawText(QRectF(0, 0, width, 16), Qt.AlignmentFlag.AlignLeft, "TOUGHEST")
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
        font.setPixelSize(13)
        if not self._rows:
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            painter.drawText(
                QRectF(0, 22, width, self.height() - 22),
                Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, self._empty,
            )
            painter.end()
            return
        peak = max(count for _, count in self._rows)
        metrics_font = QFont(font)
        for index, (name, count) in enumerate(self._rows):
            y = 22 + index * 34
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor(_colors["muted"]))
            count_text = str(count)
            painter.drawText(QRectF(0, y, width, 18), Qt.AlignmentFlag.AlignRight, count_text)
            room = width - painter.fontMetrics().horizontalAdvance(count_text) - 10
            metrics_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(metrics_font)
            painter.setPen(QColor(_colors["text"]))
            elided = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, room)
            painter.drawText(QRectF(0, y, room, 18), Qt.AlignmentFlag.AlignLeft, elided)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(_colors["track"]))
            painter.drawRoundedRect(QRectF(0, y + 21, width, 5), 2.5, 2.5)
            fill = QColor(_colors["accent"])
            fill.setAlphaF(1.0 if index == 0 else 0.6)
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(0, y + 21, max(width * count / peak, 5), 5), 2.5, 2.5)
        painter.end()


class StartBanner(QFrame):
    """"Getting started · 2 of 5": opens the guide; hides once everything's done."""

    clicked = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StartBanner")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 14, 12)
        layout.setSpacing(14)
        self._icon = QLabel()
        self._icon.setObjectName("StartBannerIcon")
        self._icon.setFixedSize(38, 38)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        self._title = QLabel()
        self._title.setObjectName("StartBannerTitle")
        self._next = QLabel()
        self._next.setObjectName("Muted")
        self._bar = QProgressBar()
        self._bar.setObjectName("TierProgress")
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(5)
        texts.addWidget(self._title)
        texts.addWidget(self._next)
        texts.addWidget(self._bar)
        self.button = QPushButton("Continue ")
        self.button.setObjectName("AccentButton")
        self.button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        icons.set_icon(self.button, "chevron-right", icons.ACCENT, size=16)
        self.button.clicked.connect(self.clicked)
        close = QPushButton()
        close.setObjectName("IconButton")
        close.setToolTip("Hide this (the ? at the top still opens the guide)")
        icons.set_icon(close, "x", size=16)
        close.clicked.connect(self.dismissed)
        layout.addWidget(self._icon)
        layout.addLayout(texts, 1)
        layout.addWidget(self.button)
        layout.addWidget(close)
        self.refresh_icon()

    def set_progress(self, done: int, total: int, next_step: str) -> None:
        self._title.setText(f"Getting started  ·  {done} of {total} done")
        self._next.setText(f"Next: {next_step}")
        self._bar.setRange(0, total)
        self._bar.setValue(done)

    def refresh_icon(self) -> None:
        self._icon.setPixmap(icons.pixmap("rocket", _colors["accent"], 20))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)
