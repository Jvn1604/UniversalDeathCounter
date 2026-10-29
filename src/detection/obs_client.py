"""
Frames from OBS, for console players with a capture card.

OBS (28+) has a built-in remote-control server, obs-websocket. Its
``GetSourceScreenshot`` request returns a still of any source, such as the
capture card, so detection can read the console's picture without opening
the card itself (a card can only be used by one program at a time) and
without a window that has to stay visible.

The WebSocket client is a small standard-library one (no extra package):
OBS only needs a handshake, text frames, ping/pong and close. Protocol:
https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import threading

import numpy as np
from PySide6.QtGui import QImage

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4455
# Wide enough for small death text, small enough to encode and decode fast.
SCREENSHOT_WIDTH = 1280
_RPC_VERSION = 1
_MAX_MESSAGE = 32 * 1024 * 1024
# Sources a capture card or a console picture usually comes from, listed first.
_VIDEO_KINDS = ("dshow_input", "av_capture_input", "v4l2_input", "game_capture",
                "window_capture", "monitor_capture", "ffmpeg_source")


class ObsError(Exception):
    """OBS couldn't be reached, refused the password, or a request failed."""


def _auth_string(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest())
    return base64.b64encode(hashlib.sha256(secret + challenge.encode()).digest()).decode()


