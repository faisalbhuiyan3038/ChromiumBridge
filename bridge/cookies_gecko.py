"""
cookies_gecko.py — Direct SQLite cookie injection for Gecko/Firefox target browsers.
Firefox profiles store cookies in an unencrypted SQLite database (`cookies.sqlite`).
This module creates and populates `cookies.sqlite` before launching Firefox,
enabling instant, authenticated sessions with zero extension dependencies.
"""

import os
import time
import sqlite3


GECKO_USER_PREFS = """
// ChromiumBridge / FirefoxBridge — Automation & Clean Launch Prefs
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("datareporting.policy.dataSubmissionPolicyAcceptedVersion", 2);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutConfig.showWarning", false);
user_pref("browser.warnOnQuit", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.tabs.warnOnClose", false);
"""


def stage_gecko_profile(profile_dir, cookies=None, target_url=""):
    """
    Configure a Firefox profile directory with automation preferences and cookies.

    Args:
        profile_dir: Path to the profile directory.
        cookies: List of cookie dictionaries from the source Chromium browser.
        target_url: The destination URL.
    """
    os.makedirs(profile_dir, exist_ok=True)

    # 1. Write user.js to suppress first-run wizards & prompts
    user_js_path = os.path.join(profile_dir, "user.js")
    existing_content = ""
    if os.path.isfile(user_js_path):
        try:
            with open(user_js_path, "r", encoding="utf-8") as f:
                existing_content = f.read()
        except OSError:
            pass

    with open(user_js_path, "w", encoding="utf-8") as f:
        f.write(existing_content + "\n" + GECKO_USER_PREFS)

    # 2. Populate cookies.sqlite if cookies are provided
    if cookies:
        inject_gecko_cookies(profile_dir, cookies)


def inject_gecko_cookies(profile_dir, cookies):
    """
    Create or update moz_cookies table in cookies.sqlite.

    Args:
        profile_dir: Firefox profile directory.
        cookies: List of cookie dictionaries (Chrome format).
    """
    db_path = os.path.join(profile_dir, "cookies.sqlite")
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS moz_cookies (
        id INTEGER PRIMARY KEY,
        originAttributes TEXT NOT NULL DEFAULT '',
        name TEXT,
        value TEXT,
        host TEXT,
        path TEXT,
        expiry INTEGER,
        lastAccessed INTEGER,
        creationTime INTEGER,
        isSecure INTEGER,
        isHttpOnly INTEGER,
        inBrowserElement INTEGER DEFAULT 0,
        sameSite INTEGER DEFAULT 0,
        schemeMap INTEGER DEFAULT 0,
        isPartitionedAttributeSet INTEGER DEFAULT 0,
        updateTime INTEGER,
        CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes)
    );
    """)

    now_micros = int(time.time() * 1_000_000)

    for c in cookies:
        name = c.get("name", "")
        value = c.get("value", "")
        domain = c.get("domain", "")
        path = c.get("path", "/")
        
        # Expiry: Chrome gives float seconds epoch, Firefox expects integer seconds
        exp_raw = c.get("expirationDate")
        if exp_raw:
            expiry = int(exp_raw)
        else:
            # Session cookie or fallback: 30 days
            expiry = int(time.time() + 86400 * 30)

        secure = 1 if c.get("secure") else 0
        httponly = 1 if c.get("httpOnly") else 0

        # Map sameSite
        samesite_raw = str(c.get("sameSite", "lax")).lower()
        if "strict" in samesite_raw:
            samesite = 2
        elif "lax" in samesite_raw:
            samesite = 1
        else:
            samesite = 0  # None / no_restriction

        # schemeMap: 1=HTTP, 2=HTTPS, 3=both
        scheme_map = 2 if secure else 3

        try:
            cur.execute("""
            INSERT OR REPLACE INTO moz_cookies 
            (originAttributes, name, value, host, path, expiry, lastAccessed, creationTime, isSecure, isHttpOnly, sameSite, schemeMap, isPartitionedAttributeSet, updateTime)
            VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (name, value, domain, path, expiry, now_micros, now_micros, secure, httponly, samesite, scheme_map, now_micros))
        except sqlite3.Error:
            continue

    con.commit()
    con.close()
