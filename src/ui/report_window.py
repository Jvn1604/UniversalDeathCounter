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
from pathlib import Path

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase, QGuiApplication
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
from src.utils.constants import APP_VERSION, GITHUB_REPO, LOG_DIR, LOG_FILE

ISSUE_URL = f"https://github.com/{GITHUB_REPO}/issues/new"
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


def issue_url(title: str, what: str, steps: str, details: str, log: str) -> str:
    """A GitHub "new issue" link, pre-filled; the log is trimmed to keep it short enough."""
    def body(log_text: str) -> str:
        parts = [f"**What happened**\n{what.strip() or '(describe it here)'}"]
        if steps.strip():
            parts.append(f"**Steps to make it happen**\n{steps.strip()}")
        parts.append(f"**App**\n{details}")
        if log_text:
            parts.append(
                "<details><summary>Last log lines</summary>\n\n```\n"
                + log_text
                + "\n```\n</details>"
            )
        return "\n\n".join(parts)

    lines = log.splitlines()
    while True:
        query = urllib.parse.urlencode(
            {"title": title.strip() or "Bug: ", "labels": "bug", "body": body("\n".join(lines))}
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


def _mono() -> object:
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


class ErrorLogWindow(QDialog):
    """The end of the app's log, for finding out what went wrong."""

    report_requested = Signal()

    def __init__(self, parent: QWidget | None = None, log_file: Path = LOG_FILE) -> None:
        super().__init__(parent)
        self._log_file = log_file
        self.setWindowTitle("Error Log")
        self.resize(820, 560)
        layout = QVBoxLayout(self)
        hint = QLabel(
            "What the app did recently, newest at the bottom. Warnings and errors are "
            "what to look for when something didn't work."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        top = QHBoxLayout()
        self.problems_check = QCheckBox("Only warnings and errors")
        self.problems_check.setChecked(True)
        self.problems_check.toggled.connect(self.refresh)
        top.addWidget(self.problems_check)
        top.addStretch()
        refresh = QPushButton(" Refresh")
        icons.set_icon(refresh, "refresh-cw", size=15)
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        layout.addLayout(top)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(_mono())
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.text, 1)
        buttons = QHBoxLayout()
        folder = QPushButton(" Open Log Folder")
        icons.set_icon(folder, "folder-open", size=15)
        folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))
        )
        copy = QPushButton(" Copy")
        icons.set_icon(copy, "copy", size=15)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text.toPlainText()))
        report = QPushButton(" Report a Bug")
        report.setObjectName("AccentButton")
        icons.set_icon(report, "bug", icons.ACCENT, size=15)
        report.clicked.connect(self._report)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for widget in (folder, copy):
            buttons.addWidget(widget)
        buttons.addStretch()
        buttons.addWidget(close)
        buttons.addWidget(report)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self, *_args) -> None:
        text = log_tail(400, self.problems_check.isChecked(), self._log_file)
        self.text.setPlainText(
            text or ("No warnings or errors logged. All good."
                     if self.problems_check.isChecked() else "The log is empty.")
        )
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())

    def _report(self) -> None:
        self.accept()
        self.report_requested.emit()


class ReportBugDialog(QDialog):
    """Write what went wrong; it opens as a pre-filled GitHub issue to review and send."""

    def __init__(
        self,
        parent: QWidget | None = None,
        extra_details: dict[str, str] | None = None,
        log_file: Path = LOG_FILE,
    ) -> None:
        super().__init__(parent)
        self._extra = extra_details or {}
        self._log_file = log_file
        self.setWindowTitle("Report a Bug or Glitch")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Thanks for helping! This opens a new issue on the app's GitHub page with "
            "what you write here filled in. You check it there and click <b>Create</b> "
            "(a free GitHub account is needed). Nothing is sent before that."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)
        layout.addWidget(QLabel("<b>Short title</b>"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("e.g. The overlay disappears when I alt-tab")
        layout.addWidget(self.title_edit)
        layout.addWidget(QLabel("<b>What happened?</b> And what did you expect?"))
        self.what_edit = QPlainTextEdit()
        self.what_edit.setPlaceholderText("Deaths stopped counting after I changed boss…")
        self.what_edit.setFixedHeight(90)
        layout.addWidget(self.what_edit)
        layout.addWidget(QLabel("<b>How to make it happen</b> (if you know)"))
        self.steps_edit = QPlainTextEdit()
        self.steps_edit.setPlaceholderText("1. Open the Death Counter page\n2. …")
        self.steps_edit.setFixedHeight(70)
        layout.addWidget(self.steps_edit)
        self.details_check = QCheckBox("Include the app version and system (recommended)")
        self.details_check.setChecked(True)
        self.log_check = QCheckBox(
            "Include the last warnings and errors from the log (user name removed)"
        )
        self.log_check.setChecked(True)
        layout.addWidget(self.details_check)
        layout.addWidget(self.log_check)
        buttons = QHBoxLayout()
        self.log_button = QPushButton(" See the Error Log")
        self.log_button.setObjectName("GhostButton")
        icons.set_icon(self.log_button, "scroll-text", size=15)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.open_button = QPushButton(" Open on GitHub")
        self.open_button.setObjectName("AccentButton")
        icons.set_icon(self.open_button, "bug", icons.ACCENT, size=15)
        self.open_button.clicked.connect(self._open)
        buttons.addWidget(self.log_button)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)
        self.opened_url = ""

    def url(self) -> str:
        details = system_details(self._extra) if self.details_check.isChecked() else "(not shared)"
        log = log_tail(60, True, self._log_file) if self.log_check.isChecked() else ""
        return issue_url(
            self.title_edit.text(),
            self.what_edit.toPlainText(),
            self.steps_edit.toPlainText(),
            details,
            log,
        )

    def _open(self) -> None:
        self.opened_url = self.url()
        QDesktopServices.openUrl(QUrl(self.opened_url))
        self.accept()
