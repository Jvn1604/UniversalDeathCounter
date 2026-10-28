"""
Small building blocks for the dashboard layout.

They only set object names and structure; the look comes from the theme
stylesheets (``src/themes/*.qss``), so both themes and the player's custom
colors and fonts apply to them automatically.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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


def nav_button(text: str, checkable: bool = True) -> QPushButton:
    """A sidebar entry (checkable ones switch pages)."""
    button = QPushButton(text)
    button.setObjectName("NavButton")
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


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


def glow(widget: QWidget, color: str = "#e63946", radius: int = 36) -> None:
    """A soft colored glow behind a widget (the big death number)."""
    effect = QGraphicsDropShadowEffect(widget)  # parented: Python would free it otherwise
    effect.setBlurRadius(radius)
    effect.setOffset(0, 0)
    shade = QColor(color)
    shade.setAlpha(140)
    effect.setColor(shade)
    widget.setGraphicsEffect(effect)
