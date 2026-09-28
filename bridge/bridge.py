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
import logging
import os

# Write debug log next to the bridge script so issues can be diagnosed easily
_log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge_debug.log")
logging.basicConfig(
    filename=_log_file,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bridge")

from detect import (
    detect_all,
    resolve_browser,
    detect_profiles,
    get_browser_family,
)
import threading
from profile import (
    create_ephemeral, resolve_persistent, cleanup,
    sweep_orphaned_profiles, is_xpi_signed, locate_companion_xpi,
    inspect_xpi, stage_gecko_ephemeral_profile, wait_profile_free, _rmtree_with_backoff,
)
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
from cookie_server import (
    start_cookie_server, start_handoff_server, stop_cookie_server,
    COOKIE_PORT, _CookieHandler,
)
from install import reinstall_from_config

import urllib.request
import urllib.parse


def _signal_return(domain):
    """
    Fire http://127.0.0.1:<PORT>/return?domain=<domain> to signal
    the Chromium extension that Firefox has exited. Called from
    background watcher threads when proc.wait() completes.
    Best-effort — silently ignores errors (server may already be gone).
    """
    try:
        encoded_domain = urllib.parse.quote(domain or "", safe="")
        url = f"http://127.0.0.1:{COOKIE_PORT}/return?domain={encoded_domain}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            resp.read()
        log.info("Signaled /return for domain=%s", domain)
    except Exception as e:
        log.debug("Could not signal /return (server may already be closed): %s", e)


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

        log.info("handle_launch: url=%s browser=%s cookies=%d storage_keys=%s",
                 url, browser_id, len(cookies),
                 list(storage_data.get("localStorage", {}).keys()) if storage_data.get("localStorage") else [])

        # Resolve browser path
        browser_path = resolve_browser(browser_id, config)
        if not browser_path:
            log.error("Browser '%s' not found on this system", browser_id)
            return {"error": f"Browser '{browser_id}' not found on this system."}

        family = get_browser_family(browser_id, config=config, path=browser_path)
        log.info("Browser family: %s, path: %s", family, browser_path)

        # ── Branch A: Gecko Target (Firefox, LibreWolf, Floorp, Zen) ──
        if family == "gecko":
            session_cfg = config.get("session", {})
            gecko_mode = session_cfg.get("gecko_injection_mode", "companion")
            log.info("Gecko injection mode: %s", gecko_mode)

            # ── Companion mode: route through gecko-extension ──
            if gecko_mode == "companion":

                # ── Ephemeral profile: cold-start Firefox with sideloaded companion ──
                if profile_mode == "ephemeral":
                    companion_xpi = locate_companion_xpi(config)
                    if not companion_xpi:
                        configured_xpi = (
                            config.get("gecko_companion_xpi")
                            or session_cfg.get("gecko_companion_xpi", "")
                        )
                        if configured_xpi:
                            msg = (
                                f"Companion XPI not found at configured path: '{configured_xpi}'. "
                                "Please verify the path in extension Settings (Options -> Session -> Companion XPI)."
                            )
                        else:
                            msg = (
                                "Gecko Companion XPI not found. Please configure the XPI file path in "
                                "extension Settings (Options -> Session -> Companion XPI) or place it in "
                                "releases/gecko-extension/."
                            )
                        return {
                            "status": "error",
                            "event": "no_xpi",
                            "error": msg,
                        }

                    if not is_xpi_signed(companion_xpi):
                        return {
                            "status": "error",
                            "event": "unsigned_xpi",
                            "path": companion_xpi,
                            "error": (
                                f"Companion XPI at '{companion_xpi}' is not signed by AMO yet. "
                                "Submit it to AMO (unlisted channel), download the signed copy, "
                                "and update the path in Settings."
                            ),
                        }

                    profile_dir = create_ephemeral()
                    log.info("Created ephemeral gecko profile: %s", profile_dir)

                    try:
                        stage_gecko_ephemeral_profile(profile_dir, companion_xpi)
                    except Exception as e:
                        log.error("Failed to stage ephemeral gecko profile: %s", e)
                        _rmtree_with_backoff(profile_dir)
                        return {"error": f"Failed to prepare ephemeral Firefox profile: {e}"}

                    # Start handoff server with tokenized payload
                    handoff_server, handoff_token = start_handoff_server(
                        cookies, target_url=url, storage_data=storage_data
                    )
                    if not handoff_server:
                        _rmtree_with_backoff(profile_dir)
                        return {"error": "Failed to start handoff server on port %d" % COOKIE_PORT}

                    launch_url = f"http://127.0.0.1:{COOKIE_PORT}/handoff?token={handoff_token}"
                    log.info("Handoff URL (ephemeral): %s", launch_url)

                    flags = build_gecko_flags(
                        config=config,
                        url=launch_url,
                        mode=mode,
                        profile_dir=profile_dir,   # isolated profile with sideloaded XPI
                        incognito=incognito,
                        companion_mode=False,       # use -profile/-no-remote/-new-instance
                    )
                    log.info("Launching Firefox (ephemeral companion mode) with flags: %s", flags)

                    start_time = time.time()
                    process = launch(browser_path, flags)

                    # Wait for the sideloaded companion to consume the payload.
                    # Cold-start with AV scanning can take up to ~15s on the first run;
                    # 30s ensures we don't falsely timeout on slow machines.
                    consumed_event = _CookieHandler._payload_consumed_event
                    consumed = consumed_event.wait(timeout=30.0) if consumed_event else False

                    duration_ms = int((time.time() - start_time) * 1000)

                    if not consumed:
                        log.warning(
                            "Ephemeral companion did not claim payload within 30s. "
                            "XPI may be unsigned or invalid on this Firefox build."
                        )
                        stop_cookie_server(handoff_server)
                        # Do NOT delete the profile — Firefox may still be starting.
                        # The background watcher thread will handle cleanup on process exit.
                        def _cleanup_if_no_consume(proc, prof, dom):
                            try:
                                proc.wait()
                                wait_profile_free(prof, timeout=30)
                            except Exception:
                                pass
                            finally:
                                _signal_return(dom)
                                _rmtree_with_backoff(prof)
                        threading.Thread(
                            target=_cleanup_if_no_consume,
                            args=(process, profile_dir, domain),
                            daemon=True,
                        ).start()
                        return {
                            "status": "error",
                            "event": "unclaimed",
                            "error": "The companion extension did not start within 30s. "
                                     "If using release Firefox, ensure the companion XPI is AMO-signed.",
                        }

                    log.info("Ephemeral Firefox handoff consumed after %d ms", duration_ms)
                    log_session(domain, browser_id, duration_ms, "launched")
                    log_launch_time(browser_id, time.time() - start_time)

                    # Spawn background watcher: wait for Firefox to fully release the
                    # profile directory, then delete it. Handles Firefox self-restarts.
                    # When Firefox exits (for any reason), signal /return so the
                    # Chromium background's waitForReturn() poll unblocks and shows
                    # the return banner.
                    def _ephemeral_watcher(proc, prof, dom):
                        try:
                            proc.wait()                          # initial PID exits
                            wait_profile_free(prof, timeout=60)  # catch self-restart
                        except Exception:
                            pass
                        finally:
                            log.info("Firefox exited — signaling return for domain: %s", dom)
                            _signal_return(dom)
                            log.info("Cleaning up ephemeral gecko profile: %s", prof)
                            _rmtree_with_backoff(prof)

                    threading.Thread(
                        target=_ephemeral_watcher,
                        args=(process, profile_dir, domain),
                        daemon=True,
                    ).start()

                    # Return immediately — Firefox retains focus, popup closes cleanly.
                    # Handoff server stays alive for /wait-return and /return endpoints.
                    return {
                        "status": "ok",
                        "event": "launched",
                        "domain": domain,
                        "duration": duration_ms,
                    }

                # ── Persistent profile: attach to existing Firefox instance ──
                else:
                    # Start handoff server with tokenized endpoint
                    handoff_server, handoff_token = start_handoff_server(
                        cookies, target_url=url, storage_data=storage_data
                    )
                    if not handoff_server:
                        log.error("Failed to start handoff server")
                        return {"error": "Failed to start handoff server on port %d" % COOKIE_PORT}

                    launch_url = f"http://127.0.0.1:{COOKIE_PORT}/handoff?token={handoff_token}"
                    log.info("Handoff URL (persistent): %s", launch_url)

                    flags = build_gecko_flags(
                        config=config,
                        url=launch_url,
                        mode=mode,
                        profile_dir=None,    # no isolation — attach to default profile
                        incognito=incognito,
                        companion_mode=True,
                    )
                    log.info("Launching Firefox (persistent companion mode) with flags: %s", flags)

                    start_time = time.time()
                    process = launch(browser_path, flags)

                    # In persistent mode, expect the companion to respond within 6s
                    # (it should already be installed in the user's main profile).
                    consumed_event = _CookieHandler._payload_consumed_event
                    consumed = consumed_event.wait(timeout=6.0) if consumed_event else False

                    duration_ms = int((time.time() - start_time) * 1000)

                    if not consumed:
                        log.warning("Companion extension did not claim payload within 6s (likely not installed)")
                        stop_cookie_server(handoff_server)
                        return {
                            "status": "error",
                            "event": "unclaimed",
                            "error": "Gecko companion extension not detected in this Firefox profile. Install the companion extension to enable automatic tab handoffs.",
                        }

                    log.info("Firefox handoff successfully consumed after %d ms", duration_ms)
                    log_session(domain, browser_id, duration_ms, "launched")
                    log_launch_time(browser_id, time.time() - start_time)

                    return {
                        "status": "ok",
                        "event": "launched",
                        "domain": domain,
                        "duration": duration_ms,
                    }

            # ── Legacy mode: direct SQLite injection (original flow) ──
            else:
                if profile_mode == "persistent":
                    per_browser = session_cfg.get("persistent_profiles", {})
                    persistent_path = per_browser.get(browser_id, "")
                    if not persistent_path:
                        persistent_path = session_cfg.get("persistent_profile_path", "")
                    profile_dir = resolve_persistent(persistent_path)
                else:
                    profile_dir = create_ephemeral()

                log.info("Gecko profile dir (legacy): %s", profile_dir)

                # Direct SQLite cookie & pref injection
                stage_gecko_profile(profile_dir, cookies=cookies, target_url=url)
                log.info("stage_gecko_profile complete: %d cookies injected", len(cookies))

                # Optional local storage server
                cookie_server = None
                if cookies or storage_data:
                    cookie_server = start_cookie_server(
                        cookies, target_url=url, storage_data=storage_data
                    )
                    log.info("Cookie server started" if cookie_server else "Cookie server FAILED to start")

                flags = build_gecko_flags(
                    config=config,
                    url=url,
                    mode=mode,
                    profile_dir=profile_dir,
                    incognito=incognito,
                    companion_mode=False,
                )
                log.info("Launching Firefox (legacy mode) with flags: %s", flags)

                start_time = time.time()
                process = launch(browser_path, flags)

                # Wait for Gecko browser to exit
                process.wait()
                duration_ms = int((time.time() - start_time) * 1000)
                log.info("Firefox exited after %d ms", duration_ms)

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


def handle_check_xpi(message):
    """Check companion XPI path and AMO signature status."""
    try:
        config = load_config()
        path = message.get("path")
        return inspect_xpi(path, config)
    except Exception as e:
        return {"found": False, "error": str(e)}


def handle_browse_file(message):
    """
    Open native OS file picker to select the signed XPI.
    Returns the exact absolute filesystem path chosen by the user.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        initial_dir = None
        current = message.get("current_path")
        if current and os.path.exists(os.path.dirname(current)):
            initial_dir = os.path.dirname(current)

        chosen = filedialog.askopenfilename(
            title="Select Gecko Companion Extension (.xpi)",
            filetypes=[("Firefox Extension (*.xpi)", "*.xpi"), ("All Files (*.*)", "*.*")],
            initialdir=initial_dir,
        )
        root.destroy()

        if chosen:
            exact_path = os.path.normpath(os.path.abspath(chosen))
            inspection = inspect_xpi(exact_path)
            return {
                "status": "ok",
                "selected": True,
                "path": exact_path,
                "signed": inspection.get("signed", False),
            }
        return {"status": "ok", "selected": False}
    except Exception as e:
        log.error("Failed to open native file dialog: %s", e)
        return {"status": "error", "error": str(e)}


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
        elif action == "check_xpi":
            response = handle_check_xpi(message)
        elif action == "browse_file":
            response = handle_browse_file(message)
        elif action == "health":
            response = {"status": "ok", "timestamp": time.time()}
        else:
            response = {"error": f"Unknown action: {action}"}

        send_message(response)


if __name__ == "__main__":
    # Sweep any leftover cb-gecko-* profiles from previous crashed sessions
    # before entering the message loop, so stale cookies don't sit on disk.
    sweep_orphaned_profiles()
    main()
