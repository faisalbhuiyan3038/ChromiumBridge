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
    Returns the absolute path.
    """
    if not path:
        # Default persistent path
        home = os.path.expanduser("~")
        path = os.path.join(home, ".fx-bridge", "profiles", "default")

    path = os.path.expanduser(path)
    path = os.path.abspath(path)

    os.makedirs(path, exist_ok=True)
    return path


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
