"""Console players: phone remote and watching a capture / Remote Play window."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.detection.game_window import WindowInfo  # noqa: E402
from src.utils import phone_remote  # noqa: E402
from src.utils.constants import DETECTION_MODE_TEMPLATE, OPTION_WINDOW_TITLE  # noqa: E402


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


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def _post(url: str, action: str) -> int:
    request = urllib.request.Request(url, data=action.encode(), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _wait_for(app, condition, seconds: float = 3.0) -> bool:
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_keys_are_short_and_unguessable() -> None:
    keys = {phone_remote.new_key() for _ in range(200)}
    assert len(keys) == 200 and all(len(k) == 10 and k.isalnum() for k in keys)


def test_phone_counts_deaths_and_sees_the_count(window) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    db = window._database
    window._reload_games(select_game_id=db.create_game("Bloodborne"))
    window._set_phone_remote(True)
    try:
        assert window._phone_toggle.is_on()
        url = window._phone_remote.url()
        port = url.split(":")[2].split("/")[0]
        key = url.split("k=")[1]
        base = f"http://127.0.0.1:{port}"

        status, page = _get(f"{base}/?k={key}")
        assert status == 200 and b"+1 Death" in page
        assert _get(f"{base}/?k=wrong")[0] == 403  # someone else on the Wi-Fi
        assert _get(f"{base}/state")[0] == 403
        assert _post(f"{base}/action?k=wrong", "increment") == 403
        assert _post(f"{base}/action?k={key}", "quit") == 400  # only the page's buttons

        for _ in range(3):
            assert _post(f"{base}/action?k={key}", "increment") == 200
        assert _wait_for(app, lambda: window._counter_manager.get_snapshot().session_deaths == 3)
        _post(f"{base}/action?k={key}", "undo")
        assert _wait_for(app, lambda: window._counter_manager.get_snapshot().session_deaths == 2)
        state = json.loads(_get(f"{base}/state?k={key}")[1])
        assert state["game"] == "Bloodborne" and state["count"] == 2
        assert "connected" in window._phone_status.text()

        window._new_phone_link()  # the old link stops working
        new_url = window._phone_remote.url()
        new_base = f"http://127.0.0.1:{new_url.split(':')[2].split('/')[0]}"
        assert new_url != url and _get(f"{new_base}/?k={key}")[0] == 403
        assert _get(f"{new_base}/?k={new_url.split('k=')[1]}")[0] == 200
        assert db.get_setting("phone_remote_enabled") == "true"
    finally:
        window._set_phone_remote(False)
    assert not window._phone_toggle.is_on() and not window._phone_remote.running
    assert db.get_setting("phone_remote_enabled") == "false"


def test_console_game_watches_the_picked_window(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    import src.ui.main_window as mw

    remote_play = WindowInfo("PS Remote Play", r"C:\Program Files\PS Remote Play\RemotePlay.exe",
                             1280, 720)
    monkeypatch.setattr(mw, "list_windows", lambda: [remote_play])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    db = window._database
    game = db.create_game("Elden Ring (PS5)")
    window._reload_games(select_game_id=game)
    window._refresh_console_page()
    assert "no window picked yet" in window._console_source.text()

    window._use_console_window()
    row = db.get_game_detection(game)
    assert row["exe_path"] == remote_play.exe_path and row["mode"] == DETECTION_MODE_TEMPLATE
    assert db.get_detection_options(game)[OPTION_WINDOW_TITLE] == "PS Remote Play"
    assert "is watching" in window._console_source.text()
    config = window._death_watcher._config
    assert config is not None and config.window_title == "PS Remote Play"

    window._stop_console_window()
    assert db.get_game_detection(game)["exe_path"] is None
    assert OPTION_WINDOW_TITLE not in db.get_detection_options(game)
    assert window._death_watcher._config is None
