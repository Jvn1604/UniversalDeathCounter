"""Run-only timer keys, first-run guide, mini mode, quick renames, tray, updates."""

from __future__ import annotations

import io
import json
import os
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.database.database import Database  # noqa: E402
from src.utils import updater  # noqa: E402
from src.utils.game_templates import add_template_bosses, get_template  # noqa: E402


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    yield win
    win._quit_app()
    app.processEvents()


# ---------------------------------------------------------------- 1. run-only timer keys
def test_timer_keys_besides_split_only_register_during_a_run(window) -> None:
    db = window._database
    game = db.create_game("G")
    window._reload_games(select_game_id=game)
    held = window._hotkey_manager._bindings
    assert held["timer_split"] == "num+1"
    assert held["timer_pause"] == held["timer_reset"] == ""  # idle: keys stay free
    window._timer_action("split")
    held = window._hotkey_manager._bindings
    assert held["timer_pause"] == "num+5" and held["timer_reset"] == "num+3"
    window._timer_action("reset")
    assert window._hotkey_manager._bindings["timer_pause"] == ""


# ---------------------------------------------------------------- 4. keys on the Timer page
def test_timer_page_buttons_show_their_keys(window) -> None:
    buttons = window._timer_buttons
    assert buttons["split"].text().endswith("\nNum+1")
    assert buttons["pause"].text().endswith("\nNum+5")
    assert "while a run is going" in buttons["reset"].toolTip()
    assert "Ctrl+F11" in window._defeated_btn.toolTip()


# ---------------------------------------------------------------- 3. first-run guide
def test_welcome_guide_adds_a_boss_list_game(window, monkeypatch) -> None:
    from src.ui.welcome_dialog import CHOICE_TEMPLATE, WelcomeDialog

    assert window._first_game_btn.isVisibleTo(window)  # empty state
    shown: list[bool] = []

    def fake_exec(dialog):
        shown.append(True)
        dialog.template_name = "Elden Ring"
        dialog.choice = CHOICE_TEMPLATE
        return 1

    monkeypatch.setattr(WelcomeDialog, "exec", fake_exec)
    window.maybe_show_welcome()
    assert shown == [True]
    assert window._game_combo.currentText() == "Elden Ring"
    assert window._boss_combo.currentText().startswith("Margit")  # first boss selected
    assert not window._first_game_btn.isVisibleTo(window)
    assert window._database.get_setting("welcome_shown") == "true"
    window.maybe_show_welcome()  # has games now: not shown again
    assert shown == [True]


def test_welcome_guide_lists_the_current_keys(window) -> None:
    from PySide6.QtWidgets import QLabel

    from src.ui.welcome_dialog import WelcomeDialog

    dialog = WelcomeDialog({"increment": "F7", "calibrate": "F6"}, parent=window)
    texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "<b>F7</b> +1 death" in texts and "<b>F6</b>" in texts
    dialog.close()


def test_template_helper_is_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "t.db")
    try:
        template = get_template("Elden Ring")
        game, added = add_template_bosses(db, template)
        again, added_again = add_template_bosses(db, template)
        assert again == game and added == len(template.bosses) and added_again == 0
    finally:
        db.close()


# ---------------------------------------------------------------- 13. delete warning
def test_deleting_a_game_says_what_it_removes(window) -> None:
    from src.ui.boss_window import BossWindow

    db = window._database
    game = db.create_game("G")
    boss = db.create_boss(game, "B")
    session = db.start_session(game)
    for _ in range(3):
        db.add_death_event(game, boss, session, +1)
    dialog = BossWindow(db, parent=window)
    text = dialog._what_goes(game)
    assert text == "This permanently removes 3 deaths, 1 boss and 1 session."
    assert dialog._what_goes(db.create_game("Empty")) == "It has no deaths, bosses or runs yet."
    dialog.close()


# ---------------------------------------------------------------- 14. quick renames
def test_rename_game_and_boss_from_home(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    db = window._database
    game = db.create_game("Elden Ring")
    db.create_game("Sekiro")
    boss = db.create_boss(game, "Margit")
    window._reload_games(select_game_id=game)
    window._boss_combo.setCurrentIndex(window._boss_combo.findData(boss))

    answers = iter([("ELDEN RING", True), ("Margit, the Fell Omen", True), ("Sekiro", True)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: next(answers))
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[1]))
    window._rename_current_game()
    window._rename_current_boss()
    assert window._game_combo.currentText() == "ELDEN RING"
    assert window._boss_combo.currentText() == "Margit, the Fell Omen"
    window._rename_current_game()  # a name another game has
    assert warnings == ["Could Not Rename"]
    assert window._game_combo.currentText() == "ELDEN RING"

    window._set_boss_defeated(True)
    assert db.get_boss(boss)["defeated"]
    window._set_boss_defeated(False)
    assert not db.get_boss(boss)["defeated"]


