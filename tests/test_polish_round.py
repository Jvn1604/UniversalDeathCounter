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
def test_hide_from_my_screen_keeps_it_on_for_the_stream(window) -> None:
    from PySide6.QtCore import Qt

    window._toggle_overlay()
    assert window._overlay.isVisible() and window._overlay_nav.is_on()
    window._on_increment()
    window._hide_overlay_from_screen()
    overlay = window._overlay
    # Still open (OBS can't capture a hidden window), but behind everything and
    # letting clicks through: out of the player's way.
    assert overlay.isVisible()
    assert not overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert window._overlay_nav.is_on()
    window._on_increment()  # the count keeps updating while it's behind
    assert overlay.count_text() == "DEATH - 2"
    assert window._stream.running
    with urllib.request.urlopen(window._stream.url() + "state", timeout=5) as response:
        state = json.loads(response.read())
    assert state["active"] is True and state["number"] == 2
    with urllib.request.urlopen(window._stream.url(), timeout=5) as response:
        assert b"fetch(\"/state\"" in response.read()

    window._toggle_overlay()  # the overlay key / sidebar: back in front, as set up
    assert overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert not overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    window._turn_overlay_off()
    assert not overlay.isVisible() and not window._overlay_nav.is_on()
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


def test_save_lights_up_only_when_something_changed(window) -> None:
    from src.ui.main_window import _PAGE_SETTINGS

    window._show_page(_PAGE_SETTINGS)
    settings = window._settings
    assert not settings._save_button.isEnabled()  # nothing to save yet
    assert not settings._cancel_button.isEnabled()
    check = settings._confirm_close_check
    check.setChecked(not check.isChecked())
    settings._update_save_buttons()  # what the short timer does
    assert settings._save_button.isEnabled() and settings._cancel_button.isEnabled()
    check.setChecked(not check.isChecked())  # changed back: nothing to save again
    settings._update_save_buttons()
    assert not settings._save_button.isEnabled()
    check.setChecked(not check.isChecked())
    settings._save()
    assert not settings._save_button.isEnabled()  # saved
    import time

    from PySide6.QtWidgets import QApplication

    end = time.monotonic() + 0.5  # the app reloads its settings: still nothing to save
    while time.monotonic() < end:
        QApplication.processEvents()
    assert not settings._save_button.isEnabled() and not settings.has_changes()
    check.setChecked(not check.isChecked())
    settings.reject()  # Discard Changes
    assert not settings._save_button.isEnabled()


def test_detection_page_names_the_next_setup_step(window) -> None:
    from src.utils.constants import DETECTION_MODE_TEMPLATE

    game = window._counter_manager.current_game_id
    window._refresh_detection_page()
    assert "Step 1 of 3" in window._detect_page_info.text()
    window._database.set_game_detection(game, "C:/Games/LOP.exe", DETECTION_MODE_TEMPLATE)
    window._refresh_detection_page()
    assert "Step 2 of 3" in window._detect_page_info.text()
    assert "F8" in window._detect_page_info.text()
    window._database.add_death_template(game, "[0.3, 0.4, 0.4, 0.15]", b"\x01\x00\x01\x00\x80")
    window._refresh_detection_page()
    assert "Step 3 of 3" in window._detect_page_info.text()


def test_a_death_key_with_no_game_says_so_once_in_a_while(window, monkeypatch) -> None:
    said: list[str] = []
    monkeypatch.setattr(window._toast, "say", lambda text, **_k: said.append(text))
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    window._counter_manager.set_current_game(None, None)
    for _ in range(10):
        window._on_increment()
    assert len(said) == 1 and "wasn't counted" in said[0]
    assert window._database.get_total_deaths() == 0


def test_clear_all_data_keeps_a_copy_to_load_back(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from src.utils import save_files

    window._on_increment()
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    window._clear_all_data()
    assert window._database.get_games() == []
    folder = save_files.saves_folder(window._database.path)
    backups = list(folder.glob("Before clearing *.json"))
    assert len(backups) == 1
    data = save_files.read_save(backups[0])
    assert [g["name"] for g in data["games"]] == ["Lies of P"]
    assert len(data["death_events"]) == 1


def test_quick_autosave_isnt_put_off_by_every_death(window) -> None:
    window._progress_soon.stop()
    window._on_increment()
    assert window._progress_soon.isActive()
    first = window._progress_soon.remainingTime()
    import time

    time.sleep(0.05)
    window._on_increment()  # another death: the save still comes 15 s after the first
    assert window._progress_soon.remainingTime() < first


def test_a_save_file_held_for_a_moment_is_written_anyway(tmp_path, monkeypatch) -> None:
    import os

    from src.utils import save_files

    real_replace, calls = os.replace, []

    def busy_then_free(src, dst):
        calls.append(dst)
        if len(calls) < 3:
            raise PermissionError("held by OneDrive")
        real_replace(src, dst)

    monkeypatch.setattr(save_files.os, "replace", busy_then_free)
    monkeypatch.setattr(save_files.time, "sleep", lambda s: None)
    save_files.write_save(tmp_path / "a.json", {"games": []})
    assert save_files.read_save(tmp_path / "a.json") == {"games": []} and len(calls) == 3
