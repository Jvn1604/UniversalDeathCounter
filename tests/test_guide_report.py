"""
Release 4: a guide that teaches, reporting bugs, the error log, and
detection without the .exe that's easy to find.
"""

from __future__ import annotations

import logging
import os
import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ui import report_window as rw  # noqa: E402


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    monkeypatch.setattr(mw, "list_displays", lambda: [(1, "Display 1"), (2, "Display 2")])
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    yield win
    win._quit_app()
    app.processEvents()


# ---------------------------------------------------------------- error log and reports
def _log(tmp_path: Path) -> Path:
    home = str(Path.home())
    log = tmp_path / "app.log"
    log.write_text(
        "2026-10-31 10:00:00 | INFO     | src.a | Started\n"
        f"2026-10-31 10:00:01 | WARNING  | src.b | Theme missing in {home}\\saves\n"
        "2026-10-31 10:00:02 | ERROR    | src.c | Death watcher stopped\n"
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in run\n'
        "ValueError: boom\n"
        "2026-10-31 10:00:03 | INFO     | src.a | Fine again\n",
        encoding="utf-8",
    )
    return log


def test_log_tail_keeps_problems_and_their_tracebacks(tmp_path) -> None:
    log = _log(tmp_path)
    problems = rw.log_tail(problems_only=True, log_file=log)
    assert "Started" not in problems and "Fine again" not in problems
    assert "Death watcher stopped" in problems and "ValueError: boom" in problems
    assert str(Path.home()) not in problems and "~\\saves" in problems  # user name removed
    assert "Fine again" in rw.log_tail(log_file=log)


def test_issue_link_is_prefilled_and_short_enough() -> None:
    log = "\n".join(f"2026-10-31 | ERROR | x | problem {i} " + "x" * 80 for i in range(400))
    url = rw.issue_url("Overlay vanishes", "It disappears", "1. Alt-tab", "- Version: v9", log)
    assert url.startswith(rw.ISSUE_URL) and len(url) <= 7800
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert query["title"] == ["Overlay vanishes"] and query["labels"] == ["bug"]
    body = query["body"][0]
    assert "It disappears" in body and "1. Alt-tab" in body and "Version: v9" in body
    assert "problem 399" in body  # the newest lines are kept


