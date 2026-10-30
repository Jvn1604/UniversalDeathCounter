"""
Small building blocks for the dashboard layout.

They only set object names and structure; the look comes from the theme
stylesheets (``src/themes/*.qss``), so both themes and the player's custom
colors and fonts apply to them automatically.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.ui import icons

# Words in a detection status that mean "working", "waiting" or "needs attention".
_ACTIVE_WORDS = ("watching",)
_WAITING_WORDS = ("waiting", "paused", "starting")
_WARNING_WORDS = ("black", "not responding", "needs", "error", "can't", "minimized", "stopped")
# The status dot: green = hooked, yellow = waiting, red = needs attention, grey = off.
_DOT_COLORS = {"active": "#3ad07a", "waiting": "#f5c84c", "warning": "#ff5c5c", "": "#7a7d88"}


class StatTile(QFrame):
    """A small card: a caption over one value (e.g. "THIS BOSS" / "12")."""

    def __init__(self, caption: str, value: str = "–", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatTile")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        self.caption = QLabel(caption.upper())
        self.caption.setObjectName("StatLabel")
        self.value = QLabel(value)
        self.value.setObjectName("StatValue")
        layout.addWidget(self.caption)
        layout.addWidget(self.value)

    def set_value(self, text: str, tooltip: str = "") -> None:
        self.value.setText(text)
        self.setToolTip(tooltip)


class StatusPill(QLabel):
    """
    A rounded status label that colors itself from its text.

    Mirrors (other labels) receive the same text, so one status shows on
    several pages while the code keeps setting a single label.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("StatusPill")
        self._mirrors: list[StatusPill] = []
        self._apply_state(text)
        # Room for the dot (QSS padding-left would be overwritten by themes).
        self.setIndent(14)

    def add_mirror(self, mirror: StatusPill) -> None:
        self._mirrors.append(mirror)
        mirror.setText(self.text())

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        super().setText(text)
        self._apply_state(text)
        for mirror in self._mirrors:
            mirror.setText(text)

    def _apply_state(self, text: str) -> None:
        lowered = text.lower()
        if any(word in lowered for word in _WARNING_WORDS):
            state = "warning"
        elif any(word in lowered for word in _ACTIVE_WORDS):
            state = "active"
        elif any(word in lowered for word in _WAITING_WORDS):
            state = "waiting"
        else:
            state = ""
        if self.property("state") != state:
            self.setProperty("state", state)
            self.style().unpolish(self)  # re-evaluate [state=...] selectors
            self.style().polish(self)


    def state(self) -> str:
        return self.property("state") or ""

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_DOT_COLORS.get(self.state(), _DOT_COLORS[""])))
        painter.drawEllipse(QRectF(13, self.height() / 2 - 4, 8, 8))
        painter.end()


class AutoHideLabel(QLabel):
    """A label that takes no space while it has no text."""

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        super().setText(text)
        self.setHidden(not text)


def nav_button(text: str, icon_name: str = "", checkable: bool = True) -> QPushButton:
    """A sidebar entry (checkable ones switch pages)."""
    button = QPushButton(f"  {text}")
    button.setObjectName("NavButton")
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        icons.set_icon(button, icon_name, icons.NAV, size=18)
    return button


class NavToggle(QPushButton):
    """A button for something that is on or off (the overlay), with an ON/OFF tag."""

    def __init__(
        self,
        text: str,
        icon_name: str,
        object_name: str = "NavButton",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(f"  {text}", parent)
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        in_sidebar = object_name == "NavButton"
        icons.set_icon(self, icon_name, icons.NAV if in_sidebar else icons.NORMAL, size=18)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 22 if in_sidebar else 10, 0)
        layout.addStretch()
        self._state = QLabel("OFF")
        self._state.setObjectName("NavState")
        self._state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._state, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_on(False)

    def set_compact(self, compact: bool) -> None:
        """Collapsed sidebar: no ON/OFF tag; the tooltip says it instead."""
        if not hasattr(self, "_tip"):
            self._tip = self.toolTip()
        self._compact = compact
        self._state.setVisible(not compact)
        self.set_on(self.is_on())

    def set_on(self, on: bool) -> None:
        if getattr(self, "_compact", False):
            self.setToolTip(f"Overlay: {'ON' if on else 'OFF'}\n{self._tip}")
        elif hasattr(self, "_tip"):
            self.setToolTip(self._tip)
        self._state.setText("ON" if on else "OFF")
        self._state.setProperty("on", "true" if on else "false")
        self._state.style().unpolish(self._state)
        self._state.style().polish(self._state)

    def is_on(self) -> bool:
        return self._state.text() == "ON"


