"""
Small building blocks for the dashboard layout.

They only set object names and structure; the look comes from the theme
stylesheets (``src/themes/*.qss``), so both themes and the player's custom
colors and fonts apply to them automatically.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QMouseEvent, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.ui import icons

# Words in a detection status that mean "working" or "needs attention".
_ACTIVE_WORDS = ("watching",)
_WARNING_WORDS = ("black", "not responding", "needs", "error", "can't", "minimized", "stopped")


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
        else:
            state = ""
        if self.property("state") != state:
            self.setProperty("state", state)
            self.style().unpolish(self)  # re-evaluate [state=...] selectors
            self.style().polish(self)


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

    def set_on(self, on: bool) -> None:
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
    """The big counter card, with a faint skull watermark in the corner."""

    def __init__(self, watermark: str = "skull", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeroCard")
        self._watermark = watermark

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
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
        layout.addWidget(avatar)
        layout.addLayout(texts, 1)
        layout.addWidget(self._play)
        self.refresh_icon()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def refresh_icon(self) -> None:
        self._play.setPixmap(icons.pixmap("youtube", "#ff0033", 18))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
            QDesktopServices.openUrl(QUrl(self._url))
        super().mouseReleaseEvent(event)


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
