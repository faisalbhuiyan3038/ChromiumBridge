/**
 * receiver.js — ChromeBridge Chromium companion service worker.
 *
 * Flow:
 *   1. Chrome opens about:blank (no cookies sent to the target server)
 *   2. Companion fetches { token, url, cookies } from bridge's cookie server
 *   3. Injects all cookies via chrome.cookies.set()
 *   4. Navigates the tab to the real target URL (cookies are now in place)
 *
 * This prevents the target server from seeing a cookieless initial request
 * and creating a conflicting new session.
 */

// !! BRIDGE_COOKIE_INJECTION_POINT — replaced by bridge/cookies.py before launch !!
const INJECTED_COOKIES = null;

const COOKIE_SERVER_URL = "http://127.0.0.1:47831/cookies";
const MAX_RETRIES = 8;
const RETRY_DELAY_MS = 500;
const TOKEN_KEY = "_cb_last_token";

let _injecting = false;

/**
 * Main entry: fetch cookies + target URL, inject cookies, then navigate.
 */
async function injectCookies() {
  if (_injecting) return;
  _injecting = true;

  try {
    let cookies = null;
    let targetUrl = null;
    let token = null;

    // Method 1: inline-injected cookies (from --load-extension session copy)
    if (INJECTED_COOKIES && Array.isArray(INJECTED_COOKIES) && INJECTED_COOKIES.length > 0) {
      console.log("[ChromeBridge Companion] Using inline-injected cookies.");
      cookies = INJECTED_COOKIES;
    }

    // Method 2: fetch from bridge's localhost cookie server
    if (!cookies) {
      console.log("[ChromeBridge Companion] Fetching from cookie server...");
      const result = await fetchFromServer();
      if (result) {
        cookies = result.cookies;
        targetUrl = result.url || null;
        token = result.token || null;
      }
    }

    if (!cookies || cookies.length === 0) {
      console.log("[ChromeBridge Companion] No cookies available.");
      return;
    }

    // Check if we already processed this session
    if (token) {
      const stored = await getStoredToken();
      if (stored === token) {
        console.log("[ChromeBridge Companion] Already processed this session.");
        return;
      }
    }

    // Inject cookies
    console.log(`[ChromeBridge Companion] Injecting ${cookies.length} cookies...`);
    await setCookies(cookies);

    // Mark this session as processed
    if (token) {
      await storeToken(token);
    }

    // Navigate to the target URL (Chrome was opened with about:blank)
    if (targetUrl) {
      console.log(`[ChromeBridge Companion] Navigating to: ${targetUrl}`);
      await navigateToTarget(targetUrl);
    }
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

      // Handle both formats: { token, url, cookies } or plain array
      let cookies, token, url;
      if (Array.isArray(data)) {
        cookies = data; token = null; url = null;
      } else {
        cookies = data.cookies || [];
        token = data.token || null;
        url = data.url || null;
      }

      if (cookies.length > 0) {
        console.log(`[ChromeBridge Companion] Got ${cookies.length} cookies (attempt ${attempt}).`);
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

// ── Navigation ───────────────────────────────────────

async function navigateToTarget(url) {
  try {
    // Find the about:blank tab (the one we launched with)
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tabs.length > 0) {
      await chrome.tabs.update(tabs[0].id, { url });
      console.log("[ChromeBridge Companion] Tab navigated to target.");
    } else {
      // Fallback: create a new tab
      await chrome.tabs.create({ url });
    }
  } catch (err) {
    console.warn("[ChromeBridge Companion] Navigation failed:", err);
  }
}

// ── Event Listeners ──────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  injectCookies();
});

chrome.runtime.onStartup.addListener(() => {
  injectCookies();
});

// Fallback: fires on every tab load — catches stale service worker state
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    injectCookies(); // No-ops if already injecting or same token
  }
});
