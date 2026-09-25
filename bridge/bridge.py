#!/usr/bin/env python3 -u
"""
bridge.py — ChromeBridge / FirefoxBridge unified native messaging host.
Reads length-prefixed JSON from stdin, dispatches actions, responds via stdout.
Supports bidirectional handoff: Firefox -> Chromium and Chromium -> Gecko.
"""

import sys
import json
import struct
import time
import traceback

from detect import (
    detect_all,
    resolve_browser,
    detect_profiles,
    get_browser_family,
)
from profile import create_ephemeral, resolve_persistent, cleanup
from cookies import stage_cookies
from cookies_gecko import stage_gecko_profile
from launcher import (
    prepare_companion,
    build_flags,
    build_gecko_flags,
    launch,
    wait_and_cleanup,
)
from config import load_config, save_config, get_config_value, set_config_value
from logger import log_session, log_launch_time
from cookie_server import start_cookie_server, stop_cookie_server, COOKIE_PORT
from install import reinstall_from_config


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


def handle_ping(message=None):
    """Handle ping action — return status and detected browsers."""
    try:
        config = load_config()
        target_type = message.get("target_type") if message else None
        browsers = detect_all(config, target_type=target_type)
        chromium_browsers = [b for b in browsers if b.get("family") == "chromium"]
        gecko_browsers = [b for b in browsers if b.get("family") == "gecko"]

        return {
            "status": "ok",
            "browsers": browsers,
            "chromium_browsers": chromium_browsers,
            "gecko_browsers": gecko_browsers,
            "timestamp": time.time(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def handle_detect(message=None):
    """Handle detect action — return list of detected browsers."""
    try:
        config = load_config()
        target_type = message.get("target_type") if message else None
        browsers = detect_all(config, target_type=target_type)
        chromium_browsers = [b for b in browsers if b.get("family") == "chromium"]
        gecko_browsers = [b for b in browsers if b.get("family") == "gecko"]

        return {
            "browsers": browsers,
            "chromium_browsers": chromium_browsers,
            "gecko_browsers": gecko_browsers,
        }
    except Exception as e:
        return {"error": str(e)}


def handle_launch(message):
    """Handle launch action — full handoff flow for both Chromium and Gecko."""
    try:
        config = load_config()
        url = message.get("url", "")
        domain = message.get("domain", "")
        cookies = message.get("cookies", [])
        browser_id = message.get("browser", config.get("default_browser", "brave"))
        mode = message.get("mode", "popup")
        profile_mode = message.get("profile", "ephemeral")
        incognito = message.get("incognito", False)
        storage_data = message.get("storage", {})

        # Resolve browser path
        browser_path = resolve_browser(browser_id, config)
        if not browser_path:
            return {"error": f"Browser '{browser_id}' not found on this system."}

        family = get_browser_family(browser_id)

        # ── Branch A: Gecko Target (Firefox, LibreWolf, Floorp, Zen) ──
        if family == "gecko":
            if profile_mode == "persistent":
                session_cfg = config.get("session", {})
                per_browser = session_cfg.get("persistent_profiles", {})
                persistent_path = per_browser.get(browser_id, "")
                if not persistent_path:
                    persistent_path = session_cfg.get("persistent_profile_path", "")
                profile_dir = resolve_persistent(persistent_path)
            else:
                profile_dir = create_ephemeral()

            # Direct SQLite cookie & pref injection
            stage_gecko_profile(profile_dir, cookies=cookies, target_url=url)

            # Optional local storage server
            cookie_server = None
            if cookies or storage_data:
                cookie_server = start_cookie_server(
                    cookies, target_url=url, storage_data=storage_data
                )

            flags = build_gecko_flags(
                config=config,
                url=url,
                mode=mode,
                profile_dir=profile_dir,
                incognito=incognito,
            )

            start_time = time.time()
            process = launch(browser_path, flags)

            # Wait for Gecko browser to exit
            process.wait()
            duration_ms = int((time.time() - start_time) * 1000)

            stop_cookie_server(cookie_server)
            log_session(domain, browser_id, duration_ms, "closed")
            log_launch_time(browser_id, time.time() - start_time)
            wait_and_cleanup(profile_dir, profile_mode)

            return {
                "event": "closed",
                "domain": domain,
                "duration": duration_ms,
            }

        # ── Branch B: Chromium Target (Brave, Edge, Vivaldi, Opera) ──
        else:
            if profile_mode == "persistent":
                session_cfg = config.get("session", {})
                per_browser = session_cfg.get("persistent_profiles", {})
                persistent_path = per_browser.get(browser_id, "")
                if not persistent_path:
                    persistent_path = session_cfg.get("persistent_profile_path", "")
                profile_dir = resolve_persistent(persistent_path)
            else:
                profile_dir = create_ephemeral()

            companion_dir = prepare_companion(profile_dir)

            if cookies:
                stage_cookies(cookies, url, companion_dir)

            cookie_server = None
            if cookies or storage_data:
                cookie_server = start_cookie_server(
                    cookies, target_url=url, storage_data=storage_data
                )

            if cookie_server:
                launch_url = f"http://127.0.0.1:{COOKIE_PORT}/"
            else:
                launch_url = url

            flags = build_flags(
                config=config,
                url=launch_url,
                mode=mode,
                profile_dir=profile_dir,
                companion_dir=companion_dir,
                incognito=incognito,
            )

            start_time = time.time()
            process = launch(browser_path, flags)

            process.wait()
            duration_ms = int((time.time() - start_time) * 1000)

            stop_cookie_server(cookie_server)
            log_session(domain, browser_id, duration_ms, "closed")
            log_launch_time(browser_id, time.time() - start_time)
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
        for key, value in new_config.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
        save_config(config)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}


def handle_reinstall(message):
    """Re-run native host installation with current config paths."""
    try:
        new_python = message.get("python_path")
        new_bridge_dir = message.get("bridge_dir")
        if new_python or new_bridge_dir:
            config = load_config()
            if new_python:
                config["python_path"] = new_python
            if new_bridge_dir:
                config["bridge_dir"] = new_bridge_dir
            save_config(config)
        return reinstall_from_config()
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}


def handle_detect_profiles(message):
    """Detect existing browser profiles for a specific browser."""
    try:
        config = load_config()
        browser_id = message.get("browser_id", "")
        if browser_id:
            profiles = detect_profiles(browser_id, config)
            return {"profiles": profiles}
        else:
            all_profiles = {}
            browsers = detect_all(config)
            for b in browsers:
                all_profiles[b["id"]] = detect_profiles(b["id"], config)
            return {"profiles": all_profiles}
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
            response = handle_ping(message)
        elif action == "detect":
            response = handle_detect(message)
        elif action == "launch":
            response = handle_launch(message)
        elif action == "config_get":
            response = handle_config_get()
        elif action == "config_set":
            response = handle_config_set(message)
        elif action == "reinstall":
            response = handle_reinstall(message)
        elif action == "detect_profiles":
            response = handle_detect_profiles(message)
        elif action == "health":
            response = {"status": "ok", "timestamp": time.time()}
        else:
            response = {"error": f"Unknown action: {action}"}

        send_message(response)


if __name__ == "__main__":
    main()
