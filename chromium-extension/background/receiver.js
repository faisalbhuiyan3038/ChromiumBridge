/**
 * receiver.js — ChromeBridge Chromium companion service worker.
 *
 * Cookie injection flow:
 *   1. Browser opens the target URL (app/popup/normal mode)
 *   2. Companion gets cookies from either:
 *      a. Inline INJECTED_COOKIES (ephemeral --load-extension path)
 *      b. Bridge's localhost HTTP server (persistent / manual-install path)
 *   3. Injects all cookies via chrome.cookies.set()
 *   4. Reloads the active tab so the server sees the injected cookies
 *
 * Dedup strategy:
 *   - Server path: unique token per bridge launch (stored in session storage)
 *   - Inline path: simple boolean flag in session storage
 *   Both prevent the tabs.onUpdated fallback from re-injecting after reload.
 */

// !! BRIDGE_COOKIE_INJECTION_POINT — replaced by bridge/cookies.py !!
const INJECTED_COOKIES = null;
const INJECTED_URL = null;

const COOKIE_SERVER_URL = "http://127.0.0.1:47831/cookies";
const MAX_RETRIES = 8;
const RETRY_DELAY_MS = 500;
const TOKEN_KEY = "_cb_last_token";
const DONE_KEY = "_cb_done";

let _injecting = false;

/**
 * Main entry: fetch cookies, inject once, navigate.
 */
async function injectCookies() {
  if (_injecting) return;
  _injecting = true;

  try {
    // ── Quick bail: already injected this browser session ──
    try {
      const s = await chrome.storage.session.get(DONE_KEY);
      if (s[DONE_KEY]) {
        if (INJECTED_COOKIES) return; // inline → done forever
        // server path: fall through to token check below
      }
    } catch { /* session storage unavailable — continue */ }

    let cookies = null;
    let token = null;
    let targetUrl = INJECTED_URL;

    // Method 1: inline-injected cookies (--load-extension session copy)
    if (INJECTED_COOKIES && Array.isArray(INJECTED_COOKIES) && INJECTED_COOKIES.length > 0) {
      console.log("[ChromeBridge Companion] Using inline cookies.");
      cookies = INJECTED_COOKIES;
    }

    // Method 2: fetch from bridge's localhost cookie server
    if (!cookies) {
      const result = await fetchFromServer();
      if (result) {
        cookies = result.cookies || [];
        token = result.token;
        if (result.url) targetUrl = result.url;
      }
    }

    // ── Token dedup (server path only) ──
    if (token) {
      const stored = await getStoredToken();
      if (stored === token) return; // same handoff session
    }

    // ── Inject cookies ──
    if (cookies && cookies.length > 0) {
      console.log(`[ChromeBridge Companion] Injecting ${cookies.length} cookies...`);
      await setCookies(cookies);
    }

    // ── Mark done ──
    if (token) await storeToken(token);
    try { await chrome.storage.session.set({ [DONE_KEY]: true }); } catch {}

    // ── Navigate tab to target URL ──
    await updateActiveTab(targetUrl);
  } finally {
    _injecting = false;
  }
}

// ── Token Storage ────────────────────────────────────

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

      let cookies, token, url;
      if (Array.isArray(data)) {
        cookies = data; token = null; url = null;
      } else {
        cookies = data.cookies || [];
        token = data.token || null;
        url = data.url || null;
      }

      if (cookies !== undefined) {
        console.log(`[ChromeBridge Companion] Got ${cookies.length || 0} cookies from server.`);
        return { cookies, token, url };
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

// ── Tab Navigation ───────────────────────────────────

async function updateActiveTab(targetUrl) {
  try {
    // Service workers don't always have a "currentWindow" during startup.
    // lastFocusedWindow is more reliable; fall back to any active tab.
    let tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tabs.length === 0) {
      tabs = await chrome.tabs.query({ active: true });
    }

    if (tabs.length > 0) {
      await new Promise((r) => setTimeout(r, 300));
      if (targetUrl) {
        await chrome.tabs.update(tabs[0].id, { url: targetUrl });
        console.log(`[ChromeBridge Companion] Tab navigated to ${targetUrl}`);
      } else {
        await chrome.tabs.reload(tabs[0].id);
        console.log("[ChromeBridge Companion] Tab reloaded with cookies.");
      }
    } else {
      console.warn("[ChromeBridge Companion] No active tab found to navigate.");
    }
  } catch (err) {
    console.warn("[ChromeBridge Companion] Navigation failed:", err);
  }
}

// ── Event Listeners ──────────────────────────────────

chrome.runtime.onInstalled.addListener(() => injectCookies());
chrome.runtime.onStartup.addListener(() => injectCookies());

// Fallback: fires on tab navigations. The DONE_KEY / token check
// ensures this is a no-op after the first successful injection.
chrome.tabs.onUpdated.addListener((_tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    injectCookies();
  }
});

// Handle messages from content scripts
chrome.runtime.onMessage.addListener((message, sender) => {
  if (message.action === "closeWindow" && sender.tab) {
    chrome.windows.remove(sender.tab.windowId).catch(() => {
      chrome.tabs.remove(sender.tab.id).catch(() => {});
    });
  }
});
