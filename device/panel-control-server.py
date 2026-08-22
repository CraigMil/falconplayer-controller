"""Minimal HTTP control endpoint for the panel's display services.

    POST /start                     # world clock — the original form
    POST /scoreboard/start          # any registered service
    POST /current/restart           # kick whatever is live, whatever it is
    GET  /status
    GET  /scoreboard/status
    GET  /current/status

The one-segment paths are kept exactly as they were. Home Assistant has been
calling POST /start and GET /status since this was written, and a rename would
have meant coordinating two changes to gain nothing.

No external dependencies (stdlib http.server only) so it runs in the existing venv.
Auth: a shared-secret bearer token, read from WORLDCLOCK_TOKEN_FILE.
"""

from __future__ import annotations

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CTL = "/home/fpp/fpp-panel-ctl.sh"
TOKEN_FILE = os.environ.get("WORLDCLOCK_TOKEN_FILE", "/home/fpp/.worldclock-control-token")
PORT = int(os.environ.get("WORLDCLOCK_CONTROL_PORT", "8090"))

_ACTIONS = {"start", "stop", "restart", "status"}
# "current" is not a unit — the ctl script resolves it to whichever display
# service is live, or to the playing playlist when neither is.
_SERVICES = {"worldclock", "scoreboard", "current"}
_DEFAULT_SERVICE = "worldclock"


def _token() -> str:
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def _route(path: str) -> tuple[str, str] | None:
    """Map a URL path to (service, action), or None if it is not one of ours."""
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) == 1 and parts[0] in _ACTIONS:
        return _DEFAULT_SERVICE, parts[0]
    if len(parts) == 2 and parts[0] in _SERVICES and parts[1] in _ACTIONS:
        return parts[0], parts[1]
    return None


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self) -> bool:
        return self.headers.get("Authorization", "") == f"Bearer {_token()}"

    def _run(self, service: str, action: str) -> None:
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            result = subprocess.run(
                [CTL, service, action], capture_output=True, text=True, timeout=30,
            )
            # "status" reports state (active/inactive/failed) via stdout — a non-zero
            # exit just means "inactive", which is a normal query result, not a failure.
            ok = action == "status" or result.returncode == 0
            self._send(200 if ok else 500, {
                "service": service,
                "action": action,
                "ok": ok,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            })
        except Exception as e:
            self._send(500, {"service": service, "action": action,
                             "ok": False, "error": str(e)})

    def do_POST(self) -> None:
        route = _route(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        self._run(*route)

    def do_GET(self) -> None:
        route = _route(self.path)
        if route is None or route[1] != "status":
            self.send_response(404)
            self.end_headers()
            return
        self._run(*route)

    def log_message(self, fmt: str, *args) -> None:
        pass  # keep journalctl output quiet; systemd already timestamps


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