class ActionButton(QPushButton):
    """
    A big button: icon, label, and its hotkey as a keycap chip.

    The label and key are child labels (a QPushButton can't style part of its
    text), so :meth:`text` returns the label and :meth:`key_text` the key.
    """

    def __init__(
        self, text: str, icon_name: str, role: str = icons.NORMAL, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(9)
        self._icon = QLabel()
        self._label = QLabel(text)
        self._label.setStyleSheet("font-size: 15px; font-weight: 700;")
        self._key = QLabel()
        self._key.setObjectName("KeyCap")
        for child in (self._icon, self._label, self._key):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addStretch()
        for child in (self._icon, self._label, self._key):
            layout.addWidget(child, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch()
        self._icon_name, self._role = icon_name, role
        self.refresh_icon()
        self.set_key("")

    def refresh_icon(self) -> None:
        self._icon.setVisible(bool(self._icon_name))
        if self._icon_name:
            self._icon.setPixmap(icons.pixmap(self._icon_name, icons.color(self._role), 20))

    def text(self) -> str:  # noqa: D102 - the label, not QPushButton's (empty) text
        return self._label.text()

    def set_label(self, text: str, icon_name: str = "") -> None:
        self._label.setText(text)
        if icon_name and icon_name != self._icon_name:
            self._icon_name = icon_name
            self.refresh_icon()

    def key_text(self) -> str:
        return self._key.text()

    def set_key(self, key: str) -> None:
        self._key.setText(key)
        self._key.setVisible(bool(key))


class HeroCard(QFrame):
    """
    The big counter card, with a faint skull watermark in the corner, or
    the game's artwork fading in from the right (see :meth:`set_artwork`).
    """

    def __init__(self, watermark: str = "skull", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeroCard")
        self._watermark = watermark
        self._art: QPixmap | None = None
        self._art_faded: QPixmap | None = None  # cache: redrawn only on resize

    def set_artwork(self, pixmap: QPixmap | None) -> None:
        if pixmap is self._art:
            return
        self._art, self._art_faded = pixmap, None
        self.update()

    def has_artwork(self) -> bool:
        return self._art is not None

    def _fade_artwork(self) -> QPixmap:
        """The artwork filling the card, see-through on the left where the text is."""
        from src.utils.backgrounds import cover  # here: backgrounds imports widgets' deps

        faded = QPixmap(self.size())
        faded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(faded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 22, 22)
        painter.setClipPath(path)
        painter.setOpacity(0.42)
        painter.drawPixmap(0, 0, cover(self._art, self.size()))
        painter.setOpacity(1.0)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        fade = QLinearGradient(0, 0, self.width(), 0)
        fade.setColorAt(0.0, QColor(0, 0, 0, 25))
        fade.setColorAt(0.55, QColor(0, 0, 0, 150))
        fade.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.fillRect(self.rect(), fade)
        painter.end()
        return faded

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._art is not None and not self._art.isNull():
            if self._art_faded is None or self._art_faded.size() != self.size():
                self._art_faded = self._fade_artwork()
            painter = QPainter(self)
            painter.drawPixmap(0, 0, self._art_faded)
            painter.end()
            return  # the artwork replaces the watermark
        size = min(self.height() // 2, 110)
        if size < 48 or not self._watermark or self.width() < 560:
            return
        painter = QPainter(self)
        painter.setOpacity(0.07)
        art = icons.pixmap(self._watermark, icons.color(icons.NORMAL), size, ratio=1.0)
        painter.drawPixmap(self.width() - size - 26, 18, art)
        painter.end()


def round_pixmap(source: QPixmap, size: int) -> QPixmap:
    """``source`` scaled to ``size`` and cut to a circle."""
    ratio = 2.0
    pixels = round(size * ratio)
    scaled = source.scaled(
        pixels,
        pixels,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    result = QPixmap(pixels, pixels)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, pixels, pixels))
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    result.setDevicePixelRatio(ratio)
    return result


class UpdateCard(QFrame):
    """
    Sidebar card for updates: this version, whether it's current, and an
    Update button when a newer one is out.

    States: "idle" (checks are off), "checking", "current", "failed",
    "available". :attr:`button` is the Update button.
    """

    check_requested = Signal()

    # state -> (icon, icon color or "" for the theme's, title)
    _LOOK = {
        "idle": ("info", "", "Updates"),
        "checking": ("refresh-cw", "", "Checking for updates…"),
        "current": ("circle-check", "#3ad07a", "Up to date"),
        "failed": ("circle-alert", "#f0a030", "Couldn't check for updates"),
        "available": ("circle-arrow-up", "#ff3d55", ""),
    }

    def __init__(self, version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UpdateCard")
        self._version = version
        self._state = "idle"
        self._latest = ""
        self._compact = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 8, 10)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(9)
        self._icon = QLabel()
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self._title = QLabel()
        self._title.setObjectName("UpdateTitle")
        self._title.setWordWrap(True)
        self._detail = QLabel()
        self._detail.setObjectName("UpdateDetail")
        texts.addWidget(self._title)
        texts.addWidget(self._detail)
        self._check = QPushButton()
        self._check.setObjectName("UpdateCheck")
        self._check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._check.setToolTip("Check for updates now")
        icons.set_icon(self._check, "refresh-cw", size=15)
        self._check.clicked.connect(self.check_requested)
        top.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(texts, 1)
        top.addWidget(self._check, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        self.button = QPushButton()
        self.button.setObjectName("AccentButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setToolTip("Download and install the new version")
        icons.set_icon(self.button, "download", icons.ACCENT, size=15)
        layout.addWidget(self.button)
        self.set_state("idle")

    def state(self) -> str:
        return self._state

    def set_state(self, state: str, latest: str = "") -> None:
        self._state = state
        _icon_name, _color, title = self._LOOK[state]
        available = state == "available"
        self._title.setText(f"{latest} is out!" if available else title)
        self._detail.setText(f"You have v{self._version}")
        self.button.setText(f" Update to {latest}")
        self.button.setVisible(available)
        self._check.setVisible(not available)
        self._check.setEnabled(state != "checking")
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.refresh_icon()
        self._latest = latest
        if self._compact:
            self.set_compact(True)

    def set_compact(self, compact: bool) -> None:
        """Collapsed sidebar: just the status icon (and Update, when there is one)."""
        self._compact = compact
        for widget in (self._title, self._detail):
            widget.setVisible(not compact)
        self._check.setVisible(not compact and self._state != "available")
        self.button.setText("" if compact else f" Update to {self._latest}")
        self.setToolTip(f"{self._title.text()} ({self._detail.text()})" if compact else "")

    def refresh_icon(self) -> None:
        icon_name, color, _title = self._LOOK[self._state]
        self._icon.setPixmap(icons.pixmap(icon_name, color or icons.color(icons.NORMAL), 18))


class CreditCard(QFrame):
    """'Made by DePhantom' with the channel logo; opens the YouTube channel."""

    clicked = Signal()

    def __init__(self, logo: QPixmap, name: str, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CreditCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{name} on YouTube: {url}")
        self._url = url
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        avatar = QLabel()
        if not logo.isNull():
            avatar.setPixmap(round_pixmap(logo, 34))
        avatar.setFixedSize(34, 34)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        small = QLabel("MADE BY")
        small.setObjectName("CreditSmall")
        big = QLabel(name)
        big.setObjectName("CreditName")
        texts.addWidget(small)
        texts.addWidget(big)
        self._play = QLabel()
        self._texts = (small, big)
        self._layout = layout
        layout.addWidget(avatar)
        layout.addLayout(texts, 1)
        layout.addWidget(self._play)
        self.refresh_icon()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def refresh_icon(self) -> None:
        self._play.setPixmap(icons.pixmap("youtube", "#ff0033", 18))

    def set_compact(self, compact: bool) -> None:
        """Collapsed sidebar: only the logo, still a link to the channel."""
        for widget in (*self._texts, self._play):
            widget.setVisible(not compact)
        self._layout.setContentsMargins(*((6, 6, 6, 6) if compact else (10, 8, 10, 8)))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
            QDesktopServices.openUrl(QUrl(self._url))
        super().mouseReleaseEvent(event)


class ResponsiveGrid(QWidget):
    """
    Widgets side by side that rearrange when space runs out.

    Wide: one row, with ``stretch`` per widget. Compact: ``columns`` per row,
    and widgets listed in ``full_width`` take a whole row. The main window
    switches it from the width it has (see ``MainWindow._fit_to_width``).
    """

    def __init__(
        self,
        widgets: list[QWidget],
        stretch: tuple[int, ...] = (),
        columns: int = 1,
        full_width: tuple[QWidget, ...] = (),
        spacing: int = 10,
        align: dict[QWidget, Qt.AlignmentFlag] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._widgets = list(widgets)
        self._stretch = stretch
        self._columns = max(1, columns)
        self._full = set(full_width)
        self._align = align or {}
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)
        self.compact: bool | None = None
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        if compact == self.compact:
            return
        self.compact = compact
        grid = self._grid
        for widget in self._widgets:
            grid.removeWidget(widget)
        for column in range(grid.columnCount()):
            grid.setColumnStretch(column, 0)
        if not compact:
            for index, widget in enumerate(self._widgets):
                grid.addWidget(widget, 0, index, self._align.get(widget, Qt.AlignmentFlag(0)))
                stretch = self._stretch[index] if index < len(self._stretch) else 0
                grid.setColumnStretch(index, stretch)
            return
        row = column = 0
        for widget in self._widgets:
            if widget in self._full:
                if column:
                    row, column = row + 1, 0
                grid.addWidget(widget, row, 0, 1, self._columns)
                row += 1
                continue
            grid.addWidget(widget, row, column)
            column += 1
            if column == self._columns:
                row, column = row + 1, 0
        for column in range(self._columns):
            grid.setColumnStretch(column, 1)


def page_header(title: str, subtitle: str = "") -> QWidget:
    """Big page title with an optional muted line under it."""
    header = QWidget()
    layout = QVBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 4)
    layout.setSpacing(2)
    title_label = QLabel(title)
    title_label.setObjectName("PageTitle")
    layout.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
    return header


def field(label_text: str, widget: QWidget) -> QWidget:
    """A small uppercase caption above a control."""
    container = QWidget()
    container.setObjectName("Field")
    # Only this wrapper (not the control): it sits on cards as well as pages.
    container.setStyleSheet("QWidget#Field { background: transparent; }")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    label = QLabel(label_text.upper())
    label.setObjectName("FieldLabel")
    layout.addWidget(label)
    layout.addWidget(widget)
    return container


def section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("SectionTitle")
    return label


def card(object_name: str = "Card", margins: int = 18) -> tuple[QFrame, QVBoxLayout]:
    """A rounded panel and its layout."""
    frame = QFrame()
    frame.setObjectName(object_name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(10)
    return frame, layout


def row(*widgets: QWidget, spacing: int = 8, stretch: tuple[int, ...] = ()) -> QHBoxLayout:
    """Widgets side by side; ``stretch`` gives per-widget stretch factors."""
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, stretch[index] if index < len(stretch) else 0)
    return layout


def glow(widget: QWidget, color: str = "#ff3d55", radius: int = 36) -> None:
    """A soft colored glow behind a widget (the big death number)."""
    effect = QGraphicsDropShadowEffect(widget)  # parented: Python would free it otherwise
    effect.setBlurRadius(radius)
    effect.setOffset(0, 0)
    shade = QColor(color)
    shade.setAlpha(140)
    effect.setColor(shade)
    widget.setGraphicsEffect(effect)
