"""
The bug-sheet round: the overlay keeps counting while hidden, the app comes
back as it was left, every change says so, saving is automatic and visible,
and reports can go to the bug sheet.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _open(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    QApplication.instance() or QApplication([])
    return mw.MainWindow()


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    win = _open(tmp_path, monkeypatch)
    game = win._database.create_game("Lies of P")
    win._reload_games(select_game_id=game)
    win.show()
    yield win
    win._quit_app()
    QApplication.processEvents()


# ---------------------------------------------------------------- BUG-002
def test_the_app_comes_back_as_it_was_left(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw

    first = _open(tmp_path, monkeypatch)
    game = first._database.create_game("Lies of P")
    first._reload_games(select_game_id=game)
    first._toggle_overlay()  # overlay ON
    first._show_page(mw._PAGE_TIMER)
    first._quit_app()
    QApplication.processEvents()

    second = _open(tmp_path, monkeypatch)
    QApplication.processEvents()
    try:
        assert second._overlay.isVisible()  # ON again, no re-setup
        assert second._pages.currentIndex() == mw._PAGE_TIMER
        second._hide_overlay_from_screen(announce=False)
    finally:
        second._quit_app()
        QApplication.processEvents()
    third = _open(tmp_path, monkeypatch)
    QApplication.processEvents()
    try:
        assert third._overlay_hidden_local  # still behind the windows, still ON
        assert third._overlay_nav.is_on()
    finally:
        third._quit_app()
        QApplication.processEvents()


def test_closing_with_unsaved_settings_asks_to_save(window, monkeypatch) -> None:
    import src.ui.main_window as mw

    window._show_page(mw._PAGE_SETTINGS)
    window._settings._confirm_close_check.setChecked(False)
    monkeypatch.setattr(
        mw.QMessageBox, "exec",
        lambda box: next(b for b in box.buttons() if b.text() == "Save").click(),
    )
    window._quit_app()
    assert window._closed
    assert window._database.path.exists()
    from src.database.database import Database

    reopened = Database(window._database.path)
    assert reopened.get_setting("confirm_close") == "false"  # kept, not thrown away
    reopened.close()


# ---------------------------------------------------------------- BUG-003
def test_changes_say_so_in_the_window(window, monkeypatch) -> None:
    import src.ui.main_window as mw

    monkeypatch.setattr(mw.QInputDialog, "getText", lambda *a, **k: ("Lies of P 2", True))
    window._rename_current_game()
    assert "renamed" in window._toast._text.text()
    window._notify("Hello")  # used to go to the tray only
    assert window._toast.isVisibleTo(window) and window._toast._text.text() == "Hello"


def test_games_and_bosses_say_so_too(window, monkeypatch) -> None:
    import src.ui.boss_window as bw

    dialog = bw.BossWindow(window._database, parent=window)
    monkeypatch.setattr(bw.QInputDialog, "getText", lambda *a, **k: ("Hades", True))
    dialog._create_game()
    assert dialog._toast._text.text() == "Game added: Hades"
    dialog.close()


# ---------------------------------------------------------------- BUG-004
def test_progress_saves_itself_after_a_change(window) -> None:
    window._on_increment()
    assert window._progress_soon.isActive()  # a full save file follows shortly
    window._progress_soon.timeout.emit()
    assert window._saved_label.text().startswith("Auto-saved")


# ---------------------------------------------------------------- bug sheet
def test_report_goes_to_the_bug_sheet(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    import src.ui.report_window as rw
    from src.utils.constants import BUG_SHEET_URL

    opened: list[str] = []
    monkeypatch.setattr(rw.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    dialog = rw.ReportBugDialog(parent=window)
    dialog.what_edit.setPlainText("Overlay froze")
    dialog.sheet_button.click()
    assert opened == [BUG_SHEET_URL]
    assert "Overlay froze" in QApplication.clipboard().text()  # ready to paste in a row
    texts = [a.text() for a in window._more_menu.actions()]
    assert any("Bug Sheet" in text for text in texts)
