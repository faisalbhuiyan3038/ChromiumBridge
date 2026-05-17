/**
 * receiver.js — ChromeBridge Chromium companion service worker.
 *
 * Flow:
 *   1. Chrome opens the target URL directly (app/popup/normal mode)
 *   2. Companion fetches cookies from bridge's localhost server (port 47831)
 *   3. Injects all cookies via chrome.cookies.set()
 *   4. Reloads the active tab so the server sees the injected cookies
 *
 * Token-based dedup: each bridge launch has a unique token stored in
 * chrome.storage.session to prevent re-injection on tab navigations.
 */

// !! BRIDGE_COOKIE_INJECTION_POINT — replaced by bridge/cookies.py before launch !!
const INJECTED_COOKIES = null;

const COOKIE_SERVER_URL = "http://127.0.0.1:47831/cookies";
const MAX_RETRIES = 8;
const RETRY_DELAY_MS = 500;
const TOKEN_KEY = "_cb_last_token";

let _injecting = false;

/**
 * Main entry: fetch cookies, inject, reload.
 */
async function injectCookies() {
  if (_injecting) return;
  _injecting = true;

  try {
    let cookies = null;
    let token = null;

    // Method 1: inline-injected cookies (--load-extension session copy)
    if (INJECTED_COOKIES && Array.isArray(INJECTED_COOKIES) && INJECTED_COOKIES.length > 0) {
      console.log("[ChromeBridge Companion] Using inline-injected cookies.");
      cookies = INJECTED_COOKIES;
    }

    // Method 2: fetch from bridge's localhost cookie server
    if (!cookies) {
      const result = await fetchFromServer();
      if (result) {
        cookies = result.cookies;
        token = result.token;
      }
    }

    if (!cookies || cookies.length === 0) {
      return; // No cookies available — silent
    }

    // Check if we already processed this session
    if (token) {
      const stored = await getStoredToken();
      if (stored === token) {
        return; // Already injected for this handoff
      }
    }

    // Inject cookies
    console.log(`[ChromeBridge Companion] Injecting ${cookies.length} cookies...`);
    await setCookies(cookies);

    // Mark this session as processed
    if (token) {
      await storeToken(token);
    }

    // Reload the active tab so the server sees the new cookies
    await reloadActiveTab();
  } finally {
    _injecting = false;
  }
}

// ── Token Storage (chrome.storage.session clears on browser restart) ──

async function getStoredToken() {
  try {
    const data = await chrome.storage.session.get(TOKEN_KEY);
    return data[TOKEN_KEY] || null;
  } catch { return null; }
}

async function storeToken(token) {
  try {
    await chrome.storage.session.set({ [TOKEN_KEY]: token });
  } catch {}
}

// ── Server Fetch ─────────────────────────────────────

async function fetchFromServer() {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(COOKIE_SERVER_URL);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();

      let cookies, token;
      if (Array.isArray(data)) {
        cookies = data; token = null;
      } else {
        cookies = data.cookies || [];
        token = data.token || null;
      }

      if (cookies.length > 0) {
        console.log(`[ChromeBridge Companion] Got ${cookies.length} cookies from server.`);
        return { cookies, token };
      }
    } catch {
      if (attempt < MAX_RETRIES) {
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
      }
    }
  }
  return null;
}

// ── Cookie Injection ─────────────────────────────────

async function setCookies(cookies) {
  let success = 0;
  let failed = 0;

  for (const cookie of cookies) {
    try {
      const protocol = cookie.secure ? "https" : "http";
      const domain = cookie.domain.startsWith(".") ? cookie.domain.slice(1) : cookie.domain;
      const cookieUrl = `${protocol}://${domain}${cookie.path || "/"}`;

      const params = {
        url: cookieUrl,
        name: cookie.name,
        value: cookie.value,
      };

      if (cookie.domain) params.domain = cookie.domain;
      if (cookie.path) params.path = cookie.path;
      if (cookie.secure !== undefined) params.secure = cookie.secure;
      if (cookie.httpOnly !== undefined) params.httpOnly = cookie.httpOnly;

      if (cookie.sameSite) {
        const map = { no_restriction: "no_restriction", lax: "lax", strict: "strict", none: "no_restriction" };
        params.sameSite = map[cookie.sameSite.toLowerCase()] || "lax";
      }

      if (cookie.expirationDate) {
        params.expirationDate = cookie.expirationDate;
      }

      await chrome.cookies.set(params);
      success++;
    } catch (err) {
      failed++;
      console.warn(`[ChromeBridge Companion] Cookie "${cookie.name}" failed:`, err.message);
    }
  }

  console.log(`[ChromeBridge Companion] Done: ${success} set, ${failed} failed.`);
}

// ── Tab Reload ───────────────────────────────────────

async function reloadActiveTab() {
  try {
    // Service workers don't always have a "currentWindow" during startup
    let tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tabs.length === 0) {
      tabs = await chrome.tabs.query({ active: true }); // fallback to any active tab
    }
    
    if (tabs.length > 0) {
      // Small delay to ensure cookies are fully committed
      await new Promise((r) => setTimeout(r, 300));
      await chrome.tabs.reload(tabs[0].id);
      console.log("[ChromeBridge Companion] Tab reloaded with cookies.");
    } else {
      console.warn("[ChromeBridge Companion] Could not find active tab to reload.");
    }
  } catch (err) {
    console.warn("[ChromeBridge Companion] Reload failed:", err);
  }
}

// ── Event Listeners ──────────────────────────────────

chrome.runtime.onInstalled.addListener(() => injectCookies());
chrome.runtime.onStartup.addListener(() => injectCookies());

// Reliable fallback: on any tab load, try injection (no-ops if same token)
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    injectCookies();
  }
});
