"""The notification bell: keeps what the app wanted to tell you."""

from __future__ import annotations

import pytest

from src.ui.notifications import MAX_KEPT, NotificationBell, ago


@pytest.fixture()
def bell():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    widget = NotificationBell()
    yield widget
    widget.deleteLater()


def test_the_badge_counts_unread_and_opening_reads_them(bell) -> None:
    assert bell.unread() == 0 and bell._badge.isHidden()
    bell.add("Version 2.20.0 is out.", "circle-arrow-up")
    bell.add("F9 is taken.", "keyboard")
    assert bell.unread() == 2 and bell._badge.text() == "2"
    assert bell.items[0].text == "F9 is taken."  # newest first
    bell.open_panel()
    assert bell.unread() == 0 and bell._badge.isHidden()
    bell._panel.close()


def test_the_same_message_again_soon_is_one_entry(bell) -> None:
    bell.add("Screen capture blocked.")
    bell.mark_all_read()
    bell.add("Other.")
    bell.add("Screen capture blocked.")
    assert [i.text for i in bell.items] == ["Screen capture blocked.", "Other."]
    assert bell.unread() == 2


def test_only_the_last_ones_are_kept_and_clear_empties(bell) -> None:
    for number in range(MAX_KEPT + 10):
        bell.add(f"message {number}")
    assert len(bell.items) == MAX_KEPT and bell._badge.text() == "9+"
    bell.clear()
    assert bell.items == [] and bell._badge.isHidden()


def test_a_button_goes_where_it_can_be_fixed(bell) -> None:
    from PySide6.QtWidgets import QPushButton

    done: list[bool] = []
    bell.add("F9 is taken.", "keyboard", "Change Keys", lambda: done.append(True))
    bell.open_panel()
    buttons = [b for b in bell._panel.findChildren(QPushButton) if b.text() == "Change Keys"]
    buttons[0].click()
    assert done == [True]


def test_ago_reads_naturally() -> None:
    assert ago(5) == "just now"
    assert ago(300) == "5 min ago"
    assert ago(7200) == "2 h ago"
    assert ago(86400) == "1 day ago"


def test_the_app_files_what_matters(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    app = QApplication.instance() or QApplication([])
    window = mw.MainWindow()
    try:
        window._on_update_available("9.9.9", "https://example.com")
        window._on_hotkeys_failed([("increment", "f9")])
        window._note_detection_trouble("Watching game.exe for deaths")  # routine: not kept
        window._note_detection_trouble("Auto-detect stopped (error, see log)")
        texts = [item.text for item in window._bell.items]
        assert texts[0] == "Auto-detect stopped (error, see log)"
        assert any("F9" in t for t in texts) and any("9.9.9" in t for t in texts)
        assert len(texts) == 3
        labels = {item.action_label for item in window._bell.items}
        assert labels == {"Update", "Change Keys", "Detection"}
    finally:
        window._quit_app()
        app.processEvents()
