#!/usr/bin/env python3
"""
SecureAuth Demo Server
──────────────────────────────────────────────────────────────────────
Auth endpoints
  POST /api/auth/trigger          Inbound  — IVA fires auth request
  GET  /api/auth/state            Poll     — frontend checks every 2 s
  POST /api/auth/response         Outbound — user result → IVA callback
  POST /api/auth/reset            Dev      — clear state

Web Push endpoints
  GET  /api/push/vapid-public-key          Returns VAPID public key
  POST /api/push/subscribe                 Stores a push subscription
  POST /api/push/unsubscribe               Removes a push subscription
──────────────────────────────────────────────────────────────────────
Set OUTBOUND_CALLBACK_URL to the real IVA webhook when ready.
VAPID keys are generated on first run and saved to .vapid_keys.json.
For Render: set VAPID_PRIVATE_KEY + VAPID_PUBLIC_KEY env vars so keys
survive deploys (see render.yaml).
"""

import json
import os
import threading
import uuid
import urllib.request
import urllib.error
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

# ── Configuration ────────────────────────────────────────────────────
OUTBOUND_CALLBACK_URL = "https://placeholder.api/iva/auth/callback"   # TODO
PORT                  = int(os.environ.get("PORT", 3000))
VAPID_KEY_FILE        = os.path.join(os.path.dirname(__file__), ".vapid_keys.json")
VAPID_CONTACT         = "mailto:demo@secureauth.app"

# ── VAPID keys (loaded at startup) ───────────────────────────────────
_vapid_private_pem = None   # PEM string → fed to pywebpush
_vapid_public_b64  = None   # base64url uncompressed EC point → sent to browser

def _load_or_create_vapid_keys():
    """Load VAPID keys from env vars → file → generate fresh."""
    global _vapid_private_pem, _vapid_public_b64

    # 1. Prefer env vars (survives Render deploys without losing subscriptions)
    env_priv = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    env_pub  = os.environ.get("VAPID_PUBLIC_KEY",  "").strip()
    if env_priv and env_pub:
        _vapid_private_pem = env_priv.replace("\\n", "\n")
        _vapid_public_b64  = env_pub
        print("[vapid] Keys loaded from environment variables.")
        return

    # 2. File cache (local dev)
    if os.path.exists(VAPID_KEY_FILE):
        with open(VAPID_KEY_FILE) as f:
            keys = json.load(f)
        _vapid_private_pem = keys["private_pem"]
        _vapid_public_b64  = keys["public_b64"]
        print(f"[vapid] Keys loaded from {VAPID_KEY_FILE}.")
        return

    # 3. Generate a fresh P-256 EC keypair
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, NoEncryption
    )
    private_key = ec.generate_private_key(ec.SECP256R1())

    # Private key → PEM (what pywebpush expects)
    _vapid_private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    ).decode()

    # Public key → uncompressed EC point (04 || x || y) → base64url (what the browser expects)
    pub   = private_key.public_key().public_numbers()
    raw   = b"\x04" + pub.x.to_bytes(32, "big") + pub.y.to_bytes(32, "big")
    _vapid_public_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    # Persist to file for next run
    with open(VAPID_KEY_FILE, "w") as f:
        json.dump({"private_pem": _vapid_private_pem, "public_b64": _vapid_public_b64}, f)
    print(f"[vapid] Fresh keys generated and saved to {VAPID_KEY_FILE}.")
    print(f"[vapid] Public key: {_vapid_public_b64}")


# ── Push subscription store ───────────────────────────────────────────
_subs      = []          # list of subscription dicts from the browser
_subs_lock = threading.Lock()


def _send_push_to_all(payload: dict):
    """Encrypt and send a Web Push notification to every stored subscription."""
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("[push] pywebpush not installed — skipping notifications.")
        return

    with _subs_lock:
        subs = list(_subs)

    stale = []
    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=json.dumps(payload),
                vapid_private_key=_vapid_private_pem,
                vapid_claims={"sub": VAPID_CONTACT},
            )
            print(f"[push] Sent to {sub['endpoint'][:60]}…")
        except Exception as exc:
            # 404 / 410 means the subscription is no longer valid → remove it
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                stale.append(sub)
                print(f"[push] Stale subscription removed (HTTP {status}).")
            else:
                print(f"[push] Send error: {exc}")

    if stale:
        with _subs_lock:
            for s in stale:
                try:
                    _subs.remove(s)
                except ValueError:
                    pass


