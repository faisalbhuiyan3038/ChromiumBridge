#!/usr/bin/env python3
"""
install.py — Unified installer for ChromiumBridge native messaging host.
Registers the native host manifest with:
  - Mozilla Firefox (Windows registry / Linux & macOS paths)
  - Chromium-based browsers: Chrome, Brave, Edge, Vivaldi, Opera, Chromium

Usage:
    python install.py                  # Install for Firefox & Chromium browsers
    python install.py --chrome-id ID   # Register specific Chrome extension ID
    python install.py --uninstall      # Uninstall registration across all browsers
"""

import os
import sys
import json
import platform
import argparse

HOST_NAME = "chromiumbridge"
FIREFOX_EXTENSION_ID = "chromiumbridges@faisalbhuiyan.com"

# Known Chromium registry paths on Windows
WINDOWS_CHROMIUM_REG_PATHS = [
    r"Software\Google\Chrome\NativeMessagingHosts",
    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    r"Software\Microsoft\Edge\NativeMessagingHosts",
    r"Software\Chromium\NativeMessagingHosts",
    r"Software\Vivaldi\NativeMessagingHosts",
    r"Software\Opera Software\NativeMessagingHosts",
]

# Known Chromium paths on Linux
LINUX_CHROMIUM_DIRS = [
    "~/.config/google-chrome/NativeMessagingHosts",
    "~/.config/chromium/NativeMessagingHosts",
    "~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts",
    "~/.config/microsoft-edge/NativeMessagingHosts",
    "~/.config/vivaldi/NativeMessagingHosts",
    "~/.config/opera/NativeMessagingHosts",
]

# Known Chromium paths on macOS
DARWIN_CHROMIUM_DIRS = [
    "~/Library/Application Support/Google/Chrome/NativeMessagingHosts",
    "~/Library/Application Support/Chromium/NativeMessagingHosts",
    "~/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts",
    "~/Library/Application Support/Microsoft Edge/NativeMessagingHosts",
    "~/Library/Application Support/Vivaldi/NativeMessagingHosts",
    "~/Library/Application Support/com.operasoftware.Opera/NativeMessagingHosts",
]


def get_bridge_dir():
    """Get the directory where this script lives."""
    return os.path.dirname(os.path.abspath(__file__))


def get_bridge_script(bridge_dir=None):
    """Get the absolute path to bridge.py."""
    return os.path.join(bridge_dir or get_bridge_dir(), "bridge.py")


def get_python_path():
    """Get the path to the Python interpreter."""
    return sys.executable


def get_executable_path(bridge_dir, python_path=None):
    """
    Get the script/wrapper path to invoke from native messaging.
    On Windows, uses a .bat wrapper. On Unix, uses bridge.py directly.
    """
    system = platform.system()
    python_path = python_path or get_python_path()

    if system == "Windows":
        bat_path = os.path.join(bridge_dir, "chromiumbridge.bat")
        bridge_script = get_bridge_script(bridge_dir)
        with open(bat_path, "w") as f:
            f.write(f'@echo off\n"{python_path}" -u "{bridge_script}"\n')
        return bat_path
    else:
        bridge_script = get_bridge_script(bridge_dir)
        os.chmod(bridge_script, 0o755)
        return bridge_script


def generate_mozilla_manifest(bridge_dir, python_path=None):
    """Generate the Firefox native messaging host manifest."""
    exec_path = get_executable_path(bridge_dir, python_path)
    return {
        "name": HOST_NAME,
        "description": "ChromiumBridge unified native messaging host (Firefox)",
        "path": exec_path,
        "type": "stdio",
        "allowed_extensions": [FIREFOX_EXTENSION_ID],
    }


