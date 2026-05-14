"""
cookies.py — Cookie relay for ChromeBridge.
Writes decrypted cookie JSON into the companion extension's session-local copy.
No SQLite manipulation — pure JSON.
"""

import os
import json


def stage_cookies(cookies, companion_dir):
    """
    Write the cookie array as JSON into the companion extension directory.
    The Chromium companion reads this via chrome.runtime.getURL('cookies.json').

    Args:
        cookies: list of cookie dicts from Firefox's browser.cookies.getAll()
        companion_dir: path to the session-local companion extension copy
    """
    if not cookies:
        return

    cookie_path = os.path.join(companion_dir, "cookies.json")
    with open(cookie_path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=None, separators=(",", ":"))
