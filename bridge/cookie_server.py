"""
cookie_server.py — Tiny localhost HTTP server for cookie & storage delivery.

Serves two distinct flows:
  1. Chromium companion flow (Firefox → Chromium):
     - /cookies  → JSON payload with cookies + token + target URL
     - /storage  → JSON payload with localStorage/sessionStorage
     - /         → Loading splash page

  2. Gecko companion flow (Chromium → Firefox):
     - /handoff?token=<TOKEN>  → Single-use JSON payload with cookies + storage + target URL
     - /handoff (no token)     → Fallback HTML page with install instructions

Response format for /cookies:  { "token": "<uuid>", "url": "<target>", "cookies": [...] }
Response format for /storage:  { "origin": "<origin>", "localStorage": {...}, "sessionStorage": {...} }
Response format for /handoff:  { "url": "<target>", "cookies": [...], "storage": {...} }
"""

import json
import time
import secrets
import uuid
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

log = logging.getLogger(__name__)

COOKIE_PORT = 47831
_HANDOFF_TIMEOUT_SECONDS = 30


# ── Fallback HTML for when gecko-extension is not installed ──────────
_FALLBACK_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>ChromiumBridge — Waiting for Extension</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      background: #161C24;
      color: #C4CDD5;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      text-align: center;
      padding: 24px;
    }
    .spinner {
      width: 48px; height: 48px;
      border: 4px solid #2E3A45;
      border-top-color: #00A76F;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin-bottom: 24px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    h2 {
      color: #FFFFFF;
      font-size: 20px;
      font-weight: 600;
      margin-bottom: 8px;
    }
    p { font-size: 14px; line-height: 1.6; max-width: 420px; }
    .status { margin-top: 16px; font-size: 13px; color: #637381; }
    .error-state { display: none; }
    .error-state h2 { color: #FF5630; }
    .error-state a {
      display: inline-block;
      margin-top: 16px;
      padding: 10px 24px;
      background: #00A76F;
      color: #fff;
      border-radius: 8px;
      text-decoration: none;
      font-weight: 600;
      font-size: 14px;
      transition: background 200ms;
    }
    .error-state a:hover { background: #007B55; }
  </style>
</head>
<body>
  <div id="waiting-state">
    <div class="spinner"></div>
    <h2>Waiting for ChromiumBridge Companion&hellip;</h2>
    <p>The handoff payload is ready. The Gecko Companion extension should pick it up automatically.</p>
    <div class="status" id="status">Checking&hellip;</div>
  </div>
  <div id="error-state" class="error-state">
    <h2>Extension Not Detected</h2>
    <p>The ChromiumBridge Gecko Companion extension is not installed or not active in this Firefox profile.</p>
    <p style="margin-top:8px;">Install it to enable authenticated tab handoffs from Chromium browsers.</p>
    <a href="https://github.com/niceBridge/ChromiumBridge#gecko-companion" target="_blank">
      Install Gecko Companion &rarr;
    </a>
  </div>
  <script>
    (function() {
      const TOKEN = "__HANDOFF_TOKEN__";
      const statusUrl = "http://127.0.0.1:__PORT__/status?token=" + TOKEN;
      let attempts = 0;
      const maxAttempts = 15;
      const interval = 1500;

      function check() {
        attempts++;
        document.getElementById("status").textContent = "Waiting for companion extension (attempt " + attempts + " of " + maxAttempts + ")…";
        fetch(statusUrl)
          .then(r => r.json())
          .then(data => {
            if (data.consumed) {
              document.getElementById("status").textContent = "Handoff complete! Redirecting…";
            } else {
              retry();
            }
          })
          .catch(() => retry());
      }

      function retry() {
        if (attempts >= maxAttempts) {
          document.getElementById("waiting-state").style.display = "none";
          document.getElementById("error-state").style.display = "block";
        } else {
          setTimeout(check, interval);
        }
      }

      setTimeout(check, interval);
    })();
  </script>
</body>
</html>"""


class _CookieHandler(BaseHTTPRequestHandler):
    """Handler serving both Chromium companion and Gecko companion endpoints."""

    # ── Chromium companion data (class-level, set before server starts) ──
    response_data = b'{"token":"","url":"","cookies":[]}'
    storage_data = b'{"origin":"","localStorage":null,"sessionStorage":null}'

    # ── Gecko handoff data (class-level, set before server starts) ──
    handoff_token = None          # The valid single-use token
    handoff_payload = None        # bytes: JSON payload for /handoff
    _token_consumed = False       # Set True after first successful read
    _payload_consumed_event = None  # threading.Event signalled on consumption
    _return_event = None          # threading.Event signalled when user clicks Back to Chromium
    _return_domain = None         # Domain returned from
    _return_cleaned = None        # None=pending, True/False after ephemeral cleanup
    _start_time = None            # Epoch start time

    def do_GET(self):
        # Reject requests not targeting localhost — guards against SSRF/port-scan
        host_header = self.headers.get("Host", "")
        if not host_header.startswith("127.0.0.1"):
            log.warning("Rejected request with unexpected Host header: %r", host_header)
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"Forbidden"}')
            return

        parsed = urlparse(self.path)
        path = parsed.path

        # ── Chromium companion endpoints (existing) ────────────
        if path == "/cookies":
            self._send_json(self.response_data)

        elif path == "/storage":
            self._send_json(self.storage_data)

        # ── Gecko companion handoff endpoint (new) ─────────────
        elif path == "/handoff":
            self._handle_handoff(parsed)

        elif path == "/status":
            query = parse_qs(parsed.query)
            token = query.get("token", [None])[0]
            status_obj = {
                "consumed": _CookieHandler._token_consumed,
                "valid": token == _CookieHandler.handoff_token,
            }
            self._send_json(json.dumps(status_obj).encode("utf-8"))

        elif path == "/return":
            query = parse_qs(parsed.query)
            domain = query.get("domain", [""])[0]
            _CookieHandler._return_domain = domain
            log.info("Return to Chromium triggered for domain: %s", domain)
            if _CookieHandler._return_event:
                _CookieHandler._return_event.set()
            self._send_json(b'{"status":"ok"}')

        elif path == "/wait-return":
            query = parse_qs(parsed.query)
            evt = _CookieHandler._return_event
            timeout_param = query.get("timeout", [None])[0]
            if timeout_param is not None:
                try:
                    timeout_val = min(max(float(timeout_param), 0.5), 30.0)
                except ValueError:
                    timeout_val = 5.0
            else:
                timeout_val = 5.0

            returned = evt.wait(timeout=timeout_val) if evt else False
            start = _CookieHandler._start_time or time.time()
            duration_ms = int((time.time() - start) * 1000)
            res = {
                "returned": bool(returned),
                "domain": _CookieHandler._return_domain or query.get("domain", [""])[0],
                "duration": duration_ms,
                "cleaned": _CookieHandler._return_cleaned,
            }
            if returned:
                log.info("wait-return returning RETURNED: domain=%s, duration=%d ms", res["domain"], duration_ms)
            self._send_json(json.dumps(res).encode("utf-8"))

        elif path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = '<html><head><title>ChromeBridge</title></head><body style="background:#222;color:#eee;text-align:center;padding-top:20vh;font-family:sans-serif;"><h2>Loading session...</h2></body></html>'
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, data):
        """Send a JSON response with CORS headers."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _handle_handoff(self, parsed):
        """
        Handle /handoff requests for the Gecko companion extension.
        - With valid token: serve the payload JSON (single-use).
        - With consumed/invalid token: 403 Forbidden.
        - Without token: serve fallback HTML page.
        """
        query = parse_qs(parsed.query)
        token = query.get("token", [None])[0]

        # No token provided → serve fallback HTML page
        if not token:
            self._serve_fallback_html()
            return

        # Token already consumed → reject
        if _CookieHandler._token_consumed:
            self.send_response(403)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"Token already consumed"}')
            return

        # Wrong token → reject
        if token != _CookieHandler.handoff_token:
            self.send_response(403)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"Invalid token"}')
            return

        # Distinguish between browser tab navigation and extension fetch.
        # The browser tab should just see the splash screen, preserving the token.
        # The extension specifically sends the X-Bridge-Fetch header.
        if self.headers.get("X-Bridge-Fetch") != "1":
            self._serve_fallback_html()
            return

        # ── Valid token: serve payload and mark consumed ──
        _CookieHandler._token_consumed = True
        self._send_json(_CookieHandler.handoff_payload)
        log.info("Handoff payload consumed by extension (token: %s...)", token[:8])

        # Signal that the payload was consumed (triggers server shutdown)
        if _CookieHandler._payload_consumed_event:
            _CookieHandler._payload_consumed_event.set()

    def _serve_fallback_html(self):
        """Serve the fallback HTML page for missing extension."""
        html = _FALLBACK_HTML_TEMPLATE
        html = html.replace("__HANDOFF_TOKEN__", _CookieHandler.handoff_token or "")
        html = html.replace("__PORT__", str(COOKIE_PORT))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress console output


# ── Public API ────────────────────────────────────────────────────────


def start_cookie_server(cookies, target_url="", storage_data=None):
    """
    Start the cookie server for the Chromium companion flow.
    Returns the HTTPServer instance, or None on failure.
    (Existing API — unchanged for backward compatibility.)
    """
    payload = {
        "token": str(uuid.uuid4()),
        "url": target_url,
        "cookies": cookies or [],
    }
    _CookieHandler.response_data = json.dumps(payload).encode("utf-8")

    # Stage storage data for the /storage endpoint
    storage_payload = storage_data or {}
    _CookieHandler.storage_data = json.dumps(storage_payload).encode("utf-8")

    # Clear any leftover handoff state
    _CookieHandler.handoff_token = None
    _CookieHandler.handoff_payload = None
    _CookieHandler._token_consumed = False
    _CookieHandler._payload_consumed_event = None

    try:
        HTTPServer.allow_reuse_address = True
        server = HTTPServer(("127.0.0.1", COOKIE_PORT), _CookieHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server
    except OSError:
        return None


def start_handoff_server(cookies, target_url="", storage_data=None):
    """
    Start the cookie server for the Gecko companion handoff flow.
    Serves a single-use /handoff?token=<TOKEN> endpoint with the full
    state payload (cookies + storage + target URL).

    Returns (server, token) on success, or (None, None) on failure.
    The server auto-shuts down after the payload is consumed or after
    a 30-second timeout.
    """
    token = secrets.token_urlsafe(32)

    handoff_payload = {
        "url": target_url,
        "cookies": cookies or [],
        "storage": storage_data or {},
    }

    # Set up handler class-level state
    _CookieHandler.handoff_token = token
    _CookieHandler.handoff_payload = json.dumps(handoff_payload).encode("utf-8")
    _CookieHandler._token_consumed = False

    consumed_event = threading.Event()
    return_event = threading.Event()
    _CookieHandler._payload_consumed_event = consumed_event
    _CookieHandler._return_event = return_event
    _CookieHandler._return_domain = None
    _CookieHandler._return_cleaned = None
    _CookieHandler._start_time = time.time()

    # Also stage the Chromium companion endpoints (in case they're needed)
    chromium_payload = {
        "token": str(uuid.uuid4()),
        "url": target_url,
        "cookies": cookies or [],
    }
    _CookieHandler.response_data = json.dumps(chromium_payload).encode("utf-8")
    _CookieHandler.storage_data = json.dumps(storage_data or {}).encode("utf-8")

    try:
        HTTPServer.allow_reuse_address = True
        server = HTTPServer(("127.0.0.1", COOKIE_PORT), _CookieHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        # NOTE: No watchdog timer here. bridge.py manages the server lifecycle
        # explicitly — it calls stop_cookie_server() after the companion
        # consumes the payload (or after the 30s timeout). An independent
        # watchdog was racing with the companion extension on cold starts,
        # killing the server before the extension could fetch the payload.

        return server, token
    except OSError as e:
        log.error("Failed to start handoff server: %s", e)
        return None, None


def stop_cookie_server(server):
    """Shut down the cookie server."""
    if server:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
