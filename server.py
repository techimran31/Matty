"""
server.py - Web edition of Matty, for Render (or any WSGI host).

WHY THIS FILE EXISTS
--------------------
Matty's desktop build talks straight to the machine: microphone, SAPI speech,
screen lock, system volume, installed applications, WhatsApp Web automation.
None of that exists on a Linux cloud host, so this server exposes only the
parts that still make sense remotely:

    GET  /              -> the same matty_hud.html interface
    POST /api/action    -> {"kind": ..., "args": {...}}  safe actions + AI brain
    GET  /api/status    -> cloud / key / cooldown state
    GET  /api/market    -> live market briefing
    GET  /api/vitals    -> CPU / RAM / disk of the host running this service
    GET  /healthz       -> health check used by Render

SECURITY
--------
Anything that controls a computer is in DESKTOP_ONLY and is refused with 403
instead of executed, and set_key is blocked too - otherwise any visitor to the
public URL could overwrite the owner's API key.

READING GUIDE
-------------
    STEP 1  Flask app + small in-memory rate limiter
    STEP 2  safe action handlers (AI, market, links)
    STEP 3  routes
    STEP 4  entry point
"""

import os
import threading
import time
from collections import defaultdict, deque

from flask import Flask, jsonify, request, send_from_directory

import matty_brain
import matty_market

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# STEP 1 - app + rate limiter
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)

# Actions that make sense on a server. Everything else needs the desktop app.
WEB_ACTIONS = {"command", "youtube", "whatsapp", "email", "market", "status", "test_cloud"}

# Refused on purpose: these either control a computer or leak the API key.
DESKTOP_ONLY = {
    "lock", "screenshot", "shutdown", "restart", "sleep", "test_mic",
    "activate", "set_key", "setup_email", "add_contact",
}

MAX_TEXT_CHARS = 500

# Naive per-IP limit: 20 requests per 5 minutes. Enough for a person, not enough
# to burn a free Groq quota if the URL is discovered.
RATE_LIMIT = 20
RATE_WINDOW = 300.0
_hits = defaultdict(deque)
_hits_lock = threading.Lock()


def rate_limited(ip):
    """True when this IP has used up its window."""
    now = time.time()
    with _hits_lock:
        bucket = _hits[ip]
        while bucket and now - bucket[0] > RATE_WINDOW:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT:
            return True
        bucket.append(now)
        return False


# ---------------------------------------------------------------------------
# STEP 2 - safe action handlers
# ---------------------------------------------------------------------------


def _link_action(kind, args):
    """Return a URL the browser opens, plus a sentence for the transcript."""
    if kind == "youtube":
        query = (args.get("query") or "").strip()
        if not query:
            return {"error": "No song or video given."}
        url = "https://www.youtube.com/results?search_query=" + requests_quote(query)
        return {"result": f"Opening YouTube results for {query}.", "url": url}

    if kind == "whatsapp":
        contact = (args.get("contact") or "").strip()
        message = (args.get("message") or "Hello from Matty").strip()
        digits = "".join(ch for ch in contact if ch.isdigit())
        if len(digits) >= 8:
            url = f"https://wa.me/{digits}?text={requests_quote(message)}"
            return {"result": f"Opening WhatsApp chat with {contact}.", "url": url}
        url = "https://web.whatsapp.com/send?text=" + requests_quote(message)
        return {
            "result": f"No number saved for {contact} in the web edition. Opening WhatsApp with the message drafted.",
            "url": url,
        }

    if kind == "email":
        to = (args.get("to") or "").strip()
        subject = requests_quote((args.get("subject") or "").strip())
        body = requests_quote((args.get("body") or "").strip())
        url = f"mailto:{to}?subject={subject}&body={body}"
        return {"result": f"Opening a mail draft to {to}.", "url": url}

    return {"error": "Unsupported link action."}


def requests_quote(value):
    """URL-encode without importing requests for one function."""
    from urllib.parse import quote

    return quote(value, safe="")


def _handle(kind, args):
    """Run one web-safe action and return a dict with result/error/url."""
    if kind in DESKTOP_ONLY:
        return {
            "error": f"'{kind}' is a desktop-only action. Run Matty locally for that."
        }
    if kind not in WEB_ACTIONS:
        return {"error": f"Unknown action '{kind}'."}

    if kind == "command":
        text = (args.get("text") or "").strip()[:MAX_TEXT_CHARS]
        if not text:
            return {"error": "Empty command."}
        return {"result": matty_brain.think(text)}

    if kind == "market":
        return {"result": matty_market.market_briefing() or "No market data available."}

    if kind == "status":
        state = matty_brain.cloud_status()
        if not state["has_key"]:
            return {"result": "Cloud: OFFLINE (no API key configured on the server)."}
        if state["cooldown"]:
            return {"result": f"Cloud: rate limited for {state['cooldown']}s."}
        return {"result": "Cloud: ONLINE."}

    if kind == "test_cloud":
        return {"result": matty_brain.cloud_test()}

    return _link_action(kind, args)


# ---------------------------------------------------------------------------
# STEP 3 - routes
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    return send_from_directory(APP_DIR, "matty_hud.html")


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.get("/api/status")
def api_status():
    return jsonify(matty_brain.cloud_status())


@app.get("/api/market")
def api_market():
    return jsonify({"result": matty_market.market_briefing() or "No market data."})


@app.get("/api/vitals")
def api_vitals():
    try:
        import psutil

        return jsonify(
            {
                "cpu": int(psutil.cpu_percent(interval=0.2)),
                "ram": int(psutil.virtual_memory().percent),
                "disk": int(psutil.disk_usage("/").percent),
            }
        )
    except Exception:
        return jsonify({"cpu": 0, "ram": 0, "disk": 0})


@app.post("/api/action")
def api_action():
    if rate_limited(request.remote_addr or "unknown"):
        return jsonify({"error": "Too many requests. Try again in a few minutes."}), 429

    payload = request.get_json(silent=True) or {}
    kind = str(payload.get("kind") or "command")
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        return jsonify({"error": "args must be an object."}), 400

    try:
        result = _handle(kind, args)
    except Exception as exc:  # never leak a traceback to the browser
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    status = 403 if "desktop-only" in result.get("error", "") else 200
    return jsonify(result), status


# ---------------------------------------------------------------------------
# STEP 4 - entry point (Render runs: gunicorn server:app)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
