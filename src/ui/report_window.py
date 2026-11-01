"""
Problems: the error log, and reporting a bug as a GitHub issue.

:class:`ErrorLogWindow` shows the end of the app's log (``saves/logs/app.log``),
optionally only warnings and errors. :class:`ReportBugDialog` opens a
pre-filled issue on this project's GitHub page in the browser: what happened,
the app version and system, and the last log lines. Nothing is sent by the
app itself; the player reviews it on GitHub and submits it there. Home
folder paths are shortened to ``~`` so the user name isn't shared.
"""

from __future__ import annotations

import logging
import platform
import urllib.parse
from datetime import datetime
from pathlib import Path

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFontDatabase,
    QGuiApplication,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui import icons
from src.utils.constants import APP_VERSION, GITHUB_REPO, LOG_FILE

ISSUE_URL = f"https://github.com/{GITHUB_REPO}/issues/new"
APP_STARTED = datetime.now()  # this module loads with the main window
_MAX_URL = 7800  # browsers and GitHub cut longer links
_PROBLEM_LEVELS = ("| WARNING ", "| ERROR ", "| CRITICAL ")


def anonymize(text: str) -> str:
    """Shorten the home folder (it holds the user name) to ``~``."""
    home = str(Path.home())
    for variant in {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}:
        text = text.replace(variant, "~")
    return text


def log_tail(lines: int = 400, problems_only: bool = False, log_file: Path = LOG_FILE) -> str:
    """The last ``lines`` lines of the log (only warnings and errors, if asked)."""
    try:
        with log_file.open(encoding="utf-8", errors="replace") as file:
            text = file.read().splitlines()
    except OSError:
        return ""
    if problems_only:
        kept: list[str] = []
        keep_going = False
        for line in text:
            if any(level in line for level in _PROBLEM_LEVELS):
                kept.append(line)
                keep_going = True
            elif keep_going and not line[:4].isdigit():  # a traceback under an error
                kept.append(line)
            else:
                keep_going = False
        text = kept
    return anonymize("\n".join(text[-lines:]))


def report_text(what: str, steps: str, details: str, log: str) -> str:
    """The report itself (Markdown): what happened, how, the app details and the log."""
    parts = [f"**What happened**\n{what.strip() or '(not described)'}"]
    if steps.strip():
        parts.append(f"**Steps to make it happen**\n{steps.strip()}")
    parts.append(f"**App**\n{details}")
    if log:
        parts.append(
            "<details><summary>Last log lines</summary>\n\n```\n"
            + log
            + "\n```\n</details>"
        )
    return "\n\n".join(parts)


