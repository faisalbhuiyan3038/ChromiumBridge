"""
detect.py — OS-agnostic Chromium browser detection and path resolution.
Resolution priority: user override → known paths → Windows registry → shutil.which()

IMPORTANT: Version detection is NOT done during detect_all() because running
`browser.exe --version` on Windows opens visible browser windows. Version is
read from the exe's file metadata on Windows, or via --version on Linux/macOS
only when explicitly requested.
"""

import os
import platform
import shutil
import subprocess
import re

# Known browser definitions: id → { name, executables, registry_names }
BROWSER_DEFS = {
    "edge": {
        "name": "Microsoft Edge",
        "executables": {
            "Windows": ["msedge.exe"],
            "Linux": ["microsoft-edge", "microsoft-edge-stable"],
            "Darwin": ["Microsoft Edge"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
    },
    "brave": {
        "name": "Brave",
        "executables": {
            "Windows": ["brave.exe"],
            "Linux": ["brave-browser", "brave"],
            "Darwin": ["Brave Browser"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe",
    },
    "chromium": {
        "name": "Chromium",
        "executables": {
            "Windows": ["chromium.exe", "chrome.exe"],
            "Linux": ["chromium", "chromium-browser"],
            "Darwin": ["Chromium"],
        },
        "registry_key": None,
    },
    "vivaldi": {
        "name": "Vivaldi",
        "executables": {
            "Windows": ["vivaldi.exe"],
            "Linux": ["vivaldi", "vivaldi-stable"],
            "Darwin": ["Vivaldi"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\vivaldi.exe",
    },
    "opera": {
        "name": "Opera",
        "executables": {
            "Windows": ["opera.exe"],
            "Linux": ["opera"],
            "Darwin": ["Opera"],
        },
        "registry_key": None,
    },
}


def _get_known_paths(browser_id, system):
    """Return candidate install paths for a browser on the current OS."""
    bdef = BROWSER_DEFS.get(browser_id, {})
    exes = bdef.get("executables", {}).get(system, [])
    paths = []

    if system == "Windows":
        base_dirs = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), ""),
        ]
        subpaths = {
            "edge": [r"Microsoft\Edge\Application"],
            "brave": [r"BraveSoftware\Brave-Browser\Application"],
            "chromium": [r"Chromium\Application"],
            "vivaldi": [r"Vivaldi\Application"],
            "opera": [r"Opera"],
        }
        for base in base_dirs:
            if not base:
                continue
            for sub in subpaths.get(browser_id, []):
                for exe in exes:
                    paths.append(os.path.join(base, sub, exe))

    elif system == "Linux":
        linux_dirs = ["/usr/bin", "/usr/local/bin", "/snap/bin"]
        for d in linux_dirs:
            for exe in exes:
                paths.append(os.path.join(d, exe))

    elif system == "Darwin":
        for app_name in exes:
            paths.append(f"/Applications/{app_name}.app/Contents/MacOS/{app_name}")

    return paths


def _check_registry(browser_id):
    """Try to find browser path via Windows Registry."""
    bdef = BROWSER_DEFS.get(browser_id, {})
    reg_key = bdef.get("registry_key")
    if not reg_key:
        return None

    try:
        import winreg

        for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            try:
                with winreg.OpenKey(hive, reg_key) as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    if value and os.path.isfile(value):
                        return value
            except (FileNotFoundError, OSError):
                continue
    except ImportError:
        pass

    return None


def _get_version_windows(path):
    """
    Get browser version on Windows by reading the exe's file version metadata.
    Does NOT launch the browser.
    """
    try:
        import ctypes
        from ctypes import wintypes

        # Get size of version info
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None

        # Read version info block
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf):
            return None

        # Query the fixed file info
        p_val = ctypes.c_void_p()
        val_len = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(
            buf, "\\", ctypes.byref(p_val), ctypes.byref(val_len)
        ):
            return None

        # VS_FIXEDFILEINFO structure — extract version fields
        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", wintypes.DWORD),
                ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD),
                ("dwProductVersionLS", wintypes.DWORD),
                # rest not needed
            ]

        info = ctypes.cast(
            p_val, ctypes.POINTER(VS_FIXEDFILEINFO)
        ).contents

        major = (info.dwProductVersionMS >> 16) & 0xFFFF
        minor = info.dwProductVersionMS & 0xFFFF
        build = (info.dwProductVersionLS >> 16) & 0xFFFF
        patch = info.dwProductVersionLS & 0xFFFF

        return f"{major}.{minor}.{build}.{patch}"
    except Exception:
        return None


def _get_version_unix(path):
    """
    Get browser version on Linux/macOS by running --version.
    Safe because Chromium browsers on these platforms just print and exit.
    """
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.strip()
        match = re.search(r"(\d+\.\d+\.\d+(?:\.\d+)?)", output)
        return match.group(1) if match else None
    except Exception:
        return None


def get_version(path):
    """Get browser version without opening a visible browser window."""
    system = platform.system()
    if system == "Windows":
        return _get_version_windows(path)
    else:
        return _get_version_unix(path)


