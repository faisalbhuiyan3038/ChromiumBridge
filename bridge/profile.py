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
    """
    Check if a PID is alive. No psutil dependency.

    Windows: os.kill(pid, 0) is a no-op success even for dead PIDs, and the
    Firefox launcher stub exits ~1s after spawning the real browser — so it
    must NOT be used here. Uses OpenProcess + GetExitCodeProcess instead.
    POSIX: os.kill(pid, 0) works correctly.
    """
    if not pid or pid <= 0:
        return False
    try:
        import platform
        if platform.system() == "Windows":
            import ctypes
            STILL_ACTIVE = 259
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            try:
                code = ctypes.c_ulong(0)
                if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return False
                return code.value == STILL_ACTIVE
            finally:
                k32.CloseHandle(h)
        else:
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
            # Guard: never delete a profile that a live Firefox command line
            # still references (self-restart / slow shutdown race).
            try:
                if _profile_in_use(d):
                    log.info("Skipping sweep, profile still in use: %s", d)
                    continue
            except Exception:
                pass
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


def locate_companion_xpi(config=None, message=None):
    """
    Locate the companion XPI file.
    Priority:
      1. Explicit path in launch message from extension (companion_xpi or gecko_companion_xpi).
      2. User-configured exact path from config (gecko_companion_xpi or session.gecko_companion_xpi).
         Uses the EXACT path specified. If it doesn't exist, returns None.
      3. Default signed repo location: releases/gecko-extension/signed/firefox-companion-1.0.0.xpi
      4. Default repo location: releases/gecko-extension/<id>.xpi
    Returns the absolute path, or None if not found.
    """
    if message:
        configured = message.get("companion_xpi") or message.get("gecko_companion_xpi")
        if configured and isinstance(configured, str) and configured.strip():
            target = os.path.normpath(os.path.abspath(os.path.expanduser(configured.strip())))
            if os.path.isfile(target):
                return target
            log.warning("Message companion_xpi does not exist: %s", target)

    if config:
        configured = config.get("gecko_companion_xpi") or config.get("session", {}).get("gecko_companion_xpi")
        if configured and isinstance(configured, str) and configured.strip():
            target = os.path.normpath(os.path.abspath(os.path.expanduser(configured.strip())))
            if os.path.isfile(target):
                return target
            log.warning("Configured gecko_companion_xpi does not exist: %s", target)
            return None

    # Fallback default locations relative to bridge
    bridge_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(bridge_dir)
    signed_path = os.path.normpath(os.path.join(
        repo_root, "releases", "gecko-extension", "signed",
        "firefox-companion-1.0.0.xpi"
    ))
    if os.path.isfile(signed_path):
        return signed_path

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

def resolve_persistent(path=None, browser_id=None):
    """
    Resolve and ensure a persistent profile directory exists.
    If no path provided, uses an isolated location per browser family/id.
    Returns the absolute path.
    """
    if not path:
        home = os.path.expanduser("~")
        subfolder = browser_id if browser_id else "default"
        path = os.path.join(home, ".fx-bridge", "profiles", subfolder)

    path = os.path.expanduser(path)
    path = os.path.abspath(path)

    if os.path.isdir(path):
        return path

    os.makedirs(path, exist_ok=True)
    return path


