"""
The Quick Start guide: a live checklist, your keys, and tips.

Shown once on a fresh install and any time from the ? button. Each step
ticks itself off as the player actually does it (the main window feeds it
the state) and has a button that takes them straight there, so the guide
is a to-do list rather than a slideshow. It stays open beside the main
window while the player works through it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui import dashboard, icons
from src.ui.skulls import TIERS, skull_pixmap
from src.ui.widgets import card, section_title
from src.utils.constants import APP_BRAND, ICONS_DIR
from src.utils.game_templates import get_template_names

# The checklist, in order: (key, title). The main window says which are done.
STEPS: tuple[tuple[str, str], ...] = (
    ("game", "Add your game"),
    ("death", "Count your first death"),
    ("bosses", "Add the bosses"),
    ("detect", "Let it count for you"),
    ("stream", "Put it on stream"),
)

# Actions the guide asks the main window for.
ACTION_ADD_EXE = "add_exe"
ACTION_TEMPLATE = "template:"  # + the boss list's name
ACTION_HOME = "home"
ACTION_BOSSES = "bosses"
ACTION_DETECTION = "detection"
ACTION_OVERLAY = "overlay"
ACTION_OBS = "obs"
ACTION_CONTROLS = "controls"
ACTION_CONSOLE = "console"
ACTION_TIMER = "timer"

_KEY_ROWS = (
    ("increment", "+1 death"),
    ("decrement", "−1 death"),
    ("undo", "Undo the last change"),
    ("calibrate", "Teach the death screen (while it shows)"),
    ("toggle_overlay", "Show or hide the overlay"),
    ("timer_split", "Timer: start / split"),
    ("timer_pause", "Timer: pause"),
    ("timer_reset", "Timer: reset"),
)


def _keycap(text: str) -> QLabel:
    label = QLabel(text or "not set")
    label.setObjectName("KeyCap")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


class _Step(QFrame):
    """One checklist row: a number that turns into a tick, a hint, and buttons."""

    def __init__(self, number: int, title: str, hint: str) -> None:
        super().__init__()
        self.setObjectName("GuideStep")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        self._number = number
        self._mark = QLabel(str(number))
        self._mark.setObjectName("StepMark")
        self._mark.setFixedSize(30, 30)
        self._mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        self._title = QLabel(title)
        self._title.setObjectName("StepTitle")
        texts.addWidget(self._title)
        # Hidden once the step is done, so what's left stands out.
        self._details = QWidget()
        self._details.setStyleSheet("background: transparent;")
        details = QVBoxLayout(self._details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(8)
        details.addWidget(_muted(hint))
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        details.addLayout(self.actions)
        texts.addWidget(self._details)
        layout.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(texts, 1)
        self.done = False

    def set_done(self, done: bool) -> None:
        self.done = done
        self.setProperty("done", "true" if done else "false")
        self._mark.setProperty("done", "true" if done else "false")
        if done:
            self._mark.setText("")
            self._mark.setPixmap(icons.pixmap("check", "#ffffff", 16))
        else:
            self._mark.setPixmap(QPixmap())
            self._mark.setText(str(self._number))
        self._details.setVisible(not done)
        for widget in (self, self._mark):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class GuideDialog(QDialog):
    """
    The guide. It never changes data itself: buttons emit
    :attr:`action_requested` (one of the ``ACTION_*`` values) and the main
    window does the work, then calls :meth:`set_status`.
    """

    action_requested = Signal(str)

    def __init__(self, keys: dict[str, str], parent: QWidget | None = None) -> None:
        """
        Args:
            keys: Display text of the current hotkeys, by action (see ``_KEY_ROWS``).
        """
        super().__init__(parent)
        self.setWindowTitle(f"{APP_BRAND}: Quick Start")
        self.setMinimumSize(640, 600)
        self._keys = keys
        self._steps: dict[str, _Step] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addLayout(self._header())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._scroll(self._checklist_page()), "Get Started")
        self.tabs.addTab(self._scroll(self._keys_page()), "Your Keys")
        self.tabs.addTab(self._scroll(self._tips_page()), "Tips")
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.again_check = QCheckBox("Show at startup")
        close = QPushButton(" Close")
        icons.set_icon(close, "check", size=16)
        close.clicked.connect(self.accept)
        bottom.addWidget(self.again_check)
        bottom.addStretch()
        bottom.addWidget(close)
        layout.addLayout(bottom)

    # ----------------------------------------------------------------
    # Pages
    # ----------------------------------------------------------------
    def _header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(16)
        badge = QLabel()
        badge.setObjectName("GuideBadge")
        badge.setFixedSize(72, 72)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = QPixmap(str(ICONS_DIR / "app_icon_128.png"))
        if not logo.isNull():
            logo.setDevicePixelRatio(logo.width() / 56)
            badge.setPixmap(logo)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = QLabel("Let's get you set up")
        title.setObjectName("PageTitle")
        self._summary = QLabel()
        self._summary.setObjectName("PageSubtitle")
        self._progress = QProgressBar()
        self._progress.setObjectName("TierProgress")
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setRange(0, len(STEPS))
        titles.addStretch()
        titles.addWidget(title)
        titles.addWidget(self._summary)
        titles.addWidget(self._progress)
        titles.addStretch()
        header.addWidget(badge)
        header.addLayout(titles, 1)
        return header

    @staticmethod
    def _scroll(page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    def _button(self, text: str, icon_name: str, action: str, accent: bool = False) -> QPushButton:
        button = QPushButton(f" {text}")
        if accent:
            button.setObjectName("AccentButton")
        icons.set_icon(button, icon_name, icons.ACCENT if accent else icons.NORMAL, size=16)
        button.clicked.connect(lambda: self.action_requested.emit(action))
        return button

    def _checklist_page(self) -> QWidget:
        keys = self._keys
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        hints = {
            "game": "Pick the game's .exe so deaths can be detected and the app follows "
            "you into the game. Or start from a ready-made boss list.",
            "death": f"Die in game, then press <b>{keys.get('increment') or 'your +1 key'}</b>: "
            "it works in fullscreen. Or click +1 Death on Home.",
            "bosses": "Pick the boss you're fighting so deaths count against it. "
            "◀ ▶ switch bosses, the trophy marks one beaten.",
            "detect": "Die once, then press "
            f"<b>{keys.get('calibrate') or 'the capture key'}</b> while the death screen "
            "shows. From then on, deaths count themselves.",
            "stream": "Show the overlay and add it to OBS as a Window Capture. "
            "Right-click the overlay for its options.",
        }
        for number, (key, title) in enumerate(STEPS, start=1):
            step = self._steps[key] = _Step(number, title, hints[key])
            layout.addWidget(step)
        game = self._steps["game"].actions
        game.addWidget(self._button("Pick the Game's .exe", "folder-open", ACTION_ADD_EXE, True))
        self._template_combo = QComboBox()
        self._template_combo.addItems(get_template_names())
        self._template_combo.setMinimumContentsLength(12)
        self._template_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        template = QPushButton(" Add")
        icons.set_icon(template, "library", size=16)
        template.setToolTip("Add this game with its bosses in story order")
        template.clicked.connect(
            lambda: self.action_requested.emit(ACTION_TEMPLATE + self._template_combo.currentText())
        )
        game.addWidget(self._template_combo, 1)
        game.addWidget(template)
        self._steps["death"].actions.addWidget(
            self._button("Go to Home", "house", ACTION_HOME)
        )
        self._steps["bosses"].actions.addWidget(
            self._button("Games && Bosses", "library", ACTION_BOSSES)
        )
        self._steps["detect"].actions.addWidget(
            self._button("Set Up Detection", "scan-eye", ACTION_DETECTION)
        )
        self._steps["stream"].actions.addWidget(
            self._button("Show the Overlay", "layers", ACTION_OVERLAY)
        )
        self._steps["stream"].actions.addWidget(
            self._button("OBS Setup", "radio", ACTION_OBS)
        )
        for step in self._steps.values():
            step.actions.addStretch()
        layout.addStretch()
        self.set_status({})
        return page

    def _keys_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        keys_card, keys_layout = card(margins=16)
        keys_layout.addWidget(section_title("Work in game, even in fullscreen"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        for row_index, (action, what) in enumerate(_KEY_ROWS):
            grid.addWidget(_keycap(self._keys.get(action, "")), row_index, 0)
            grid.addWidget(QLabel(what), row_index, 1)
        grid.setColumnStretch(1, 1)
        keys_layout.addLayout(grid)
        layout.addWidget(keys_card)
        layout.addWidget(
            self._tip(
                "gamepad-2",
                "On a controller?",
                "Bind a button combo to any action, such as View + D-pad Up for +1.",
                ("Change Keys", "keyboard", ACTION_CONTROLS),
            )
        )
        layout.addStretch()
        return page

    def _tip(
        self, icon_name: str, title: str, text: str, button: tuple[str, str, str] | None = None
    ) -> QWidget:
        frame, frame_layout = card(margins=14)
        top = QHBoxLayout()
        top.setSpacing(10)
        picture = QLabel()
        picture.setPixmap(icons.pixmap(icon_name, icons.color(icons.NORMAL), 20))
        top.addWidget(picture)
        top.addWidget(QLabel(f"<b>{title}</b>"), 1)
        if button is not None:
            top.addWidget(self._button(*button))
        frame_layout.addLayout(top)
        frame_layout.addWidget(_muted(text))
        return frame

    def _tips_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        skulls, skulls_layout = card(margins=14)
        skulls_layout.addWidget(QLabel("<b>Your skull evolves</b>"))
        skulls_layout.addWidget(
            _muted("Every 10 deaths it grows meaner, up to a golden God of Death at 1000.")
        )
        strip = QHBoxLayout()
        strip.setSpacing(4)
        for tier in TIERS[:6]:
            column = QVBoxLayout()
            column.setSpacing(2)
            art = QLabel()
            art.setPixmap(
                skull_pixmap(
                    tier.deaths, 52, dashboard.color("text"), dashboard.color("accent"),
                    self.devicePixelRatioF(),
                )
            )
            art.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number = QLabel(str(tier.deaths))
            number.setObjectName("Muted")
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(art)
            column.addWidget(number)
            strip.addLayout(column)
        strip.addStretch()
        skulls_layout.addLayout(strip)
        layout.addWidget(skulls)

        for tip in (
            ("heart", "No death screen? (Hollow Knight, Cuphead…)",
             "Watch the health bar or the game's log file instead.",
             ("Set Up Detection", "scan-eye", ACTION_DETECTION)),
            ("trophy", "Boss kills count too",
             "Capture a boss's victory banner once: kills mark the boss beaten and move on "
             "to the next one.", None),
            ("gamepad-2", "PlayStation or Xbox?",
             "Count from your phone, or watch the capture card through OBS.",
             ("Console Page", "gamepad-2", ACTION_CONSOLE)),
            ("timer", "Speedrunning?",
             "Splits, personal best and game time without loads, like LiveSplit.",
             ("Timer Page", "timer", ACTION_TIMER)),
            ("layers", "Right-click the overlay",
             "Count from it, change what it shows, lock it or move it to another screen. "
             "Double-click it for all its settings.", None),
        ):
            layout.addWidget(self._tip(*tip))
        layout.addStretch()
        return page

    # ----------------------------------------------------------------
    # State
    # ----------------------------------------------------------------
    def set_status(self, status: dict[str, bool]) -> None:
        """Tick off the steps that are done (keys from :data:`STEPS`)."""
        for key, step in self._steps.items():
            done = bool(status.get(key))
            if done != step.done or step.property("done") is None:
                step.set_done(done)
        done_count = sum(1 for step in self._steps.values() if step.done)
        self._progress.setValue(done_count)
        if done_count == len(STEPS):
            self._summary.setText("All set. Go get 'em: every death counts now.")
        else:
            self._summary.setText(
                f"{done_count} of {len(STEPS)} done. Each step ticks itself off when you do it."
            )

    def step_done(self, key: str) -> bool:
        return self._steps[key].done
