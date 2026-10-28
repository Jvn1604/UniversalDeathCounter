"""
Phone remote: count deaths from a phone on the same Wi-Fi.

Console players' controllers talk to the console, not the PC, so hotkeys
can't reach the app. This serves one small page on the home network with
big +1 / Undo / boss / timer buttons. Only links carrying the secret key
work, and the server runs only while the player has it switched on.

Pure standard library (``http.server`` on a daemon thread): nothing to
install, and it sleeps until a phone asks for something. Button presses
are handed to the main thread as a Qt signal.
"""

from __future__ import annotations

import json
import secrets
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, Signal

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_PORT = 8765
_PORT_TRIES = 10
# What the page may ask for; anything else is refused.
ACTIONS = frozenset(
    {
        "increment",
        "decrement",
        "undo",
        "boss_defeated",
        "prev_boss",
        "next_boss",
        "pause_detection",
        "timer_split",
        "timer_pause",
        "timer_undo",
    }
)


def new_key() -> str:
    """A short secret for the link (easy to type, impossible to guess on a LAN)."""
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"  # no 0/o/1/l mix-ups
    return "".join(secrets.choice(alphabet) for _ in range(10))


def local_ip() -> str:
    """This PC's address on the home network (no packet is actually sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.168.0.1", 9))
            return probe.getsockname()[0]
        except OSError:
            return socket.gethostbyname(socket.gethostname())


class PhoneRemote(QObject):
    """
    The phone page's server.

    Signals:
        action_requested: An action from :data:`ACTIONS`, pressed on a phone.
        phone_seen: A phone loaded the page or pressed a button.
    """

    action_requested = Signal(str)
    phone_seen = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server: ThreadingHTTPServer | None = None
        self._key = ""
        self._lock = threading.Lock()
        self._state: dict[str, object] = {}

    @property
    def running(self) -> bool:
        return self._server is not None

    def url(self) -> str:
        if self._server is None:
            return ""
        return f"http://{local_ip()}:{self._server.server_address[1]}/?k={self._key}"

    def start(self, key: str, port: int = DEFAULT_PORT) -> None:
        """Serve the page (tries the next ports if one is taken). Raises OSError."""
        self.stop()
        self._key = key
        handler = _handler_for(self)
        last_error: OSError | None = None
        for candidate in range(port, port + _PORT_TRIES):
            try:
                self._server = ThreadingHTTPServer(("0.0.0.0", candidate), handler)
                break
            except OSError as exc:
                last_error = exc
        if self._server is None:
            raise last_error or OSError("no free port")
        self._server.daemon_threads = True
        threading.Thread(
            target=self._server.serve_forever, name="PhoneRemote", daemon=True
        ).start()
        logger.info("Phone remote serving on port %s", self._server.server_address[1])

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            logger.info("Phone remote stopped")

    def set_state(self, **state: object) -> None:
        """What the page shows (counts, game, boss…); called on the main thread."""
        with self._lock:
            self._state.update(state)

    def state(self) -> dict[str, object]:
        with self._lock:
            return dict(self._state)


def _handler_for(remote: PhoneRemote) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "DUDC"

        def log_message(self, *_args) -> None:  # noqa: D102 - keep the app log clean
            pass

        def _authorized(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            return secrets.compare_digest(query.get("k", [""])[0], remote._key)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: object) -> None:
            self._send(HTTPStatus.OK, json.dumps(payload).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            path = urlparse(self.path).path
            if not self._authorized():
                self._send(HTTPStatus.FORBIDDEN, _EXPIRED_PAGE, "text/html; charset=utf-8")
            elif path == "/":
                remote.phone_seen.emit()
                self._send(HTTPStatus.OK, _PAGE, "text/html; charset=utf-8")
            elif path == "/state":
                self._json(remote.state())
            else:
                self._send(HTTPStatus.NOT_FOUND, b"", "text/plain")

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            if not self._authorized() or urlparse(self.path).path != "/action":
                self._send(HTTPStatus.FORBIDDEN, b"", "text/plain")
                return
            length = min(int(self.headers.get("Content-Length") or 0), 256)
            action = self.rfile.read(length).decode("utf-8", "replace").strip()
            if action not in ACTIONS:
                self._send(HTTPStatus.BAD_REQUEST, b"", "text/plain")
                return
            remote.phone_seen.emit()
            remote.action_requested.emit(action)
            self._json({"ok": True})

    return Handler


_EXPIRED_PAGE = b"""<!doctype html><meta name="viewport" content="width=device-width">
<body style="background:#0b0c10;color:#ececf1;font-family:sans-serif;padding:24px">
<h2>This link no longer works</h2>
<p>Open the link shown on the Console page of DePhantom Universal Death Counter.</p>"""

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<meta name="theme-color" content="#0b0c10">
<title>DUDC Remote</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none}
html,body{margin:0;height:100%;background:#0b0c10;color:#ececf1;
font-family:"Segoe UI",system-ui,sans-serif}
body{display:flex;flex-direction:column;gap:10px;padding:14px;
padding-bottom:max(14px,env(safe-area-inset-bottom))}
header{text-align:center}
#game{font-size:13px;color:#8a8f9c;letter-spacing:1px;text-transform:uppercase}
#boss{font-size:16px;font-weight:700;margin-top:2px;min-height:20px}
#count{font-size:76px;font-weight:900;color:#ff3d55;line-height:1;margin-top:6px;
text-shadow:0 0 28px rgba(255,61,85,.45)}
#sub{font-size:12px;color:#8a8f9c;margin-top:4px}
button{border:1px solid #2c2f3a;background:#1e2028;color:#ececf1;border-radius:16px;
font:700 17px "Segoe UI",system-ui,sans-serif;padding:14px 8px}
button:active{transform:scale(.97);background:#2a2d38}
#plus{flex:1;min-height:150px;font-size:34px;border:none;color:#fff;
background:linear-gradient(135deg,#ff4d63,#d91f3c);box-shadow:0 8px 30px rgba(255,61,85,.35)}
.row{display:flex;gap:10px}.row button{flex:1}
.label{font-size:10px;letter-spacing:2px;color:#6b6f7b;font-weight:800;margin:6px 2px -4px}
#status{font-size:12px;text-align:center;color:#6b6f7b;min-height:16px}
#status.bad{color:#f3bd6b}
</style></head><body>
<header><div id="game">Connecting…</div><div id="boss"></div>
<div id="count">–</div><div id="sub"></div></header>
<button id="plus" data-a="increment">+1 Death</button>
<div class="row"><button data-a="decrement">−1</button><button data-a="undo">Undo</button></div>
<div class="label">BOSS</div>
<div class="row"><button data-a="prev_boss">◀ Prev</button>
<button data-a="boss_defeated">Defeated</button><button data-a="next_boss">Next ▶</button></div>
<div class="label">TIMER</div>
<div class="row"><button data-a="timer_split">Start / Split</button>
<button data-a="timer_pause">Pause</button><button data-a="timer_undo">Undo Split</button></div>
<div id="status"></div>
<script>
const key=new URLSearchParams(location.search).get("k");
const $=id=>document.getElementById(id);
function show(s){
  $("game").textContent=s.game||"No game selected";
  $("boss").textContent=s.boss||"";
  $("count").textContent=s.count??"–";
  $("sub").textContent=s.caption||"";
  $("status").textContent=s.detection||"";$("status").className="";
}
async function refresh(){
  try{const r=await fetch("/state?k="+key,{cache:"no-store"});
    if(r.ok){show(await r.json());}else{throw 0}}
  catch(e){$("status").textContent="Can't reach the PC: is DUDC open, on the same Wi-Fi?";
    $("status").className="bad"}
}
document.querySelectorAll("button[data-a]").forEach(b=>b.addEventListener("click",async()=>{
  if(navigator.vibrate)navigator.vibrate(30);
  try{await fetch("/action?k="+key,{method:"POST",body:b.dataset.a});}catch(e){}
  setTimeout(refresh,150);
}));
refresh();setInterval(refresh,1500);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh()});
</script></body></html>""".encode()
