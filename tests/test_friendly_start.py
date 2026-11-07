"""A first start: adding a game is one click away, and nothing pretends to work without one."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


def test_add_your_first_game_offers_the_ways_to_add_one(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QMenu

    import src.ui.main_window as mw

    shown: list[list[str]] = []

    class _Menu(QMenu):  # records instead of waiting for a click
        def exec(self, *_args):
            texts = [action.text() for action in self.actions() if action.text()]
            shown.append(texts)
            ready = next(a.menu() for a in self.actions() if a.menu() is not None)
            shown.append([action.text() for action in ready.actions()])

    monkeypatch.setattr(mw, "QMenu", _Menu)
    window._first_game_btn.click()
    assert shown[0][0].startswith("Pick the game's .exe")
    assert shown[0][1].startswith("Game without .exe")
    assert "Ready-made boss list" in shown[0]
    assert "Elden Ring" in shown[1]
    window._open_counter_or_add_game()  # Home's button does the same
    assert len(shown) == 4


def test_buttons_that_need_a_game_wait_for_one(window) -> None:
    assert not window._plus_btn.isEnabled() and not window._sessions_btn.isEnabled()
    assert window._minus_btn.toolTip().endswith("Add a game first.")
    assert "counted by mistake" in window._minus_btn.toolTip()  # its own tip stays
    window._add_template_game("Elden Ring")
    assert all(widget.isEnabled() for widget in window._needs_game)
    assert not window._minus_btn.toolTip().endswith("Add a game first.")


def test_buttons_look_usable_again_once_a_game_is_added(window) -> None:
    from PySide6.QtWidgets import QLabel

    def colors() -> set[str]:
        labels = [label for label in window._minus_btn.findChildren(QLabel) if label.text()]
        return {label.palette().windowText().color().name() for label in labels}

    greyed = colors()  # no game yet
    window._add_template_game("Elden Ring")
    assert colors() != greyed  # the labels left their greyed-out colour behind
