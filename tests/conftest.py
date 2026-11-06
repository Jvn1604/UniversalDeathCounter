"""
Shared test setup.

Qt allows one application object per process, and widgets need a full
QApplication (a plain QCoreApplication crashes the process when a window
is created). Create it once, offscreen, before any test can create a
QCoreApplication of its own; tests that call ``QCoreApplication.instance()``
then get this one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])


import pytest  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402


@pytest.fixture(autouse=True)
def _no_close_question(request, monkeypatch):
    """
    Closing asks "Close the app?"; tests close windows without a click.
    A test module that sets ``REAL_CLOSE_QUESTION = True`` gets the question.
    """
    import src.ui.main_window as main_window

    if getattr(request.module, "REAL_CLOSE_QUESTION", False):
        return
    monkeypatch.setattr(main_window.MainWindow, "_confirm_close", lambda self: True)


@pytest.fixture(autouse=True)
def _no_hotkey_warning_box(monkeypatch):
    """
    Another program (often an installed copy of this app) may hold the default
    hotkeys while tests run. The "Hotkey Unavailable" box would then wait for
    a click forever; tests that care about message boxes patch them themselves.
    """
    real_warning = QMessageBox.warning

    def warning(parent, title, *args, **kwargs):
        if title == "Hotkey Unavailable":
            return QMessageBox.StandardButton.Ok
        return real_warning(parent, title, *args, **kwargs)

    monkeypatch.setattr(QMessageBox, "warning", warning)


def pytest_sessionfinish(session, exitstatus):
    """
    Delete every window the tests left open while Python is still running.
    Left to interpreter shutdown, Qt and Python free them in a random order,
    which now and then crashed the run after all tests had passed.
    """
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent

    for widget in QApplication.topLevelWidgets():
        widget.hide()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    gc.collect()


@pytest.fixture(autouse=True)
def _no_network_update_check(monkeypatch):
    """
    No real update check: it runs on a thread, and finishing after a test had
    closed its window made a test fail now and then.
    """
    from src.utils.update_checker import UpdateChecker

    monkeypatch.setattr(UpdateChecker, "check_async", lambda self: None)
