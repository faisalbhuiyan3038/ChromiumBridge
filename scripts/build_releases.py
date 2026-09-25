#!/usr/bin/env python3
"""
build_releases.py — Packages release zip files for:
  1. bridge: Native messaging host + companion extension
  2. firefox-extension: For Mozilla Add-ons (AMO)
  3. chrome-extension: For Chrome Web Store & Edge Add-ons
"""

import os
import zipfile
import json

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASES_DIR = os.path.join(ROOT_DIR, "releases")


def get_version():
    manifest_path = os.path.join(ROOT_DIR, "firefox-extension", "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("version", "1.0.0")


def zip_directory(source_dir, zip_handle, archive_prefix="", exclude_patterns=None):
    exclude_patterns = exclude_patterns or []
    for root, dirs, files in os.walk(source_dir):
        # Exclude directories in-place
        dirs[:] = [d for d in dirs if not any(p in d for p in exclude_patterns)]
        for file in files:
            if any(p in file for p in exclude_patterns):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, source_dir)
            arc_name = os.path.join(archive_prefix, rel_path) if archive_prefix else rel_path
            zip_handle.write(full_path, arc_name)


def build_bridge_release(version):
    out_dir = os.path.join(RELEASES_DIR, "bridge")
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"bridge-v{version}.zip")

    bridge_src = os.path.join(ROOT_DIR, "bridge")
    companion_src = os.path.join(ROOT_DIR, "chromium-extension")

    excludes = ["__pycache__", ".pyc", "sessions.log", "chromiumbridge.bat", "chromiumbridge.json", "chromiumbridge_chrome.json"]

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zip_directory(bridge_src, zf, archive_prefix="bridge", exclude_patterns=excludes)
        zip_directory(companion_src, zf, archive_prefix="chromium-extension", exclude_patterns=excludes)

    print(f"[OK] Built bridge release: {zip_path}")


def build_firefox_release(version):
    out_dir = os.path.join(RELEASES_DIR, "firefox-extension")
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"firefox-extension-v{version}.zip")

    fx_src = os.path.join(ROOT_DIR, "firefox-extension")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zip_directory(fx_src, zf, archive_prefix="")

    print(f"[OK] Built Firefox extension release: {zip_path}")


def build_chrome_release(version):
    out_dir = os.path.join(RELEASES_DIR, "chrome-extension")
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"chrome-extension-v{version}.zip")

    chrome_src = os.path.join(ROOT_DIR, "chrome-extension")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zip_directory(chrome_src, zf, archive_prefix="")

    print(f"[OK] Built Chromium extension release: {zip_path}")


def main():
    version = get_version()
    print(f"Building releases for version {version}...")
    build_bridge_release(version)
    build_firefox_release(version)
    build_chrome_release(version)
    print("\nAll releases built successfully!")


if __name__ == "__main__":
    main()
