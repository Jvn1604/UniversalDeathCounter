"""
v2.16.0 polish round: settings don't change by scrolling, Save shows a toast
with Undo, more ways to write the count, and "Hide From My Screen" keeps the
overlay on stream through the OBS Browser Source page.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.overlay.count_text import CountStyle  # noqa: E402


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
    game = win._database.create_game("Lies of P")
    win._reload_games(select_game_id=game)
    yield win
    win._quit_app()
    app.processEvents()


# ---------------------------------------------------------------- count text
def test_the_count_can_be_written_many_ways() -> None:
    assert CountStyle().plain(12) == "DEATH - 12"
    assert CountStyle(separator=":").plain(12) == "DEATH: 12"
    assert CountStyle(separator="").plain(12) == "DEATH 12"
    assert CountStyle(separator="×").plain(3) == "DEATH × 3"
    assert CountStyle(word="DEATHS", word_after=True, separator="").plain(7) == "7 DEATHS"
    assert CountStyle(word="").plain(5) == "5"
    html = CountStyle(word_color="#00ff00", number_color="#ff0000", word_size=50).html(9, 40)
    assert "color:#00ff00;font-size:20px" in html and "color:#ff0000;font-size:40px" in html


def test_overlay_settings_change_the_count(window) -> None:
    window._database.set_setting("overlay_separator", ":")
    window._database.set_setting("overlay_word_color", "#33ccff")
    window._database.set_setting("overlay_word_after", "false")
    window._apply_appearance(window._database.get_all_settings())
    window._on_increment()
    assert window._overlay.count_text() == "DEATH: 1"
    assert "#33ccff" in window._overlay._death_label.text()


# ---------------------------------------------------------------- settings polish
def test_scrolling_over_a_setting_doesnt_change_it(window) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from src.ui.main_window import _PAGE_SETTINGS

    window._show_page(_PAGE_SETTINGS)
    combo = window._settings._bg_mode_combo
    before = combo.currentIndex()
    event = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    QApplication.sendEvent(combo, event)
    assert combo.currentIndex() == before
    assert combo.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_save_shows_a_toast_with_undo(window) -> None:
    from src.ui.main_window import _PAGE_SETTINGS

    window._show_page(_PAGE_SETTINGS)
    settings = window._settings
    db = window._database
    assert db.get_setting("confirm_close") == "true"
    settings._confirm_close_check.setChecked(False)
    settings._save()
    assert db.get_setting("confirm_close") == "false"
    toast = window._toast
    assert toast.isVisibleTo(window) and "saved" in toast._text.text()
    assert toast.action.text().startswith("Undo (5")
    toast.action.click()  # Undo
    assert db.get_setting("confirm_close") == "true"
    assert settings._confirm_close_check.isChecked()
    assert not settings.has_changes()


# ---------------------------------------------------------------- hide from screen / stream
def test_hide_from_my_screen_keeps_it_on_for_the_stream(window, monkeypatch) -> None:
    import src.ui.main_window as mw

    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: None)
    window._toggle_overlay()
    assert window._overlay.isVisible() and window._overlay_nav.is_on()
    window._on_increment()
    window._hide_overlay_from_screen()
    assert not window._overlay.isVisible()
    assert window._overlay_nav.is_on()  # still ON: it's only hidden from the screen
    assert window._stream.running
    with urllib.request.urlopen(window._stream.url() + "state", timeout=5) as response:
        state = json.loads(response.read())
    assert state["active"] is True and state["number"] == 1
    assert "DEATH" in state["count_html"]
    with urllib.request.urlopen(window._stream.url(), timeout=5) as response:
        assert b"fetch(\"/state\"" in response.read()

    window._toggle_overlay()  # the overlay key / sidebar: shows it again
    assert window._overlay.isVisible() and window._overlay_nav.is_on()
    window._turn_overlay_off()
    assert not window._overlay.isVisible() and not window._overlay_nav.is_on()
    assert window._stream.state()["active"] is False  # off on stream too


def test_obs_setup_browser_source_turns_it_on(window) -> None:
    url = window._enable_stream_for_obs()
    assert url.startswith("http://127.0.0.1:")
    assert window._database.get_setting("stream_overlay") == "true"
    assert window._overlay_nav.is_on()  # ON for the stream, not in the way on screen


def test_a_second_copy_never_shares_the_stream_port() -> None:
    from PySide6.QtWidgets import QApplication

    from src.utils.stream_overlay import StreamOverlay

    QApplication.instance() or QApplication([])
    first, second = StreamOverlay(), StreamOverlay()
    try:
        first.start()
        second.start(port=int(first.url().rsplit(":", 1)[1].strip("/")))
        assert first.url() != second.url()  # the taken port is skipped, not shared
        first.set_state({"active": True, "number": 1})
        second.set_state({"active": True, "number": 2})
        for overlay, number in ((first, 1), (second, 2)):
            with urllib.request.urlopen(overlay.url() + "state", timeout=5) as response:
                assert json.loads(response.read())["number"] == number
    finally:
        first.stop()
        second.stop()
