"""
Stream overlay: the death counter as a web page for an OBS Browser Source.

OBS shows the page with a truly transparent background (no green screen), and
it keeps showing while the overlay window is hidden from the player's own
screen ("Hide From My Screen"). The page asks for the counts a few times a
second and pops the number when it changes.

Only this PC can open it (it listens on 127.0.0.1), it serves nothing but the
counter, and it runs only while turned on. Pure standard library, like the
phone remote.
"""

from __future__ import annotations

import json
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QObject

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_PORT = 8766
_PORT_TRIES = 10

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>DUDC Overlay</title>
<style>
  html, body { margin: 0; background: transparent; overflow: hidden; }
  #card { display: inline-block; box-sizing: border-box; padding: 12px 16px;
          font-family: "Segoe UI", sans-serif; line-height: 1.15; }
  .line { white-space: nowrap; }
  #count { display: flex; align-items: center; gap: 10px; font-weight: 800; }
  #skull { display: none; }
  .pop { animation: pop .45s ease-out; }
  @keyframes pop { 0% { transform: scale(1); } 35% { transform: scale(1.22); }
                   100% { transform: scale(1); } }
  .hidden { display: none !important; }
</style></head>
<body>
<div id="card">
  <div id="game" class="line"></div>
  <div id="boss" class="line"></div>
  <div id="count" class="line"><img id="skull" alt=""><span id="text"></span></div>
  <div id="caption" class="line"></div>
  <div id="stats" class="line"></div>
</div>
<script>
let last = "", lastNumber = null, lastSkull = "";
async function tick() {
  try {
    const response = await fetch("/state", {cache: "no-store"});
    const s = await response.json();
    const key = JSON.stringify(s);
    if (key !== last) { last = key; render(s); }
  } catch (e) { /* the app is closed: try again */ }
  setTimeout(tick, 250);
}
function show(id, on, text) {
  const el = document.getElementById(id);
  el.classList.toggle("hidden", !on);
  if (text !== undefined) el.textContent = text;
  return el;
}
function render(s) {
  const card = document.getElementById("card");
  card.classList.toggle("hidden", !s.active);
  if (!s.active) return;
  card.style.background = s.card || "transparent";
  card.style.borderRadius = (s.radius || 0) + "px";
  card.style.padding = s.padding + "px " + Math.round(s.padding * 1.2) + "px";
  card.style.textAlign = s.align;
  card.style.fontFamily = s.font || "Segoe UI, sans-serif";
  card.style.textShadow = s.shadow ? "0 0 6px rgba(0,0,0,.9), 0 0 2px #000" : "none";
  const small = {color: s.secondary};
  for (const [id, text, size] of [["game", s.game, 13], ["boss", s.boss, 12],
                                  ["caption", s.caption, 10], ["stats", s.stats, 11]]) {
    const el = show(id, s.show[id] && text, text);
    el.style.color = small.color; el.style.fontSize = size + "px";
    if (id === "caption") el.style.letterSpacing = "2px";
  }
  const count = document.getElementById("count");
  count.style.justifyContent = {left: "flex-start", center: "center", right: "flex-end"}[s.align];
  count.style.fontWeight = s.bold ? 800 : 500;
  count.style.letterSpacing = s.spacing + "px";
  document.getElementById("text").innerHTML = s.count_html;
  const skull = document.getElementById("skull");
  skull.style.display = s.show.skull ? "block" : "none";
  if (s.show.skull && s.skull !== lastSkull) {
    lastSkull = s.skull; skull.src = "/skull.png?v=" + s.skull;
  }
  skull.style.height = s.skull_px + "px";
  if (lastNumber !== null && s.number !== lastNumber && s.animate) {
    count.classList.remove("pop"); void count.offsetWidth; count.classList.add("pop");
  }
  lastNumber = s.number;
}
tick();
</script>
</body></html>
"""


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """
    A server that refuses a port another program already uses. Python's
    default allows sharing it on Windows, and then the *other* program
    answers (e.g. a second copy of the app shows its counter in OBS).
    """

    allow_reuse_address = False

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)  # Windows only
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class StreamOverlay(QObject):
    """Serves :data:`PAGE`, its state (``/state``) and the skull (``/skull.png``)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server: ThreadingHTTPServer | None = None
        self._lock = threading.Lock()
        self._state: dict[str, object] = {"active": False}
        self._skull_png = b""

    @property
    def running(self) -> bool:
        return self._server is not None

    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/" if self._server else ""

    def start(self, port: int = DEFAULT_PORT) -> None:
        """Serve on this PC only (tries the next ports if one is taken). Raises OSError."""
        if self._server is not None:
            return
        handler = _handler_for(self)
        last_error: OSError | None = None
        for candidate in range(port, port + _PORT_TRIES):
            try:
                self._server = ExclusiveHTTPServer(("127.0.0.1", candidate), handler)
                break
            except OSError as exc:
                last_error = exc
        if self._server is None:
            raise last_error or OSError("no free port")
        self._server.daemon_threads = True
        threading.Thread(
            target=self._server.serve_forever, name="StreamOverlay", daemon=True
        ).start()
        logger.info("Stream overlay serving on %s", self.url())

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            logger.info("Stream overlay stopped")

    def set_state(self, state: dict[str, object], skull_png: bytes | None = None) -> None:
        with self._lock:
            self._state = dict(state)
            if skull_png is not None:
                self._skull_png = skull_png

    def state(self) -> dict[str, object]:
        with self._lock:
            return dict(self._state)

    def skull_png(self) -> bytes:
        with self._lock:
            return self._skull_png


def _handler_for(overlay: StreamOverlay) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "DUDC"

        def log_message(self, *_args) -> None:  # noqa: D102 - keep the app log clean
            pass

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/state":
                self._send(json.dumps(overlay.state()).encode("utf-8"), "application/json")
            elif path == "/skull.png" and overlay.skull_png():
                self._send(overlay.skull_png(), "image/png")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

    return Handler
