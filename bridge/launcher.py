"""
launcher.py — Flag builder, companion staging, and subprocess manager.
"""

import os
import shutil
import subprocess
import tempfile
import uuid

from profile import cleanup


def _get_bridge_dir():
    """Get the directory where the bridge is installed."""
    return os.path.dirname(os.path.abspath(__file__))


def _get_center_position(win_w, win_h):
    """
    Calculate top-left coordinates to center a window of size (win_w, win_h).
    Uses ctypes on Windows for actual monitor size; falls back to defaults.
    """
    try:
        import platform
        if platform.system() == "Windows":
            import ctypes
            user32 = ctypes.windll.user32
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
        else:
            # Reasonable fallback for Linux/macOS
            screen_w, screen_h = 1920, 1080
    except Exception:
        screen_w, screen_h = 1920, 1080

    cx = max(0, (screen_w - win_w) // 2)
    cy = max(0, (screen_h - win_h) // 2)
    return cx, cy


def _get_companion_source():
    """Get the path to the bundled chromium-extension source."""
    bridge_dir = _get_bridge_dir()
    # Go up one level from bridge/ to ChromeBridge/, then into chromium-extension/
    project_root = os.path.dirname(bridge_dir)
    companion_src = os.path.join(project_root, "chromium-extension")
    if not os.path.isdir(companion_src):
        raise FileNotFoundError(
            f"Chromium companion extension not found at: {companion_src}"
        )
    return companion_src


def prepare_companion(profile_dir):
    """
    Copy the companion extension into a session-specific directory
    on the LOCAL filesystem (system temp dir).

    Chrome refuses to --load-extension from mapped/virtual drives,
    so we must stage to a real local path.

    Returns the path to the session-local companion copy.
    """
    # Use the OS temp directory — always on a real local drive
    session_id = str(uuid.uuid4())[:12]
    session_dir = os.path.join(tempfile.gettempdir(), "cb-sessions", session_id)
    companion_dest = os.path.join(session_dir, "companion_ext")

    companion_src = _get_companion_source()
    shutil.copytree(companion_src, companion_dest)

    return companion_dest


def build_flags(config, url, mode, profile_dir, companion_dir, incognito=False):
    """
    Build the full list of CLI flags for launching Chromium.

    Args:
        config: bridge config dict
        url: target URL
        mode: "app", "popup", or "normal"
        profile_dir: user data directory (ephemeral or persistent)
        companion_dir: path to session-local companion extension copy
        incognito: whether to pass --incognito

    Returns: list of flag strings
    """
    flags = []

    # User data directory
    flags.append(f"--user-data-dir={profile_dir}")

    # Window mode
    if mode == "app":
        # PWA-style: no URL bar, no extensions menu, minimal chrome
        flags.append(f"--app={url}")
    elif mode == "popup":
        # Compact focused window — has URL bar + extensions, but smaller
        cx, cy = _get_center_position(960, 640)
        flags.extend([
            "--new-window",
            f"--window-size=960,640",
            f"--window-position={cx},{cy}",
        ])
    elif mode == "normal":
        # Full browser window, maximized
        flags.append("--start-maximized")

    # Load companion extension (--enable-extensions is required on fresh profiles)
    flags.extend([
        "--enable-extensions",
        f"--load-extension={companion_dir}",
    ])

    # Suppress first-run UI
    flags.extend([
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-default-apps",
    ])

    # Force Chrome to fully exit when all windows close.
    # Without this, Chrome keeps background processes alive and reuses them
    # on the next launch — which means onStartup/onInstalled never fire and
    # the service worker keeps stale state.
    flags.extend([
        "--disable-background-mode",
        "--disable-backgrounding-occluded-windows",
    ])

    # Incognito
    if incognito:
        flags.append("--incognito")

    # Extra flags from config
    extra = config.get("extra_flags", [])
    if isinstance(extra, list):
        flags.extend(extra)
    elif isinstance(extra, str):
        flags.extend(extra.split())

    # For popup and normal mode, URL goes at the end as a positional argument
    if mode in ("popup", "normal"):
        flags.append(url)

    return flags


def launch(browser_path, flags):
    """
    Launch Chromium with the given flags.
    Returns the subprocess.Popen handle.
    """
    cmd = [browser_path] + flags
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process


def wait_and_cleanup(profile_dir, profile_mode, companion_dir):
    """
    Clean up after Chromium exits.
    - Session dir (companion copy) is always removed.
    - Profile dir is removed only if ephemeral.
    """
    # The companion_dir is inside sessions/{id}/companion_ext/
    # We want to remove sessions/{id}/ entirely
    session_dir = os.path.dirname(companion_dir) if companion_dir else None
    cleanup(profile_dir, profile_mode, session_dir)