def _xor_mask(payload: bytes, mask: bytes) -> bytes:
    """Apply a WebSocket 4-byte mask (fast: one big-integer XOR, not a byte loop)."""
    length = len(payload)
    repeated = (mask * (length // 4 + 1))[:length]
    return (int.from_bytes(payload, "little") ^ int.from_bytes(repeated, "little")).to_bytes(
        length, "little"
    )


class _WebSocket:
    """Just enough of RFC 6455 for a client talking to OBS."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        try:
            self._sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as exc:
            raise ObsError(
                f"Can't reach OBS at {host}:{port}. Is OBS open, with "
                "Tools → WebSocket Server Settings → Enable WebSocket server on?"
            ) from exc
        self._buffer = b""
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: obswebsocket.json\r\n\r\n"
        )
        self._sock.sendall(request.encode())
        while b"\r\n\r\n" not in self._buffer:
            self._fill()
        head, self._buffer = self._buffer.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status + b" ":
            raise ObsError(f"OBS refused the connection ({status.decode(errors='replace')}).")
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        )
        if expected not in head:
            raise ObsError("That port isn't OBS's WebSocket server.")

    def _fill(self) -> None:
        try:
            chunk = self._sock.recv(256 * 1024)
        except OSError as exc:
            raise ObsError(f"Lost the connection to OBS: {exc}") from exc
        if not chunk:
            raise ObsError("OBS closed the connection.")
        self._buffer += chunk

    def _read(self, count: int) -> bytes:
        while len(self._buffer) < count:
            self._fill()
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytes([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header += bytes([0x80 | length])
        elif length < 1 << 16:
            header += bytes([0x80 | 126]) + struct.pack("!H", length)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", length)
        mask = os.urandom(4)
        try:
            self._sock.sendall(header + mask + _xor_mask(payload, mask))
        except OSError as exc:
            raise ObsError(f"Lost the connection to OBS: {exc}") from exc

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode())

    def receive_text(self) -> str:
        """The next text message (answering pings on the way)."""
        parts: list[bytes] = []
        while True:
            first, second = self._read(2)
            opcode, final = first & 0x0F, bool(first & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            if length > _MAX_MESSAGE:
                raise ObsError("OBS sent an oversized message.")
            mask = self._read(4) if second & 0x80 else b""
            payload = self._read(length)
            if mask:  # servers don't mask, but be lenient
                payload = _xor_mask(payload, mask)
            if opcode == 0x8:  # close: code 4009 = authentication failed
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 0
                reason = payload[2:].decode(errors="replace")
                if code == 4009:
                    raise ObsError("OBS refused the password.")
                raise ObsError(f"OBS closed the connection ({code} {reason}).".strip())
            if opcode == 0x9:  # ping
                self._send_frame(0xA, payload)
                continue
            if opcode in (0x1, 0x0):
                parts.append(payload)
                if final:
                    return b"".join(parts).decode("utf-8")

    def close(self) -> None:
        try:
            self._send_frame(0x8, struct.pack("!H", 1000))
        except ObsError:
            pass
        self._sock.close()


class ObsClient:
    """A connection to OBS; use it from one thread at a time (it locks anyway)."""

    def __init__(
        self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, password: str = "",
        timeout: float = 3.0,
    ) -> None:
        self._host, self._port, self._password, self._timeout = host, port, password, timeout
        self._socket: _WebSocket | None = None
        self._lock = threading.Lock()
        self._next_id = 0

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def connect(self) -> None:
        """Connect and log in. Raises ObsError with a message for the player."""
        self.close()
        ws = _WebSocket(self._host, self._port, self._timeout)
        try:
            hello = json.loads(ws.receive_text())
            if hello.get("op") != 0:
                raise ObsError("That port isn't OBS's WebSocket server.")
            identify: dict[str, object] = {"rpcVersion": _RPC_VERSION, "eventSubscriptions": 0}
            auth = hello.get("d", {}).get("authentication")
            if auth:
                if not self._password:
                    raise ObsError("OBS asks for a password: copy it from Tools → "
                                   "WebSocket Server Settings → Show Connect Info.")
                identify["authentication"] = _auth_string(
                    self._password, auth["salt"], auth["challenge"]
                )
            ws.send_text(json.dumps({"op": 1, "d": identify}))
            answer = json.loads(ws.receive_text())
            if answer.get("op") != 2:
                raise ObsError("OBS didn't accept the login.")
        except (ValueError, KeyError, TypeError) as exc:
            ws.close()
            raise ObsError(f"Unexpected answer from OBS: {exc}") from exc
        except ObsError:
            ws.close()
            raise
        self._socket = ws
        logger.info("Connected to OBS at %s:%s", self._host, self._port)

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def request(self, request_type: str, data: dict | None = None) -> dict:
        """Send one request and return its ``responseData``."""
        with self._lock:
            if self._socket is None:
                self.connect()
            assert self._socket is not None
            self._next_id += 1
            request_id = str(self._next_id)
            message = {"op": 6, "d": {"requestType": request_type, "requestId": request_id}}
            if data:
                message["d"]["requestData"] = data
            try:
                self._socket.send_text(json.dumps(message))
                while True:
                    reply = json.loads(self._socket.receive_text())
                    body = reply.get("d", {})
                    if reply.get("op") == 7 and body.get("requestId") == request_id:
                        break
            except ObsError:
                self.close()  # reconnect on the next request
                raise
            status = body.get("requestStatus", {})
            if not status.get("result"):
                comment = status.get("comment") or f"code {status.get('code')}"
                raise ObsError(f"OBS couldn't do that: {comment}")
            return body.get("responseData") or {}

    def video_sources(self) -> list[str]:
        """Source names, capture devices and game/window captures first."""
        inputs = self.request("GetInputList").get("inputs") or []

        def rank(item: dict) -> tuple[int, str]:
            kind = str(item.get("unversionedInputKind") or item.get("inputKind") or "")
            order = _VIDEO_KINDS.index(kind) if kind in _VIDEO_KINDS else len(_VIDEO_KINDS)
            return order, str(item.get("inputName", "")).casefold()

        return [str(i.get("inputName")) for i in sorted(inputs, key=rank) if i.get("inputName")]

    def screenshot(self, source: str, width: int = SCREENSHOT_WIDTH) -> np.ndarray:
        """The source's current picture as an ``(H, W, 3)`` RGB array."""
        data = self.request(
            "GetSourceScreenshot",
            {"sourceName": source, "imageFormat": "jpg", "imageWidth": width,
             "imageCompressionQuality": 85},
        )
        encoded = str(data.get("imageData", ""))
        if "," in encoded:
            encoded = encoded.split(",", 1)[1]  # strip "data:image/jpg;base64,"
        image = QImage.fromData(base64.b64decode(encoded))
        if image.isNull():
            raise ObsError(f"OBS sent an unreadable picture of {source}.")
        image = image.convertToFormat(QImage.Format.Format_RGB888)
        height, row_width = image.height(), image.width()
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
        rows = pixels.reshape(height, image.bytesPerLine())
        return rows[:, : row_width * 3].reshape(height, row_width, 3).copy()