def issue_url(title: str, what: str, steps: str, details: str, log: str) -> str:
    """A GitHub "new issue" link, pre-filled; the log is trimmed to keep it short enough."""
    lines = log.splitlines()
    while True:
        body = report_text(what, steps, details, "\n".join(lines))
        query = urllib.parse.urlencode(
            {"title": title.strip() or "Bug: ", "labels": "bug", "body": body}
        )
        url = f"{ISSUE_URL}?{query}"
        if len(url) <= _MAX_URL or not lines:
            return url
        lines = lines[max(1, len(lines) // 5):]  # drop the oldest lines first


def system_details(extra: dict[str, str] | None = None) -> str:
    info = {
        "Version": f"v{APP_VERSION}",
        "System": platform.platform(),
        "Qt": PYSIDE_VERSION,
        **(extra or {}),
    }
    return "\n".join(f"- {key}: {value}" for key, value in info.items())


class ProblemCounter(QObject):
    """
    Counts errors logged while the app runs (any thread), so the bug button
    can show that something went wrong.

    Signals:
        problem_logged: Emitted with the error count so far.
    """

    problem_logged = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.count = 0
        counter = self

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
                counter.count += 1
                counter.problem_logged.emit(counter.count)  # queued to the UI thread

        self._handler = _Handler(logging.ERROR)
        logging.getLogger().addHandler(self._handler)

    def close(self) -> None:
        logging.getLogger().removeHandler(self._handler)


_MONO_CSS = 'font-family: "Cascadia Mono", Consolas, "Courier New", monospace; font-size: 12px;'


def _mono() -> object:
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


def count_problems(text: str) -> tuple[int, int]:
    """(errors, warnings) in log text."""
    errors = sum(1 for line in text.splitlines() if "| ERROR " in line or "| CRITICAL " in line)
    warnings = sum(1 for line in text.splitlines() if "| WARNING " in line)
    return errors, warnings


class _LogColors(QSyntaxHighlighter):
    """Errors (and their tracebacks) red, warnings orange, the time stamps dimmed."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self._error = QTextCharFormat()
        self._error.setForeground(QColor("#ff6b6b"))
        self._warning = QTextCharFormat()
        self._warning.setForeground(QColor("#f5b14c"))
        self._stamp = QTextCharFormat()
        self._stamp.setForeground(QColor("#7d8290"))

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        previous = self.previousBlockState()
        if "| ERROR " in text or "| CRITICAL " in text:
            self.setFormat(0, len(text), self._error)
            self.setCurrentBlockState(1)
        elif "| WARNING " in text:
            self.setFormat(0, len(text), self._warning)
            self.setCurrentBlockState(0)
        elif previous == 1 and text and not text[:4].isdigit():  # traceback lines
            self.setFormat(0, len(text), self._error)
            self.setCurrentBlockState(1)
        else:
            self.setCurrentBlockState(0)
            if text[:4].isdigit() and len(text) > 19:
                self.setFormat(0, 19, self._stamp)


class ErrorLogWindow(QDialog):
    """The app's log, readable: a summary, colours, a search, and only problems if wanted."""

    report_requested = Signal()
    _cleared_after = ""  # Clear hides older lines (the file itself is kept)

    def __init__(self, parent: QWidget | None = None, log_file: Path = LOG_FILE) -> None:
        super().__init__(parent)
        self._log_file = log_file
        self.setWindowTitle("Error Log")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Log")
        title.setObjectName("PageTitle")
        hint = QLabel(
            "What the app did recently, newest at the bottom. Red lines are errors, "
            "orange lines warnings."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(hint)
        top.addLayout(titles, 1)
        for text, icon_name, handler in (
            (" Refresh", "refresh-cw", self.refresh),
            (" Clear", "x", self._clear),
            (" Copy", "copy", self._copy),
            (" Open log file", "scroll-text", self._open_file),
        ):
            button = QPushButton(text)
            icons.set_icon(button, icon_name, size=15)
            button.clicked.connect(handler)
            top.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        report = QPushButton(" Report a problem…")
        report.setObjectName("AccentButton")
        icons.set_icon(report, "bug", icons.ACCENT, size=15)
        report.clicked.connect(self._report)
        top.addWidget(report, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.summary)
        filters = QHBoxLayout()
        self.problems_check = QCheckBox("Only errors and warnings")
        self.problems_check.toggled.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the log, e.g. detection or a game's name")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        filters.addWidget(self.problems_check)
        filters.addStretch()
        filters.addWidget(self.search, 1)
        layout.addLayout(filters)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(_mono())
        self.text.setStyleSheet(_MONO_CSS)  # the theme's font would win otherwise
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._colors = _LogColors(self.text.document())
        layout.addWidget(self.text, 1)
        bottom = QHBoxLayout()
        folder = QPushButton(" Open log folder")
        folder.setObjectName("GhostButton")
        icons.set_icon(folder, "folder-open", size=15)
        folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_file.parent)))
        )
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bottom.addWidget(folder)
        bottom.addStretch()
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.refresh()

    def _lines(self) -> str:
        text = log_tail(1500, self.problems_check.isChecked(), self._log_file)
        if ErrorLogWindow._cleared_after:
            text = "\n".join(
                line for line in text.splitlines()
                if line[:19] > ErrorLogWindow._cleared_after or not line[:4].isdigit()
            )
        query = self.search.text().strip().lower()
        if query:
            text = "\n".join(line for line in text.splitlines() if query in line.lower())
        return text

    def refresh(self, *_args) -> None:
        since = APP_STARTED.strftime("%Y-%m-%d %H:%M:%S")
        everything = log_tail(5000, False, self._log_file)
        this_run = "\n".join(line for line in everything.splitlines() if line[:19] >= since)
        errors, warnings = count_problems(this_run)
        dot = "#ff5c5c" if errors else "#f5b14c" if warnings else "#3ad07a"
        self.summary.setText(
            f'<span style="color:{dot}">●</span>&nbsp; Since the app started at '
            f"{APP_STARTED:%H:%M}: <b>{errors}</b> error{'' if errors == 1 else 's'}, "
            f"<b>{warnings}</b> warning{'' if warnings == 1 else 's'}"
        )
        text = self._lines()
        empty = "Nothing matches." if self.search.text().strip() else (
            "No errors or warnings. All good." if self.problems_check.isChecked()
            else "The log is empty."
        )
        self.text.setPlainText(text or empty)
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())

    def _clear(self) -> None:
        ErrorLogWindow._cleared_after = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.refresh()

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text.toPlainText())

    def _open_file(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_file)))

    def _report(self) -> None:
        self.accept()
        self.report_requested.emit()


