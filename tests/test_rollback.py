"""Roll back to an earlier version: listed from GitHub, installed with its own installer window."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.utils import update_checker, updater  # noqa: E402

_SETUP = "https://github.com/Jvn1604/UniversalDeathCounter/releases/download/{tag}/UniversalDeathCounterSetup.exe"


def _payload(current: str) -> list[dict]:
    def release(tag, **extra):
        return {"tag_name": tag, "html_url": f"https://example/{tag}",
                "assets": [{"name": "UniversalDeathCounterSetup.exe",
                            "browser_download_url": _SETUP.format(tag=tag), "size": 123}],
                **extra}
    return [release(f"v{current}"), release("v9.9.9-beta", prerelease=True),
            release("v1.5.0"), release("v2.12.0"), release("v2.4.0", draft=True)]


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def test_earlier_versions_are_listed_newest_first(monkeypatch) -> None:
    payload = json.dumps(_payload(update_checker.APP_VERSION)).encode()
    monkeypatch.setattr(update_checker.urllib.request, "urlopen",
                        lambda request, timeout: _Response(payload))
    releases = update_checker.earlier_releases()
    assert [r.tag for r in releases] == ["v2.12.0", "v1.5.0"]  # not this one, drafts, betas
    assert releases[0].installer_url.endswith("/v2.12.0/UniversalDeathCounterSetup.exe")


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


def test_rolling_back_runs_the_older_installer_with_its_window(window, monkeypatch) -> None:
    import src.ui.main_window as mw

    old = update_checker.Release("v2.12.0", "https://example/v2.12.0",
                                 _SETUP.format(tag="v2.12.0"), 123)
    monkeypatch.setattr(mw, "earlier_releases", lambda: [old])
    monkeypatch.setattr(mw, "is_installed_copy", lambda: True)
    monkeypatch.setattr(mw.QInputDialog, "getItem", lambda *a, **k: ("v2.12.0", True))
    monkeypatch.setattr(mw.QMessageBox, "question",
                        lambda *a, **k: mw.QMessageBox.StandardButton.Yes)
    installs = []
    monkeypatch.setattr(window, "_download_and_install",
                        lambda url, size, title, args=(): installs.append((url, title, args)))
    window._roll_back()
    assert installs == [(old.installer_url, "Roll Back", updater.ROLLBACK_ARGS)]
    assert "/SILENT" not in updater.ROLLBACK_ARGS  # the installer's own window, then Launch
