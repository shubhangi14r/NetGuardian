"""
NetGuardian - Self-Healing API (Person 5)

Exposes the healer's live state so Person 3's dashboard can show it:

    GET  /                       service banner
    GET  /healing/status         per-service state, restart counts, recovery times
    GET  /healing/events         recent healing events (newest first, ?limit=50)
    POST /healing/heal/{name}    manually trigger recovery of one service
    POST /healing/pause          stop the healer from acting (it keeps observing)
    POST /healing/resume         resume automatic healing

Run (from this folder):
    python healer_api.py          # listens on :9002

Standard library only - nothing extra to pip install.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import config
from self_healer import SelfHealer

healer = SelfHealer()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # dashboard runs on another origin (localhost:5173)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, {"service": "netguardian-self-healing", "status": "running",
                             "healer": "PAUSED" if healer.paused else "ACTIVE"})
        elif url.path == "/healing/status":
            self._send(200, healer.snapshot())
        elif url.path == "/healing/events":
            try:
                limit = int(parse_qs(url.query).get("limit", ["50"])[0])
            except ValueError:
                limit = 50
            self._send(200, healer.recent_events(max(1, min(limit, config.EVENT_LOG_SIZE))))
        else:
            self._send(404, {"detail": "not found"})

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if parts == ["healing", "pause"]:
            healer.pause(True)
            self._send(200, {"healer": "PAUSED"})
        elif parts == ["healing", "resume"]:
            healer.pause(False)
            self._send(200, {"healer": "ACTIVE"})
        elif len(parts) == 3 and parts[:2] == ["healing", "heal"]:
            result = healer.manual_heal(parts[2])
            self._send(200 if result["ok"] else 404, result)
        else:
            self._send(404, {"detail": "not found"})

    def log_message(self, *args):   # keep the console for healing events only
        pass


def main() -> None:
    healer.start()
    server = ThreadingHTTPServer((config.API_HOST, config.API_PORT), Handler)
    print(f"NetGuardian self-healing API on http://localhost:{config.API_PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        healer.stop()


if __name__ == "__main__":
    main()
