"""
cookie_server.py — Tiny localhost HTTP server for cookie & storage delivery.
The bridge starts this before launching Chrome. The companion extension
fetches cookies from /cookies and storage data from /storage on startup.

Response format for /cookies: { "token": "<uuid>", "url": "<target>", "cookies": [...] }
Response format for /storage: { "origin": "<origin>", "localStorage": {...}, "sessionStorage": {...} }
"""

import json
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

COOKIE_PORT = 47831


class _CookieHandler(BaseHTTPRequestHandler):
    response_data = b'{"token":"","url":"","cookies":[]}'
    storage_data = b'{"origin":"","localStorage":null,"sessionStorage":null}'

    def do_GET(self):
        if self.path == "/cookies":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(self.response_data)
        elif self.path == "/storage":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(self.storage_data)
        elif self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = '<html><head><title>ChromeBridge</title></head><body style="background:#222;color:#eee;text-align:center;padding-top:20vh;font-family:sans-serif;"><h2>Loading session...</h2></body></html>'
            self.wfile.write(html.encode("utf-8"))
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


def start_cookie_server(cookies, target_url="", storage_data=None):
    """Start the cookie server in a daemon thread. Returns the HTTPServer."""
    payload = {
        "token": str(uuid.uuid4()),
        "url": target_url,
        "cookies": cookies or [],
    }
    _CookieHandler.response_data = json.dumps(payload).encode("utf-8")

    # Stage storage data for the /storage endpoint
    storage_payload = storage_data or {}
    _CookieHandler.storage_data = json.dumps(storage_payload).encode("utf-8")

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
