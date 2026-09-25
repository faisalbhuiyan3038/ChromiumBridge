"""
detect.py — OS-agnostic browser detection and path resolution.
Supports both Chromium-based targets (Brave, Edge, Vivaldi, Opera, Chromium)
and Gecko-based targets (Firefox, LibreWolf, Floorp, Waterfox, Zen, Mullvad).

Resolution priority: user override → known paths → Windows registry → shutil.which()

IMPORTANT: Version detection is NOT done during detect_all() on Windows via CLI
because running `browser.exe --version` opens visible windows. Version is read
from the exe's file metadata on Windows, or via --version on Linux/macOS.
"""

import os
import platform
import shutil
import subprocess
import re
import configparser

# ── Chromium Browser Definitions ───────────────────────
CHROMIUM_BROWSER_DEFS = {
    "edge": {
        "name": "Microsoft Edge",
        "family": "chromium",
        "executables": {
            "Windows": ["msedge.exe"],
            "Linux": ["microsoft-edge", "microsoft-edge-stable"],
            "Darwin": ["Microsoft Edge"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
    },
    "brave": {
        "name": "Brave",
        "family": "chromium",
        "executables": {
            "Windows": ["brave.exe"],
            "Linux": ["brave-browser", "brave"],
            "Darwin": ["Brave Browser"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe",
    },
    "chromium": {
        "name": "Chromium",
        "family": "chromium",
        "executables": {
            "Windows": ["chromium.exe", "chrome.exe"],
            "Linux": ["chromium", "chromium-browser"],
            "Darwin": ["Chromium"],
        },
        "registry_key": None,
    },
    "vivaldi": {
        "name": "Vivaldi",
        "family": "chromium",
        "executables": {
            "Windows": ["vivaldi.exe"],
            "Linux": ["vivaldi", "vivaldi-stable"],
            "Darwin": ["Vivaldi"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\vivaldi.exe",
    },
    "opera": {
        "name": "Opera",
        "family": "chromium",
        "executables": {
            "Windows": ["opera.exe"],
            "Linux": ["opera"],
            "Darwin": ["Opera"],
        },
        "registry_key": None,
    },
}

# ── Gecko Browser Definitions ──────────────────────────
GECKO_BROWSER_DEFS = {
    "firefox": {
        "name": "Mozilla Firefox",
        "family": "gecko",
        "executables": {
            "Windows": ["firefox.exe"],
            "Linux": ["firefox", "firefox-esr"],
            "Darwin": ["Firefox"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe",
    },
    "librewolf": {
        "name": "LibreWolf",
        "family": "gecko",
        "executables": {
            "Windows": ["librewolf.exe"],
            "Linux": ["librewolf"],
            "Darwin": ["LibreWolf"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\librewolf.exe",
    },
    "floorp": {
        "name": "Floorp",
        "family": "gecko",
        "executables": {
            "Windows": ["floorp.exe"],
            "Linux": ["floorp"],
            "Darwin": ["Floorp"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\floorp.exe",
    },
    "waterfox": {
        "name": "Waterfox",
        "family": "gecko",
        "executables": {
            "Windows": ["waterfox.exe"],
            "Linux": ["waterfox", "waterfox-g"],
            "Darwin": ["Waterfox"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\waterfox.exe",
    },
    "zen": {
        "name": "Zen Browser",
        "family": "gecko",
        "executables": {
            "Windows": ["zen.exe"],
            "Linux": ["zen", "zen-browser"],
            "Darwin": ["Zen Browser"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\zen.exe",
    },
    "mullvad": {
        "name": "Mullvad Browser",
        "family": "gecko",
        "executables": {
            "Windows": ["mullvadbrowser.exe"],
            "Linux": ["mullvad-browser"],
            "Darwin": ["Mullvad Browser"],
        },
        "registry_key": None,
    },
}

# Combined definitions map
BROWSER_DEFS = {**CHROMIUM_BROWSER_DEFS, **GECKO_BROWSER_DEFS}


def get_browser_family(browser_id):
    """Return 'gecko' or 'chromium' for a browser ID."""
    if browser_id in GECKO_BROWSER_DEFS or str(browser_id).startswith("gecko_"):
        return "gecko"
    return "chromium"


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
            os.path.join(os.environ.get("APPDATA", ""), ""),
        ]
        subpaths = {
            # Chromium
            "edge": [r"Microsoft\Edge\Application"],
            "brave": [r"BraveSoftware\Brave-Browser\Application"],
            "chromium": [r"Chromium\Application"],
            "vivaldi": [r"Vivaldi\Application"],
            "opera": [r"Opera"],
            # Gecko
            "firefox": [r"Mozilla Firefox", r"Programs\Mozilla Firefox"],
            "librewolf": [r"LibreWolf", r"Programs\LibreWolf"],
            "floorp": [r"Floorp", r"Programs\Floorp"],
            "waterfox": [r"Waterfox", r"Programs\Waterfox"],
            "zen": [r"Zen Browser", r"Programs\Zen Browser"],
            "mullvad": [r"Mullvad Browser", r"Mullvad\Mullvad Browser"],
        }
        for base in base_dirs:
            if not base:
                continue
            for sub in subpaths.get(browser_id, []):
                for exe in exes:
                    candidate = os.path.join(base, sub, exe)
                    paths.append(candidate)

    elif system == "Linux":
        linux_dirs = ["/usr/bin", "/usr/local/bin", "/snap/bin", os.path.expanduser("~/.local/bin")]
        for d in linux_dirs:
            for exe in exes:
                paths.append(os.path.join(d, exe))

    elif system == "Darwin":
        for app_name in exes:
            paths.append(f"/Applications/{app_name}.app/Contents/MacOS/{app_name}")
            paths.append(f"/Applications/{app_name}.app/Contents/MacOS/{app_name.lower()}")

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

        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None

        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf):
            return None

        p_val = ctypes.c_void_p()
        val_len = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(
            buf, "\\", ctypes.byref(p_val), ctypes.byref(val_len)
        ):
            return None

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", wintypes.DWORD),
                ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD),
                ("dwProductVersionLS", wintypes.DWORD),
            ]

        info = ctypes.cast(p_val, ctypes.POINTER(VS_FIXEDFILEINFO)).contents

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
    Safe because browsers on these platforms just print and exit.
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
    Find a single browser by ID. Returns { id, name, family, path } or None.
    Does NOT run version detection. Does NOT scan other browsers.
    """
    config = config or {}
    system = platform.system()

    # Invariant: Google Chrome is explicitly banned as a TARGET
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
        family = bdef.get("family", get_browser_family(browser_id))
        return {"id": browser_id, "name": name, "family": family, "path": path}

    return None


def detect_all(config=None, target_type=None):
    """
    Detect installed browsers.
    Args:
        config: config dictionary (reads overrides)
        target_type: "chromium", "gecko", or None (returns all)

    Returns: list of [{ id, name, family, path, version }]
    """
    config = config or {}
    found = []
    
    overrides = config.get("browser_overrides", {})
    
    if target_type == "chromium":
        candidate_ids = set(CHROMIUM_BROWSER_DEFS.keys())
    elif target_type == "gecko":
        candidate_ids = set(GECKO_BROWSER_DEFS.keys())
    else:
        candidate_ids = set(BROWSER_DEFS.keys())

    all_ids = candidate_ids.union(overrides.keys())

    for browser_id in sorted(all_ids):
        result = _find_single_browser(browser_id, config)
        if result:
            # If target_type specified, verify family match
            if target_type and result.get("family") != target_type:
                continue
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


# ── Profile & Data Directories ─────────────────────────
_CHROMIUM_USER_DATA_DIRS = {
    "edge": {
        "Windows": [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data")],
        "Linux": [os.path.expanduser("~/.config/microsoft-edge")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/Microsoft Edge")],
    },
    "brave": {
        "Windows": [os.path.join(os.environ.get("LOCALAPPDATA", ""), "BraveSoftware", "Brave-Browser", "User Data")],
        "Linux": [os.path.expanduser("~/.config/BraveSoftware/Brave-Browser")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/BraveSoftware/Brave-Browser")],
    },
    "chromium": {
        "Windows": [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Chromium", "User Data")],
        "Linux": [os.path.expanduser("~/.config/chromium")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/Chromium")],
    },
    "vivaldi": {
        "Windows": [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Vivaldi", "User Data")],
        "Linux": [os.path.expanduser("~/.config/vivaldi")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/Vivaldi")],
    },
    "opera": {
        "Windows": [os.path.join(os.environ.get("APPDATA", ""), "Opera Software", "Opera Stable")],
        "Linux": [os.path.expanduser("~/.config/opera")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/com.operasoftware.Opera")],
    },
}

_GECKO_BASE_DIRS = {
    "firefox": {
        "Windows": [os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox")],
        "Linux": [os.path.expanduser("~/.mozilla/firefox")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/Firefox")],
    },
    "librewolf": {
        "Windows": [os.path.join(os.environ.get("APPDATA", ""), "LibreWolf")],
        "Linux": [os.path.expanduser("~/.librewolf")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/LibreWolf")],
    },
    "floorp": {
        "Windows": [os.path.join(os.environ.get("APPDATA", ""), "Floorp")],
        "Linux": [os.path.expanduser("~/.floorp")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/Floorp")],
    },
    "waterfox": {
        "Windows": [os.path.join(os.environ.get("APPDATA", ""), "Waterfox")],
        "Linux": [os.path.expanduser("~/.waterfox")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/Waterfox")],
    },
    "zen": {
        "Windows": [os.path.join(os.environ.get("APPDATA", ""), "zen")],
        "Linux": [os.path.expanduser("~/.zen")],
        "Darwin": [os.path.expanduser("~/Library/Application Support/Zen")],
    },
}


def _detect_gecko_profiles(browser_id):
    """Parse profiles.ini or scan directories for Gecko browsers."""
    system = platform.system()
    base_dirs = _GECKO_BASE_DIRS.get(browser_id, {}).get(system, [])
    profiles = []

    for base_dir in base_dirs:
        if not base_dir or not os.path.isdir(base_dir):
            continue

        ini_path = os.path.join(base_dir, "profiles.ini")
        if os.path.isfile(ini_path):
            try:
                cp = configparser.ConfigParser()
                cp.read(ini_path, encoding="utf-8")
                for sec in cp.sections():
                    if sec.startswith("Profile"):
                        name = cp.get(sec, "Name", fallback=sec)
                        rel = cp.get(sec, "IsRelative", fallback="1")
                        raw_path = cp.get(sec, "Path", fallback="")
                        if not raw_path:
                            continue
                        if rel == "1":
                            full_path = os.path.normpath(os.path.join(base_dir, raw_path))
                        else:
                            full_path = os.path.normpath(raw_path)

                        if os.path.isdir(full_path):
                            profiles.append({
                                "id": name,
                                "name": name,
                                "path": full_path,
                            })
            except Exception:
                pass

        # Fallback: scan Profiles directory
        profiles_dir = os.path.join(base_dir, "Profiles")
        if os.path.isdir(profiles_dir):
            for entry in os.listdir(profiles_dir):
                entry_path = os.path.join(profiles_dir, entry)
                if os.path.isdir(entry_path):
                    # Check if already listed
                    if any(p["path"] == entry_path for p in profiles):
                        continue
                    if os.path.isfile(os.path.join(entry_path, "prefs.js")):
                        profiles.append({
                            "id": entry,
                            "name": entry,
                            "path": entry_path,
                        })

    return profiles


def _detect_chromium_profiles(browser_id):
    """Detect existing profiles for a Chromium browser."""
    system = platform.system()
    candidates = _CHROMIUM_USER_DATA_DIRS.get(browser_id, {}).get(system, [])
    user_data_dir = None
    for c in candidates:
        if c and os.path.isdir(c):
            user_data_dir = c
            break

    if not user_data_dir:
        return []

    profiles = []
    skip_dirs = {
        "System Profile", "Guest Profile", "Crashpad", "GrShaderCache",
        "ShaderCache", "BrowserMetrics", "Safe Browsing", "Crowd Deny",
        "MEIPreload", "WidevineCdm", "pnacl", "SwReporter"
    }

    try:
        for entry in os.listdir(user_data_dir):
            entry_path = os.path.join(user_data_dir, entry)
            if not os.path.isdir(entry_path) or entry in skip_dirs:
                continue

            prefs_file = os.path.join(entry_path, "Preferences")
            if not os.path.isfile(prefs_file):
                continue

            display_name = entry
            try:
                import json
                with open(prefs_file, "r", encoding="utf-8") as f:
                    prefs = json.load(f)
                display_name = prefs.get("profile", {}).get("name") or entry
            except Exception:
                pass

            profiles.append({
                "id": entry,
                "name": display_name,
                "path": entry_path,
            })
    except OSError:
        pass

    profiles.sort(key=lambda p: (p["id"] != "Default", p["id"]))
    return profiles


def detect_profiles(browser_id, config=None):
    """
    Detect profiles for any supported browser (Chromium or Gecko).
    """
    family = get_browser_family(browser_id)
    if family == "gecko":
        return _detect_gecko_profiles(browser_id)
    else:
        return _detect_chromium_profiles(browser_id)
