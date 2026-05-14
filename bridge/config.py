"""
config.py — Configuration management for ChromeBridge.
Reads/writes config.json with sensible defaults.
"""

import os
import json

CONFIG_FILENAME = "config.json"

DEFAULT_CONFIG = {
    "version": 2,
    "default_browser": "chrome",
    "browser_overrides": {},
    "window_modes": {
        "default": "popup",
        "app_domains": ["netflix.com", "youtube.com", "figma.com"],
    },
    "session": {
        "profile_mode": "ephemeral",
        "persistent_profile_path": "",
        "port_cookies": True,
        "port_localstorage": True,
        "cleanup_on_close": True,
        "incognito_passthrough": True,
        "discard_firefox_tab": False,
        "record_history": True,
    },
    "extension_presets": {
        "streaming": [],
        "work": [],
        "minimal": [],
    },
    "extra_flags": [
        "--disable-infobars",
        "--disable-sync",
    ],
    "domain_rules": {},
    "signals": {
        "drm_detection": False,
        "hls_detection": False,
        "buffering_threshold": 3,
        "perf_longtask_threshold": 5,
    },
    "ui": {
        "show_banner": True,
        "show_badge": True,
        "badge_color": "#00A76F",
        "feedback_prompt": True,
    },
}


def _config_path():
    """Get the absolute path to config.json in the bridge directory."""
    bridge_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(bridge_dir, CONFIG_FILENAME)


def load_config():
    """Load config.json. Creates with defaults if it doesn't exist."""
    path = _config_path()
    if not os.path.isfile(path):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Merge with defaults for any missing keys
    merged = _deep_merge(DEFAULT_CONFIG.copy(), config)
    return merged


def save_config(config):
    """Save config to config.json with pretty printing."""
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_config_value(key, default=None):
    """
    Get a config value by dot-notation key.
    Example: get_config_value("session.port_cookies")
    """
    config = load_config()
    keys = key.split(".")
    current = config
    for k in keys:
        if isinstance(current, dict) and k in current:
            current = current[k]
        else:
            return default
    return current


def set_config_value(key, value):
    """
    Set a config value by dot-notation key.
    Example: set_config_value("session.port_cookies", False)
    """
    config = load_config()
    keys = key.split(".")
    current = config
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]
    current[keys[-1]] = value
    save_config(config)


def _deep_merge(base, override):
    """Deep merge override into base, returning the result."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
