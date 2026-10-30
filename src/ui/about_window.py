"""About dialog: logo, version, what it runs on, licence, and who made it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from src.ui import dashboard
from src.ui.widgets import CreditCard
from src.utils.constants import (
    ACCENT_COLOR,
    APP_BRAND,
    APP_NAME,
    APP_SUBTITLE,
    APP_VERSION,
    CREATOR_CHANNEL_URL,
    CREATOR_NAME,
    GITHUB_REPO,
    ICONS_DIR,
)
from src.utils.platform_info import IS_LINUX, IS_MAC


def _this_system() -> str:
    if IS_MAC:
        return "macOS"
    if IS_LINUX:
        return "Linux"
    return "Windows"


class AboutWindow(QDialog):
    """Simple modal dialog presenting application information."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setFixedSize(420, 580)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(24, 24, 24, 24)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(ICONS_DIR / "app_icon_128.png"))
        if not pixmap.isNull():
            logo.setPixmap(pixmap)

        title = QLabel(APP_BRAND)
        title.setObjectName("TitleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel(APP_SUBTITLE)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #a855f7; font-weight: 700;")

        def link(url: str, text: str) -> str:  # in the theme's accent, readable on any theme
            return f'<a href="{url}" style="color: {dashboard.color("accent")};">{text}</a>'

        releases = f"https://github.com/{GITHUB_REPO}/releases/tag/v{APP_VERSION}"
        version = QLabel(f"Version {APP_VERSION}  ·  {link(releases, 'What&#39;s new')}")
        version.setOpenExternalLinks(True)
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setObjectName("Muted")

        description = QLabel(
            "A free, open-source death counter for Soulslike games, challenge runs "
            "and speedruns, on PC or console. It counts deaths automatically and "
            "grows a skull that evolves as you die.\n\n"
            "Built for streamers, speedrunners, and masochists."
        )
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        description.setObjectName("Muted")

        platforms = QLabel(f"Windows  ·  macOS  ·  Linux      (you're on {_this_system()})")
        platforms.setAlignment(Qt.AlignmentFlag.AlignCenter)
        platforms.setObjectName("Muted")
        platforms.setStyleSheet("font-size: 11px;")

        license_label = QLabel("Licensed under the MIT License")
        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        license_label.setStyleSheet(f"color: {ACCENT_COLOR};")

        github_label = QLabel(
            f"{link(f'https://github.com/{GITHUB_REPO}', f'github.com/{GITHUB_REPO}')}"
            f"  ·  Icons by {link('https://lucide.dev', 'Lucide')} (ISC)"
        )
        github_label.setOpenExternalLinks(True)
        github_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        github_label.setObjectName("Muted")
        github_label.setStyleSheet("font-size: 11px;")

        credit = CreditCard(
            QPixmap(str(ICONS_DIR / "channel_logo.png")), CREATOR_NAME, CREATOR_CHANNEL_URL
        )

        close_button = QPushButton("Close")
        close_button.setObjectName("AccentButton")
        close_button.clicked.connect(self.accept)

        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(version)
        layout.addWidget(description)
        layout.addSpacing(4)
        layout.addWidget(platforms)
        layout.addStretch()
        layout.addWidget(credit)
        layout.addSpacing(6)
        layout.addWidget(license_label)
        layout.addWidget(github_label)
        layout.addWidget(close_button)
