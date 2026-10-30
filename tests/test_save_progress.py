"""
Save files that carry on where you were: the session and speedrun run in
progress come back on Load Save. Auto-save, Save Progress, and the
"Close the app?" question that saves before it asks.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.speedrun import PAUSED  # noqa: E402
from src.utils import save_files  # noqa: E402

REAL_CLOSE_QUESTION = True  # conftest: don't skip the close question here
SPLITS = ["Margit", "Godrick", "Rennala"]


def _make_window(folder: Path, monkeypatch):
    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", folder)
    monkeypatch.setattr(profiles, "DATABASE_PATH", folder / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (folder,))
    return mw.MainWindow()


@pytest.fixture()
def windows(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    made = []

    def make(name: str):
        folder = tmp_path / name
        folder.mkdir()
        window = _make_window(folder, monkeypatch)
        made.append(window)
        return window

    yield make
    for window in made:
        window._quit_app(confirm=False)
    app.processEvents()


def _play(window) -> int:
    """Phantom Blade Zero: 2 deaths last session, 3 this one, a run at Margit."""
    db = window._database
    game = db.create_game("Phantom Blade Zero")
    db.set_speedrun_splits(game, SPLITS)
    window._reload_games(select_game_id=game)
    for _ in range(2):
        window._on_increment()
    window._counter_manager.reset_session()
    act = window._action_handlers
    act["timer_split"]()  # start the run
    act["timer_split"]()  # Margit
    for _ in range(3):
        window._on_increment()
    return game


def test_a_save_carries_the_session_and_run_in_progress(windows) -> None:
    window = windows("pc1")
    _play(window)
    data = window._save_data()
    resume = data[save_files.RESUME_KEY]
    assert resume["game_name"] == "Phantom Blade Zero"
    assert resume["session_deaths"] == 3
    assert resume["run"]["deaths"] == 3 and len(resume["run"]["split_times"]) == 1
    text = save_files.describe(data)
    assert "session: 3 deaths" in text and "split 2/3" in text


def test_loading_a_save_on_another_pc_carries_on(windows, tmp_path) -> None:
    old = windows("old_pc")
    _play(old)
    path = tmp_path / "my save.json"
    save_files.write_save(path, old._save_data())

    new = windows("new_pc")
    new._apply_save(save_files.read_save(path), "replace")

    snapshot = new._counter_manager.get_snapshot()
    assert (snapshot.session_deaths, snapshot.total_deaths) == (3, 5)
    timer = new._speedrun.timer
    assert timer.state == PAUSED  # waits for the pause key
    assert len(timer.split_times) == 1 and timer.deaths == 3
    new._on_increment()  # keeps counting in the same session and run
    assert new._counter_manager.get_snapshot().session_deaths == 4
    assert timer.deaths == 4


def test_replace_saves_your_data_first(windows, tmp_path) -> None:
    window = windows("pc")
    _play(window)
    data = window._save_data()
    window._database.create_game("Hollow Knight")
    window._apply_save(data, "replace")
    games = sorted(g["name"] for g in window._database.get_games())
    assert games == ["Phantom Blade Zero"]
    befores = list(save_files.saves_folder(window._database.path).glob("before loading *.json"))
    assert len(befores) == 1
    kept = {g["name"] for g in save_files.read_save(befores[0])["games"]}
    assert kept == {"Phantom Blade Zero", "Hollow Knight"}


def test_add_alongside_resumes_the_imported_copy(windows) -> None:
    window = windows("pc")
    _play(window)
    data = window._save_data()
    window._apply_save(data, "merge")
    names = sorted(g["name"] for g in window._database.get_games())
    assert names == ["Phantom Blade Zero", "Phantom Blade Zero (Imported)"]
    current = window._database.get_game(window._counter_manager.current_game_id)
    assert current["name"] == "Phantom Blade Zero (Imported)"
    assert window._counter_manager.get_snapshot().session_deaths == 3


def test_older_backups_still_load(windows) -> None:
    window = windows("pc")
    _play(window)
    data = window._database.export_data()  # no "resume" part
    other = windows("pc2")
    other._apply_save(data, "replace")
    assert [g["name"] for g in other._database.get_games()] == ["Phantom Blade Zero"]
    assert "nothing in progress" in save_files.describe(data)


def test_auto_save_writes_only_when_something_changed(windows) -> None:
    window = windows("pc")
    assert window._write_progress_autosave() is None  # no games yet: nothing to save
    window._database.create_game("Lies of P")
    window._reload_games()
    path = window._write_progress_autosave()
    assert path == save_files.autosave_path(window._database.path) and path.exists()
    first = path.stat().st_mtime_ns
    os.utime(path, ns=(first - 10_000_000_000, first - 10_000_000_000))
    stamped = path.stat().st_mtime_ns
    window._write_progress_autosave()
    assert path.stat().st_mtime_ns == stamped  # unchanged: not rewritten
    window._on_increment()
    window._write_progress_autosave()
    assert path.stat().st_mtime_ns != stamped
    assert not path.with_name(path.name + ".tmp").exists()


def _answer_close_question(monkeypatch, button_text: str, never_again: bool = False):
    from PySide6.QtWidgets import QMessageBox

    asked = []

    def exec_(box):
        asked.append(box.informativeText())
        box.checkBox().setChecked(never_again)
        for button in box.buttons():
            if button.text().replace("&", "") == button_text:
                button.click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    return asked


def test_closing_asks_first_and_saves_before_asking(windows, monkeypatch) -> None:
    window = windows("pc")
    _play(window)
    asked = _answer_close_question(monkeypatch, "Cancel")
    window._quit_app()
    assert asked and "saved" in asked[0]
    assert not window._closed  # Cancel keeps the app open
    path = save_files.autosave_path(window._database.path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved[save_files.RESUME_KEY]["run"]["deaths"] == 3

    asked = _answer_close_question(monkeypatch, "Close", never_again=True)
    window._quit_app()
    assert window._closed and asked


def test_dont_ask_again_turns_the_question_off(windows, monkeypatch) -> None:
    from src.utils.constants import SETTING_CONFIRM_CLOSE

    window = windows("pc")
    window._database.create_game("Lies of P")
    window._reload_games()
    _answer_close_question(monkeypatch, "Close", never_again=True)
    assert window._confirm_close()
    assert window._database.get_setting(SETTING_CONFIRM_CLOSE) == "false"
    asked = _answer_close_question(monkeypatch, "Cancel")
    assert window._confirm_close() and not asked  # no question any more
    assert save_files.autosave_path(window._database.path).exists()
