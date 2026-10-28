"""
First-run guide: three steps to a working counter.

Shown once, when the app starts with no games (and again from Help →
Welcome Guide). It only collects the player's choice; the main window runs
the actual add-game flows, so there's one code path for each.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.widgets import card, section_title
from src.utils.constants import APP_BRAND, APP_SUBTITLE, ICONS_DIR
from src.utils.game_templates import get_template_names

CHOICE_EXE = "exe"
CHOICE_TEMPLATE = "template"
CHOICE_OBS = "obs"


class WelcomeDialog(QDialog):
    """
    The welcome guide.

    After ``exec()``, :attr:`choice` is ``CHOICE_EXE``, ``CHOICE_TEMPLATE``
    (with :attr:`template_name`), ``CHOICE_OBS`` or ``None`` (just closed),
    and :attr:`show_again` says whether to show it on the next start.
    """

    def __init__(self, keys: dict[str, str], parent: QWidget | None = None) -> None:
        """
        Args:
            keys: Display text of the current hotkeys, by action
                ("increment", "decrement", "undo", "calibrate", "toggle_overlay").
        """
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {APP_BRAND}")
        self.setMinimumWidth(560)
        self.choice: str | None = None
        self.template_name = ""
        self.show_again = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        logo = QLabel()
        pixmap = QPixmap(str(ICONS_DIR / "app_icon_48.png"))
        if not pixmap.isNull():
            logo.setPixmap(pixmap)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(f"Welcome to {APP_BRAND}")
        title.setObjectName("PageTitle")
        subtitle = QLabel(f"{APP_SUBTITLE}: three steps and you're counting.")
        subtitle.setObjectName("PageSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addWidget(logo)
        header.addLayout(titles, 1)
        layout.addLayout(header)

        # Step 1: a game
        step1, step1_layout = card(margins=16)
        step1_layout.addWidget(section_title("1 · Add your game"))
        hint = QLabel(
            "Pick the game's .exe so deaths can be detected and the app switches to it "
            "when you start playing. Or start from a ready-made boss list."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        step1_layout.addWidget(hint)
        exe_button = QPushButton("Choose the Game's .exe…")
        exe_button.setObjectName("AccentButton")
        exe_button.clicked.connect(lambda: self._choose(CHOICE_EXE))
        self._template_combo = QComboBox()
        self._template_combo.addItems(get_template_names())
        template_button = QPushButton("Add with Boss List")
        template_button.clicked.connect(self._choose_template)
        row = QHBoxLayout()
        row.addWidget(exe_button, 2)
        row.addWidget(self._template_combo, 2)
        row.addWidget(template_button, 1)
        step1_layout.addLayout(row)
        layout.addWidget(step1)

        # Step 2: keys
        step2, step2_layout = card(margins=16)
        step2_layout.addWidget(section_title("2 · Count from inside the game"))
        keys_label = QLabel(
            f"<b>{keys.get('increment', 'F9')}</b> +1 death &nbsp;·&nbsp; "
            f"<b>{keys.get('decrement', 'F10')}</b> −1 &nbsp;·&nbsp; "
            f"<b>{keys.get('undo', 'F11')}</b> undo &nbsp;·&nbsp; "
            f"<b>{keys.get('calibrate', 'F8')}</b> teach the death screen"
        )
        keys_label.setTextFormat(Qt.TextFormat.RichText)
        step2_layout.addWidget(keys_label)
        more = QLabel(
            "These work while the game has focus. Change them, or bind a controller "
            "combo, in Settings → Controls."
        )
        more.setObjectName("Muted")
        more.setWordWrap(True)
        step2_layout.addWidget(more)
        layout.addWidget(step2)

        # Step 3: streaming
        step3, step3_layout = card(margins=16)
        step3_layout.addWidget(section_title("3 · Streaming? (optional)"))
        obs_row = QHBoxLayout()
        obs_hint = QLabel(
            f"Show the overlay with <b>{keys.get('toggle_overlay', 'Ctrl+F12')}</b> and "
            "capture it in OBS."
        )
        obs_hint.setTextFormat(Qt.TextFormat.RichText)
        obs_hint.setWordWrap(True)
        obs_button = QPushButton("OBS Setup Guide…")
        obs_button.clicked.connect(lambda: self._choose(CHOICE_OBS))
        obs_row.addWidget(obs_hint, 1)
        obs_row.addWidget(obs_button)
        step3_layout.addLayout(obs_row)
        layout.addWidget(step3)

        bottom = QHBoxLayout()
        self._again_check = QCheckBox("Show this guide next time")
        close = QPushButton("I'll Explore on My Own")
        close.setObjectName("GhostButton")
        close.clicked.connect(self.reject)
        bottom.addWidget(self._again_check)
        bottom.addStretch()
        bottom.addWidget(close)
        layout.addLayout(bottom)

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def _choose_template(self) -> None:
        self.template_name = self._template_combo.currentText()
        self._choose(CHOICE_TEMPLATE)

    def done(self, result: int) -> None:  # noqa: D102 - remember the checkbox however it closes
        self.show_again = self._again_check.isChecked()
        super().done(result)
