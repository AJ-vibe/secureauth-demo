#!/usr/bin/env python3
"""
SecureAuth Demo Server
──────────────────────────────────────────────────────────
Inbound  │ POST /api/auth/trigger   — External system (IVA) fires auth request
         │ GET  /api/auth/state     — Frontend polls for pending request
Outbound │ POST /api/auth/response  — Frontend submits approve/deny;
         │                            server then forwards result to IVA callback
──────────────────────────────────────────────────────────
Replace OUTBOUND_CALLBACK_URL with the real IVA webhook when ready.
"""

import json
import os
import threading
import uuid
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

# ── Configuration (replace with real values when ready) ──────────────
OUTBOUND_CALLBACK_URL = "https://placeholder.api/iva/auth/callback"  # TODO
PORT = int(os.environ.get("PORT", 3000))

# ── Shared auth-request state ─────────────────────────────────────────
_lock = threading.Lock()
_state = {
    "pending":       False,
    "request_id":    None,
    "requester":     "IVA",
    "message":       "IVA is requesting your authentication approval.",
    "triggered_at":  None,
    "response":      None,   # "approved" | "denied" | None
    "responded_at":  None,
}


def _reset_state():
    _state.update({
        "pending":      False,
        "request_id":   None,
        "requester":    "IVA",
        "message":      "IVA is requesting your authentication approval.",
        "triggered_at": None,
        "response":     None,
        "responded_at": None,
    })


def _fire_outbound_callback(payload: dict):
    """Forward the auth result to the external IVA callback (placeholder)."""
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            OUTBOUND_CALLBACK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"[callback] IVA notified → HTTP {resp.status}")
    except Exception as exc:
        # Placeholder URL will fail — log and continue gracefully
        print(f"[callback] Could not reach IVA callback (placeholder): {exc}")


# ── HTTP Handler ──────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    # ── helpers ──────────────────────────────────────────────────────
    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}

    def _json(self, code: int, data: dict):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _serve_file(self):
        path = self.path.split("?")[0].lstrip("/") or "index.html"
        file_path = os.path.join(os.path.dirname(__file__), path)
        if not os.path.isfile(file_path):
            self._json(404, {"error": "file not found"})
            return
        ext_map = {
            ".html": "text/html; charset=utf-8",
            ".css":  "text/css",
            ".js":   "application/javascript",
            ".json": "application/json",
            ".ico":  "image/x-icon",
            ".png":  "image/png",
        }
        ext = os.path.splitext(file_path)[1]
        with open(file_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ext_map.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, fmt, *args):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {fmt % args}")

    # ── CORS pre-flight ───────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ── GET ───────────────────────────────────────────────────────────
    def do_GET(self):
        if self.path.startswith("/api/auth/state"):
            with _lock:
                self._json(200, _state.copy())
        else:
            self._serve_file()

    # ── POST ──────────────────────────────────────────────────────────
    def do_POST(self):
        body = self._read_body()

        # ── Endpoint 1: Inbound trigger from IVA ─────────────────────
        if self.path == "/api/auth/trigger":
            with _lock:
                if _state["pending"]:
                    self._json(409, {"error": "An auth request is already pending."})
                    return
                _state["pending"]      = True
                _state["request_id"]   = uuid.uuid4().hex[:8].upper()
                _state["requester"]    = body.get("requester", "IVA")
                _state["message"]      = body.get(
                    "message", "IVA is requesting your authentication approval."
                )
                _state["triggered_at"] = datetime.now(timezone.utc).isoformat()
                _state["response"]     = None
                _state["responded_at"] = None
                snapshot = _state.copy()

            print(f"[trigger] Auth request #{snapshot['request_id']} created by {snapshot['requester']}")
            self._json(200, {
                "status":     "ok",
                "request_id": snapshot["request_id"],
                "message":    "Auth request is now pending on the dashboard.",
            })

        # ── Endpoint 2: Frontend submits approve / deny ───────────────
        elif self.path == "/api/auth/response":
            approved = body.get("approved", False)
            with _lock:
                if not _state["pending"] and _state["response"] is not None:
                    self._json(409, {"error": "No pending auth request."})
                    return
                _state["response"]     = "approved" if approved else "denied"
                _state["pending"]      = False
                _state["responded_at"] = datetime.now(timezone.utc).isoformat()
                callback_payload = {
                    "request_id":   _state["request_id"],
                    "requester":    _state["requester"],
                    "response":     _state["response"],
                    "responded_at": _state["responded_at"],
                }

            print(f"[response] Request #{callback_payload['request_id']} → {callback_payload['response'].upper()}")

            # Fire outbound callback to IVA in a background thread
            threading.Thread(
                target=_fire_outbound_callback,
                args=(callback_payload,),
                daemon=True,
            ).start()

            self._json(200, {
                "status":   "ok",
                "response": callback_payload["response"],
                "message":  f"Result forwarded to IVA callback ({OUTBOUND_CALLBACK_URL}).",
            })

        # ── Endpoint 3: Reset state (dev/demo helper) ─────────────────
        elif self.path == "/api/auth/reset":
            with _lock:
                _reset_state()
            print("[reset] Auth state cleared.")
            self._json(200, {"status": "ok", "message": "Auth state reset."})

        else:
            self._json(404, {"error": "Unknown endpoint."})


# ── Entry point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    _reset_state()   # always start with a clean slate
    server = HTTPServer(("", PORT), Handler)
    print(f"""
╔══════════════════════════════════════════════════════╗
║           SecureAuth Demo  •  http://localhost:{PORT}   ║
╠══════════════════════════════════════════════════════╣
║  POST /api/auth/trigger   Inbound  — IVA fires req   ║
║  GET  /api/auth/state     Poll     — frontend checks  ║
║  POST /api/auth/response  Outbound — sends result     ║
║  POST /api/auth/reset     Dev      — clear state      ║
╚══════════════════════════════════════════════════════╝
Outbound callback → {OUTBOUND_CALLBACK_URL}
""")
    server.serve_forever()
