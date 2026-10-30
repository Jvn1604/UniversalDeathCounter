"""Skull evolution, the overlay's "DEATH - n", and Home's dashboard."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ui.skulls import TIERS, next_tier, skull_pixmap, tier_index  # noqa: E402


@pytest.fixture()
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    app = QApplication.instance() or QApplication([])
    win = mw.MainWindow()
    yield win
    win._quit_app()
    app.processEvents()


def test_skull_evolves_every_ten_deaths() -> None:
    assert [tier_index(n) for n in (0, 9, 10, 19, 20, 55, 99, 100)] == [0, 0, 1, 1, 2, 5, 9, 10]
    assert TIERS[tier_index(149)].deaths == 100 and TIERS[tier_index(150)].deaths == 150
    assert TIERS[tier_index(5000)].name == "God of Death"
    assert tier_index(-3) == 0
    upcoming, progress = next_tier(25)
    assert upcoming is not None and upcoming.deaths == 30 and progress == pytest.approx(0.5)
    assert next_tier(1000) == (None, 1.0)


def test_skull_art_is_drawn_once_and_differs_by_tier() -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    plain = skull_pixmap(0, 64)
    assert skull_pixmap(5, 64) is plain  # same tier, same cached picture
    horned = skull_pixmap(10, 64)
    assert horned is not plain and horned.toImage() != plain.toImage()
    assert plain.width() == 64 and not plain.toImage().isNull()
    gold = skull_pixmap(1000, 64)  # the last tier has its own colour
    assert gold.toImage() != skull_pixmap(100, 64).toImage()


def test_overlay_shows_death_dash_number_with_its_skull(window) -> None:
    db = window._database
    window._reload_games(select_game_id=db.create_game("Sekiro"))
    for _ in range(12):
        window._on_increment()
    overlay = window._overlay
    assert overlay._death_label.text() == "DEATH - 12"
    assert overlay._caption_label.text() == "THIS SESSION  ·  BRUISED"
    assert not overlay._skull_label.pixmap().isNull()
    window._set_overlay_setting("overlay_show_skull", "false")
    assert overlay._caption_label.text() == "THIS SESSION"
    assert not overlay._skull_label.isVisibleTo(overlay)


def test_home_dashboard_shows_the_week_and_the_bosses(window) -> None:
    db = window._database
    window._add_template_game("Elden Ring")
    game = window._counter_manager.current_game_id
    session = db.start_session(game)
    bosses = db.get_bosses(game)
    now = datetime.now(UTC)
    for days_ago, count in ((0, 3), (2, 4), (9, 5)):  # 9 days ago: last week
        for _ in range(count):
            when = (now - timedelta(days=days_ago)).isoformat()
            db.add_death_event(game, bosses[1]["id"], session, 1, timestamp=when)
    db.set_boss_defeated(bosses[0]["id"], True)
    window._show_page(0)
    window._refresh_home()

    days = window._week_chart._days
    assert len(days) == 7 and days[-1] == (days[-1][0], 3, True)
    assert window._week_total.text() == "7 deaths"
    assert window._week_delta.text() == "+2 vs last week"
    assert window._week_delta.property("tone") == "up"
    assert (window._boss_ring._done, window._boss_ring._total) == (1, len(bosses))
    assert window._toughest._rows == [(bosses[1]["name"], 12)]
    assert window._greeting_line.text().startswith("3 deaths today")
    assert window._skull_badge._name.text() == "Fresh Spawn"


def test_start_banner_follows_the_checklist_and_can_be_hidden(window) -> None:
    window._show_page(0)
    window._refresh_home()
    banner = window._start_banner
    assert banner.isVisibleTo(window) and "0 of 5" in banner._title.text()
    window._reload_games(select_game_id=window._database.create_game("Hades"))
    window._refresh_home()
    assert "1 of 5" in banner._title.text() and "first death" in banner._next.text()
    banner.dismissed.emit()
    window._refresh_home()
    assert not banner.isVisibleTo(window)
    assert window._database.get_setting("quick_start_hidden") == "true"


def test_downloaded_themes_refresh_after_an_app_update(tmp_path, monkeypatch) -> None:
    from src.themes import theme_manager

    monkeypatch.setattr(theme_manager, "INSTALLED_THEMES_DIR", tmp_path)
    assert theme_manager.outdated_themes() == []  # nothing downloaded
    theme_manager.install_theme("glass")  # from the source tree's themes/
    assert theme_manager.outdated_themes() == []
    stale = tmp_path / "glass.qss"
    stale.write_text("/* old */\nQWidget {}\n", encoding="utf-8")  # from an older version
    assert theme_manager.outdated_themes() == ["glass"]
