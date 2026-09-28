"""
profile.py — Ephemeral and persistent profile management for Chromium → Gecko handoffs.

Handles:
  - Ephemeral temp profile creation with session.pid tracking
  - Orphan sweep of leftover cb-gecko-* dirs on bridge startup
  - Persistent profile resolution
  - Profile cleanup with exponential backoff for Windows file locks
  - psutil-based wait for Firefox to fully release the profile path
"""

import os
import glob
import json
import shutil
import tempfile
import time
import uuid
import logging

log = logging.getLogger(__name__)

ADDON_ID = "chromiumbridge-companion@faisalbhuiyan.com"

# ── Ephemeral Profile ───────────────────────────────────

def create_ephemeral():
    """
    Create an ephemeral temp profile directory.
    Writes a session.pid file so orphan sweeps can detect dead sessions.
    Returns the absolute path.
    """
    profile_dir = tempfile.mkdtemp(prefix="cb-gecko-")
    _write_session_pid(profile_dir)
    return profile_dir


def _write_session_pid(profile_dir):
    """Write the current bridge PID into session.pid inside the profile dir."""
    pid_path = os.path.join(profile_dir, "session.pid")
    try:
        with open(pid_path, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError as e:
        log.warning("Could not write session.pid to %s: %s", profile_dir, e)


# ── Orphan Sweep ────────────────────────────────────────

def _pid_alive(pid):
    """Check if a PID is alive using os.kill(pid, 0). Works cross-platform, no psutil needed."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def sweep_orphaned_profiles():
    """
    Scan %TEMP% (or /tmp on Unix) for leftover cb-gecko-* profile directories
    whose bridge PID is no longer alive. Deletes them with best-effort cleanup.
    Called once on bridge startup.
    """
    tmp = tempfile.gettempdir()
    pattern = os.path.join(tmp, "cb-gecko-*")
    removed = 0
    for d in glob.glob(pattern):
        if not os.path.isdir(d):
            continue
        pid_file = os.path.join(d, "session.pid")
        should_delete = False
        if not os.path.isfile(pid_file):
            # No PID file — orphan from an older build or interrupted run
            should_delete = True
        else:
            try:
                with open(pid_file, "r", encoding="utf-8") as f:
                    pid = int(f.read().strip())
                should_delete = not _pid_alive(pid)
            except Exception:
                should_delete = True

        if should_delete:
            log.info("Sweeping orphaned gecko profile: %s", d)
            _rmtree_with_backoff(d)
            removed += 1

    if removed:
        log.info("Orphan sweep removed %d leftover profile(s).", removed)


# ── XPI Validation ──────────────────────────────────────

def is_xpi_signed(xpi_path):
    """
    Check that the XPI file contains META-INF/mozilla.rsa, confirming it was
    signed by AMO. Returns True if signed, False otherwise.
    """
    if not xpi_path or not os.path.isfile(xpi_path):
        return False
    try:
        import zipfile
        with zipfile.ZipFile(xpi_path, "r") as z:
            return "META-INF/mozilla.rsa" in z.namelist()
    except Exception as e:
        log.warning("Could not inspect XPI at %s: %s", xpi_path, e)
        return False


def locate_companion_xpi(config=None):
    """
    Locate the companion XPI file.
    Priority:
      1. User-configured exact path from config (gecko_companion_xpi or session.gecko_companion_xpi).
         Uses the EXACT path specified. If it doesn't exist, returns None.
      2. Default repo location: releases/gecko-extension/<id>.xpi
    Returns the absolute path, or None if not found.
    """
    if config:
        configured = config.get("gecko_companion_xpi") or config.get("session", {}).get("gecko_companion_xpi")
        if configured and isinstance(configured, str) and configured.strip():
            target = os.path.normpath(os.path.abspath(os.path.expanduser(configured.strip())))
            if os.path.isfile(target):
                return target
            log.warning("Configured gecko_companion_xpi does not exist: %s", target)
            return None

    # Fallback default location relative to bridge
    bridge_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(bridge_dir)
    std_path = os.path.normpath(os.path.join(
        repo_root, "releases", "gecko-extension",
        f"{ADDON_ID}.xpi"
    ))
    if os.path.isfile(std_path):
        return std_path

    return None


def inspect_xpi(xpi_path=None, config=None):
    """
    Inspect an XPI file for presence and signature status.
    Uses the exact path provided. No path guessing.
    Returns dict: { 'found': bool, 'path': str, 'signed': bool, 'status': str, 'error': str }
    """
    path = xpi_path
    if not path:
        path = locate_companion_xpi(config)

    if not path:
        configured = ""
        if config:
            configured = config.get("gecko_companion_xpi") or config.get("session", {}).get("gecko_companion_xpi") or ""
        return {
            "found": False,
            "path": configured,
            "signed": False,
            "status": "not_found",
            "error": "No companion XPI file found. Please select a signed .xpi file.",
        }

    exact_path = os.path.normpath(os.path.abspath(os.path.expanduser(str(path).strip())))
    if not os.path.isfile(exact_path):
        return {
            "found": False,
            "path": exact_path,
            "signed": False,
            "status": "not_found",
            "error": f"File does not exist: {exact_path}",
        }

    signed = is_xpi_signed(exact_path)
    return {
        "found": True,
        "path": exact_path,
        "signed": signed,
        "status": "signed" if signed else "unsigned",
        "error": None if signed else "XPI is not signed by AMO (META-INF/mozilla.rsa missing)",
    }


# ── Companion Staging ───────────────────────────────────

def stage_gecko_ephemeral_profile(profile_dir, companion_xpi):
    """
    Prepare an ephemeral Firefox profile for a cold-start companion handoff:
      1. Sideload the signed companion XPI into <profile>/extensions/<id>.xpi
      2. Write user.js with extensions.autoDisableScopes=0 and pinned UUID

    No cookies.sqlite injection — the companion handles cookie restoration
    entirely via browser.cookies.set() before navigating to the target.

    Args:
        profile_dir:    Path to the temp profile directory.
        companion_xpi:  Path to the signed companion .xpi file.

    Raises:
        ValueError: If the XPI is not signed.
    """
    os.makedirs(profile_dir, exist_ok=True)

    # 1. Sideload companion XPI
    ext_dir = os.path.join(profile_dir, "extensions")
    os.makedirs(ext_dir, exist_ok=True)
    dest_xpi = os.path.join(ext_dir, f"{ADDON_ID}.xpi")
    shutil.copy2(companion_xpi, dest_xpi)
    log.info("Sideloaded companion XPI -> %s", dest_xpi)

    # 2. Generate per-session moz-extension:// UUID and double-encode for prefs
    session_uuid = str(uuid.uuid4())
    uuids_map = {ADDON_ID: session_uuid}
    # Firefox requires the value to be a JSON string inside a pref string
    uuids_pref_value = json.dumps(json.dumps(uuids_map))

    user_js = f"""// ChromiumBridge — Ephemeral session prefs (auto-generated, do not edit)
user_pref("extensions.autoDisableScopes", 0);
user_pref("extensions.webextensions.uuids", {uuids_pref_value});
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("datareporting.policy.dataSubmissionPolicyAcceptedVersion", 2);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.warnOnQuit", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.tabs.warnOnClose", false);
"""
    user_js_path = os.path.join(profile_dir, "user.js")
    with open(user_js_path, "w", encoding="utf-8") as f:
        f.write(user_js)
    log.info("Wrote user.js to %s (UUID: %s)", user_js_path, session_uuid)


# ── Persistent Profile ──────────────────────────────────

def resolve_persistent(path=None):
    """
    Resolve and ensure a persistent profile directory exists.
    If no path provided, uses a default location.
    Returns the absolute path.
    """
    if not path:
        home = os.path.expanduser("~")
        path = os.path.join(home, ".fx-bridge", "profiles", "default")

    path = os.path.expanduser(path)
    path = os.path.abspath(path)

    if os.path.isdir(path):
        return path

    os.makedirs(path, exist_ok=True)
    return path


# ── Profile Validation ──────────────────────────────────

def validate_profile(path):
    """
    Check if a path looks like a valid Chromium user data / profile directory.
    Returns a dict with validation info.
    """
    result = {
        "valid": False,
        "exists": False,
        "is_profile": False,
        "is_user_data": False,
        "locked": False,
        "path": path,
    }

    if not path:
        return result

    path = os.path.expanduser(path)
    path = os.path.abspath(path)
    result["path"] = path

    if not os.path.isdir(path):
        return result

    result["exists"] = True

    if os.path.isfile(os.path.join(path, "Preferences")):
        result["is_profile"] = True
        result["valid"] = True

    if os.path.isdir(os.path.join(path, "Default")):
        result["is_user_data"] = True
        result["valid"] = True

    lock_files = ["SingletonLock", "lockfile", "SingletonSocket"]
    for lock in lock_files:
        if os.path.exists(os.path.join(path, lock)):
            result["locked"] = True
            break

    return result


# ── Process Release Check ───────────────────────────────

def _profile_in_use(profile_dir):
    """
    Check if any running process references profile_dir in its command line.
    Uses WMIC on Windows, /proc on Linux. No psutil dependency.
    Returns True if the profile is still in use.
    """
    import subprocess as _sp
    import platform

    norm = os.path.normpath(profile_dir)

    try:
        if platform.system() == "Windows":
            # WMIC lists all process command lines — look for our profile path
            result = _sp.run(
                ["wmic", "process", "get", "CommandLine"],
                capture_output=True, text=True, timeout=10,
                creationflags=_sp.CREATE_NO_WINDOW,
            )
            # Case-insensitive match for Windows paths
            for line in result.stdout.splitlines():
                if norm.lower() in line.lower():
                    return True
        else:
            # On Linux/macOS, scan /proc/*/cmdline
            for pid_dir in glob.glob("/proc/[0-9]*/cmdline"):
                try:
                    with open(pid_dir, "rb") as f:
                        cmdline = f.read().decode("utf-8", errors="replace")
                    if norm in cmdline:
                        return True
                except (OSError, PermissionError):
                    continue
    except Exception as e:
        log.debug("_profile_in_use check failed: %s", e)

    return False


def wait_profile_free(profile_dir, timeout=60):
    """
    Wait until no running process references profile_dir in its command line.
    This catches Firefox self-restarts (e.g. after update) that cause proc.wait()
    to return while the profile is still in use.

    Returns True if the profile is free before timeout, False otherwise.
    """
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not _profile_in_use(profile_dir):
            return True
        time.sleep(1.0)

    log.warning("Profile still in use after %ds: %s", timeout, profile_dir)
    return False


# ── Cleanup ─────────────────────────────────────────────

def cleanup(profile_path, mode, session_dir=None):
    """
    Clean up after a session.
    - Ephemeral: removes the entire profile directory with exponential backoff.
    - Persistent: no-op for the profile, but session_dir is always cleaned.
    - session_dir: always cleaned (contains the companion copy for Chromium targets).
    """
    # Always clean up the session directory (companion copy for Chromium targets)
    if session_dir and os.path.isdir(session_dir):
        _rmtree_with_backoff(session_dir)

    # Only clean up ephemeral profiles
    if mode == "ephemeral" and profile_path and os.path.isdir(profile_path):
        _rmtree_with_backoff(profile_path)


def _rmtree_with_backoff(path, max_wait=10.0):
    """
    Remove a directory tree with exponential backoff retry.
    Handles Windows SQLite .wal file locks and AV scanner holds.
    """
    delay = 0.3
    elapsed = 0.0
    while elapsed < max_wait:
        try:
            shutil.rmtree(path)
            log.debug("Removed directory: %s", path)
            return True
        except OSError as e:
            log.debug("rmtree failed (%s), retrying in %.1fs: %s", e, delay, path)
            time.sleep(delay)
            elapsed += delay
            delay = min(delay * 2, 3.0)

    # Final attempt — ignore errors
    shutil.rmtree(path, ignore_errors=True)
    if os.path.isdir(path):
        log.warning("Could not fully remove directory after %.1fs: %s", elapsed, path)
        return False
    return True
