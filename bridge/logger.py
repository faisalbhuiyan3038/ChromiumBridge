"""
logger.py — Session and launch time logging for ChromeBridge.
Logs are stored as JSON lines in sessions.log.
"""

import os
import json
import time


def _log_path():
    """Get the path to the sessions log file."""
    bridge_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(bridge_dir, "sessions.log")


def log_session(domain, browser, duration_ms, outcome):
    """
    Append a session entry to the log.

    Args:
        domain: the domain that was handed off
        browser: browser ID used
        duration_ms: session duration in milliseconds
        outcome: "closed", "error", etc.
    """
    entry = {
        "type": "session",
        "timestamp": time.time(),
        "domain": domain,
        "browser": browser,
        "duration_ms": duration_ms,
        "outcome": outcome,
    }
    _append_log(entry)


def log_launch_time(browser, seconds):
    """
    Log the launch time for a browser.

    Args:
        browser: browser ID
        seconds: time from launch to close in seconds
    """
    entry = {
        "type": "launch_time",
        "timestamp": time.time(),
        "browser": browser,
        "seconds": round(seconds, 2),
    }
    _append_log(entry)


def get_recent(n=50):
    """
    Get the last N log entries.

    Returns: list of dicts (most recent last)
    """
    path = _log_path()
    if not os.path.isfile(path):
        return []

    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return entries[-n:]


def _append_log(entry):
    """Append a JSON line to the log file."""
    path = _log_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")
