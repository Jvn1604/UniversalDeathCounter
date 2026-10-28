"""Tests for the start-with-Windows registry helpers (Windows only).

They write to a throwaway key under HKCU\\Software, never the real Run key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils import startup  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows registry only")

TEST_KEY = r"Software\UniversalDeathCounterTests\Run"


@pytest.fixture()
def key_path():
    import winreg

    yield TEST_KEY
    for path in (TEST_KEY, r"Software\UniversalDeathCounterTests"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass


def test_enable_then_disable(key_path: str) -> None:
    assert not startup.is_enabled(key_path)
    startup.set_enabled(True, key_path, command=r'"C:\Apps\UDC\UniversalDeathCounter.exe"')
    assert startup.is_enabled(key_path)
    startup.set_enabled(False, key_path)
    assert not startup.is_enabled(key_path)


def test_disable_when_not_registered_is_a_no_op(key_path: str) -> None:
    startup.set_enabled(False, key_path)
    assert not startup.is_enabled(key_path)


def test_source_checkout_is_not_supported() -> None:
    assert not startup.startup_supported()  # pytest runs from source, not frozen
