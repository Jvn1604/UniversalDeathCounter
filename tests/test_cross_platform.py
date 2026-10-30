"""
macOS and Linux support: key and button mapping, Wine process matching,
Retina captures, start at login, the one-copy lock, and (on those systems
themselves) real hotkeys and window lists.

The mapping tests run everywhere; the ones marked for one OS run in CI on
that OS (the Linux hotkey test needs an X server and xdotool).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.detection import game_window  # noqa: E402
from src.hotkeys import gamepad, mac_hotkeys, x11_hotkeys  # noqa: E402
from src.hotkeys.hotkey_manager import HotkeyManager, parse_hotkey  # noqa: E402

IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"


# ----------------------------------------------------------------
# Keys
# ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "keysym", "mask"),
    [
        ("f9", 0xFFC6, 0),
        ("ctrl+shift+d", ord("d"), 4 | 1),
        ("alt+5", ord("5"), 8),
        ("meta+space", 0x20, 64),
        ("num+5", 0xFFB5, 0),
        ("pgdown", 0xFF56, 0),
        ("shift+-", ord("-"), 1),
    ],
)
def test_x11_keys(text: str, keysym: int, mask: int) -> None:
    modifiers, vk = parse_hotkey(text)
    assert x11_hotkeys.keysym_for(vk) == keysym
    assert x11_hotkeys.modifier_mask(modifiers) == mask


@pytest.mark.parametrize(
    ("text", "key_code", "flags"),
    [
        ("f9", 0x65, 0),
        ("ctrl+f12", 0x6F, 0x0100),  # Qt's "Ctrl" is the Command key on a Mac
        ("meta+a", 0x00, 0x1000),  # and "Meta" is Control
        ("alt+shift+0", 0x1D, 0x0800 | 0x0200),
        ("num+7", 0x59, 0),
        ("left", 0x7B, 0),
    ],
)
def test_mac_keys(text: str, key_code: int, flags: int) -> None:
    modifiers, vk = parse_hotkey(text)
    assert mac_hotkeys.key_code_for(vk) == key_code
    assert mac_hotkeys.modifier_flags(modifiers) == flags


def test_mac_has_no_f21() -> None:
    assert mac_hotkeys.key_code_for(parse_hotkey("f21")[1]) is None


# ----------------------------------------------------------------
# Controllers on Linux
# ----------------------------------------------------------------
def test_linux_buttons_follow_the_driver() -> None:
    xbox, sony = 0x045E, 0x054C
    assert gamepad.linux_button_name(0x130, 0, xbox) == "south"
    assert gamepad.linux_button_name(0x133, 2, xbox) == "west"  # Xbox X
    assert gamepad.linux_button_name(0x134, 3, xbox) == "north"  # Xbox Y
    assert gamepad.linux_button_name(0x133, 2, sony) == "north"  # Triangle
    assert gamepad.linux_button_name(0x134, 3, sony) == "west"  # Square
    assert gamepad.linux_button_name(0x13A, 8, sony) == "back"
    assert gamepad.linux_button_name(0x2C0, 15, xbox) == "button16"


def test_linux_axes() -> None:
    assert gamepad.linux_axis_buttons(0x10, -32767) == {"dpad_left"}
    assert gamepad.linux_axis_buttons(0x11, 32767) == {"dpad_down"}
    assert gamepad.linux_axis_buttons(0x11, 0) == set()
    assert gamepad.linux_axis_buttons(0x02, 20000) == {"lt"}
    assert gamepad.linux_axis_buttons(0x05, -32767) == set()  # trigger at rest
    assert gamepad.linux_axis_buttons(0x00, 32767) == set()  # a stick


# ----------------------------------------------------------------
# Finding Wine / Proton games
# ----------------------------------------------------------------
class _FakeProcess:
    def __init__(self, cmdline: list[str]) -> None:
        self._cmdline = cmdline

    def cmdline(self) -> list[str]:
        return self._cmdline


def test_file_name_reads_windows_paths() -> None:
    assert game_window.file_name(r"Z:\home\me\Game\DarkSoulsIII.exe") == "DarkSoulsIII.exe"
    assert game_window.file_name("/home/me/Game/eldenring.exe") == "eldenring.exe"


def test_wine_names_cut_to_15_characters_still_match(monkeypatch) -> None:
    monkeypatch.setattr(game_window, "IS_WINDOWS", False)
    wine = _FakeProcess([r"Z:\games\DS3\Game\DarkSoulsIII.exe"])
    assert game_window._name_matches(wine, "darksoulsiii.ex", "darksoulsiii.exe")
    other = _FakeProcess([r"C:\other\darksoulsiii_launcher.exe"])
    assert not game_window._name_matches(other, "darksoulsiii.ex", "darksoulsiii.exe")
    # Wine runs as "wine64-preloader", which counts for the picked .exe.
    assert game_window._path_matches("/usr/bin/wine64-preloader", "/games/eldenring.exe")


def test_windows_keeps_exact_paths(monkeypatch) -> None:
    monkeypatch.setattr(game_window, "IS_WINDOWS", True)
    assert not game_window._name_matches(_FakeProcess([]), "darksoulsiii.ex", "darksoulsiii.exe")


def test_app_bundle_points_at_its_program(tmp_path: Path) -> None:
    import plistlib

    app = tmp_path / "Hollow Knight.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleExecutable": "hollow_knight", "CFBundleName": "Hollow Knight"})
    )
    assert game_window._bundle_executable(str(app)).endswith(
        os.path.join("Contents", "MacOS", "hollow_knight")
    )
    assert game_window._bundle_name(str(app)) == "Hollow Knight"
    assert game_window.exe_display_name(str(app)) == "Hollow Knight"


def test_retina_capture_is_scaled_to_points() -> None:
    shot = np.zeros((200, 400, 4), dtype=np.uint8)  # 2x of a 200x100 point area
    shot[0, 0] = (10, 20, 30, 255)  # BGRA
    frame = game_window._rgb(shot, 200, 100)
    assert frame.shape == (100, 200, 3)
    assert tuple(frame[0, 0]) == (30, 20, 10)


# ----------------------------------------------------------------
# Start at login, one copy
# ----------------------------------------------------------------
@pytest.mark.skipif(not (IS_LINUX or IS_MAC), reason="macOS / Linux login items")
def test_login_file_round_trip(monkeypatch, tmp_path: Path) -> None:
    from src.utils import startup

    monkeypatch.setattr(startup, "login_file", lambda: tmp_path / "entry")
    assert not startup.is_enabled()
    startup.set_enabled(True, command="/Applications/DUDC.app/Contents/MacOS/DUDC")
    assert startup.is_enabled()
    assert "DUDC" in (tmp_path / "entry").read_text()
    startup.set_enabled(False)
    assert not startup.is_enabled()


@pytest.mark.skipif(not (IS_LINUX or IS_MAC), reason="file lock and Unix socket")
def test_second_copy_knocks_on_the_first(monkeypatch, tmp_path: Path) -> None:
    from PySide6.QtCore import QCoreApplication

    from src.utils import single_instance

    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(single_instance, "_lock_path", lambda: tmp_path / "lock")
    monkeypatch.setattr(single_instance, "_socket_path", lambda: str(tmp_path / "s.sock"))
    assert single_instance.acquire()
    shown: list[bool] = []
    single_instance.listen_for_others(lambda: shown.append(True))
    try:
        # A second copy (another process) can't take the lock.
        code = (
            "import fcntl,sys;f=open(sys.argv[1],'a+');"
            "fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
        )
        second = subprocess.run([sys.executable, "-c", code, str(tmp_path / "lock")])
        assert second.returncode != 0
        assert single_instance._knock_on_first_copy()
        deadline = time.monotonic() + 2
        while not shown and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert shown
    finally:
        single_instance.release()


# ----------------------------------------------------------------
# The real thing, on each OS
# ----------------------------------------------------------------
@pytest.mark.skipif(
    not (IS_LINUX and os.environ.get("DISPLAY") and shutil.which("xdotool")),
    reason="needs X11 and xdotool",
)
def test_x11_hotkey_fires_and_reports_taken_keys() -> None:
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    manager = HotkeyManager(increment_key="ctrl+alt+shift+f9", undo_key="ctrl+alt+shift+f10")
    fired: list[str] = []
    manager.action_triggered.connect(fired.append)
    manager.start()
    try:
        # The same combo can't be grabbed twice.
        assert manager.key_available("ctrl+alt+shift+f9")  # held by us: counts as free
        assert not x11_hotkeys.probe(*parse_hotkey("ctrl+alt+shift+f9"))
        subprocess.run(["xdotool", "key", "ctrl+alt+shift+F9"], check=True)
        deadline = time.monotonic() + 3
        while not fired and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert fired == ["increment"]
    finally:
        manager.stop()
    assert x11_hotkeys.probe(*parse_hotkey("ctrl+alt+shift+f9"))  # let go again


@pytest.mark.skipif(not IS_LINUX, reason="X11 window list")
def test_x11_window_queries_never_crash() -> None:
    from src.detection import x11_windows

    assert isinstance(x11_windows.windows(), list)
    assert x11_windows.rect(0x7FFFFFF) is None  # a window that doesn't exist
    assert x11_windows.title(0x7FFFFFF) == ""
    game_window.list_windows()


@pytest.mark.skipif(not IS_MAC, reason="Carbon hot keys")
def test_mac_hotkey_registers_and_releases() -> None:
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.instance() or QCoreApplication([])
    manager = HotkeyManager(increment_key="ctrl+alt+shift+f19")
    failed: list = []
    manager.registration_failed.connect(failed.extend)
    manager.start()
    try:
        assert failed == []
        assert manager._thread.held_combos
        assert not mac_hotkeys.probe(*parse_hotkey("ctrl+alt+shift+f19"))
    finally:
        manager.stop()
    assert mac_hotkeys.probe(*parse_hotkey("ctrl+alt+shift+f19"))


@pytest.mark.skipif(not IS_MAC, reason="Quartz window list")
def test_mac_window_queries_never_crash() -> None:
    from src.detection import mac_windows

    windows = mac_windows.windows()
    assert isinstance(windows, list)
    assert mac_windows.rect(0x7FFFFFF) is None
    assert mac_windows.cursor() is not None
    if windows:
        mac_windows.title(windows[0].handle)
    game_window.list_windows()
