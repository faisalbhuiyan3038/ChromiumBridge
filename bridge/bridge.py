#!/usr/bin/env python3 -u
"""
bridge.py — ChromeBridge native messaging host.
Reads length-prefixed JSON from stdin, dispatches actions, responds via stdout.
"""

import sys
import json
import struct
import time
import traceback

from detect import detect_all, resolve_browser
from profile import create_ephemeral, resolve_persistent, cleanup
from cookies import stage_cookies
from launcher import prepare_companion, build_flags, launch, wait_and_cleanup
from config import load_config, save_config, get_config_value, set_config_value
from logger import log_session, log_launch_time
from cookie_server import start_cookie_server, stop_cookie_server


def read_message():
    """Read a native messaging message from stdin."""
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length or len(raw_length) < 4:
        return None
    message_length = struct.unpack("=I", raw_length)[0]
    raw_message = sys.stdin.buffer.read(message_length)
    if not raw_message:
        return None
    return json.loads(raw_message.decode("utf-8"))


def send_message(message):
    """Write a native messaging message to stdout."""
    encoded = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def handle_ping():
    """Handle ping action — return status and detected browsers."""
    try:
        config = load_config()
        browsers = detect_all(config)
        return {
            "status": "ok",
            "browsers": browsers,
            "timestamp": time.time(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def handle_detect():
    """Handle detect action — return list of detected browsers."""
    try:
        config = load_config()
        browsers = detect_all(config)
        return {"browsers": browsers}
    except Exception as e:
        return {"error": str(e)}


def handle_launch(message):
    """Handle launch action — full handoff flow."""
    try:
        config = load_config()
        url = message.get("url", "")
        domain = message.get("domain", "")
        cookies = message.get("cookies", [])
        browser_id = message.get("browser", config.get("default_browser", "chrome"))
        mode = message.get("mode", "popup")
        profile_mode = message.get("profile", "ephemeral")
        incognito = message.get("incognito", False)

        # Resolve browser path
        browser_path = resolve_browser(browser_id, config)
        if not browser_path:
            return {"error": f"Browser '{browser_id}' not found on this system."}

        # Create profile
        if profile_mode == "persistent":
            # Check per-browser path first, then global fallback
            session_cfg = config.get("session", {})
            per_browser = session_cfg.get("persistent_profiles", {})
            persistent_path = per_browser.get(browser_id, "")
            if not persistent_path:
                persistent_path = session_cfg.get("persistent_profile_path", "")
            profile_dir = resolve_persistent(persistent_path)
        else:
            profile_dir = create_ephemeral()

        # Prepare companion extension (session-local copy)
        companion_dir = prepare_companion(profile_dir)

        # Stage cookies into companion copy (for --load-extension path)
        if cookies:
            stage_cookies(cookies, companion_dir)

        # Start localhost cookie server with target URL
        # Chrome opens about:blank first; the companion injects cookies then
        # navigates to the target URL. This prevents the server from creating
        # a new session on the initial (cookieless) page load.
        cookie_server = None
        if cookies:
            cookie_server = start_cookie_server(cookies, target_url=url)

        # Build flags — use about:blank as the initial URL when we have cookies
        # (companion will navigate to the real URL after injection)
        launch_url = "about:blank" if cookies else url
        flags = build_flags(
            config=config,
            url=launch_url,
            mode=mode,
            profile_dir=profile_dir,
            companion_dir=companion_dir,
            incognito=incognito,
        )

        # Launch
        start_time = time.time()
        process = launch(browser_path, flags)

        # Wait for Chromium to close
        process.wait()
        duration_ms = int((time.time() - start_time) * 1000)

        # Stop cookie server
        stop_cookie_server(cookie_server)

        # Log session
        log_session(domain, browser_id, duration_ms, "closed")
        log_launch_time(browser_id, time.time() - start_time)

        # Cleanup
        wait_and_cleanup(profile_dir, profile_mode, companion_dir)

        return {
            "event": "closed",
            "domain": domain,
            "duration": duration_ms,
        }

    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}


def handle_config_get():
    """Return the current config."""
    try:
        config = load_config()
        return config
    except Exception as e:
        return {"error": str(e)}


def handle_config_set(message):
    """Merge partial config update."""
    try:
        config = load_config()
        new_config = message.get("config", {})
        # Deep merge top-level keys
        for key, value in new_config.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
        save_config(config)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}


def main():
    """Main message loop."""
    while True:
        message = read_message()
        if message is None:
            break

        action = message.get("action", "")

        if action == "ping":
            response = handle_ping()
        elif action == "detect":
            response = handle_detect()
        elif action == "launch":
            response = handle_launch(message)
        elif action == "config_get":
            response = handle_config_get()
        elif action == "config_set":
            response = handle_config_set(message)
        elif action == "health":
            response = {"status": "ok", "timestamp": time.time()}
        else:
            response = {"error": f"Unknown action: {action}"}

        send_message(response)


if __name__ == "__main__":
    main()
