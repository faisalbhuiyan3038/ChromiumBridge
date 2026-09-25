"""
cookies_gecko.py — Direct SQLite cookie injection for Gecko/Firefox target browsers.
Firefox profiles store cookies in an unencrypted SQLite database (`cookies.sqlite`).
This module creates and populates `cookies.sqlite` before launching Firefox,
enabling instant, authenticated sessions with zero extension dependencies.

Schema reference: Firefox 104+ moz_cookies table (verified against archiveteam.org)
"""

import os
import sys
import time
import sqlite3
import logging

log = logging.getLogger(__name__)


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


def _normalize_host(domain):
    """
    Normalize a Chrome cookie domain to Firefox moz_cookies host format.

    Chrome:  ".example.com"  -> host-only domain (subdomain cookies)
    Chrome:  "example.com"   -> exact host cookie
    Firefox: ".example.com" means shared across subdomains (domain cookie)
    Firefox: "example.com"  means exact host only
    We preserve the Chrome convention exactly—it matches Firefox's expected format.
    """
    if not domain:
        return domain
    # Chrome uses leading dot for subdomain cookies. Firefox uses the same.
    # No transformation needed; pass through as-is.
    return domain


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
        n_written = inject_gecko_cookies(profile_dir, cookies)
        log.debug("stage_gecko_profile: injected %d cookies into %s", n_written, profile_dir)
    else:
        log.debug("stage_gecko_profile: no cookies to inject")


def inject_gecko_cookies(profile_dir, cookies):
    """
    Create or update moz_cookies table in cookies.sqlite.
    Uses the canonical Firefox 104+ schema (with rawSameSite column).

    Args:
        profile_dir: Firefox profile directory.
        cookies: List of cookie dictionaries (Chrome format).
    Returns:
        Number of cookies successfully written.
    """
    db_path = os.path.join(profile_dir, "cookies.sqlite")
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Firefox 104+ canonical schema
    # rawSameSite is required — it stores the original value before browser overrides
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
        rawSameSite INTEGER DEFAULT 0,
        schemeMap INTEGER DEFAULT 0,
        CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes)
    );
    """)

    # Add rawSameSite column if it is missing (Firefox 104+ requirement)
    try:
        cur.execute("ALTER TABLE moz_cookies ADD COLUMN rawSameSite INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists

    now_micros = int(time.time() * 1_000_000)
    written = 0

    for c in cookies:
        name = c.get("name", "")
        value = c.get("value", "")
        domain = _normalize_host(c.get("domain", ""))
        path = c.get("path", "/")

        # Expiry: Chrome gives float seconds epoch, Firefox expects integer seconds
        exp_raw = c.get("expirationDate")
        if exp_raw:
            expiry = int(exp_raw)
        else:
            # Session cookie: use far-future expiry so Firefox treats it as persistent
            expiry = int(time.time() + 86400 * 30)

        secure = 1 if c.get("secure") else 0
        httponly = 1 if c.get("httpOnly") else 0

        # Map Chrome SameSite string to Firefox integer
        # Firefox: 0=None/Unset, 1=Lax, 2=Strict
        samesite_raw = str(c.get("sameSite", "unspecified")).lower()
        if "strict" in samesite_raw:
            samesite = 2
        elif "lax" in samesite_raw:
            samesite = 1
        else:
            samesite = 0  # None / no_restriction / unspecified

        # rawSameSite mirrors sameSite (original value before overrides)
        raw_samesite = samesite

        # schemeMap: 1=HTTP-only, 2=HTTPS-only, 3=both
        # If secure flag is set, HTTPS only; otherwise allow both
        scheme_map = 2 if secure else 3

        try:
            cur.execute("""
            INSERT OR REPLACE INTO moz_cookies
            (originAttributes, name, value, host, path, expiry, lastAccessed, creationTime,
             isSecure, isHttpOnly, sameSite, rawSameSite, schemeMap)
            VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, value, domain, path, expiry, now_micros, now_micros,
                  secure, httponly, samesite, raw_samesite, scheme_map))
            written += 1
        except sqlite3.Error as e:
            log.warning("Failed to insert cookie %r for host %r: %s", name, domain, e)
            continue

    con.commit()
    con.close()
    return written
