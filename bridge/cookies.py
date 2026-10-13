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


def stage_storage(storage_data, companion_dir):
    """
    Embed the storage dictionary directly into the companion's storage-injector.js file.
    Replaces the placeholder with actual data so storage is available at document_start.

    Args:
        storage_data: dict with 'origin', 'localStorage', 'sessionStorage'
        companion_dir: path to the session-local companion extension copy
    """
    if not storage_data:
        return

    injector_path = os.path.join(companion_dir, "content", "storage-injector.js")
    if not os.path.isfile(injector_path):
        return

    with open(injector_path, "r", encoding="utf-8") as f:
        content = f.read()

    storage_json = json.dumps(storage_data, indent=None, separators=(",", ":"))
    replacement = f"const INJECTED_STORAGE = {storage_json};"
    content = content.replace("const INJECTED_STORAGE = null;", replacement, 1)

    with open(injector_path, "w", encoding="utf-8") as f:
        f.write(content)