def _find_single_browser(browser_id, config=None):
    """
    Find a single browser by ID. Returns { id, name, path } or None.
    Does NOT run version detection. Does NOT scan other browsers.
    """
    config = config or {}
    system = platform.system()

    if browser_id == "chrome":
        return None

    bdef = BROWSER_DEFS.get(browser_id)
    
    overrides = config.get("browser_overrides", {})
    path = None

    # 1. User override (supports completely custom IDs)
    override = overrides.get(browser_id)
    if override and os.path.isfile(override):
        path = override

    # If it's a completely custom ID (no bdef) and no valid override path, fail
    if not bdef and not path:
        return None

    # 2. Known paths
    if not path and bdef:
        for candidate in _get_known_paths(browser_id, system):
            if os.path.isfile(candidate):
                path = candidate
                break

    # 3. Windows registry
    if not path and bdef and system == "Windows":
        path = _check_registry(browser_id)

    # 4. shutil.which fallback
    if not path and bdef:
        for exe in bdef.get("executables", {}).get(system, []):
            which_path = shutil.which(exe)
            if which_path:
                path = which_path
                break

    if path:
        name = bdef["name"] if bdef else browser_id.capitalize()
        return {"id": browser_id, "name": name, "path": path}

    return None


def detect_all(config=None):
    """
    Detect all installed Chromium-based browsers, plus any custom overrides.
    Returns: [{ id, name, path, version }]
    """
    config = config or {}
    found = []
    
    # Get all known IDs plus any custom IDs from overrides
    overrides = config.get("browser_overrides", {})
    all_ids = set(BROWSER_DEFS.keys()).union(overrides.keys())

    for browser_id in sorted(all_ids):
        result = _find_single_browser(browser_id, config)
        if result:
            result["version"] = get_version(result["path"])
            found.append(result)

    return found


def resolve_browser(browser_id, config=None):
    """
    Resolve a single browser by ID. Returns absolute path or None.
    Only checks the requested browser — does NOT scan all browsers.
    """
    if browser_id == "chrome":
        return None
    result = _find_single_browser(browser_id, config)
    return result["path"] if result else None


# ── User Data Directory Locations ─────────────────────
# Known default user-data-dir paths per browser per OS.
_USER_DATA_DIRS = {
    "edge": {
        "Windows": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data"),
        ],
        "Linux": [os.path.expanduser("~/.config/microsoft-edge")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/Microsoft Edge")],
    },
    "brave": {
        "Windows": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "BraveSoftware", "Brave-Browser", "User Data"),
        ],
        "Linux": [os.path.expanduser("~/.config/BraveSoftware/Brave-Browser")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/BraveSoftware/Brave-Browser")],
    },
    "chromium": {
        "Windows": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Chromium", "User Data"),
        ],
        "Linux": [os.path.expanduser("~/.config/chromium")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/Chromium")],
    },
    "vivaldi": {
        "Windows": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Vivaldi", "User Data"),
        ],
        "Linux": [os.path.expanduser("~/.config/vivaldi")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/Vivaldi")],
    },
    "opera": {
        "Windows": [
            os.path.join(os.environ.get("APPDATA", ""), "Opera Software", "Opera Stable"),
        ],
        "Linux": [os.path.expanduser("~/.config/opera")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/com.operasoftware.Opera")],
    },
}


def _find_user_data_dir(browser_id):
    """Find the User Data directory for a browser on the current OS."""
    system = platform.system()
    candidates = _USER_DATA_DIRS.get(browser_id, {}).get(system, [])
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return None


def _read_profile_name(profile_path):
    """Read the user-visible profile name from Preferences JSON."""
    prefs_path = os.path.join(profile_path, "Preferences")
    if not os.path.isfile(prefs_path):
        return None
    try:
        with open(prefs_path, "r", encoding="utf-8") as f:
            import json as _json
            prefs = _json.load(f)
        # Profile name is typically in profile.name
        return prefs.get("profile", {}).get("name", None)
    except Exception:
        return None


def detect_profiles(browser_id, config=None):
    """
    Detect existing profiles for a specific Chromium browser.
    Scans the browser's User Data directory for profile subdirectories.

    Returns: [{ "id": "Default", "name": "Person 1", "path": "C:\\...\\Default" }]
    """
    user_data_dir = _find_user_data_dir(browser_id)
    if not user_data_dir:
        return []

    profiles = []

    # Chromium profiles are named "Default", "Profile 1", "Profile 2", etc.
    # Some browsers also use "Guest Profile", "System Profile" — skip those.
    skip_dirs = {"System Profile", "Guest Profile", "Crashpad", "GrShaderCache",
                 "ShaderCache", "BrowserMetrics", "Safe Browsing", "Crowd Deny",
                 "MEIPreload", "WidevineCdm", "pnacl", "SwReporter"}

    try:
        for entry in os.listdir(user_data_dir):
            entry_path = os.path.join(user_data_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry in skip_dirs:
                continue

            # Check if it looks like a profile directory (has Preferences file)
            prefs_file = os.path.join(entry_path, "Preferences")
            if not os.path.isfile(prefs_file):
                continue

            display_name = _read_profile_name(entry_path) or entry
            profiles.append({
                "id": entry,
                "name": display_name,
                "path": entry_path,
            })
    except OSError:
        pass

    # Sort: "Default" first, then alphabetically
    profiles.sort(key=lambda p: (p["id"] != "Default", p["id"]))
    return profiles

