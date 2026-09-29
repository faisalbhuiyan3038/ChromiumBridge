#!/usr/bin/env python3
"""
session_daemon.py — Detached per-handoff session host for Chromium -> Gecko.

Why this exists:
  bridge.py runs as a one-shot native-messaging host (one stdin message, one
  stdout response, then Chrome closes the pipe and the process exits). Any
  daemon threads it spawns (HTTP handoff server, Firefox watcher) die with it.
  That broke both /wait-return (no banner) and ephemeral profile cleanup
  (folder survived until the next popup opened and swept orphans).

  This daemon is spawned DETACHED (no window, survives bridge exit) and owns:
    1. The localhost HTTP server (127.0.0.1:47831) serving /handoff, /status,
       /return, /wait-return (with `cleaned` flag), /cookies, /storage.
    2. The Firefox liveness watch (PID poll + profile-in-use probe).
    3. Ephemeral profile deletion with extended backoff.
    4. Per-session status JSON for debugging.

Usage (spawned by bridge.py, not by hand):
  python session_daemon.py --profile-dir <dir> --firefox-pid <pid> \\
      --domain <domain> --port 47831 --payload-file <json> [--await-consume]
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from profile import (  # noqa: E402
    _rmtree_with_backoff,
    _pid_alive,
    _profile_in_use,
    _lock_files_free,
)

COOKIE_PORT_DEFAULT = 47831

_log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge_debug.log")
logging.basicConfig(
    filename=_log_file,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("session_daemon")


def _write_status(status_path, data):
    try:
        tmp = status_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, status_path)
    except OSError as e:
        log.debug("Could not write session status %s: %s", status_path, e)


def run_daemon(profile_dir, firefox_pid, domain, port, payload, await_consume=False, profile_mode="ephemeral"):
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs

    HTTPServer.allow_reuse_address = True
    token = payload.get("token")
    handoff_payload_bytes = json.dumps({
        "url": payload.get("url", ""),
        "cookies": payload.get("cookies", []),
        "storage": payload.get("storage", {}),
    }).encode("utf-8")
    chromium_payload_bytes = json.dumps({
        "token": token,
        "url": payload.get("url", ""),
        "cookies": payload.get("cookies", []),
    }).encode("utf-8")
    storage_bytes = json.dumps(payload.get("storage", {})).encode("utf-8")

    state = {
        "token_consumed": False,
        "consumed_event": threading.Event(),
        "return_event": threading.Event(),
        "return_explicit": False,  # True only when /return arrived via HTTP
        "return_domain": None,
        "return_cleaned": False if profile_mode == "persistent" else None,  # False for persistent, True/False after ephemeral cleanup
        "start_time": time.time(),
    }

    sessions_dir = os.path.join(tempfile.gettempdir(), "cb-sessions")
    try:
        os.makedirs(sessions_dir, exist_ok=True)
    except OSError:
        pass
    status_path = os.path.join(
        sessions_dir, os.path.basename(profile_dir.rstrip(os.sep)) + ".json"
    )

    def set_status(**kw):
        base = {
            "profile_dir": profile_dir,
            "firefox_pid": firefox_pid,
            "domain": domain,
            "port": port,
            "daemon_pid": os.getpid(),
            "updated": time.time(),
        }
        base.update(kw)
        _write_status(status_path, base)

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, data):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            host_header = self.headers.get("Host", "")
            if not host_header.startswith("127.0.0.1"):
                log.warning("Rejected request with Host %r", host_header)
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"Forbidden"}')
                return
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/cookies":
                self._send_json(chromium_payload_bytes)
            elif path == "/storage":
                self._send_json(storage_bytes)
            elif path == "/handoff":
                query = parse_qs(parsed.query)
                req_token = query.get("token", [None])[0]
                if not req_token:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<html><body>ChromiumBridge handoff ready.</body></html>")
                    return
                if state["token_consumed"]:
                    self.send_response(403)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error":"Token already consumed"}')
                    return
                if req_token != token:
                    self.send_response(403)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error":"Invalid token"}')
                    return
                if self.headers.get("X-Bridge-Fetch") != "1":
                    # Browser tab navigation, not the extension fetch: keep token alive.
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<html><body>ChromiumBridge handoff ready.</body></html>")
                    return
                state["token_consumed"] = True
                self._send_json(handoff_payload_bytes)
                log.info("Daemon: handoff payload consumed (token %s...)", (token or "")[:8])
                state["consumed_event"].set()
                set_status(consumed=True)
            elif path == "/status":
                query = parse_qs(parsed.query)
                t = query.get("token", [None])[0]
                self._send_json(json.dumps({
                    "consumed": state["token_consumed"],
                    "valid": t == token,
                }).encode("utf-8"))
            elif path == "/return":
                query = parse_qs(parsed.query)
                d = query.get("domain", [""])[0]
                state["return_domain"] = d
                state["return_explicit"] = True
                log.info("Daemon: explicit /return ping for domain=%s", d)
                state["return_event"].set()
                set_status(returned=True, return_explicit=True, return_domain=d)
                self._send_json(b'{"status":"ok"}')
            elif path == "/wait-return":
                query = parse_qs(parsed.query)
                timeout_param = query.get("timeout", [None])[0]
                try:
                    timeout_val = min(max(float(timeout_param), 0.5), 30.0) \
                        if timeout_param is not None else 5.0
                except ValueError:
                    timeout_val = 5.0
                returned = state["return_event"].wait(timeout=timeout_val)
                duration_ms = int((time.time() - state["start_time"]) * 1000)
                res = {
                    "returned": bool(returned),
                    "domain": state["return_domain"]
                    or query.get("domain", [""])[0],
                    "duration": duration_ms,
                    "cleaned": state["return_cleaned"],
                }
                if returned:
                    log.info("Daemon: /wait-return RETURNED domain=%s cleaned=%s",
                             res["domain"], res["cleaned"])
                self._send_json(json.dumps(res).encode("utf-8"))
            elif path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>ChromiumBridge session active.</body></html>")
            else:
                self.send_response(404)
                self.end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET")
            self.end_headers()

        def log_message(self, *args):
            pass

    # Bind with retry: bridge.py stops its own server just before spawning us,
    # but the port may take a moment to release. Small delay avoids a hot loop.
    time.sleep(0.8)
    server = None
    for attempt in range(20):
        try:
            server = HTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError as e:
            log.debug("Daemon bind attempt %d failed: %s", attempt + 1, e)
            time.sleep(0.5)
    if server is None:
        log.error("Daemon could not bind 127.0.0.1:%d — exiting", port)
        set_status(error="bind_failed")
        return 1

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log.info("Daemon listening on 127.0.0.1:%d pid=%d profile=%s firefox_pid=%s domain=%s",
             port, os.getpid(), profile_dir, firefox_pid, domain)
    set_status(listening=True, consumed=False, returned=False)

    # Overwrite session.pid so orphan sweeps know this daemon owns the profile.
    try:
        with open(os.path.join(profile_dir, "session.pid"), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

    if await_consume:
        # Unclaimed path: give the companion a grace window, then fall through
        # to the lifetime watch (cleanup on Firefox exit regardless).
        state["consumed_event"].wait(timeout=30.0)

    # ── Lifetime watch ──
    # The Popen'd Firefox launcher stub exits ~1s after spawning the real
    # browser (verified: exit code 0 while the window stays open), so its PID
    # is USELESS for lifetime tracking. The real browser carries
    # `-profile <dir>` in its command line, hence:
    #   Phase 1: require the profile to be observed IN USE at least once
    #            (60s grace for slow start / slow CIM query).
    #   Phase 2: conclude "exited" only after launcher dead AND profile not
    #            in use AND lock files free, confirmed 3x in a row (absorbs
    #            self-restart gaps and single CIM blips).
    # An explicit /return ping (Back to Chromium click) unblocks Chromium
    # immediately, but cleanup STILL waits for real browser exit below.
    # Watch errors NEVER fall through to cleanup — they reset confirmations
    # and keep waiting (3h session cap as backstop so the port is released).
    exit_confirmed = False
    my_pid = os.getpid()
    try:
        seen_in_use = False
        for _ in range(30):  # Phase 1: up to ~60s
            try:
                if _profile_in_use(profile_dir, exclude_pid=my_pid) or not _lock_files_free(profile_dir):
                    seen_in_use = True
                    break
            except Exception as e:
                log.warning("Daemon startup probe error: %r", e)
            time.sleep(2.0)
        if seen_in_use:
            log.info("Daemon: Firefox session confirmed (profile in use)")
        else:
            log.warning("Daemon: session never observed in use within 60s; "
                        "exit detection armed anyway")
        set_status(session_confirmed=seen_in_use)

        deadline = time.monotonic() + 3 * 3600
        confirmations = 0
        capped = False
        while True:  # Phase 2
            if time.monotonic() >= deadline:
                capped = True
                break
            try:
                launcher = _pid_alive(firefox_pid)
                in_use = _profile_in_use(profile_dir, exclude_pid=my_pid)
                locks_free = _lock_files_free(profile_dir)
            except Exception as e:
                log.warning("Daemon watch probe error, continuing: %r", e)
                confirmations = 0
                time.sleep(2.0)
                continue
            if (not launcher) and (not in_use) and locks_free:
                confirmations += 1
                if confirmations >= 3:
                    break
            else:
                if confirmations:
                    log.debug("Daemon: exit signal interrupted "
                              "(launcher=%s in_use=%s locks_free=%s)",
                              launcher, in_use, locks_free)
                confirmations = 0
            time.sleep(2.0)
        if capped:
            log.warning("Daemon: session cap reached without confirmed exit")
        else:
            log.info("Daemon: Firefox session ended (exit confirmed x3)")
        set_status(firefox_exited=True)
        exit_confirmed = True
    except Exception:
        log.exception("Daemon lifetime watch unexpected failure — "
                      "will NOT delete profile without confirmed exit")

    # ── Cleanup ──
    # Ephemeral profiles are deleted with extended backoff.
    # Persistent profiles are preserved across sessions (never deleted).
    cleaned = False
    if profile_mode == "persistent":
        log.info("Daemon: persistent profile retained (not deleted): %s", profile_dir)
        cleaned = False
    elif not exit_confirmed:
        log.error("Daemon: no confirmed exit — leaving profile for orphan sweep")
    else:
        try:
            log.info("Daemon: cleaning ephemeral profile %s", profile_dir)
            cleaned = bool(_rmtree_with_backoff(profile_dir, max_wait=60.0))
        except Exception as e:
            log.warning("Daemon cleanup failed: %s", e)
    state["return_cleaned"] = cleaned
    log.info("Daemon: cleanup cleaned=%s profile=%s (mode=%s)", cleaned, profile_dir, profile_mode)
    set_status(cleaned=cleaned)

    # Signal return so Chromium unblocks + banners (idempotent if the user
    # already clicked Back to Chromium, which sets return_explicit).
    if state["return_domain"] is None:
        state["return_domain"] = domain
    state["return_event"].set()
    set_status(returned=True, return_domain=state["return_domain"])

    # If rmtree failed, leave folder for the next-launch orphan sweep (safe).
    # Keep server alive briefly so pending /wait-return polls see cleaned flag.
    time.sleep(5.0)
    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass
    # Remove payload + status files (best effort).
    try:
        if os.path.isfile(payload.get("_payload_file", "")):
            os.remove(payload["_payload_file"])
    except OSError:
        pass
    if cleaned or profile_mode == "persistent":
        try:
            if os.path.isfile(status_path):
                os.remove(status_path)
        except OSError:
            pass
    else:
        set_status(cleaned=False, note="left for orphan sweep")
    log.info("Daemon exiting cleaned=%s", cleaned)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile-dir", required=True)
    ap.add_argument("--firefox-pid", required=True, type=int)
    ap.add_argument("--domain", default="")
    ap.add_argument("--port", default=COOKIE_PORT_DEFAULT, type=int)
    ap.add_argument("--payload-file", required=True)
    ap.add_argument("--await-consume", action="store_true")
    ap.add_argument("--profile-mode", default="ephemeral", choices=["ephemeral", "persistent"])
    args = ap.parse_args(argv)

    try:
        with open(args.payload_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        log.error("Daemon could not read payload file %s: %s", args.payload_file, e)
        return 1
    payload["_payload_file"] = args.payload_file
    return run_daemon(args.profile_dir, args.firefox_pid, args.domain,
                      args.port, payload, await_consume=args.await_consume,
                      profile_mode=args.profile_mode)


if __name__ == "__main__":
    raise SystemExit(main())
