"""
cookie_server.py — Tiny localhost HTTP server for cookie delivery.
The bridge starts this before launching Chrome. The companion extension
fetches cookies from it on startup or tab load.

Response format: { "token": "<uuid>", "url": "<target>", "cookies": [...] }
The token is unique per bridge launch so the companion can detect new sessions.
The url is the target page — Chrome opens about:blank first, then the companion
navigates there AFTER injecting cookies.
"""

import json
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

COOKIE_PORT = 47831


class _CookieHandler(BaseHTTPRequestHandler):
    response_data = b'{"token":"","url":"","cookies":[]}'

    def do_GET(self):
        if self.path == "/cookies":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(self.response_data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress console output


def start_cookie_server(cookies, target_url=""):
    """Start the cookie server in a daemon thread. Returns the HTTPServer."""
    payload = {
        "token": str(uuid.uuid4()),
        "url": target_url,
        "cookies": cookies or [],
    }
    _CookieHandler.response_data = json.dumps(payload).encode("utf-8")
    try:
        server = HTTPServer(("127.0.0.1", COOKIE_PORT), _CookieHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server
    except OSError:
        return None


def stop_cookie_server(server):
    """Shut down the cookie server."""
    if server:
        try:
            server.shutdown()
        except Exception:
            pass
