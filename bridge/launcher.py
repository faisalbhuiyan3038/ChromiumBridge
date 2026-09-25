"""
launcher.py — Flag builder, companion staging, and subprocess manager
for both Chromium and Gecko browser families.
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
            screen_w, screen_h = 1920, 1080
    except Exception:
        screen_w, screen_h = 1920, 1080

    cx = max(0, (screen_w - win_w) // 2)
    cy = max(0, (screen_h - win_h) // 2)
    return cx, cy


def _get_companion_source():
    """Get the path to the bundled chromium-extension source."""
    bridge_dir = _get_bridge_dir()
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
    """
    session_id = str(uuid.uuid4())[:12]
    session_dir = os.path.join(tempfile.gettempdir(), "cb-sessions", session_id)
    companion_dest = os.path.join(session_dir, "companion_ext")

    companion_src = _get_companion_source()
    shutil.copytree(companion_src, companion_dest)

    return companion_dest


# ── Chromium Flag Builder ──────────────────────────────
def build_flags(config, url, mode, profile_dir, companion_dir, incognito=False):
    """
    Build the full list of CLI flags for launching Chromium.
    """
    flags = []

    # User data directory
    prefs_file = os.path.join(profile_dir, "Preferences")
    if os.path.isfile(prefs_file):
        user_data_dir = os.path.dirname(profile_dir)
        profile_name = os.path.basename(profile_dir)
        flags.append(f"--user-data-dir={user_data_dir}")
        flags.append(f"--profile-directory={profile_name}")
    else:
        flags.append(f"--user-data-dir={profile_dir}")

    # Window mode
    if mode == "app":
        flags.append(f"--app={url}")
    elif mode == "popup":
        cx, cy = _get_center_position(960, 640)
        flags.extend([
            "--new-window",
            "--window-size=960,640",
            f"--window-position={cx},{cy}",
        ])
    elif mode == "normal":
        flags.append("--start-maximized")

    # Load companion extension
    flags.extend([
        "--enable-extensions",
        f"--load-extension={companion_dir}",
    ])

    # Suppress first-run UI
    flags.extend([
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-default-apps",
        "--disable-custom-jumplist",
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

    # Positional URL
    if mode in ("popup", "normal"):
        flags.append(url)

    return flags


# ── Gecko / Firefox Flag Builder ───────────────────────
def build_gecko_flags(config, url, mode, profile_dir, incognito=False):
    """
    Build CLI arguments for launching Firefox / Gecko browsers.
    Uses -profile, -no-remote, and -new-instance for total isolation.
    """
    flags = [
        "-profile", profile_dir,
        "-no-remote",
        "-new-instance",
    ]

    if mode == "popup":
        flags.extend(["-width", "960", "-height", "640"])

    if incognito:
        flags.append("-private-window")

    # Extra Gecko flags from config if present
    extra = config.get("extra_gecko_flags", config.get("extra_flags", []))
    if isinstance(extra, list):
        flags.extend(extra)
    elif isinstance(extra, str):
        flags.extend(extra.split())

    flags.append(url)
    return flags


def launch(browser_path, flags):
    """
    Launch a browser subprocess.
    Returns subprocess.Popen handle.
    """
    cmd = [browser_path] + flags
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process


def wait_and_cleanup(profile_dir, profile_mode, companion_dir=None):
    """
    Clean up after browser exits.
    - Session dir (companion copy) is always removed if provided.
    - Profile dir is removed only if ephemeral.
    """
    session_dir = os.path.dirname(companion_dir) if companion_dir else None
    cleanup(profile_dir, profile_mode, session_dir)