def generate_chromium_manifest(bridge_dir, python_path=None, chrome_ids=None):
    """Generate the Chromium native messaging host manifest."""
    exec_path = get_executable_path(bridge_dir, python_path)
    
    origins = []
    if chrome_ids:
        for cid in chrome_ids:
            if cid:
                origins.append(f"chrome-extension://{cid}/")
    
    # Default fallback / wildcard development origins if none specified
    if not origins:
        origins = [
            "chrome-extension://*/*",
        ]

    return {
        "name": HOST_NAME,
        "description": "ChromiumBridge unified native messaging host (Chromium)",
        "path": exec_path,
        "type": "stdio",
        "allowed_origins": origins,
    }


def get_mozilla_manifest_path(system):
    """Get path for Mozilla host manifest."""
    if system == "Windows":
        return os.path.join(get_bridge_dir(), f"{HOST_NAME}.json")
    elif system == "Linux":
        return os.path.expanduser(f"~/.mozilla/native-messaging-hosts/{HOST_NAME}.json")
    elif system == "Darwin":
        return os.path.expanduser(f"~/Library/Application Support/Mozilla/NativeMessagingHosts/{HOST_NAME}.json")
    else:
        raise RuntimeError(f"Unsupported OS: {system}")


def install(python_path=None, bridge_dir=None, chrome_id=None):
    """Install the native messaging host for both Mozilla and Chromium browsers."""
    system = platform.system()
    bridge_dir = bridge_dir or get_bridge_dir()
    python_path = python_path or get_python_path()

    print("[ChromiumBridge] Installing unified native messaging host...")
    print(f"  OS: {system}")
    print(f"  Bridge dir: {bridge_dir}")
    print(f"  Python path: {python_path}")

    # Load configured chrome_id if present
    chrome_ids = []
    if chrome_id:
        chrome_ids.append(chrome_id)
    try:
        from config import load_config, save_config
        cfg = load_config()
        stored_id = cfg.get("chrome_extension_id")
        if stored_id and stored_id not in chrome_ids:
            chrome_ids.append(stored_id)
    except Exception:
        pass

    # 1. Mozilla Manifest
    moz_manifest = generate_mozilla_manifest(bridge_dir, python_path)
    moz_manifest_path = get_mozilla_manifest_path(system)
    os.makedirs(os.path.dirname(moz_manifest_path), exist_ok=True)
    with open(moz_manifest_path, "w", encoding="utf-8") as f:
        json.dump(moz_manifest, f, indent=2)
    print(f"  Mozilla manifest written to: {moz_manifest_path}")

    # 2. Chromium Manifest
    chrome_manifest = generate_chromium_manifest(bridge_dir, python_path, chrome_ids)
    chrome_manifest_path = os.path.join(bridge_dir, f"{HOST_NAME}_chrome.json")
    with open(chrome_manifest_path, "w", encoding="utf-8") as f:
        json.dump(chrome_manifest, f, indent=2)
    print(f"  Chromium manifest written to: {chrome_manifest_path}")

    # 3. Registration
    if system == "Windows":
        try:
            import winreg

            # Register Mozilla
            moz_reg = f"Software\\Mozilla\\NativeMessagingHosts\\{HOST_NAME}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, moz_reg) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, moz_manifest_path)
            print(f"  [OK] Firefox registry registered: HKCU\\{moz_reg}")

            # Register Chromium browsers
            for reg_base in WINDOWS_CHROMIUM_REG_PATHS:
                full_reg = f"{reg_base}\\{HOST_NAME}"
                try:
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, full_reg) as key:
                        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, chrome_manifest_path)
                    print(f"  [OK] Chromium registry registered: HKCU\\{full_reg}")
                except Exception as err:
                    print(f"  [!] Skipped {full_reg}: {err}")

        except Exception as e:
            print(f"  ERROR: Failed to create Windows registry keys: {e}")
            return False

    elif system == "Linux":
        # Register for each Linux Chromium location
        for d in LINUX_CHROMIUM_DIRS:
            target_dir = os.path.expanduser(d)
            os.makedirs(target_dir, exist_ok=True)
            target_file = os.path.join(target_dir, f"{HOST_NAME}.json")
            try:
                shutil.copyfile(chrome_manifest_path, target_file)
                print(f"  [OK] Installed Chromium manifest: {target_file}")
            except Exception as err:
                print(f"  [!] Skipped {target_file}: {err}")

    elif system == "Darwin":
        # Register for each macOS Chromium location
        for d in DARWIN_CHROMIUM_DIRS:
            target_dir = os.path.expanduser(d)
            os.makedirs(target_dir, exist_ok=True)
            target_file = os.path.join(target_dir, f"{HOST_NAME}.json")
            try:
                shutil.copyfile(chrome_manifest_path, target_file)
                print(f"  [OK] Installed Chromium manifest: {target_file}")
            except Exception as err:
                print(f"  [!] Skipped {target_file}: {err}")

    # Save paths to config
    try:
        from config import load_config, save_config
        config = load_config()
        config["python_path"] = python_path
        config["bridge_dir"] = bridge_dir
        if chrome_id:
            config["chrome_extension_id"] = chrome_id
        save_config(config)
    except Exception:
        pass

    print(f"\n[ChromiumBridge] Installation complete!")
    print(f"  Host name: {HOST_NAME}")
    print(f"  Firefox Extension ID: {FIREFOX_EXTENSION_ID}")
    return True


