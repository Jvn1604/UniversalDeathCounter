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
