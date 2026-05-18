"""
cookies.py — Cookie relay for ChromeBridge.
Embeds decrypted cookie JSON directly into the companion extension's receiver.js
via string replacement. This is far more reliable than writing a separate file
that the service worker tries to fetch().
"""

import os
import json


# The exact placeholder line in receiver.js that gets replaced
PLACEHOLDER = "const INJECTED_COOKIES = null;"


def stage_cookies(cookies, target_url, companion_dir):
    """
    Embed the cookie array and target URL directly into the companion's receiver.js file.
    Replaces the placeholders with actual data.

    Args:
        cookies: list of cookie dicts
        target_url: the real destination URL
        companion_dir: path to the session-local companion extension copy
    """
    if not cookies:
        return

    receiver_path = os.path.join(companion_dir, "background", "receiver.js")

    if not os.path.isfile(receiver_path):
        raise FileNotFoundError(f"receiver.js not found at: {receiver_path}")

    with open(receiver_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Serialize cookies to compact JSON
    cookie_json = json.dumps(cookies, indent=None, separators=(",", ":"))

    # Replace the placeholder with actual cookie data
    replacement = f"const INJECTED_COOKIES = {cookie_json};"
    content = content.replace("const INJECTED_COOKIES = null;", replacement, 1)

    if target_url:
        escaped_url = target_url.replace("'", "\\'")
        content = content.replace(
            "const INJECTED_URL = null;", 
            f"const INJECTED_URL = '{escaped_url}';", 
            1
        )

    with open(receiver_path, "w", encoding="utf-8") as f:
        f.write(content)
