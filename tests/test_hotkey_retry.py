"""A key another program holds starts working once that program lets go (BUG-006)."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from src.utils.platform_info import IS_WINDOWS

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="Windows hotkeys")

_COMBO = "ctrl+alt+shift+f20"  # nothing else uses this
_HOLDER = """
import ctypes, sys, time
user32 = ctypes.windll.user32
ok = user32.RegisterHotKey(None, 1, 0x0002 | 0x0001 | 0x0004 | 0x4000, 0x83)
print("held" if ok else "busy", flush=True)
time.sleep(float(sys.argv[1]))
"""


def test_a_taken_key_is_picked_up_when_freed(monkeypatch) -> None:
    from PySide6.QtCore import QCoreApplication

    import src.hotkeys.hotkey_manager as hm

    QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(hm, "RETRY_TAKEN_MS", 300)
    holder = subprocess.Popen([sys.executable, "-c", _HOLDER, "1.5"],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        manager = hm.HotkeyManager(increment_key=_COMBO)
        failed, freed = [], []
        manager.registration_failed.connect(failed.append)
        manager.registration_recovered.connect(freed.append)
        manager.start()
        deadline = time.monotonic() + 8
        while not freed and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.05)
        manager.stop()
    finally:
        holder.kill()
    assert failed == [[("increment", _COMBO)]]
    assert freed == [[("increment", _COMBO)]]
