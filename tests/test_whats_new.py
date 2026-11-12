"""What's New: the changelog in the app, and shown once after an update."""

from __future__ import annotations

from src.utils import changelog
from src.utils.constants import APP_VERSION, CHANGELOG_PATH

_SAMPLE = """# Changelog

## [Unreleased]

### Fixed
- Coming soon.

## [2.19.0] - 2026-11-07

### New
- Roll back.

## [2.17.0] - 2026-11-06

### New
- Save file.

[Unreleased]: https://example.com/compare
[2.19.0]: https://example.com/2.19.0
"""


def test_the_changelog_reads_into_versions() -> None:
    releases = changelog.parse(_SAMPLE)
    assert [r.version for r in releases] == ["Unreleased", "2.19.0", "2.17.0"]
    assert releases[0].title == "Coming next"
    assert releases[1].date == "2026-11-07" and "Roll back." in releases[1].notes
    assert "example.com" not in releases[2].notes  # the link lines are left out
    assert [r.version for r in changelog.newer_than(releases, "2.16.0", "2.19.0")] == [
        "2.19.0", "2.17.0"]
    assert changelog.newer_than(releases, "2.19.0", "2.19.0") == []


def test_the_shipped_changelog_has_this_version() -> None:
    releases = changelog.load(CHANGELOG_PATH)
    assert any(r.version == APP_VERSION for r in releases)
    assert all(r.notes for r in releases)


def test_the_window_opens_on_your_version_or_what_the_update_brought() -> None:
    from PySide6.QtWidgets import QApplication

    from src.ui.whats_new_window import WhatsNewWindow

    QApplication.instance() or QApplication([])
    releases = changelog.parse(_SAMPLE.replace("2.19.0", APP_VERSION))
    window = WhatsNewWindow(releases=releases)
    assert window.versions.count() == 3
    assert "(you have this)" in window.versions.currentItem().text()
    assert "Roll back." in window.notes.toPlainText()
    window.close()
    updated = WhatsNewWindow(releases=releases, since="2.17.0")
    assert APP_VERSION in updated.versions.currentItem().text()
    updated.close()
    empty = WhatsNewWindow(releases=[])
    assert "All Releases Online" in empty.notes.toPlainText()
    empty.close()


def test_it_opens_once_after_an_update_not_on_a_fresh_install(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(mw.UpdateChecker, "check_async", lambda self: None)
    app = QApplication.instance() or QApplication([])
    opened: list[str] = []
    monkeypatch.setattr(mw.MainWindow, "_open_whats_new",
                        lambda self, since="": opened.append(since))
    window = mw.MainWindow()
    try:
        window._whats_new_after_update()  # fresh install: just remembers the version
        assert opened == []
        window._database.set_setting("last_seen_version", "2.17.0")  # had an older one
        window._whats_new_after_update()
        assert opened == ["2.17.0"]
        window._whats_new_after_update()  # once
        assert opened == ["2.17.0"]
    finally:
        window._quit_app()
        app.processEvents()
