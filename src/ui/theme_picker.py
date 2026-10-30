"""
Theme gallery for Settings → Appearance.

One card per theme with a small painted preview. Built-in themes can be
picked straight away; the others show Download first, and Uninstall once
they're installed. Downloads run on a worker thread.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.themes.theme_manager import (
    THEMES,
    ThemeInfo,
    install_theme,
    is_installed,
    uninstall_theme,
)
from src.ui import icons


class ThemeDownload(QObject):
    """Downloads one theme off the UI thread; ``finished(name, error)`` ("" = ok)."""

    finished = Signal(str, str)

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    def start(self) -> None:
        threading.Thread(target=self._run, name="ThemeDownload", daemon=True).start()

    def _run(self) -> None:
        try:
            install_theme(self._name)
        except (OSError, ValueError) as exc:
            self.finished.emit(self._name, str(exc))
            return
        self.finished.emit(self._name, "")


class _Swatch(QWidget):
    """A tiny drawing of the app in the theme's colors."""

    def __init__(self, info: ThemeInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._info = info
        self.setFixedHeight(70)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        info = self._info
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(info.base))
        painter.drawRoundedRect(rect, 9, 9)
        if info.name == "glass":  # its violet glow
            glow = QColor(info.accent)
            glow.setAlpha(70)
            painter.setBrush(glow)
            painter.drawEllipse(QRectF(rect.width() * 0.55, -18, 80, 60))
        side = QColor(info.surface)
        if info.name == "glass":
            side.setAlpha(150)
        painter.setBrush(side)
        painter.drawRoundedRect(QRectF(6, 6, 22, rect.height() - 12), 5, 5)
        painter.drawRoundedRect(QRectF(34, 6, rect.width() - 40, 34), 7, 7)
        painter.setBrush(QColor(info.accent))
        painter.drawRoundedRect(QRectF(34, 46, (rect.width() - 40) * 0.55, 16), 6, 6)
        painter.setBrush(QColor(info.text))
        painter.drawRoundedRect(QRectF(42, 14, 30, 6), 3, 3)
        painter.setBrush(QColor(info.accent))
        painter.drawRoundedRect(QRectF(42, 25, 16, 8), 3, 3)
        painter.end()


class ThemeCard(QFrame):
    """One theme: preview, name, and Use / Download / Uninstall."""

    chosen = Signal(str)
    download_requested = Signal(str)
    uninstall_requested = Signal(str)

    def __init__(self, info: ThemeInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ThemeCard")
        self.info = info
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(info.description)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        layout.addWidget(_Swatch(info))
        title_row = QHBoxLayout()
        title = QLabel(info.title)
        title.setStyleSheet("font-weight: 800;")
        self._state = QLabel()
        self._state.setObjectName("Muted")
        title_row.addWidget(title, 1)
        title_row.addWidget(self._state)
        layout.addLayout(title_row)
        self._button = QPushButton()
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.clicked.connect(self._on_button)
        layout.addWidget(self._button)
        self.set_selected(False)
        self.refresh()

    def refresh(self, busy: bool = False) -> None:
        installed = is_installed(self.info.name)
        self._button.setVisible(not self.info.builtin)
        self._button.setEnabled(not busy)
        if busy:
            self._button.setText("Downloading…")
        elif installed:
            self._button.setText(" Uninstall")
            icons.set_icon(self._button, "trash-2", icons.DANGER, size=14)
        else:
            self._button.setText(f" Download · {self.info.size_kb} KB")
            icons.set_icon(self._button, "download", size=14)
        self._state.setText("Built in" if self.info.builtin else "Installed" if installed else "")

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def _on_button(self) -> None:
        if is_installed(self.info.name):
            self.uninstall_requested.emit(self.info.name)
        else:
            self.download_requested.emit(self.info.name)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            if is_installed(self.info.name):
                self.chosen.emit(self.info.name)
            else:
                self.download_requested.emit(self.info.name)
        super().mouseReleaseEvent(event)


class ThemeGallery(QWidget):
    """
    All themes in a grid. :meth:`theme` is the picked one.

    Signals:
        theme_changed: A different (installed) theme was picked.
    """

    theme_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = "dark"
        self._downloads: dict[str, ThemeDownload] = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        self._cards: dict[str, ThemeCard] = {}
        for index, info in enumerate(THEMES.values()):
            theme_card = ThemeCard(info)
            theme_card.chosen.connect(self.set_theme)
            theme_card.download_requested.connect(self._download)
            theme_card.uninstall_requested.connect(self._uninstall)
            self._cards[info.name] = theme_card
            grid.addWidget(theme_card, index // 2, index % 2)

    def theme(self) -> str:
        return self._theme

    def set_theme(self, name: str) -> None:
        if name not in THEMES or not is_installed(name):
            name = "dark"
        changed = name != self._theme
        self._theme = name
        for card_name, theme_card in self._cards.items():
            theme_card.set_selected(card_name == name)
        if changed:
            self.theme_changed.emit(name)

    def _download(self, name: str) -> None:
        if name in self._downloads:
            return
        self._cards[name].refresh(busy=True)
        download = self._downloads[name] = ThemeDownload(name)
        download.finished.connect(self._on_downloaded)
        download.start()

    def _on_downloaded(self, name: str, error: str) -> None:
        self._downloads.pop(name, None)
        self._cards[name].refresh()
        if error:
            QMessageBox.warning(self, "Download Failed", error)
            return
        self.set_theme(name)

    def _uninstall(self, name: str) -> None:
        title = THEMES[name].title
        confirm = QMessageBox.question(
            self, "Uninstall Theme", f"Remove the {title} theme? You can download it again later."
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        uninstall_theme(name)
        self._cards[name].refresh()
        if self._theme == name:
            self.set_theme("dark")

    def refresh_icons(self) -> None:
        for theme_card in self._cards.values():
            theme_card.refresh()
