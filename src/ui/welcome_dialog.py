"""
The Guide: a short, page-by-page tour of the app.

Shown once on a fresh install, and any time from the ? button at the top of
the window. Page one gets the player's first game added; the rest show the
keys, auto-detect, the speedrun timer and the stream overlay. It only
collects the player's choice; the main window runs the actual add-game flows,
so there's one code path for each.
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui import icons
from src.ui.widgets import card, section_title
from src.utils.constants import APP_BRAND, APP_SUBTITLE, ICONS_DIR
from src.utils.game_templates import get_template_names

CHOICE_EXE = "exe"
CHOICE_TEMPLATE = "template"
CHOICE_OBS = "obs"


def _keycap(key: str) -> str:
    """Rich text for one key, drawn like a key."""
    return (
        "<span style='background-color: rgba(128,128,128,0.18); border-radius: 4px;'>"
        f"&nbsp;<b>{key}</b>&nbsp;</span>"
    )


class WelcomeDialog(QDialog):
    """
    The guide.

    After ``exec()``, :attr:`choice` is ``CHOICE_EXE``, ``CHOICE_TEMPLATE``
    (with :attr:`template_name`), ``CHOICE_OBS`` or ``None`` (just closed),
    and :attr:`show_again` says whether to show it on the next start.
    """

    def __init__(self, keys: dict[str, str], parent: QWidget | None = None) -> None:
        """
        Args:
            keys: Display text of the current hotkeys, by action ("increment",
                "decrement", "undo", "calibrate", "toggle_overlay", "timer_split",
                "timer_pause", "timer_reset").
        """
        super().__init__(parent)
        self.setWindowTitle(f"{APP_BRAND} Guide")
        self.setMinimumSize(620, 520)
        self.choice: str | None = None
        self.template_name = ""
        self.show_again = False
        self._keys = keys

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 18)
        layout.setSpacing(14)
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)
        for page in (
            self._welcome_page(),
            self._counting_page(),
            self._detection_page(),
            self._timer_page(),
            self._stream_page(),
        ):
            self._stack.addWidget(page)

        bottom = QHBoxLayout()
        self._again_check = QCheckBox("Show at startup")
        self._dots: list[QLabel] = []
        dots = QHBoxLayout()
        dots.setSpacing(6)
        for _ in range(self._stack.count()):
            dot = QLabel()
            dot.setObjectName("StepDot")
            dot.setFixedSize(8, 8)
            self._dots.append(dot)
            dots.addWidget(dot)
        self._back = QPushButton(" Back")
        self._back.setObjectName("GhostButton")
        icons.set_icon(self._back, "chevron-left", size=16)
        self._back.clicked.connect(lambda: self._go(-1))
        self._next = QPushButton()
        self._next.setObjectName("AccentButton")
        self._next.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # arrow after text
        self._next.setMinimumWidth(120)
        self._next.clicked.connect(lambda: self._go(+1))
        bottom.addWidget(self._again_check)
        bottom.addStretch()
        bottom.addLayout(dots)
        bottom.addStretch()
        bottom.addWidget(self._back)
        bottom.addWidget(self._next)
        layout.addLayout(bottom)
        self._show(0)

    # ----------------------------------------------------------------
    # Pages
    # ----------------------------------------------------------------
    @staticmethod
    def _page(icon_name: str, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(16)
        badge = QLabel()
        badge.setObjectName("GuideBadge")
        badge.setFixedSize(72, 72)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icons.pixmap(icon_name, "#ff3d55", 34))
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        title_label.setWordWrap(True)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setWordWrap(True)
        titles.addStretch()
        titles.addWidget(title_label)
        titles.addWidget(subtitle_label)
        titles.addStretch()
        header.addWidget(badge)
        header.addLayout(titles, 1)
        layout.addLayout(header)
        return page, layout

    @staticmethod
    def _tip(icon_name: str, title: str, text: str) -> QWidget:
        """A card with an icon, a bold line and an explanation."""
        frame, frame_layout = card(margins=14)
        top = QHBoxLayout()
        top.setSpacing(10)
        picture = QLabel()
        picture.setPixmap(icons.pixmap(icon_name, icons.color(icons.NORMAL), 20))
        heading = QLabel(f"<b>{title}</b>")
        top.addWidget(picture)
        top.addWidget(heading, 1)
        frame_layout.addLayout(top)
        body = QLabel(text)
        body.setObjectName("Muted")
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        frame_layout.addWidget(body)
        return frame

    def _welcome_page(self) -> QWidget:
        page, layout = self._page(
            "skull",
            f"Welcome to {APP_BRAND}",
            f"{APP_SUBTITLE}. Let's get your first game in: it takes ten seconds.",
        )
        pixmap = QPixmap(str(ICONS_DIR / "app_icon_128.png"))
        badge = page.findChild(QLabel, "GuideBadge")
        if not pixmap.isNull() and badge is not None:  # the app's own logo up front
            pixmap.setDevicePixelRatio(pixmap.width() / 64)
            badge.setPixmap(pixmap)

        exe_card, exe_layout = card(margins=16)
        exe_layout.addWidget(section_title("Recommended"))
        exe_text = QLabel(
            "Pick the game's .exe: deaths can then be detected automatically, and the "
            "app switches to the game when you start playing it."
        )
        exe_text.setObjectName("Muted")
        exe_text.setWordWrap(True)
        exe_layout.addWidget(exe_text)
        exe_button = QPushButton(" Choose the Game's .exe")
        exe_button.setObjectName("AccentButton")
        exe_button.setMinimumHeight(40)
        icons.set_icon(exe_button, "folder-open", icons.ACCENT, size=16)
        exe_button.clicked.connect(lambda: self._choose(CHOICE_EXE))
        exe_layout.addWidget(exe_button)
        layout.addWidget(exe_card)

        list_card, list_layout = card(margins=16)
        list_layout.addWidget(section_title("Or start from a boss list"))
        self._template_combo = QComboBox()
        self._template_combo.addItems(get_template_names())
        template_button = QPushButton(" Add with Boss List")
        icons.set_icon(template_button, "library", size=16)
        template_button.clicked.connect(self._choose_template)
        row = QHBoxLayout()
        row.addWidget(self._template_combo, 1)
        row.addWidget(template_button)
        list_layout.addLayout(row)
        layout.addWidget(list_card)
        layout.addStretch()
        return page

    def _counting_page(self) -> QWidget:
        keys = self._keys
        page, layout = self._page(
            "keyboard",
            "Count without leaving the game",
            "These keys work while the game has focus, even in fullscreen.",
        )
        keys_label = QLabel(
            f"<b>{keys.get('increment', 'F9')}</b> +1 death &nbsp;·&nbsp; "
            f"<b>{keys.get('decrement', 'F10')}</b> −1 &nbsp;·&nbsp; "
            f"<b>{keys.get('undo', 'F11')}</b> undo &nbsp;·&nbsp; "
            f"<b>{keys.get('calibrate', 'F8')}</b> teach the death screen"
        )
        keys_label.setTextFormat(Qt.TextFormat.RichText)
        keys_label.setStyleSheet("font-size: 14px;")
        keys_card, keys_layout = card(margins=16)
        keys_layout.addWidget(section_title("Your keys"))
        keys_layout.addWidget(keys_label)
        layout.addWidget(keys_card)
        layout.addWidget(
            self._tip(
                "gamepad-2",
                "Playing on a controller?",
                "Bind a button combo to any action in Settings → Controls, such as "
                "View + D-pad Up for +1.",
            )
        )
        layout.addWidget(
            self._tip(
                "chevron-right",
                "Bosses",
                "Pick the boss on the Home page; ◀ ▶ switch bosses and the trophy marks "
                "one defeated. Right-click the Game or Boss box to rename it.",
            )
        )
        layout.addStretch()
        return page

    def _detection_page(self) -> QWidget:
        keys = self._keys
        page, layout = self._page(
            "scan-eye",
            "Let it count for you",
            "Auto-detect reads the screen (or a log file). Nothing touches the game, so "
            "it's safe with anti-cheat.",
        )
        layout.addWidget(
            self._tip(
                "camera",
                "Teach it your death screen",
                f"When you die, press {_keycap(keys.get('calibrate', 'F8'))} while the "
                "death screen shows. From then on, deaths count themselves.",
            )
        )
        layout.addWidget(
            self._tip(
                "heart",
                "No death screen? (Hollow Knight, Cuphead…)",
                "Use the health bar or the game's log file instead: Detection → "
                "Set Up Detection.",
            )
        )
        layout.addWidget(
            self._tip(
                "trophy",
                "Boss kills",
                "Capture a boss's victory banner once and kills mark the boss defeated "
                "and move on to the next one.",
            )
        )
        layout.addStretch()
        return page

    def _timer_page(self) -> QWidget:
        keys = self._keys
        page, layout = self._page(
            "timer",
            "Speedrun timer",
            "Splits, personal best, gold splits and game time, like LiveSplit.",
        )
        layout.addWidget(
            self._tip(
                "flag",
                "Start and split",
                f"{_keycap(keys.get('timer_split', 'Num+1'))} starts the run and splits. "
                f"{_keycap(keys.get('timer_pause', 'Num+5'))} pauses and "
                f"{_keycap(keys.get('timer_reset', 'Num+3'))} resets, only while a run "
                "is going. Num Lock must be on.",
            )
        )
        layout.addWidget(
            self._tip(
                "list-ordered",
                "Splits from your boss list",
                "Timer → Edit Splits can fill the splits from the game's bosses.",
            )
        )
        layout.addWidget(
            self._tip(
                "pause",
                "Game time",
                "Settings → Speedrun can leave out loads, pauses and crashes.",
            )
        )
        layout.addStretch()
        return page

    def _stream_page(self) -> QWidget:
        keys = self._keys
        page, layout = self._page(
            "radio",
            "Show it on stream",
            "The overlay is a small window you capture in OBS.",
        )
        obs_hint = QLabel(
            f"Show the overlay with <b>{keys.get('toggle_overlay', 'Ctrl+F12')}</b> "
            "(or Overlay in the sidebar) and add it in OBS as a Window Capture."
        )
        obs_hint.setTextFormat(Qt.TextFormat.RichText)
        obs_hint.setWordWrap(True)
        obs_card, obs_layout = card(margins=16)
        obs_layout.addWidget(obs_hint)
        obs_button = QPushButton(" Open the OBS Setup Guide")
        icons.set_icon(obs_button, "radio", size=16)
        obs_button.clicked.connect(lambda: self._choose(CHOICE_OBS))
        obs_layout.addWidget(obs_button)
        layout.addWidget(obs_card)
        layout.addWidget(
            self._tip(
                "layers",
                "Right-click the overlay",
                "Count from it, switch what the big number shows, change the background, "
                "lock it in place or move it to another screen. Double-click it for all "
                "its settings.",
            )
        )
        layout.addWidget(
            self._tip(
                "circle-help",
                "This guide is always here",
                "Click the ? at the top of the window to see it again.",
            )
        )
        layout.addStretch()
        return page

    # ----------------------------------------------------------------
    # Navigation
    # ----------------------------------------------------------------
    def _show(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        last = index == self._stack.count() - 1
        self._back.setVisible(index > 0)
        self._next.setText("Done " if last else "Next ")
        icons.set_icon(self._next, "check" if last else "chevron-right", icons.ACCENT, size=16)
        for number, dot in enumerate(self._dots):
            dot.setProperty("active", "true" if number == index else "false")
            dot.style().unpolish(dot)
            dot.style().polish(dot)

    def _go(self, step: int) -> None:
        index = self._stack.currentIndex() + step
        if index >= self._stack.count():
            self.accept()
            return
        self._show(max(index, 0))

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def _choose_template(self) -> None:
        self.template_name = self._template_combo.currentText()
        self._choose(CHOICE_TEMPLATE)

    def done(self, result: int) -> None:  # noqa: D102 - remember the checkbox however it closes
        self.show_again = self._again_check.isChecked()
        super().done(result)
