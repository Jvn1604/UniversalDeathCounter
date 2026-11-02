"""
The game's own death count, read from its save file: learned from a few
deaths, then read even when the save changes shape; this cycle only (NG+).
"""

from __future__ import annotations

import json
import os
import random
import struct
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.detection import save_watcher as sw  # noqa: E402
from src.detection.save_deaths import (  # noqa: E402
    SaveLearner,
    SaveLocation,
    read_save,
)


class _Game:
    """A fake game's save: a BND4 file with two character slots."""

    def __init__(self, deaths: int = 412, slot: int = 1, offset: int = 0x1235) -> None:
        rng = random.Random(3)
        self.slots = [bytearray(rng.randbytes(0x8000)) for _ in range(2)]
        self.slot, self.offset, self.deaths = slot, offset, deaths
        self.play_time = 0x2000
        struct.pack_into("<I", self.slots[slot], offset, deaths)
        self._rng = rng

    def autosave(self) -> None:
        """Playing without dying: time passes, some other things change."""
        slot = self.slots[self.slot]
        struct.pack_into("<I", slot, self.play_time,
                         struct.unpack_from("<I", slot, self.play_time)[0] + 4000)
        for _ in range(10):  # other values change by more than one
            spot = self._rng.randrange(0x4000, 0x8000)
            slot[spot] ^= 0x80

    def die(self) -> None:
        self.deaths += 1
        struct.pack_into("<I", self.slots[self.slot], self.offset, self.deaths)
        self.autosave()

    def file(self) -> bytes:
        header = bytearray(b"BND4" + bytes(8) + struct.pack("<i", len(self.slots)))
        header += bytes(0x40 - len(header))
        offset = 0x40 + 0x20 * len(self.slots)
        for slot in self.slots:
            header += bytes(8) + struct.pack("<q", len(slot)) + struct.pack("<i", offset)
            header += bytes(12)
            offset += len(slot)
        return bytes(header) + b"".join(bytes(slot) for slot in self.slots)


def test_the_count_is_learned_from_two_deaths(tmp_path) -> None:
    game = _Game()
    path = tmp_path / "save.sl2"
    learner, app_count = SaveLearner(), 0

    def saved():
        path.write_bytes(game.file())
        return read_save(path)

    learner.observe(saved(), app_count)
    game.autosave()
    assert learner.observe(saved(), app_count) is None
    for _ in range(2):
        game.die()
        app_count += 1
        location = learner.observe(saved(), app_count)
        game.autosave()
        learner.observe(saved(), app_count)
    assert location is not None and (location.entry, location.offset) == (1, 0x1235)
    assert learner.finish(saved()) == 414  # the game's own total, not the app's 2

    # Saved and restored, it keeps reading, even after the save grows before it.
    location = SaveLocation.from_json(location.to_json())
    game.die()
    game.slots[1][0x100:0x100] = bytes(48)  # e.g. a new item in the inventory
    game.offset += 48
    assert location.read(saved()) == 415
    game.die()
    assert location.read(saved()) == 416 and location.offset == 0x1235 + 48


def test_a_death_the_app_missed_starts_learning_again() -> None:
    game = _Game()
    learner = SaveLearner()
    learner.observe([bytes(s) for s in game.slots], 0)
    game.die()
    learner.observe([bytes(s) for s in game.slots], 1)
    assert learner.candidate_count >= 1
    game.die()
    game.die()  # two deaths, but the app counted one
    learner.observe([bytes(s) for s in game.slots], 2)
    assert learner.location is None and learner.candidate_count == 0  # starts over


def test_text_saves_are_learned_too(tmp_path) -> None:
    path = tmp_path / "progress.json"
    learner = SaveLearner()

    def save(deaths: int, gold: int) -> object:
        path.write_text(json.dumps({"gold": gold, "level": 3, "stats": {"deaths": deaths}}))
        return read_save(path)

    learner.observe(save(57, 10), 0)
    learner.observe(save(58, 25), 1)
    location = learner.observe(save(59, 25), 2)
    assert location is not None and location.is_text
    restored = SaveLocation.from_json(location.to_json())
    assert restored.read(save(60, 99)) == 60


def test_shown_count_this_cycle_only() -> None:
    assert sw.shown_count({}) is None
    assert sw.shown_count({"last": 900}) == 900
    assert sw.shown_count({"last": 900, "cycle_only": True, "cycle_base": 850}) == 50
    assert sw.shown_count({"last": 900, "cycle_only": False, "cycle_base": 850}) == 900


def test_the_watcher_reads_the_save_while_playing(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    class _NowThread:  # reads right away: no waiting on the event loop's timing
        def __init__(self, target, **_kwargs) -> None:
            self._target = target

        def start(self) -> None:
            self._target()

    monkeypatch.setattr(sw, "_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(sw, "threading", SimpleNamespace(Thread=_NowThread))
    app = QApplication.instance() or QApplication([])
    game = _Game(deaths=99)
    path = tmp_path / "ER0000.sl2"
    stored: list[dict] = []
    writes: list[int] = []
    watcher = sw.SaveWatcher()
    watcher.config_changed.connect(lambda _game, config: stored.append(config))

    def written() -> None:
        path.write_bytes(game.file())
        writes.append(time.time_ns() + len(writes) * 1_000_000_000)  # a second apart
        os.utime(path, ns=(writes[-1], writes[-1]))
        watcher._poll()
        app.processEvents()

    path.write_bytes(game.file())
    watcher.set_game(5, {"path": str(path)}, deaths=0)
    written()
    assert watcher.learning and "Learning" in watcher.status
    for app_count in (1, 2):
        game.die()
        watcher.note_deaths(app_count)
        written()
    assert stored and stored[-1]["last"] == 101
    assert "101 deaths" in watcher.status
    game.die()
    written()
    assert stored[-1]["last"] == 102  # no app count needed once it's learned
    watcher.stop()


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    monkeypatch.setattr(mw, "find_known_saves", lambda: [])
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    game = win._database.create_game("Elden Ring")
    win._reload_games(select_game_id=game)
    yield win
    win._quit_app()
    app.processEvents()


def test_the_save_count_shows_as_the_big_number(window, tmp_path) -> None:
    from src.ui.main_window import _PAGE_DETECTION

    game_id = window._counter_manager.current_game_id
    save = tmp_path / "ER0000.sl2"
    save.write_bytes(_Game().file())
    window._show_page(_PAGE_DETECTION)
    window._set_save_file(str(save))
    assert window._save_config()["path"] == str(save)
    assert not window._save_show_btn.isEnabled()  # nothing learned yet
    # What the watcher stores once it has learned the count:
    window._on_save_config_changed(game_id, {"path": str(save), "location": None, "last": 1234})
    assert window._save_show_btn.isEnabled()
    window._save_show_btn.click()
    assert window._counter_label.text() == "1234"
    assert window._counter_caption.text() == "IN-GAME DEATHS (SAVE FILE)"
    assert window._overlay.count_text() == "DEATH - 1234"

    window._start_save_cycle()  # NG+ starts
    window._on_save_config_changed(game_id, {"path": str(save), "location": None, "last": 1240})
    assert window._counter_label.text() == "6"
    assert window._counter_caption.text() == "IN-GAME DEATHS THIS CYCLE"
    window._save_cycle_check.setChecked(False)
    assert window._counter_label.text() == "1240"

    window._forget_save_file()
    assert window._save_config() == {}
    assert window._counter_label.text() == "0"
