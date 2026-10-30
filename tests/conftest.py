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
