"""
profile.py — Ephemeral and persistent profile management.
"""

import os
import shutil
import tempfile
import uuid


def create_ephemeral():
    """
    Create an ephemeral temp profile directory.
    Returns the absolute path.
    """
    profile_dir = tempfile.mkdtemp(prefix="fx-bridge-")
    return profile_dir


def resolve_persistent(path=None):
    """
    Resolve and ensure a persistent profile directory exists.
    If no path provided, uses a default location.

    Supports two styles:
      1. Existing browser profile path (e.g., "C:\\Users\\...\\Chrome\\User Data\\Default")
         → used as-is, directory already exists
      2. Custom path or default path
         → created if it doesn't exist

    Returns the absolute path.
    """
    if not path:
        # Default persistent path
        home = os.path.expanduser("~")
        path = os.path.join(home, ".fx-bridge", "profiles", "default")

    path = os.path.expanduser(path)
    path = os.path.abspath(path)

    # For existing profiles, just validate the path exists
    if os.path.isdir(path):
        return path

    # For new custom paths, create the directory
    os.makedirs(path, exist_ok=True)
    return path


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

    # Check if it's a profile directory (has Preferences file)
    if os.path.isfile(os.path.join(path, "Preferences")):
        result["is_profile"] = True
        result["valid"] = True

    # Check if it's a User Data directory (has a "Default" subdirectory)
    if os.path.isdir(os.path.join(path, "Default")):
        result["is_user_data"] = True
        result["valid"] = True

    # Check for lock file (SingletonLock on Linux, lockfile on Windows)
    lock_files = ["SingletonLock", "lockfile", "SingletonSocket"]
    for lock in lock_files:
        if os.path.exists(os.path.join(path, lock)):
            result["locked"] = True
            break

    return result


def cleanup(profile_path, mode, session_dir=None):
    """
    Clean up after a session.
    - Ephemeral: removes the entire profile directory.
    - Persistent: no-op for the profile, but session_dir is always cleaned.
    - session_dir: always cleaned (contains the companion copy).
    """
    # Always clean up the session directory (companion copy)
    if session_dir and os.path.isdir(session_dir):
        try:
            shutil.rmtree(session_dir)
        except OSError:
            pass

    # Only clean up ephemeral profiles
    if mode == "ephemeral" and profile_path and os.path.isdir(profile_path):
        try:
            shutil.rmtree(profile_path)
        except OSError:
            pass