def stage_gecko_persistent_profile(profile_dir, companion_xpi):
    """
    Prepare a persistent Firefox profile for companion handoff:
      1. Sideload/update the signed companion XPI into <profile>/extensions/<id>.xpi
      2. Ensure user.js has autoDisableScopes=0 and pinned UUID (updating/appending,
         without wiping existing profile preferences).

    Args:
        profile_dir:    Path to the persistent profile directory.
        companion_xpi:  Path to the signed companion .xpi file.
    """
    os.makedirs(profile_dir, exist_ok=True)

    # 1. Sideload companion XPI
    ext_dir = os.path.join(profile_dir, "extensions")
    os.makedirs(ext_dir, exist_ok=True)
    dest_xpi = os.path.join(ext_dir, f"{ADDON_ID}.xpi")
    shutil.copy2(companion_xpi, dest_xpi)
    log.info("Staged companion XPI -> %s", dest_xpi)

    # 2. Update/append user.js without overwriting user's persistent prefs
    user_js_path = os.path.join(profile_dir, "user.js")
    existing_content = ""
    if os.path.isfile(user_js_path):
        try:
            with open(user_js_path, "r", encoding="utf-8") as f:
                existing_content = f.read()
        except OSError:
            pass

    # Ensure pinned UUID exists or generate one
    session_uuid = str(uuid.uuid4())
    uuids_map = {ADDON_ID: session_uuid}
    uuids_pref_value = json.dumps(json.dumps(uuids_map))

    required_prefs = [
        ('user_pref("extensions.autoDisableScopes"', 'user_pref("extensions.autoDisableScopes", 0);'),
        ('user_pref("extensions.webextensions.uuids"', f'user_pref("extensions.webextensions.uuids", {uuids_pref_value});'),
        ('user_pref("browser.shell.checkDefaultBrowser"', 'user_pref("browser.shell.checkDefaultBrowser", false);'),
        ('user_pref("browser.aboutwelcome.enabled"', 'user_pref("browser.aboutwelcome.enabled", false);'),
        ('user_pref("browser.startup.homepage_override.mstone"', 'user_pref("browser.startup.homepage_override.mstone", "ignore");'),
        ('user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification"', 'user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);'),
        ('user_pref("datareporting.policy.dataSubmissionPolicyAcceptedVersion"', 'user_pref("datareporting.policy.dataSubmissionPolicyAcceptedVersion", 2);'),
        ('user_pref("toolkit.telemetry.reportingpolicy.firstRun"', 'user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);'),
        ('user_pref("browser.warnOnQuit"', 'user_pref("browser.warnOnQuit", false);'),
        ('user_pref("browser.sessionstore.resume_from_crash"', 'user_pref("browser.sessionstore.resume_from_crash", false);'),
        ('user_pref("browser.tabs.warnOnClose"', 'user_pref("browser.tabs.warnOnClose", false);'),
    ]

    lines = existing_content.splitlines() if existing_content else []
    for prefix, full_pref in required_prefs:
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(prefix):
                lines[i] = full_pref
                found = True
                break
        if not found:
            lines.append(full_pref)

    with open(user_js_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log.info("Updated persistent user.js at %s", user_js_path)


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

def _in_use_via_wmic(norm, exclude_pid=None):
    """Fast path: WMIC lists all process command lines. Returns None if WMIC is unavailable."""
    import subprocess as _sp
    try:
        result = _sp.run(
            ["wmic", "process", "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=10,
            creationflags=_sp.CREATE_NO_WINDOW,
        )
    except (OSError, FileNotFoundError):
        return None  # WMIC removed (Win11 23H2+) — caller falls back to CIM
    if result.returncode != 0 or not result.stdout:
        return None
    needle = norm.lower()
    exclude_str = str(exclude_pid) if exclude_pid else None
    for line in result.stdout.splitlines():
        if needle not in line.lower():
            continue
        # Each line is "CommandLine    ProcessId" — skip if PID matches exclude_pid
        if exclude_str:
            parts = line.strip().rsplit(None, 1)
            if len(parts) >= 2 and parts[-1].strip() == exclude_str:
                continue
        return True
    return False


def _in_use_via_cim(norm, exclude_pid=None):
    """
    Fallback path: PowerShell Get-CimInstance Win32_Process. Slower (~1s)
    but present on all supported Windows builds. Returns None if the query
    itself fails so the caller can fail SAFE (assume in use).
    """
    import subprocess as _sp
    try:
        result = _sp.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process | Select-Object ProcessId, CommandLine | "
             "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
            creationflags=_sp.CREATE_NO_WINDOW,
        )
    except (OSError, FileNotFoundError) as e:
        log.warning("_profile_in_use CIM query failed to start: %s", e)
        return None
    if result.returncode != 0:
        log.warning("_profile_in_use CIM query rc=%s err=%s",
                    result.returncode, (result.stderr or "")[:200])
        return None
    needle = norm.lower()
    exclude_str = str(exclude_pid) if exclude_pid else None
    for line in result.stdout.splitlines():
        if needle not in line.lower():
            continue
        # Lines are "PID|CommandLine" — skip the daemon's own process
        if exclude_str:
            sep = line.find("|")
            if sep > 0 and line[:sep].strip() == exclude_str:
                continue
        return True
    return False


def _profile_in_use(profile_dir, exclude_pid=None):
    """
    Check if any running process references profile_dir in its command line.
    Uses WMIC on Windows (fast) with a PowerShell CIM fallback, /proc on
    Linux. No psutil dependency.
    If exclude_pid is provided, that PID's command line is ignored (used by
    session_daemon.py to exclude itself from the check).
    Returns True if the profile is still in use. On total check failure
    returns True (fail SAFE: never report a live profile as free — the
    daemon keeps waiting and the orphan sweep skips).
    """
    import platform

    norm = os.path.normpath(profile_dir)

    try:
        if platform.system() == "Windows":
            hit = _in_use_via_wmic(norm, exclude_pid=exclude_pid)
            if hit is None:
                hit = _in_use_via_cim(norm, exclude_pid=exclude_pid)
            if hit is None:
                return True
            return hit
        else:
            # On Linux/macOS, scan /proc/*/cmdline
            for pid_dir in glob.glob("/proc/[0-9]*/cmdline"):
                try:
                    # Extract PID from path
                    pid_str = pid_dir.split("/")[2]
                    if exclude_pid and pid_str == str(exclude_pid):
                        continue
                    with open(pid_dir, "rb") as f:
                        cmdline = f.read().decode("utf-8", errors="replace")
                    if norm in cmdline:
                        return True
                except (OSError, PermissionError):
                    continue
    except Exception as e:
        log.debug("_profile_in_use check failed: %s", e)
        return True

    return False


def _lock_files_free(profile_dir):
    """
    Probe well-known Firefox lock / WAL files. If any exists and cannot be
    opened for append (exclusive lock held by Firefox or AV scanner), the
    profile is still busy. A merely-present-but-openable file counts as free
    (Firefox sometimes leaves parent.lock behind after a clean exit).
    """
    for name in (
        "parent.lock", "lock",
        "places.sqlite-wal", "places.sqlite-shm",
        "cookies.sqlite-wal", "cookies.sqlite-shm",
        "favicons.sqlite-wal", "favicons.sqlite-shm",
    ):
        p = os.path.join(profile_dir, name)
        if os.path.lexists(p) and os.path.isfile(p):
            try:
                with open(p, "a+b"):
                    pass
            except OSError:
                return False
    return True


def wait_profile_free(profile_dir, timeout=60):
    """
    Wait until no running process references profile_dir in its command line
    AND lock/WAL files are openable.
    This catches Firefox self-restarts (e.g. after update) that cause proc.wait()
    to return while the profile is still in use, plus AV-scanner holds.

    Returns True if the profile is free before timeout, False otherwise.
    """
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not _profile_in_use(profile_dir) and _lock_files_free(profile_dir):
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


def _rmtree_with_backoff(path, max_wait=60.0):
    """
    Remove a directory tree with exponential backoff retry.
    Handles Windows SQLite .wal file locks and AV scanner holds.
    Default window raised to 60s (Firefox shutdown + AV); callers with a
    tight budget can pass a smaller max_wait explicitly.
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
