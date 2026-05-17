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
    "chrome": {
        "name": "Google Chrome",
        "executables": {
            "Windows": ["chrome.exe"],
            "Linux": ["google-chrome", "google-chrome-stable"],
            "Darwin": ["Google Chrome"],
        },
        "registry_key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
    },
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
            "chrome": [r"Google\Chrome\Application"],
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
    bdef = BROWSER_DEFS.get(browser_id)
    if not bdef:
        return None

    overrides = config.get("browser_overrides", {})
    path = None

    # 1. User override
    override = overrides.get(browser_id)
    if override and os.path.isfile(override):
        path = override

    # 2. Known paths
    if not path:
        for candidate in _get_known_paths(browser_id, system):
            if os.path.isfile(candidate):
                path = candidate
                break

    # 3. Windows registry
    if not path and system == "Windows":
        path = _check_registry(browser_id)

    # 4. shutil.which fallback
    if not path:
        for exe in bdef.get("executables", {}).get(system, []):
            which_path = shutil.which(exe)
            if which_path:
                path = which_path
                break

    if path:
        return {"id": browser_id, "name": bdef["name"], "path": path}

    return None


def detect_all(config=None):
    """
    Detect all installed Chromium-based browsers.
    Returns: [{ id, name, path, version }]

    Version is detected safely (file metadata on Windows, --version on Unix).
    NO browser windows are opened during detection.
    """
    config = config or {}
    found = []

    for browser_id in BROWSER_DEFS:
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
    result = _find_single_browser(browser_id, config)
    return result["path"] if result else None