def reinstall_from_config():
    """Re-run installation using paths from config.json."""
    try:
        from config import load_config
        config = load_config()
        python_path = config.get("python_path") or get_python_path()
        bridge_dir = config.get("bridge_dir") or get_bridge_dir()
        chrome_id = config.get("chrome_extension_id") or None
        success = install(python_path=python_path, bridge_dir=bridge_dir, chrome_id=chrome_id)
        return {"status": "ok" if success else "error"}
    except Exception as e:
        return {"error": str(e)}


def uninstall():
    """Uninstall the native messaging host from all browsers."""
    system = platform.system()
    print("[ChromiumBridge] Uninstalling native messaging host...")

    # Remove manifest files
    moz_path = get_mozilla_manifest_path(system)
    if os.path.isfile(moz_path):
        os.remove(moz_path)
        print(f"  Removed: {moz_path}")

    chrome_manifest = os.path.join(get_bridge_dir(), f"{HOST_NAME}_chrome.json")
    if os.path.isfile(chrome_manifest):
        os.remove(chrome_manifest)
        print(f"  Removed: {chrome_manifest}")

    if system == "Windows":
        bat_path = os.path.join(get_bridge_dir(), "chromiumbridge.bat")
        if os.path.isfile(bat_path):
            os.remove(bat_path)
            print(f"  Removed: {bat_path}")

        try:
            import winreg
            # Mozilla
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"Software\\Mozilla\\NativeMessagingHosts\\{HOST_NAME}")
                print("  Removed Mozilla registry key")
            except Exception:
                pass
            # Chromium
            for reg_base in WINDOWS_CHROMIUM_REG_PATHS:
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{reg_base}\\{HOST_NAME}")
                    print(f"  Removed {reg_base}\\{HOST_NAME}")
                except Exception:
                    pass
        except Exception:
            pass

    print("\n[ChromiumBridge] Uninstall complete.")
    return True


def main():
    parser = argparse.ArgumentParser(description="ChromiumBridge unified native host installer")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall native messaging host")
    parser.add_argument("--python-path", type=str, default=None, help="Absolute path to Python interpreter")
    parser.add_argument("--bridge-dir", type=str, default=None, help="Absolute path to bridge directory")
    parser.add_argument("--chrome-id", type=str, default=None, help="Chrome/Chromium extension ID to authorize")
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
    else:
        install(python_path=args.python_path, bridge_dir=args.bridge_dir, chrome_id=args.chrome_id)


if __name__ == "__main__":
    main()
