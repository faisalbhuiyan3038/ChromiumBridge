"""
detect.py — OS-agnostic Chromium browser detection and path resolution.
Resolution priority: user override → known paths → Windows registry → shutil.which()
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


def _get_version(path):
    """Get browser version by running --version."""
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.strip()
        # Extract version number pattern
        match = re.search(r"(\d+\.\d+\.\d+(?:\.\d+)?)", output)
        return match.group(1) if match else output
    except Exception:
        return None


def detect_all(config=None):
    """
    Detect all installed Chromium-based browsers.
    Returns: [{ id, name, path, version }]
    """
    config = config or {}
    system = platform.system()
    found = []
    overrides = config.get("browser_overrides", {})

    for browser_id, bdef in BROWSER_DEFS.items():
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
            version = _get_version(path)
            found.append({
                "id": browser_id,
                "name": bdef["name"],
                "path": path,
                "version": version,
            })

    return found


def resolve_browser(browser_id, config=None):
    """
    Resolve a single browser by ID. Returns absolute path or None.
    """
    config = config or {}

    # Check override first
    override = config.get("browser_overrides", {}).get(browser_id)
    if override and os.path.isfile(override):
        return override

    # Search normally
    browsers = detect_all(config)
    for b in browsers:
        if b["id"] == browser_id:
            return b["path"]

    return None
