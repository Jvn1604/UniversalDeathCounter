"""
Release 3: Glass and Clay are built from the built-in themes and painted over
a soft glow; game artwork is optional, cached and only fetched when wanted.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_themes():
    spec = importlib.util.spec_from_file_location("make_themes", ROOT / "packaging/make_themes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- themes
@pytest.mark.parametrize("name", ["glass", "clay"])
def test_theme_files_are_built_from_the_current_built_in_themes(name) -> None:
    from src.themes.theme_manager import _check_stylesheet

    themes = _make_themes()
    source, palette, layer = {
        "glass": ("dark", themes.GLASS_PALETTE, themes.GLASS_LAYER),
        "clay": ("light", themes.CLAY_PALETTE, themes.CLAY_LAYER),
    }[name]
    built = themes.build(source, palette, layer, themes.HEADERS[name])
    on_disk = (ROOT / "themes" / f"{name}.qss").read_text(encoding="utf-8")
    assert on_disk == built, "run: python packaging/make_themes.py"
    _check_stylesheet(built.encode())
    for selector in ("QLabel#HomeCount", 'QPushButton#NavButton[collapsed="true"]',
                     'QLabel#StatusPill[state="waiting"]'):
        assert selector in built  # every new screen is styled in Glass and Clay too


@pytest.mark.parametrize("name", ["glass", "clay"])
def test_installed_theme_lets_the_glow_show_through(name, tmp_path, monkeypatch) -> None:
    import src.themes.theme_manager as tm

    monkeypatch.setattr(tm, "INSTALLED_THEMES_DIR", tmp_path)
    tm.install_theme(name)
    assert b"\r" not in (tmp_path / f"{name}.qss").read_bytes()
    info = tm.theme_info(name)
    assert info.backdrop
    sheet = tm.customize_stylesheet(tm.load_stylesheet(name), name, see_through=True)
    assert sheet.startswith("/* DUDC theme")
    assert "QWidget {\n    background-color: transparent;" in sheet


def test_backdrop_paints_a_glow() -> None:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from src.themes.theme_manager import theme_info
    from src.ui.main_window import _BackgroundHost

    QApplication.instance() or QApplication([])
    info = theme_info("glass")
    host = _BackgroundHost()
    host.resize(QSize(400, 300))
    host.set_background(None, QColor(0, 0, 0, 0), info.base, info.backdrop)
    image = host.grab().toImage()
    base = QColor(info.base)
    lit = image.pixelColor(int(0.22 * 400), int(0.88 * 300))
    assert lit.green() > base.green() + 40  # lime glow where the first blob sits


# ---------------------------------------------------------------- artwork
def _png() -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    image = QImage(64, 32, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def test_steam_app_found_from_the_game_folder(tmp_path) -> None:
    from src.utils.artwork import steam_app_id_from_exe

    steamapps = tmp_path / "Steam" / "steamapps"
    game = steamapps / "common" / "ELDEN RING" / "Game"
    game.mkdir(parents=True)
    (steamapps / "appmanifest_1245620.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"1245620"\n\t"installdir"\t\t"ELDEN RING"\n}\n'
    )
    (steamapps / "appmanifest_7.acf").write_text('"installdir"  "Other"')
    assert steam_app_id_from_exe(str(game / "eldenring.exe")) == 1245620
    assert steam_app_id_from_exe(str(tmp_path / "Games" / "x.exe")) is None
    assert steam_app_id_from_exe(None) is None


def test_artwork_downloads_once_by_name(tmp_path, monkeypatch) -> None:
    import src.utils.artwork as art

    asked: list[str] = []

    def fake_get(url: str) -> bytes:
        asked.append(url)
        if "storesearch" in url:
            assert "Hollow%20Knight" in url  # only the name is sent
            return b'{"items": [{"id": 367520, "name": "Hollow Knight"}]}'
        if "library_hero" in url:
            raise OSError("404")
        return _png()

    monkeypatch.setattr(art, "_get", fake_get)
    path = art.download_artwork(5, "Hollow Knight", None, tmp_path)
    assert path == tmp_path / "5.jpg" and path.read_bytes() == _png()
    assert any("367520/header.jpg" in url for url in asked)


def test_main_window_artwork_is_optional(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    app = QApplication.instance() or QApplication([])
    window = mw.MainWindow()
    try:
        fetched: list[int] = []
        monkeypatch.setattr(
            window._artwork_fetcher, "fetch", lambda game_id, *a: fetched.append(game_id)
        )
        db = window._database
        game = db.create_game("Lies of P")
        window._reload_games(select_game_id=game)
        assert fetched == [] and not window._hero_card.has_artwork()  # off by default

        db.set_setting("game_artwork", "true")
        window._refresh_artwork()
        assert fetched == [game]  # looked up once it's on
        window._on_artwork_found(game, "")  # Steam had nothing
        fetched.clear()
        window._refresh_artwork()
        assert fetched == []  # not asked again

        own = tmp_path / "mine.png"
        own.write_bytes(_png())
        monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", lambda *a, **k: (str(own), ""))
        window._choose_artwork()
        assert window._hero_card.has_artwork() and window._now_card.has_artwork()
        window._remove_artwork()
        assert not window._hero_card.has_artwork()
    finally:
        window._quit_app()
        app.processEvents()
