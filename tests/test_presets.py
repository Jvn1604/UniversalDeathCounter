"""Ready-made auto-detect setups: share a game's setup, import it, use the online library."""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.database.database import SCREEN_DEATH, SCREEN_VICTORY, Database  # noqa: E402
from src.utils import presets  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PATCH = (4).to_bytes(2, "little") + (6).to_bytes(2, "little") + bytes(range(24))


@pytest.fixture()
def database(tmp_path):
    db = Database(tmp_path / "d.db")
    yield db
    db.close()


def _game_with_setup(db: Database) -> int:
    game = db.create_game("Lies of P")
    db.set_game_detection(game, r"C:\Users\someone\Games\LiesofP\LOP.exe", "template")
    db.update_detection_options(game, log_path=r"C:\Users\someone\log.txt", window_title="LOP",
                                obs_source="Elgato", screen_display=2)
    db.add_death_template(game, json.dumps([0.3, 0.4, 0.4, 0.1]), PATCH, SCREEN_DEATH)
    db.add_death_template(game, json.dumps([0.2, 0.1, 0.6, 0.2]), PATCH, SCREEN_VICTORY)
    for boss in ("Parade Master", "Scrapped Watchman"):
        db.create_boss(game, boss)
    return game


def test_a_setup_travels_without_anything_personal(database, tmp_path) -> None:
    game = _game_with_setup(database)
    preset = presets.export_preset(database, game, author="me")
    text = json.dumps(preset)
    assert "someone" not in text and "Elgato" not in text  # no paths, user names, sources
    assert preset["exe_names"] == ["LOP.exe"] and preset["options"] == {"window_title": "LOP"}
    path = tmp_path / presets.preset_file_name(preset)
    assert path.name == "lies-of-p.dudc.json"
    presets.write_preset(path, preset)

    other = Database(tmp_path / "friend.db")
    try:
        friend_game = other.create_game("Lies of P")
        other.create_boss(friend_game, "Parade Master")
        added = presets.apply_preset(other, friend_game, presets.read_preset(path))
        assert added == 2
        assert other.get_game_detection(friend_game)["mode"] == "template"
        assert len(other.get_death_templates(friend_game, SCREEN_DEATH)) == 1
        assert len(other.get_death_templates(friend_game, SCREEN_VICTORY)) == 1
        assert [b["name"] for b in other.get_bosses(friend_game)] == [
            "Parade Master", "Scrapped Watchman"]  # no duplicate
    finally:
        other.close()


@pytest.mark.parametrize("change", [
    lambda p: p.update(format=99),
    lambda p: p.update(mode="hack"),
    lambda p: p["screens"][0].update(region=[0, 0, 5, 1]),
    lambda p: p["screens"][0].update(patch=base64.b64encode(b"\x09\x00\x09\x00xx").decode()),
    lambda p: p.update(screens=p["screens"] * 50),
])
def test_damaged_or_unsafe_setups_are_refused(database, change) -> None:
    preset = presets.export_preset(database, _game_with_setup(database))
    change(preset)
    with pytest.raises(presets.PresetError):
        presets.parse_preset(json.dumps(preset).encode())


def test_the_library_in_this_repository_is_valid() -> None:
    index = json.loads((ROOT / "presets" / "index.json").read_text(encoding="utf-8"))
    files = sorted(p.name for p in (ROOT / "presets").glob("*.dudc.json"))
    assert sorted(item["file"] for item in index["presets"]) == files
    for name in files:
        preset = presets.read_preset(ROOT / "presets" / name)
        assert presets.preset_file_name(preset) == name


def test_the_library_is_only_fetched_from_this_repository(monkeypatch) -> None:
    asked = []

    class _Response:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self, _limit):
            return self.body

    index = (ROOT / "presets" / "index.json").read_bytes()
    monkeypatch.setattr(presets.urllib.request, "urlopen",
                        lambda request, timeout: asked.append(request.full_url) or _Response(index))
    entries = presets.fetch_library()
    assert asked == [presets.LIBRARY_URL + "index.json"]
    assert asked[0].startswith("https://raw.githubusercontent.com/Jvn1604/UniversalDeathCounter/")
    assert any(entry.matches_exe("pbz.EXE") for entry in entries)
    with pytest.raises(presets.PresetError):
        presets._download("https://example.com/evil.json", 100)


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    yield win
    win._quit_app()
    app.processEvents()


def _wait_for(condition) -> None:
    import time

    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def _fake_library(monkeypatch, preset: dict) -> None:
    entry = presets.LibraryEntry(game=preset["game"], file="x.dudc.json",
                                 exe_names=tuple(preset["exe_names"]), mode=preset["mode"],
                                 screens=len(preset["screens"]), author="someone")
    monkeypatch.setattr(presets, "fetch_library", lambda: [entry])
    monkeypatch.setattr(presets, "fetch_preset", lambda _entry: preset)


def test_a_new_game_is_offered_its_library_setup(window, monkeypatch, tmp_path) -> None:
    preset = presets.export_preset(window._database, _game_with_setup(window._database))
    _fake_library(monkeypatch, preset)
    game = window._database.create_game("My Lies of P")
    window._database.set_game_detection(game, r"D:\Games\LOP.exe", "template")
    window._reload_games(select_game_id=game)
    window._suggest_library_setup(game, "LOP.exe")
    _wait_for(lambda: window._toast.isVisible())
    assert "ready-made setup for Lies of P" in window._toast._text.text()
    window._toast.action.click()  # Use It
    _wait_for(lambda: window._database.get_death_templates(game))
    assert len(window._database.get_death_templates(game)) == 1
    assert window._database.get_game_detection(game)["exe_path"] == r"D:\Games\LOP.exe"


def test_the_library_window_applies_a_setup(window, monkeypatch) -> None:
    from src.ui.library_window import LibraryDialog

    preset = presets.export_preset(window._database, _game_with_setup(window._database))
    _fake_library(monkeypatch, preset)
    game = window._database.create_game("Fresh Game")
    dialog = LibraryDialog(window._database, game, "Fresh Game", window)
    _wait_for(lambda: dialog._list.count() == 1)
    dialog._list.setCurrentRow(0)
    applied = []
    dialog.applied.connect(applied.append)
    dialog._use_btn.click()
    _wait_for(lambda: applied)
    assert applied == ["Lies of P"]
    assert len(window._database.get_death_templates(game)) == 1
