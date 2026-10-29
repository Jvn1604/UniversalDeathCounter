"""Reading a capture card through OBS (obs-websocket v5), against a stand-in OBS."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.detection import death_watcher as dw  # noqa: E402
from src.detection.matchers import DeathTemplate, TemplateMatcher  # noqa: E402
from src.detection.obs_client import ObsClient, ObsError  # noqa: E402
from src.utils.constants import OPTION_OBS_SOURCE, OPTION_WINDOW_TITLE  # noqa: E402

REGION = (0.30, 0.40, 0.40, 0.15)


def _picture(death: bool, width: int = 1280, height: int = 720) -> np.ndarray:
    rng = np.random.default_rng(5)
    frame = (rng.random((height, width, 3)) * 60 + 40).astype(np.uint8)
    if death:
        x, y, w, h = (int(REGION[0] * width), int(REGION[1] * height),
                      int(REGION[2] * width), int(REGION[3] * height))
        frame[y : y + h, x : x + w // 2] = 235
        frame[y : y + h, x + w // 2 : x + w] = 12
    return frame


def _jpeg(frame: np.ndarray) -> str:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage

    height, width = frame.shape[:2]
    image = QImage(frame.tobytes(), width, height, width * 3, QImage.Format.Format_RGB888)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPG", 92)
    return "data:image/jpg;base64," + base64.b64encode(bytes(data)).decode()


class FakeObs:
    """Speaks just enough obs-websocket v5 for the client: login, list, screenshot."""

    def __init__(self, password: str = "") -> None:
        self.password = password
        self.death = False
        self.requests: list[str] = []
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen()
        self.port = self._server.getsockname()[1]
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self) -> None:
        self._stop = True
        self._server.close()

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    @staticmethod
    def _send(conn, payload: bytes, opcode: int = 0x1) -> None:
        header = bytes([0x80 | opcode])
        if len(payload) < 126:
            header += bytes([len(payload)])
        elif len(payload) < 1 << 16:
            header += bytes([126]) + struct.pack("!H", len(payload))
        else:
            header += bytes([127]) + struct.pack("!Q", len(payload))
        conn.sendall(header + payload)

    @staticmethod
    def _receive(conn, buffer: bytearray) -> tuple[int, bytes]:
        def read(n: int) -> bytes:
            while len(buffer) < n:
                chunk = conn.recv(65536)
                if not chunk:
                    raise ConnectionError
                buffer.extend(chunk)
            data = bytes(buffer[:n])
            del buffer[:n]
            return data

        first, second = read(2)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", read(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", read(8))[0]
        assert second & 0x80, "clients must mask their frames"
        mask = read(4)
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(read(length)))
        return first & 0x0F, payload

    def _client(self, conn) -> None:
        buffer = bytearray()
        try:
            while b"\r\n\r\n" not in buffer:
                buffer.extend(conn.recv(4096))
            head, _, rest = bytes(buffer).partition(b"\r\n\r\n")
            buffer = bytearray(rest)
            key = next(line.split(b":", 1)[1].strip() for line in head.split(b"\r\n")
                       if line.lower().startswith(b"sec-websocket-key"))
            accept = base64.b64encode(
                hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()
            )
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                         b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
            hello: dict = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
            salt, challenge = "c2FsdA==", "Y2hhbGxlbmdl"
            if self.password:
                hello["authentication"] = {"salt": salt, "challenge": challenge}
            self._send(conn, json.dumps({"op": 0, "d": hello}).encode())
            opcode, identify = self._receive(conn, buffer)
            if opcode == 0x8:  # the client gave up before logging in
                return
            sent = json.loads(identify)["d"].get("authentication")
            if self.password:
                secret = base64.b64encode(hashlib.sha256((self.password + salt).encode()).digest())
                wanted = base64.b64encode(
                    hashlib.sha256(secret + challenge.encode()).digest()
                ).decode()
                if sent != wanted:
                    self._send(conn, struct.pack("!H", 4009) + b"Authentication failed.", 0x8)
                    return
            self._send(conn, json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}).encode())
            while True:
                opcode, message = self._receive(conn, buffer)
                if opcode == 0x8:
                    return
                request = json.loads(message)["d"]
                kind = request["requestType"]
                self.requests.append(kind)
                ok, data = True, {}
                if kind == "GetInputList":
                    data = {"inputs": [
                        {"inputName": "Mic/Aux", "unversionedInputKind": "wasapi_input_capture"},
                        {"inputName": "Elgato HD60 X", "unversionedInputKind": "dshow_input"},
                        {"inputName": "Webcam", "unversionedInputKind": "dshow_input"},
                    ]}
                elif kind == "GetSourceScreenshot":
                    if request["requestData"]["sourceName"] != "Elgato HD60 X":
                        ok = False
                    else:
                        width = request["requestData"]["imageWidth"]
                        data = {"imageData": _jpeg(_picture(self.death, width, width * 9 // 16))}
                reply = {"op": 7, "d": {
                    "requestType": kind, "requestId": request["requestId"],
                    "requestStatus": {"result": ok, "code": 100 if ok else 600,
                                      "comment": None if ok else "No source was found."},
                    "responseData": data,
                }}
                self._send(conn, json.dumps(reply).encode())
        except (ConnectionError, OSError, StopIteration):
            pass
        finally:
            conn.close()


@pytest.fixture()
def obs():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    server = FakeObs(password="hunter2")
    yield server
    server.close()


def test_logs_in_lists_sources_and_reads_the_picture(obs) -> None:
    client = ObsClient("127.0.0.1", obs.port, "hunter2")
    try:
        assert client.video_sources()[:2] == ["Elgato HD60 X", "Webcam"]  # capture cards first
        frame = client.screenshot("Elgato HD60 X")  # > 64 KB message: the long-length path
        assert frame.shape == (720, 1280, 3) and frame.dtype == np.uint8
        expected = _picture(False)
        assert abs(float(frame.mean()) - float(expected.mean())) < 4  # JPEG is close
        with pytest.raises(ObsError, match="No source"):
            client.screenshot("Missing")
        assert client.screenshot("Elgato HD60 X").shape == (720, 1280, 3)  # still usable
    finally:
        client.close()


def test_tells_the_player_what_is_wrong(obs) -> None:
    with pytest.raises(ObsError, match="refused the password"):
        ObsClient("127.0.0.1", obs.port, "wrong").connect()
    with pytest.raises(ObsError, match="asks for a password"):
        ObsClient("127.0.0.1", obs.port, "").connect()
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    with pytest.raises(ObsError, match="Is OBS open"):
        ObsClient("127.0.0.1", port, "", timeout=1).connect()


def test_watcher_counts_a_death_seen_through_obs(obs, monkeypatch) -> None:
    from PySide6.QtCore import Qt

    monkeypatch.setattr(dw, "FRAMES_PER_SECOND", 20.0)
    matcher = TemplateMatcher(DeathTemplate.from_frame(_picture(True), REGION))
    watcher = dw.DeathWatcher(cooldown_seconds=0.0)
    deaths: list[int] = []
    watcher.death_detected.connect(deaths.append, Qt.ConnectionType.DirectConnection)
    watcher.configure(dw.WatchConfig(
        game_id=3, exe_path="", matcher=matcher, obs_source="Elgato HD60 X",
        obs_host="127.0.0.1", obs_port=obs.port, obs_password="hunter2",
    ))

    class _NoScreen:  # OBS mode never touches the screen
        monitors = [{"left": 0, "top": 0, "width": 1, "height": 1}]

        def grab(self, area):
            raise AssertionError("captured the screen in OBS mode")

    thread = threading.Thread(target=watcher._watch_loop, args=(_NoScreen(),), daemon=True)
    thread.start()
    time.sleep(0.8)
    assert deaths == []
    obs.death = True
    deadline = time.monotonic() + 4
    while not deaths and time.monotonic() < deadline:
        time.sleep(0.05)
    watcher._stop_event.set()
    thread.join(3)
    assert deaths == [3]
    assert watcher.recent_frames()  # Capture Screen can pick OBS frames too


def test_console_page_uses_an_obs_source(obs, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    import src.ui.main_window as mw
    import src.utils.profiles as profiles

    monkeypatch.setattr(profiles, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(profiles, "DATABASE_PATH", tmp_path / "death_counter.db")
    monkeypatch.setattr(mw.ProfileManager.__init__, "__defaults__", (tmp_path,))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window = mw.MainWindow()
    try:
        db = window._database
        game = db.create_game("Sekiro (PS4)")
        window._reload_games(select_game_id=game)
        window._obs_port.setValue(obs.port)
        window._obs_password.setText("hunter2")
        window._connect_obs()
        assert "Connected to OBS" in window._obs_status.text(), window._obs_status.text()
        assert window._obs_source_combo.currentText() == "Elgato HD60 X"

        window._use_obs_source()
        options = db.get_detection_options(game)
        assert options[OPTION_OBS_SOURCE] == "Elgato HD60 X"
        assert OPTION_WINDOW_TITLE not in options
        config = window._death_watcher._config
        assert config is not None and config.obs_source == "Elgato HD60 X"
        assert config.obs_port == obs.port and config.obs_password == "hunter2"
        assert "reads <b>Elgato HD60 X</b> from OBS" in window._console_source.text()

        window._stop_console_window()
        assert OPTION_OBS_SOURCE not in db.get_detection_options(game)
        assert window._death_watcher._config is None
    finally:
        window._quit_app()
        QApplication.instance().processEvents()
