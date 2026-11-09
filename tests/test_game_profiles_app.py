"""The app with one game per profile: upgrading, adding a game, a game launching."""

from __future__ import annotations

import pytest

from src.database.database import Database


@pytest.fixture()
def start(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    app = QApplication.instance() or QApplication([])
    windows = []

    def make():
        window = mw.MainWindow()
        windows.append(window)
        return window

    yield make, tmp_path, monkeypatch, QInputDialog
    for window in windows:
        window._quit_app()
    app.processEvents()


def _default_db(tmp_path) -> Database:
    return Database(tmp_path / "death_counter.db")


def test_upgrading_moves_each_game_and_opens_the_last_one(start) -> None:
    make, tmp_path, _monkeypatch, _dialog = start
    db = _default_db(tmp_path)
    db.set_setting("hotkey_increment", "f7")
    elden = db.create_game("Elden Ring")
    hollow = db.create_game("Hollow Knight")
    session = db.start_session(hollow)
    for _ in range(4):
        db.add_death_event(hollow, None, session, 1)
    db.set_setting("last_game_id", str(hollow))
    db.close()
    assert elden != hollow

    window = make()
    assert window._profile_manager.list_profiles() == ["Default", "Elden Ring", "Hollow Knight"]
    assert window._profile_manager.active_profile == "Hollow Knight"
    assert window._counter_manager.get_snapshot().game_name == "Hollow Knight"
    assert window._counter_manager.get_snapshot().total_deaths == 4
    assert window._database.get_setting("hotkey_increment", "") == "f7"


def test_a_new_game_gets_its_own_profile_and_settings_follow(start) -> None:
    make, tmp_path, monkeypatch, dialog = start
    window = make()
    window._database.set_setting("hotkey_increment", "f6")
    monkeypatch.setattr(dialog, "getText", staticmethod(lambda *a, **k: ("Sekiro", True)))
    window._add_game_without_exe()
    assert window._profile_manager.active_profile == "Sekiro"
    assert window._counter_manager.get_snapshot().game_name == "Sekiro"
    assert window._database.get_setting("hotkey_increment", "") == "f6"
    window._on_increment()
    assert window._counter_manager.get_snapshot().total_deaths == 1

    monkeypatch.setattr(dialog, "getText", staticmethod(lambda *a, **k: ("Lies of P", True)))
    window._add_game_without_exe()  # from Sekiro's profile: another profile again
    assert window._profile_manager.active_profile == "Lies of P"
    sekiro = Database(window._profile_manager.db_path("Sekiro"))
    assert [g["name"] for g in sekiro.get_games()] == ["Sekiro"]
    sekiro.close()


def test_a_game_launching_switches_to_its_profile(start) -> None:
    import src.ui.main_window as mw

    make, tmp_path, monkeypatch, _dialog = start
    db = _default_db(tmp_path)
    for name in ("Elden Ring", "Hollow Knight"):
        game = db.create_game(name)
        db.set_game_detection(game, f"C:/Games/{name}.exe", "template")
    db.close()
    window = make()
    playing = window._profile_manager.active_profile
    other = "Hollow Knight" if playing == "Elden Ring" else "Elden Ring"
    monkeypatch.setattr(
        mw, "running_exe_paths", lambda paths: [p for p in paths if other in p]
    )
    window._check_game_launches()
    assert window._profile_manager.active_profile == other
    window._check_game_launches()  # then counts in it, like any launch
    assert window._counter_manager.get_snapshot().game_name == other