class ReportBugDialog(QDialog):
    """
    Write what went wrong. The report (shown live) can be copied, or opened as
    a pre-filled GitHub issue to review and send.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        extra_details: dict[str, str] | None = None,
        log_file: Path = LOG_FILE,
    ) -> None:
        super().__init__(parent)
        self._extra = extra_details or {}
        self._log_file = log_file
        self.setWindowTitle("Report a Problem")
        self.setMinimumWidth(640)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        tag = QLabel("HELP")
        tag.setObjectName("SectionTitle")
        title = QLabel("Report a problem")
        title.setObjectName("PageTitle")
        intro = QLabel(
            "Say in a few words what happened and what you did just before. The app adds "
            "its version, your system and the last errors, and leaves out your Windows user "
            "name. Nothing is sent: copy the report, or open it on GitHub and send it there."
        )
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        for widget in (tag, title, intro):
            layout.addWidget(widget)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(
            "Short title, e.g. The overlay disappears when I alt-tab"
        )
        layout.addWidget(self.title_edit)
        self.what_edit = QPlainTextEdit()
        self.what_edit.setPlaceholderText(
            "What happened? For example: after I changed boss, deaths stopped counting."
        )
        self.what_edit.setFixedHeight(80)
        layout.addWidget(self.what_edit)
        self.steps_edit = QPlainTextEdit()
        self.steps_edit.setPlaceholderText("How to make it happen (if you know): 1. … 2. …")
        self.steps_edit.setFixedHeight(56)
        layout.addWidget(self.steps_edit)
        checks = QHBoxLayout()
        self.details_check = QCheckBox("App version and system")
        self.details_check.setChecked(True)
        self.log_check = QCheckBox("Last errors and warnings")
        self.log_check.setChecked(True)
        checks.addWidget(self.details_check)
        checks.addWidget(self.log_check)
        checks.addStretch()
        layout.addLayout(checks)
        preview_title = QLabel("REPORT")
        preview_title.setObjectName("SectionTitle")
        layout.addWidget(preview_title)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(_mono())
        self.preview.setStyleSheet(_MONO_CSS)
        self.preview.setMinimumHeight(160)
        layout.addWidget(self.preview, 1)
        for widget in (self.title_edit,):
            widget.textChanged.connect(self._update_preview)
        for widget in (self.what_edit, self.steps_edit):
            widget.textChanged.connect(self._update_preview)
        for check in (self.details_check, self.log_check):
            check.toggled.connect(self._update_preview)
        buttons = QHBoxLayout()
        self.log_button = QPushButton(" See the error log")
        self.log_button.setObjectName("GhostButton")
        icons.set_icon(self.log_button, "scroll-text", size=15)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        self.copy_button = QPushButton(" Copy report")
        icons.set_icon(self.copy_button, "copy", size=15)
        self.copy_button.clicked.connect(self._copy)
        self.open_button = QPushButton(" Open on GitHub")
        self.open_button.setObjectName("AccentButton")
        icons.set_icon(self.open_button, "bug", icons.ACCENT, size=15)
        self.open_button.clicked.connect(self._open)
        buttons.addWidget(self.log_button)
        buttons.addStretch()
        buttons.addWidget(close)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)
        self.opened_url = ""
        self._update_preview()

    def _parts(self) -> tuple[str, str, str, str]:
        details = system_details(self._extra) if self.details_check.isChecked() else "(not shared)"
        log = log_tail(60, True, self._log_file) if self.log_check.isChecked() else ""
        return self.what_edit.toPlainText(), self.steps_edit.toPlainText(), details, log

    def report(self) -> str:
        title = self.title_edit.text().strip()
        return (f"# {title}\n\n" if title else "") + report_text(*self._parts())

    def _update_preview(self, *_args) -> None:
        self.preview.setPlainText(self.report())

    def url(self) -> str:
        return issue_url(self.title_edit.text(), *self._parts())

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.report())
        self.copy_button.setText(" Copied")

    def _open(self) -> None:
        self.opened_url = self.url()
        QDesktopServices.openUrl(QUrl(self.opened_url))
        self.accept()