def test_report_dialog_opens_github(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    opened: list[str] = []
    monkeypatch.setattr(rw.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    dialog = rw.ReportBugDialog(extra_details={"Theme": "glass"}, log_file=_log(tmp_path))
    dialog.title_edit.setText("Counter froze")
    dialog.what_edit.setPlainText("It stopped at 12")
    dialog.open_button.click()
    assert opened and opened[0].startswith(rw.ISSUE_URL)
    body = urllib.parse.parse_qs(urllib.parse.urlsplit(dialog.opened_url).query)["body"][0]
    assert "It stopped at 12" in body and "Theme: glass" in body and "ValueError" in body
    dialog.log_check.setChecked(False)
    dialog.details_check.setChecked(False)
    body = urllib.parse.parse_qs(urllib.parse.urlsplit(dialog.url()).query)["body"][0]
    assert "ValueError" not in body and "(not shared)" in body


def test_errors_turn_the_bug_button_red(window) -> None:
    from PySide6.QtWidgets import QApplication

    logging.getLogger("dudc.test").error("something broke")
    QApplication.processEvents()
    assert window._problems.count >= 1
    assert "error" in window._bug_button.toolTip()


def test_error_log_window_shows_problems(tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    log_window = rw.ErrorLogWindow(log_file=_log(tmp_path))
    assert "Death watcher stopped" in log_window.text.toPlainText()
    assert "Started" not in log_window.text.toPlainText()
    log_window.problems_check.setChecked(False)
    assert "Started" in log_window.text.toPlainText()


# ---------------------------------------------------------------- the guide
def test_learn_tab_teaches_every_major_feature(window) -> None:
    from src.ui.guide_dialog import LESSONS, GuideDialog

    dialog = GuideDialog({"increment": "F9", "calibrate": "F8"}, parent=window)
    titles = [dialog.lessons.item(i).text() for i in range(dialog.lessons.count())]
    for topic in ("Counting deaths", "Auto-detect without the .exe", "Speedrun timer",
                  "Overlay and OBS", "Something not working?"):
        assert topic in titles
    assert dialog.lesson_pages.count() == len(LESSONS)
    handled: list[str] = []
    dialog.action_requested.connect(handled.append)
    for _title, _icon, text, button in LESSONS:
        assert "{" not in text.format(**{k: "K" for k in (
            "increment", "decrement", "undo", "calibrate", "toggle_overlay",
            "timer_split", "timer_pause", "timer_reset")})
        if button is not None:
            dialog.action_requested.emit(button[2])  # every lesson's button sends an action
    assert len(handled) == sum(1 for lesson in LESSONS if lesson[3] is not None)


def test_guide_buttons_reach_their_place(window, monkeypatch) -> None:
    import src.ui.main_window as mw
    from src.ui.guide_dialog import ACTION_APPEARANCE, ACTION_REPORT, ACTION_SAVE
    from src.ui.settings_window import SettingsWindow

    called: list[str] = []
    monkeypatch.setattr(window, "_save_progress", lambda: called.append("save"))
    monkeypatch.setattr(window, "_open_report_bug", lambda: called.append("report"))
    window._on_guide_action(ACTION_SAVE)
    window._on_guide_action(ACTION_REPORT)
    window._on_guide_action(ACTION_APPEARANCE)
    assert called == ["save", "report"]
    assert window._pages.currentIndex() == mw._PAGE_SETTINGS
    assert window._settings._tabs.currentIndex() == SettingsWindow.TAB_APPEARANCE


# ---------------------------------------------------------------- no .exe, easy to find
def test_add_a_game_without_its_exe(window, monkeypatch) -> None:
    import src.ui.main_window as mw
    from src.utils.constants import DETECTION_MODE_TEMPLATE, OPTION_SCREEN_DISPLAY

    combo = window._game_combo
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert "+ Add game without .exe…" in labels
    monkeypatch.setattr(mw.QInputDialog, "getText", lambda *a, **k: ("Cloud Game", True))
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: None)
    combo.setCurrentIndex(combo.findData(mw._ADD_NO_EXE_SENTINEL))
    game = window._counter_manager.current_game_id
    assert combo.currentText() == "Cloud Game"
    db = window._database
    assert db.get_game_detection(game)["mode"] == DETECTION_MODE_TEMPLATE
    assert db.get_detection_options(game)[OPTION_SCREEN_DISPLAY] in (1, 2)
    assert window._pages.currentIndex() == mw._PAGE_DETECTION
    assert window._watch_buttons.checkedId() == 1  # "A whole display" is shown chosen


def test_detection_page_switches_what_to_watch(window, monkeypatch) -> None:
    import src.ui.main_window as mw
    from src.utils.constants import DETECTION_MODE_TEMPLATE, OPTION_SCREEN_DISPLAY

    db = window._database
    game = db.create_game("Hades")
    window._reload_games(select_game_id=game)
    window._show_page(mw._PAGE_DETECTION)
    assert window._watch_card.isVisibleTo(window)
    window._watch_display_combo.setCurrentIndex(1)
    window._watch_buttons.button(1).click()  # A whole display
    assert db.get_detection_options(game)[OPTION_SCREEN_DISPLAY] == 2
    assert db.get_game_detection(game)["mode"] == DETECTION_MODE_TEMPLATE
    exe = Path(db.path).parent / "Hades.exe"
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", lambda *a, **k: (str(exe), ""))
    window._watch_buttons.button(0).click()  # back to the game's window: asks for the .exe
    assert OPTION_SCREEN_DISPLAY not in db.get_detection_options(game)
    assert db.get_game_detection(game)["exe_path"] == str(exe)


def test_setup_window_shows_watch_even_when_detection_is_off(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    import src.ui.auto_detect_window as adw
    from src.database.database import Database
    from src.utils.constants import DETECTION_MODE_OFF, DETECTION_MODE_TEMPLATE

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(adw, "list_displays", lambda: [(1, "Display 1")])
    db = Database(tmp_path / "d.db")
    game = db.create_game("New Game")
    dialog = adw.AutoDetectWindow(db, game, "New Game")
    assert dialog._mode_combo.currentData() == DETECTION_MODE_OFF
    assert dialog._form.isRowVisible(dialog._source_combo)  # visible before choosing a method
    dialog._source_combo.setCurrentIndex(1)
    assert dialog._mode_combo.currentData() == DETECTION_MODE_TEMPLATE  # turned on for you
    db.close()
