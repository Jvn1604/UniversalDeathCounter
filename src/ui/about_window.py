"""About dialog showing the logo, app metadata, version, and license info."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from src.utils.constants import (
    ACCENT_COLOR,
    APP_BRAND,
    APP_NAME,
    APP_SUBTITLE,
    APP_VERSION,
    GITHUB_REPO,
    ICONS_DIR,
)


class AboutWindow(QDialog):
    """Simple modal dialog presenting application information."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setFixedSize(400, 470)
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
        subtitle.setStyleSheet("color: #b56cff; font-weight: 600;")

        version = QLabel(f"Version {APP_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: #999999;")

        description = QLabel(
            "A free, open-source death counter for Soulslike games,\n"
            "challenge runs, speedruns, and any PC game.\n\n"
            "Built for streamers, speedrunners, and masochists."
        )
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)

        license_label = QLabel("Licensed under the MIT License")
        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        license_label.setStyleSheet(f"color: {ACCENT_COLOR};")

        github_label = QLabel(
            f'<a href="https://github.com/{GITHUB_REPO}" style="color: #999999;">'
            f"github.com/{GITHUB_REPO}</a>"
        )
        github_label.setOpenExternalLinks(True)
        github_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        github_label.setStyleSheet("font-size: 11px;")

        close_button = QPushButton("Close")
        close_button.setObjectName("AccentButton")
        close_button.clicked.connect(self.accept)

        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(version)
        layout.addWidget(description)
        layout.addStretch()
        layout.addWidget(license_label)
        layout.addWidget(github_label)
        layout.addWidget(close_button)
