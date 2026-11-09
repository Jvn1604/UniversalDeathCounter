"""What's New: the changelog inside the app, one version at a time."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.ui import icons
from src.ui.widgets import drawable
from src.utils import changelog
from src.utils.constants import APP_VERSION, GITHUB_REPO


class WhatsNewWindow(QDialog):
    """
    Versions on the left (newest first, yours marked), that version's notes on
    the right. ``releases`` defaults to the shipped changelog; ``since`` (a
    version) opens on the newest one and says what an update brought.
    """

    def __init__(
        self,
        releases: list[changelog.Release] | None = None,
        since: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("What's New")
        self.resize(820, 560)
        self._releases = changelog.load() if releases is None else releases

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        badge = QLabel()
        badge.setPixmap(icons.pixmap("sparkles", "#ff3d55", 26))
        title = QLabel("What's New")
        title.setObjectName("TitleLabel")
        heading.addWidget(badge)
        heading.addSpacing(6)
        heading.addWidget(title)
        heading.addStretch()
        layout.addLayout(heading)
        if since:
            brought = changelog.newer_than(self._releases, since, APP_VERSION)
            note = QLabel(
                f"Updated from v{since} to v{APP_VERSION}. "
                + (f"Here's what changed ({len(brought)} version"
                   f"{'' if len(brought) == 1 else 's'})." if brought else "")
            )
        else:
            note = QLabel(f"You have v{APP_VERSION}. Every version, newest first.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.versions = QListWidget()
        self.versions.setFixedWidth(210)
        self.notes = QTextBrowser()
        self.notes.setOpenLinks(False)  # links open in the browser, not in here
        self.notes.anchorClicked.connect(QDesktopServices.openUrl)
        body.addWidget(self.versions)
        body.addWidget(self.notes, 1)
        layout.addLayout(body, 1)

        for release in self._releases:
            label = release.title
            if release.version == APP_VERSION:
                label += "\n(you have this)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, release)
            self.versions.addItem(item)
        self.versions.currentItemChanged.connect(self._show)

        buttons = QHBoxLayout()
        online = QPushButton(" All Releases Online")
        online.setObjectName("GhostButton")
        icons.set_icon(online, "book-open", size=16)
        online.clicked.connect(lambda: QDesktopServices.openUrl(
            f"https://github.com/{GITHUB_REPO}/releases"))
        close = QPushButton("Close")
        close.setObjectName("AccentButton")
        close.clicked.connect(self.accept)
        buttons.addWidget(online)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)

        if not self._releases:
            self.notes.setMarkdown(
                "The list of changes isn't available here. See **All Releases Online**."
            )
            return
        start = next((i for i, r in enumerate(self._releases) if r.version == APP_VERSION), 0)
        if since:  # the newest version the update brought
            start = next((i for i, r in enumerate(self._releases)
                          if r.version != changelog.UNRELEASED), start)
        self.versions.setCurrentRow(start)

    def _show(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        release: changelog.Release = item.data(Qt.ItemDataRole.UserRole)
        intro = ("_Not released yet: these changes come with the next version._\n\n"
                 if release.version == changelog.UNRELEASED else "")
        # drawable(): a character the app's font lacks would load every fallback font.
        self.notes.setMarkdown(drawable(f"## {release.title}\n\n{intro}{release.notes}"))
