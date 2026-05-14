#!/usr/bin/env python3
"""
install.py — One-shot installer for ChromeBridge native messaging host.
Registers the native host manifest with Firefox on Windows, Linux, and macOS.

Usage:
    python install.py           # Install
    python install.py --uninstall  # Uninstall
"""

import os
import sys
import json
import platform
import argparse
import shutil

HOST_NAME = "chromiumbridge"
EXTENSION_ID = "chromiumbridge@faisalbhuiyan.com"


def get_bridge_dir():
    """Get the directory where this script lives."""
    return os.path.dirname(os.path.abspath(__file__))


def get_bridge_script():
    """Get the absolute path to bridge.py."""
    return os.path.join(get_bridge_dir(), "bridge.py")


def get_python_path():
    """Get the path to the Python interpreter."""
    return sys.executable


def generate_host_manifest(bridge_dir):
    """
    Generate the native messaging host manifest.
    On Windows, the path should be to a .bat wrapper since Firefox can't
    directly execute .py files.
    """
    system = platform.system()

    if system == "Windows":
        # Create a .bat wrapper
        bat_path = os.path.join(bridge_dir, "chromiumbridge.bat")
        python_path = get_python_path()
        bridge_script = get_bridge_script()

        with open(bat_path, "w") as f:
            f.write(f'@echo off\n"{python_path}" -u "{bridge_script}"\n')

        path_value = bat_path
    else:
        # On Unix, use bridge.py directly (must be executable)
        bridge_script = get_bridge_script()
        os.chmod(bridge_script, 0o755)
        path_value = bridge_script

    manifest = {
        "name": HOST_NAME,
        "description": "ChromeBridge native messaging host — seamless Firefox-to-Chromium handoff",
        "path": path_value,
        "type": "stdio",
        "allowed_extensions": [EXTENSION_ID],
    }

    return manifest


def get_manifest_install_path(system):
    """Get the OS-specific path where the host manifest should be installed."""
    if system == "Windows":
        # On Windows, the manifest can live anywhere — the registry points to it.
        return os.path.join(get_bridge_dir(), f"{HOST_NAME}.json")
    elif system == "Linux":
        return os.path.expanduser(
            f"~/.mozilla/native-messaging-hosts/{HOST_NAME}.json"
        )
    elif system == "Darwin":
        return os.path.expanduser(
            f"~/Library/Application Support/Mozilla/NativeMessagingHosts/{HOST_NAME}.json"
        )
    else:
        raise RuntimeError(f"Unsupported OS: {system}")


def install():
    """Install the native messaging host."""
    system = platform.system()
    bridge_dir = get_bridge_dir()

    print(f"[ChromeBridge] Installing native messaging host...")
    print(f"  OS: {system}")
    print(f"  Bridge dir: {bridge_dir}")

    # Generate manifest
    manifest = generate_host_manifest(bridge_dir)
    manifest_path = get_manifest_install_path(system)

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)

    # Write manifest
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"  Manifest written to: {manifest_path}")

    # Windows: register in registry
    if system == "Windows":
        try:
            import winreg

            reg_path = f"Software\\Mozilla\\NativeMessagingHosts\\{HOST_NAME}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, manifest_path)
            print(f"  Registry key created: HKCU\\{reg_path}")
        except Exception as e:
            print(f"  ERROR: Failed to create registry key: {e}")
            return False

    print(f"\n[ChromeBridge] Installation complete!")
    print(f"  Host name: {HOST_NAME}")
    print(f"  Extension ID: {EXTENSION_ID}")
    return True


def uninstall():
    """Uninstall the native messaging host."""
    system = platform.system()

    print(f"[ChromeBridge] Uninstalling native messaging host...")

    manifest_path = get_manifest_install_path(system)

    # Remove manifest file
    if os.path.isfile(manifest_path):
        os.remove(manifest_path)
        print(f"  Removed manifest: {manifest_path}")
    else:
        print(f"  Manifest not found: {manifest_path}")

    # Remove .bat wrapper on Windows
    if system == "Windows":
        bat_path = os.path.join(get_bridge_dir(), "chromiumbridge.bat")
        if os.path.isfile(bat_path):
            os.remove(bat_path)
            print(f"  Removed .bat wrapper: {bat_path}")

        # Remove registry key
        try:
            import winreg

            reg_path = f"Software\\Mozilla\\NativeMessagingHosts\\{HOST_NAME}"
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_path)
            print(f"  Removed registry key: HKCU\\{reg_path}")
        except Exception:
            print(f"  Registry key not found or already removed.")

    print(f"\n[ChromeBridge] Uninstall complete.")
    return True


def main():
    parser = argparse.ArgumentParser(description="ChromeBridge native host installer")
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall the native messaging host",
    )
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
    else:
        install()


if __name__ == "__main__":
    main()