# ---------------------------------------------------------------- 15. mini mode
def test_mini_mode_swaps_windows_and_counts(window) -> None:
    db = window._database
    game = db.create_game("G")
    window._reload_games(select_game_id=game)
    window.show()
    window._toggle_mini_mode()
    assert window._mini.isVisible() and not window.isVisible()
    window._mini.action_requested.emit("increment")
    window._mini.action_requested.emit("increment")
    window._mini.action_requested.emit("undo")
    assert window._mini._count.text() == "1"
    assert window._counter_manager.get_snapshot().session_deaths == 1
    window._mini.action_requested.emit("expand")
    assert window.isVisible() and not window._mini.isVisible()
    assert db.get_setting("mini_geometry")  # reopens where it was


# ---------------------------------------------------------------- 16. tray actions
def test_tray_menu_has_quick_actions(window) -> None:
    if window._tray is None:
        pytest.skip("no system tray here")
    texts = [action.text() for action in window._tray.contextMenu().actions()]
    for wanted in ("+1 Death", "Undo", "Boss Defeated", "Pause / Resume Auto-Detect",
                   "Timer: Start / Split", "Show / Hide Timer Window", "Mini Mode"):
        assert wanted in texts


# ---------------------------------------------------------------- 18. auto-update
class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


GOOD_URL = (
    "https://github.com/Jvn1604/UniversalDeathCounter/releases/download/v9.9.9/"
    "UniversalDeathCounterSetup.exe"
)


def test_download_checks_source_size_and_cancel(tmp_path, monkeypatch) -> None:
    payload = b"MZ" + b"\x00" * 1000
    monkeypatch.setattr(
        updater.urllib.request, "urlopen", lambda url, timeout: _FakeResponse(payload)
    )
    dest = tmp_path / "setup.exe"
    seen: list[tuple[int, int]] = []
    progress = lambda done, total: seen.append((done, total))  # noqa: E731
    assert updater.download_installer(GOOD_URL, dest, len(payload), progress)
    assert dest.read_bytes() == payload and seen[-1] == (len(payload), len(payload))

    with pytest.raises(updater.UpdateError):  # someone else's file
        updater.download_installer("https://evil.example/UniversalDeathCounterSetup.exe", dest, 1)
    with pytest.raises(updater.UpdateError):  # wrong size: not installed
        updater.download_installer(GOOD_URL, tmp_path / "b.exe", len(payload) + 1)
    assert not (tmp_path / "b.exe").exists() and not (tmp_path / "b.part").exists()
    stop = threading.Event()
    stop.set()
    with pytest.raises(updater.UpdateError):
        updater.download_installer(GOOD_URL, tmp_path / "c.exe", len(payload), cancelled=stop)


def test_installed_copy_detection_and_silent_launch(tmp_path, monkeypatch) -> None:
    exe = tmp_path / "UniversalDeathCounter.exe"
    assert not updater.is_installed_copy(exe)
    (tmp_path / "unins000.exe").write_bytes(b"")
    assert updater.is_installed_copy(exe)
    launched: list[list[str]] = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **k: launched.append(args))
    updater.launch_installer(tmp_path / "setup.exe")
    assert launched[0][1:] == list(updater.INSTALLER_ARGS) and "/SILENT" in launched[0]


def test_update_checker_finds_the_installer(monkeypatch) -> None:
    from src.utils import update_checker

    release = {
        "tag_name": "v99.0.0",
        "html_url": "https://github.com/x/releases/tag/v99.0.0",
        "assets": [
            {"name": "UniversalDeathCounter-99.0.0-portable.zip", "size": 1,
             "browser_download_url": "zip"},
            {"name": "UniversalDeathCounterSetup.exe", "size": 4242,
             "browser_download_url": GOOD_URL},
        ],
    }
    monkeypatch.setattr(
        update_checker.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(json.dumps(release).encode()),
    )
    checker = update_checker.UpdateChecker()
    found: list[tuple[str, str]] = []
    checker.update_available.connect(lambda v, u: found.append((v, u)))
    checker._check()
    assert found and checker.installer_url == GOOD_URL and checker.installer_size == 4242


def test_update_button_and_portable_copies_open_the_release_page(window, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox

    import src.ui.main_window as mw

    # Without a tray (as here) the notice is a message box: don't wait for a click.
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window._on_update_available("v99.0.0", "https://github.com/x/releases/tag/v99.0.0")
    assert window._update_btn.isVisibleTo(window) and "v99.0.0" in window._update_btn.text()
    opened: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    monkeypatch.setattr(mw, "is_installed_copy", lambda: False)
    window._start_update()
    assert opened == ["https://github.com/x/releases/tag/v99.0.0"]
