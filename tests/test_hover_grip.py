"""The resize grip only shows on hover, and color buttons never cut off their text."""

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


def _hover(widget, inside: bool) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtWidgets import QApplication

    event = QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)) if inside else QEvent(
        QEvent.Type.Leave
    )
    QApplication.sendEvent(widget, event)


def test_resize_grip_only_shows_while_hovering(window) -> None:
    from PySide6.QtWidgets import QApplication

    for capture in (window._overlay, window._timer_window):
        capture.setGeometry(300, 300, 320, 170)  # away from the test cursor
        capture.show()
        QApplication.processEvents()
        grip = capture._size_grip
        assert not grip.isVisible()  # never on stream
        _hover(capture, True)
        assert grip.isVisible()
        assert grip.geometry().bottomRight() == capture.rect().bottomRight()
        _hover(capture, False)
        assert not grip.isVisible()
        capture.hide()


def test_settings_preview_has_no_grip(window) -> None:
    from src.ui.main_window import _PAGE_SETTINGS

    window._show_page(_PAGE_SETTINGS)
    preview = window._settings._overlay_preview
    _hover(preview, True)
    assert not preview._size_grip.isVisible()


def test_color_button_fits_its_text(window) -> None:
    from PySide6.QtGui import QFontMetrics

    from src.ui.main_window import _PAGE_SETTINGS

    window._show_page(_PAGE_SETTINGS)
    choice = window._settings._word_color
    button = choice._button
    assert button.text() == "Same as number"
    text = QFontMetrics(button.font()).horizontalAdvance(button.text())
    assert button.minimumWidth() > text
    choice.set_color("#33ccff")
    assert button.minimumWidth() >= 90
    choice.set_color("")  # unsaved changes would ask on close


def test_grip_goes_when_clicks_pass_through(window) -> None:
    overlay = window._overlay
    overlay.setGeometry(300, 300, 320, 170)
    window._toggle_overlay()
    _hover(overlay, True)
    assert overlay._size_grip.isVisible()
    window._hide_overlay_from_screen(announce=False)  # behind + click-through
    assert overlay.isVisible() and not overlay._size_grip.isVisible()


def test_profile_overlay_state_is_followed(window) -> None:
    from PySide6.QtWidgets import QApplication

    db = window._database
    window._toggle_overlay()
    db.set_setting("overlay_state", "off")  # as another profile would have it
    window._apply_saved_settings()
    assert not window._overlay_active()
    db.set_setting("overlay_state", "behind")
    window._apply_saved_settings()
    QApplication.processEvents()
    assert window._overlay_hidden_local and window._overlay.isVisible()
    db.set_setting("overlay_state", "on")
    window._apply_saved_settings()
    QApplication.processEvents()
    assert not window._overlay_hidden_local and window._overlay.isVisible()


def test_theme_refresh_doesnt_move_the_windows(window) -> None:
    overlay = window._overlay
    overlay.setGeometry(300, 300, 320, 170)
    window._database.set_setting("overlay_geometry", "10,10,300,160")  # last close
    window._on_theme_refreshed("dark", "")
    assert overlay.geometry().topLeft().x() == 300
