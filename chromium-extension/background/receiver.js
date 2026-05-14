/**
 * receiver.js — ChromeBridge Chromium companion service worker.
 * Reads cookies.json from its own extension directory and injects via chrome.cookies.set().
 * Handles both onInstalled (ephemeral/first launch) and onStartup (persistent profile relaunches).
 */

const COOKIE_FILE = "cookies.json";

/**
 * Inject cookies from the staged cookies.json file.
 */
async function injectCookies() {
  try {
    const url = chrome.runtime.getURL(COOKIE_FILE);
    const response = await fetch(url);

    if (!response.ok) {
      console.log("[ChromeBridge Companion] No cookies.json found — skipping injection.");
      return;
    }

    const cookies = await response.json();

    if (!Array.isArray(cookies) || cookies.length === 0) {
      console.log("[ChromeBridge Companion] cookies.json is empty — skipping.");
      return;
    }

    console.log(`[ChromeBridge Companion] Injecting ${cookies.length} cookies...`);

    let success = 0;
    let failed = 0;

    for (const cookie of cookies) {
      try {
        // Build the cookie URL from domain + path + secure
        const protocol = cookie.secure ? "https" : "http";
        const domain = cookie.domain.startsWith(".") ? cookie.domain.slice(1) : cookie.domain;
        const cookieUrl = `${protocol}://${domain}${cookie.path || "/"}`;

        const params = {
          url: cookieUrl,
          name: cookie.name,
          value: cookie.value,
        };

        // Optional fields — only set if present
        if (cookie.domain) params.domain = cookie.domain;
        if (cookie.path) params.path = cookie.path;
        if (cookie.secure !== undefined) params.secure = cookie.secure;
        if (cookie.httpOnly !== undefined) params.httpOnly = cookie.httpOnly;

        // Map sameSite values (Firefox uses different casing)
        if (cookie.sameSite) {
          const sameSiteMap = {
            no_restriction: "no_restriction",
            lax: "lax",
            strict: "strict",
            none: "no_restriction",
          };
          params.sameSite = sameSiteMap[cookie.sameSite.toLowerCase()] || "lax";
        }

        // Expiration: Firefox uses expirationDate (seconds since epoch)
        if (cookie.expirationDate) {
          params.expirationDate = cookie.expirationDate;
        }

        await chrome.cookies.set(params);
        success++;
      } catch (err) {
        failed++;
        console.warn(`[ChromeBridge Companion] Failed to set cookie "${cookie.name}":`, err);
      }
    }

    console.log(
      `[ChromeBridge Companion] Cookie injection complete: ${success} set, ${failed} failed.`
    );

    // Reload the active tab so the site picks up the new cookies
    await reloadActiveTab();
  } catch (err) {
    console.error("[ChromeBridge Companion] Cookie injection error:", err);
  }
}

/**
 * Reload the currently active tab.
 */
async function reloadActiveTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tabs.length > 0) {
      // Small delay to let cookies propagate
      await new Promise((r) => setTimeout(r, 300));
      await chrome.tabs.reload(tabs[0].id);
      console.log("[ChromeBridge Companion] Active tab reloaded.");
    }
  } catch (err) {
    console.warn("[ChromeBridge Companion] Could not reload tab:", err);
  }
}

// ── Event Listeners ──────────────────────────────────

// onInstalled fires on first load (ephemeral profiles, or first-ever persistent load)
chrome.runtime.onInstalled.addListener((details) => {
  console.log("[ChromeBridge Companion] onInstalled:", details.reason);
  injectCookies();
});

// onStartup fires when Chromium starts with an existing persistent profile
chrome.runtime.onStartup.addListener(() => {
  console.log("[ChromeBridge Companion] onStartup — persistent profile relaunch.");
  injectCookies();
});
