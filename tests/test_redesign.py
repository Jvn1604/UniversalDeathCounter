"""Redesign: icons, downloadable themes, live preview, overlay menu, ON/OFF state, guide."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.themes import theme_manager  # noqa: E402
from src.utils.constants import (  # noqa: E402
    SETTING_OVERLAY_COUNTER_SOURCE,
    SETTING_OVERLAY_LOCKED,
    SETTING_THEME,
)


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(theme_manager, "INSTALLED_THEMES_DIR", tmp_path / "themes")
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    yield win
    win._quit_app()
    app.processEvents()


# ---------------------------------------------------------------- themes
class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_extra_themes_install_and_uninstall(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(theme_manager, "INSTALLED_THEMES_DIR", tmp_path)
    assert theme_manager.available_themes() == ["dark", "light"]
    assert not theme_manager.is_installed("glass")
    # Not installed: falls back to dark instead of failing.
    assert theme_manager.active_theme("glass") == "dark"
    assert theme_manager.load_stylesheet("glass") == theme_manager.load_stylesheet("dark")

    theme_manager.install_theme("glass")  # from the repo's themes/ folder when run from source
    assert theme_manager.available_themes() == ["dark", "light", "glass"]
    assert "Glass" in theme_manager.load_stylesheet("glass")
    theme_manager.uninstall_theme("glass")
    assert not theme_manager.is_installed("glass")
    theme_manager.uninstall_theme("dark")  # built in: can't be removed
    assert theme_manager.is_installed("dark")


def test_theme_download_only_from_this_repo_and_checked(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(theme_manager, "INSTALLED_THEMES_DIR", tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)  # like the installed app
    asked: list[str] = []
    payload = {"body": b"QWidget { color: red; }"}

    def fake_urlopen(url, timeout):
        asked.append(url)
        return _Response(payload["body"])

    monkeypatch.setattr(theme_manager.urllib.request, "urlopen", fake_urlopen)
    theme_manager.install_theme("clay")
    assert asked[0].startswith(
        "https://raw.githubusercontent.com/Jvn1604/UniversalDeathCounter/v"
    ) and asked[0].endswith("/themes/clay.qss")
    assert theme_manager.is_installed("clay")

    payload["body"] = b"QWidget { image: url(C:/evil.png); }"
    with pytest.raises(OSError):
        theme_manager.install_theme("glass")
    payload["body"] = b"<html>not found</html>"
    with pytest.raises(OSError):
        theme_manager.install_theme("glass")
    assert not theme_manager.is_installed("glass")
    with pytest.raises(ValueError):
        theme_manager.install_theme("dark")


def test_downloadable_theme_files_are_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    for name, info in theme_manager.THEMES.items():
        if info.builtin:
            continue
        text = theme_manager._check_stylesheet((root / "themes" / f"{name}.qss").read_bytes())
        assert f"color: {info.text};" in text  # the player's text color can replace it
        assert abs(len(text.encode()) / 1024 - info.size_kb) < 2


# ---------------------------------------------------------------- shell
def test_one_home_per_function(window) -> None:
    assert window.menuBar().actions() == []  # the old menu bar duplicated everything
    more = [a.text() for a in window._more_menu.actions() if a.text()]
    assert more == ["Export Backup…", "Import Backup…", "About", "Clear All Data…", "Quit"]
    assert window._credit._url == "https://www.youtube.com/@ImDePhantom"


def test_overlay_and_timer_window_show_on_off(window) -> None:
    assert not window._overlay_nav.is_on()
    window._toggle_overlay()
    assert window._overlay.isVisible() and window._overlay_nav.is_on()
    window._toggle_overlay()
    assert not window._overlay_nav.is_on()
    window._toggle_timer_window()
    assert window._timer_window_btn.is_on()
    window._toggle_timer_window()
    assert not window._timer_window_btn.is_on()


def test_overlay_right_click_menu_changes_it(window, monkeypatch) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    import src.ui.main_window as mw

    shown: list[list[str]] = []

    class _Menu(QMenu):  # records instead of waiting for a click
        def exec(self, *_args):
            shown.append([action.text() for action in self.actions()])

    monkeypatch.setattr(mw, "QMenu", _Menu)
    before = len(window._menu_icons)
    window._overlay.menu_requested.emit(QPoint(10, 10))
    assert "+1 Death" in shown[0] and "Overlay Settings…" in shown[0]
    assert len(window._menu_icons) == before  # the menu's icons aren't kept around

    window._set_overlay_setting(SETTING_OVERLAY_COUNTER_SOURCE, "total")
    assert window._overlay._caption_label.text().startswith("ALL-TIME")
    assert window._counter_caption.text() == "ALL-TIME DEATHS"
    window._set_overlay_setting(SETTING_OVERLAY_LOCKED, "true")
    assert window._overlay.is_locked()

    opened: list[int] = []
    monkeypatch.setattr(window, "_open_settings_window", lambda tab=0: opened.append(tab))
    window._overlay.settings_requested.emit()
    from src.ui.settings_window import SettingsWindow

    assert opened == [SettingsWindow.TAB_OVERLAY]


# ---------------------------------------------------------------- live preview
def test_settings_preview_live_and_cancel_restores(window) -> None:
    from src.ui.settings_window import SettingsWindow

    db = window._database
    dialog = SettingsWindow(db, parent=window)
    dialog.preview_changed.connect(window._preview_appearance)
    dialog._gallery.set_theme("light")
    index = dialog._ui_font_combo.findData("Consolas")
    if index > 0:
        dialog._ui_font_combo.setCurrentIndex(index)
    dialog._send_preview()  # what the debounce timer does
    assert dialog.previewed
    assert "#f3f4f8" in window.styleSheet()  # light, before saving
    assert db.get_setting(SETTING_THEME, "dark") == "dark"
    dialog.reject()
    window._preview_appearance({})
    assert "#0b0c10" in window.styleSheet()  # back to the saved dark theme

    dialog = SettingsWindow(db, parent=window, tab=SettingsWindow.TAB_OVERLAY)
    assert dialog._tabs.currentIndex() == SettingsWindow.TAB_OVERLAY
    dialog._gallery.set_theme("light")
    dialog._apply()
    assert db.get_setting(SETTING_THEME) == "light"
    assert not dialog.previewed
    dialog.close()


def test_font_list_draws_fonts_without_giving_every_item_a_font() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

    from src.ui.settings_window import _font_combo

    QApplication.instance() or QApplication([])
    combo = _font_combo("Default")
    if combo.count() == 1:
        pytest.skip("no fonts on this platform")
    # Per-item fonts made every restyle load all fonts (seconds of "Not Responding").
    assert all(
        combo.itemData(i, Qt.ItemDataRole.FontRole) is None for i in range(combo.count())
    )
    option = QStyleOptionViewItem()
    index = combo.model().index(1, 0)
    combo.itemDelegate().initStyleOption(option, index)
    assert option.font.family() == combo.itemData(1)


# ---------------------------------------------------------------- guide + icons
def test_guide_buttons_go_to_the_right_place(window, monkeypatch) -> None:
    from src.ui.guide_dialog import (
        ACTION_BOSSES,
        ACTION_CONSOLE,
        ACTION_OVERLAY,
        ACTION_TIMER,
        GuideDialog,
    )

    opened: list[str] = []
    monkeypatch.setattr(window, "_open_boss_window", lambda: opened.append("bosses"))
    dialog = GuideDialog({"timer_split": "Num+1"}, parent=window)
    dialog.action_requested.connect(window._on_guide_action)
    assert dialog.tabs.count() == 3
    dialog.action_requested.emit(ACTION_CONSOLE)
    assert window._pages.currentIndex() == 4
    dialog.action_requested.emit(ACTION_TIMER)
    assert window._pages.currentIndex() == 1
    dialog.action_requested.emit(ACTION_BOSSES)
    assert opened == ["bosses"]
    dialog.action_requested.emit(ACTION_OVERLAY)
    assert window._overlay.isVisible()
    assert window._quick_start_status()["stream"]
    assert window._database.get_setting("overlay_ever_shown") == "true"
    window._overlay.hide()
    dialog.close()


def test_icons_are_tinted_and_cached() -> None:
    from PySide6.QtWidgets import QApplication

    from src.ui import icons

    QApplication.instance() or QApplication([])
    red = icons.pixmap("skull", "#ff0000", 20)
    assert not red.isNull() and red is icons.pixmap("skull", "#ff0000", 20)
    image = red.toImage()
    colors = {
        image.pixelColor(x, y).name()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() == 255
    }
    assert colors == {"#ff0000"}
    used = set()
    root = Path(__file__).resolve().parents[1] / "src"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("skull", "layers", "timer", "trophy", "radio", "circle-help"):
            if f'"{name}"' in text:
                used.add(name)
    for name in used:
        assert (icons.UI_ICONS_DIR / f"{name}.png").is_file()
