"""
The guide: a live checklist, lessons on every feature, and your keys.

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
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
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
ACTION_COUNTER = "counter"
ACTION_BOSSES = "bosses"
ACTION_DETECTION = "detection"
ACTION_OVERLAY = "overlay"
ACTION_OBS = "obs"
ACTION_CONTROLS = "controls"
ACTION_CONSOLE = "console"
ACTION_TIMER = "timer"
ACTION_SAVE = "save"
ACTION_APPEARANCE = "appearance"
ACTION_REPORT = "report"

# The Learn tab: (title, icon, explanation, button or None). {key} = the
# player's own key for that action. Plain words, the steps in order.
LESSONS: tuple[tuple[str, str, str, tuple[str, str, str] | None], ...] = (
    (
        "Counting deaths", "skull",
        "<p>Press <b>{increment}</b> when you die. It works in game, even in "
        "fullscreen, so you never have to leave the game.</p>"
        "<ul>"
        "<li><b>−1 Death</b> ({decrement}) takes one off, for a death counted by "
        "mistake. It's logged as a −1.</li>"
        "<li><b>Undo</b> ({undo}) takes back the last +1 or −1 as if it never "
        "happened.</li>"
        "<li><b>Set Exact Count</b> types in any number, e.g. deaths from before "
        "you used the app.</li>"
        "<li><b>Reset Session</b> starts the session count at 0 (the all-time "
        "count keeps them). <b>Reset Total</b> clears the game's all-time count.</li>"
        "<li>Click the caption under the big number to choose what it counts: all-time, "
        "this session, this boss or this speedrun run. The overlay follows.</li>"
        "</ul>"
        "<p>Your skull evolves every 10 deaths, up to a golden God of Death at 1000.</p>",
        ("Go to Death Counter", "skull", "counter"),
    ),
    (
        "Sessions and saving", "history",
        "<p>A <b>session</b> is one sitting. Closing the app (or an update, a crash, "
        "a night's sleep) within 16 hours continues the same session.</p>"
        "<ul>"
        "<li><b>Sessions</b> (next to Undo) lists every session of the game. Pick one "
        "and click <b>Continue This Session</b> to keep counting in it.</li>"
        "<li>Everything is saved the moment it happens. On top of that, <b>⋮ → Save "
        "Progress</b> (Ctrl+S) writes one file with everything, including the "
        "session and speedrun run in progress: copy it to another PC or keep it "
        "safe, and <b>⋮ → Load Save</b> carries on from it.</li>"
        "<li>It also auto-saves every 5 minutes and when you close the app (closing "
        "asks first; turn that off in Settings → General).</li>"
        "</ul>",
        ("Save Progress Now", "save", "save"),
    ),
    (
        "Bosses", "trophy",
        "<ol>"
        "<li>Add the bosses with <b>Games &amp; Bosses</b>, or pick a ready-made boss "
        "list when adding a game.</li>"
        "<li>Choose the boss you're fighting in the Boss list: deaths now count "
        "against it too.</li>"
        "<li>◀ ▶ switch bosses. The trophy marks the boss beaten and moves on.</li>"
        "<li>Beaten automatically: after a boss, <b>Capture Screen</b> → \"A boss "
        "victory screen\". The next time that banner shows, the boss is marked "
        "beaten (and the timer can split).</li>"
        "</ol>"
        "<p>Home shows how many you've beaten and which boss killed you most.</p>",
        ("Games && Bosses", "library", "bosses"),
    ),
    (
        "Auto-detect: the game's window", "scan-eye",
        "<p>The app can count deaths by itself by watching for your death screen. It "
        "only reads the screen, so it's safe with anti-cheat.</p>"
        "<ol>"
        "<li>Add the game from its <b>.exe</b> (game list → + Add game from .exe).</li>"
        "<li>Run the game in <b>borderless</b> or <b>windowed</b> mode (exclusive "
        "fullscreen can capture as black).</li>"
        "<li>Die once. While the death screen shows, press <b>{calibrate}</b> and "
        "draw a box around the death text (e.g. YOU DIED). Or afterwards, Detection "
        "→ <b>Capture Screen</b> and pick the frame.</li>"
        "<li>Done: the same screen now counts a death. Add more screens if some "
        "deaths are missed.</li>"
        "</ol>"
        "<p>The dot shows what it's doing: <b>green</b> watching, <b>yellow</b> "
        "waiting for the game, <b>red</b> needs attention, <b>grey</b> off.</p>",
        ("Go to Detection", "scan-eye", "detection"),
    ),
    (
        "Auto-detect without the .exe", "monitor",
        "<p>Use this when the .exe isn't found: the status keeps saying "
        "<i>Waiting for the game to start</i> while you play. Common with launchers, "
        "emulators and cloud gaming.</p>"
        "<ol>"
        "<li>Add the game with <b>+ Add game without .exe</b> in the game list, or on "
        "the Detection page choose <b>What to watch → A whole display</b>.</li>"
        "<li>Pick the display the game is on.</li>"
        "<li>Teach it your death screen like before: <b>{calibrate}</b> while it "
        "shows, or Capture Screen afterwards.</li>"
        "</ol>"
        "<p>Anything on that display that looks like your death screen counts, so "
        "use <b>Pause</b> when you're not playing.</p>",
        ("Go to Detection", "monitor", "detection"),
    ),
    (
        "No death screen?", "heart",
        "<p>Some games don't show one (Hollow Knight, Cuphead, roguelikes). In "
        "<b>Set Up Detection</b> choose another method:</p>"
        "<ul>"
        "<li><b>Health bar</b>: box your health bar at full health with "
        "{calibrate}. A death counts when it empties.</li>"
        "<li><b>Log file</b>: pick the game's log file and the text it writes when "
        "you die. Test Text shows what it would find.</li>"
        "<li>Souls games (Elden Ring, Dark Souls, Sekiro…) are recognized without any "
        "setup.</li>"
        "</ul>",
        ("Set Up Detection", "wand-sparkles", "detection"),
    ),
    (
        "Speedrun timer", "timer",
        "<ol>"
        "<li>On the Timer page, enter your splits (or load a list).</li>"
        "<li><b>{timer_split}</b> starts the run and splits. While a run goes, "
        "{timer_pause} pauses and {timer_reset} resets.</li>"
        "<li><b>Game time</b> leaves out loads and pauses: mark your loading and "
        "pause screens in Set Up Detection.</li>"
        "<li>Reset a run by accident? <b>Run History</b> → Continue This Run.</li>"
        "</ol>"
        "<p>The big number can show <b>deaths this run</b> (click its caption).</p>",
        ("Go to Timer", "timer", "timer"),
    ),
    (
        "Overlay and OBS", "layers",
        "<ul>"
        "<li><b>Overlay</b> in the sidebar (or {toggle_overlay}) shows the counter "
        "on top of your game. Drag it anywhere.</li>"
        "<li>Right-click it for quick options; double-click for all its settings: "
        "background (card, <b>green screen</b> for OBS, <b>transparent</b>, or an "
        "image), font, colours, what it shows, alignment.</li>"
        "<li><b>Click-through</b> lets clicks go to the game underneath. Turn it off "
        "from the tray icon's menu.</li>"
        "<li><b>OBS Setup</b> walks you through adding it to your stream: as a window "
        "with Chroma Key, or as a text file (deaths.txt).</li>"
        "</ul>",
        ("OBS Setup", "radio", "obs"),
    ),
    (
        "Mini mode, phone and controller", "smartphone",
        "<ul>"
        "<li><b>Mini Mode</b> swaps this window for a tiny always-on-top counter with "
        "+1 and Undo.</li>"
        "<li><b>Phone</b> (Console page): scan the code and count from your phone on "
        "the same Wi-Fi.</li>"
        "<li><b>Controller</b>: Settings → Controls binds a button combo to any "
        "action, e.g. View + D-pad Up for +1.</li>"
        "</ul>",
        ("Change Keys", "keyboard", "controls"),
    ),
    (
        "Playing on a console", "gamepad-2",
        "<ul>"
        "<li>Count from your <b>phone</b> or a <b>controller</b> on this PC.</li>"
        "<li>With a <b>capture card</b> in OBS: on the Console page connect to OBS "
        "and pick the card's source. Deaths are then detected from it like a PC "
        "game.</li>"
        "<li>PS Remote Play or a capture viewer on this PC: pick its window on the "
        "Console page.</li>"
        "</ul>",
        ("Console Page", "gamepad-2", "console"),
    ),
    (
        "Make it yours", "palette",
        "<ul>"
        "<li><b>Settings → Appearance</b>: themes (Phantom Dark, Daylight, and the "
        "downloadable Glass and Clay), text and number colours, any font, a "
        "background image.</li>"
        "<li><b>Game artwork</b>: a faded banner of the game behind the counter "
        "(found on Steam, or right-click the game → Choose Artwork).</li>"
        "<li>The button at the top of the sidebar collapses it to icons.</li>"
        "<li><b>Profiles</b> (top right) keep separate games and counts, e.g. for "
        "two players on one PC.</li>"
        "</ul>",
        ("Appearance Settings", "palette", "appearance"),
    ),
    (
        "Something not working?", "circle-alert",
        "<ul>"
        "<li><b>Deaths not counted</b>: check the dot on the Detection page. Yellow "
        "\"Waiting for the game\" while you play → use <i>A whole display</i>. "
        "\"Capture is black\" → run the game borderless or windowed.</li>"
        "<li><b>A key does nothing</b>: another program may own it (Settings → "
        "Controls warns you). Pick another key.</li>"
        "<li><b>See what went wrong</b>: ⋮ → Error Log shows the warnings and "
        "errors. The bug icon at the top turns red when an error happened.</li>"
        "<li><b>Report it</b>: the bug icon opens a ready-made report on GitHub with "
        "your app version and the last errors (your user name is removed).</li>"
        "</ul>",
        ("Report a Bug", "bug", "report"),
    ),
)

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
        self.tabs.addTab(self._learn_page(), "Learn")
        self.tabs.addTab(self._scroll(self._keys_page()), "Your Keys")
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
            "it works in fullscreen. Or click +1 Death on the Death Counter page.",
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
            self._button("Go to Death Counter", "skull", ACTION_COUNTER)
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

    def _learn_page(self) -> QWidget:
        """Every major feature, explained step by step, with a button to try it."""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(12)
        self.lessons = QListWidget()
        self.lessons.setFixedWidth(240)
        self.lesson_pages = QStackedWidget()
        keys = {action: self._keys.get(action) or "its key" for action, _w in _KEY_ROWS}
        keys.setdefault("calibrate", "the capture key")
        for title, icon_name, text, button in LESSONS:
            item = QListWidgetItem(icons.icon(icon_name, icons.color(icons.NORMAL), size=16), title)
            self.lessons.addItem(item)
            lesson = QWidget()
            lesson_layout = QVBoxLayout(lesson)
            lesson_layout.setContentsMargins(4, 0, 4, 0)
            heading = QLabel(title)
            heading.setObjectName("PageTitle")
            lesson_layout.addWidget(heading)
            body = QLabel(text.format(**keys))
            body.setWordWrap(True)
            body.setTextFormat(Qt.TextFormat.RichText)
            body.setAlignment(Qt.AlignmentFlag.AlignTop)
            lesson_layout.addWidget(body)
            if icon_name == "skull":
                lesson_layout.addWidget(self._skull_strip())
            if button is not None:
                row = QHBoxLayout()
                row.addWidget(self._button(*button))
                row.addStretch()
                lesson_layout.addLayout(row)
            lesson_layout.addStretch()
            self.lesson_pages.addWidget(self._scroll(lesson))
        self.lessons.currentRowChanged.connect(self.lesson_pages.setCurrentIndex)
        self.lessons.setCurrentRow(0)
        layout.addWidget(self.lessons)
        layout.addWidget(self.lesson_pages, 1)
        return page

    def _skull_strip(self) -> QWidget:
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
        return skulls

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