# ── Shared auth-request state ─────────────────────────────────────────
_lock  = threading.Lock()
_state = {
    "pending":      False,
    "request_id":   None,
    "requester":    "IVA",
    "message":      "IVA is requesting your authentication approval.",
    "triggered_at": None,
    "response":     None,   # "approved" | "denied" | None
    "responded_at": None,
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
        req  = urllib.request.Request(
            OUTBOUND_CALLBACK_URL, data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"[callback] IVA notified → HTTP {resp.status}")
    except Exception as exc:
        print(f"[callback] Could not reach IVA callback (placeholder): {exc}")


# ── HTTP Handler ──────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw    = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}

    def _json(self, code: int, data: dict):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _serve_file(self):
        path      = self.path.split("?")[0].lstrip("/") or "index.html"
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
            ".svg":  "image/svg+xml",
            ".webp": "image/webp",
            ".woff2":"font/woff2",
        }
        ext = os.path.splitext(file_path)[1]
        with open(file_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type",   ext_map.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

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

        elif self.path == "/api/push/vapid-public-key":
            self._json(200, {"publicKey": _vapid_public_b64})

        else:
            self._serve_file()

    # ── POST ─────────────────────────────────────────────────────────
    def do_POST(self):
        body = self._read_body()

        # ── Auth: inbound trigger from IVA ────────────────────────────
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

            print(f"[trigger] Auth request #{snapshot['request_id']} from {snapshot['requester']}")

            # Send Web Push notification to all subscribed devices
            threading.Thread(
                target=_send_push_to_all,
                args=({
                    "title": "Authentication Request",
                    "body":  f"{snapshot['requester']} is requesting your approval.",
                    "url":   "/",
                    "request_id": snapshot["request_id"],
                },),
                daemon=True,
            ).start()

            self._json(200, {
                "status":     "ok",
                "request_id": snapshot["request_id"],
                "message":    "Auth request pending on dashboard. Push sent to subscribed devices.",
            })

        # ── Auth: frontend submits approve / deny ─────────────────────
        elif self.path == "/api/auth/response":
            approved = body.get("approved", False)
            with _lock:
                if not _state["pending"] and _state["response"] is not None:
                    self._json(409, {"error": "No pending auth request."})
                    return
                _state["response"]     = "approved" if approved else "denied"
                _state["pending"]      = False
                _state["responded_at"] = datetime.now(timezone.utc).isoformat()
                cb_payload = {
                    "request_id":   _state["request_id"],
                    "requester":    _state["requester"],
                    "response":     _state["response"],
                    "responded_at": _state["responded_at"],
                }

            print(f"[response] #{cb_payload['request_id']} → {cb_payload['response'].upper()}")
            threading.Thread(target=_fire_outbound_callback, args=(cb_payload,), daemon=True).start()
            self._json(200, {
                "status":   "ok",
                "response": cb_payload["response"],
                "message":  f"Result forwarded to IVA callback ({OUTBOUND_CALLBACK_URL}).",
            })

        # ── Auth: reset state (dev helper) ────────────────────────────
        elif self.path == "/api/auth/reset":
            with _lock:
                _reset_state()
            print("[reset] Auth state cleared.")
            self._json(200, {"status": "ok", "message": "Auth state reset."})

        # ── Push: store a new subscription ────────────────────────────
        elif self.path == "/api/push/subscribe":
            endpoint = body.get("endpoint", "")
            keys     = body.get("keys", {})
            if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
                self._json(400, {"error": "Invalid subscription object."})
                return
            with _subs_lock:
                # Replace existing subscription for same endpoint
                existing = [s for s in _subs if s["endpoint"] == endpoint]
                for s in existing:
                    _subs.remove(s)
                _subs.append({"endpoint": endpoint, "keys": keys})
                count = len(_subs)
            print(f"[push] Subscription stored. Total: {count}")
            self._json(200, {"status": "ok", "subscriptions": count})

        # ── Push: remove a subscription ───────────────────────────────
        elif self.path == "/api/push/unsubscribe":
            endpoint = body.get("endpoint", "")
            with _subs_lock:
                before = len(_subs)
                _subs[:] = [s for s in _subs if s["endpoint"] != endpoint]
                removed  = before - len(_subs)
            print(f"[push] Unsubscribed {removed} subscription(s).")
            self._json(200, {"status": "ok", "removed": removed})

        else:
            self._json(404, {"error": "Unknown endpoint."})


# ── Entry point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    _reset_state()
    _load_or_create_vapid_keys()
    server = HTTPServer(("", PORT), Handler)
    print(f"""
╔══════════════════════════════════════════════════════════╗
║         SecureAuth Demo  •  http://localhost:{PORT}         ║
╠══════════════════════════════════════════════════════════╣
║  POST /api/auth/trigger          IVA fires auth request  ║
║  GET  /api/auth/state            Frontend polls state    ║
║  POST /api/auth/response         User approve/deny       ║
║  POST /api/auth/reset            Dev — clear state       ║
║  GET  /api/push/vapid-public-key Browser fetches key     ║
║  POST /api/push/subscribe        Browser subscribes      ║
║  POST /api/push/unsubscribe      Browser unsubscribes    ║
╚══════════════════════════════════════════════════════════╝
Outbound callback → {OUTBOUND_CALLBACK_URL}
VAPID public key  → {_vapid_public_b64}
""")
    server.serve_forever()
