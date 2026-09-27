/**
 * receiver.js — ChromiumBridge Gecko Companion background script.
 *
 * Receives authenticated tab handoffs from Chromium browsers via the bridge's
 * localhost handoff server. Restores cookies via browser.cookies.set(), navigates
 * to the target URL, and injects localStorage/sessionStorage via executeScript.
 *
 * Flow:
 *   1. Detect navigation to http://127.0.0.1:47831/handoff?token=...
 *   2. Fetch the payload JSON from the handoff server.
 *   3. Set all cookies via browser.cookies.set() (supports HttpOnly).
 *   4. Navigate the tab to the target URL.
 *   5. Once loaded, inject localStorage/sessionStorage via tabs.executeScript().
 */

(function () {
  "use strict";

  const HANDOFF_ORIGIN = "http://127.0.0.1:47831";
  const HANDOFF_PATH = "/handoff";

  // Track active handoffs to avoid duplicate processing
  const _activeHandoffs = new Set();

  // ── Handoff Detection ─────────────────────────────────

  browser.webNavigation.onCompleted.addListener(
    async (details) => {
      // Only handle top-level frame navigations
      if (details.frameId !== 0) return;

      const url = details.url;
      if (!url.startsWith(HANDOFF_ORIGIN + HANDOFF_PATH)) return;

      const tabId = details.tabId;

      // Prevent duplicate processing for the same tab
      if (_activeHandoffs.has(tabId)) return;
      _activeHandoffs.add(tabId);

      try {
        await processHandoff(tabId, url);
      } catch (err) {
        console.error("[ChromiumBridge Gecko Companion] Handoff failed:", err);
      } finally {
        _activeHandoffs.delete(tabId);
      }
    },
    { url: [{ hostEquals: "127.0.0.1", pathPrefix: "/handoff" }] }
  );

  // ── Core Handoff Processing ───────────────────────────

  async function processHandoff(tabId, handoffUrl) {
    console.log("[ChromiumBridge Gecko Companion] Handoff detected:", handoffUrl);

    // 1. Fetch the payload from the handoff server
    const payload = await fetchPayload(handoffUrl);
    if (!payload) {
      console.error("[ChromiumBridge Gecko Companion] Failed to fetch handoff payload.");
      return;
    }

    const targetUrl = payload.url;
    const cookies = payload.cookies || [];
    const storage = payload.storage || {};

    console.log(
      `[ChromiumBridge Gecko Companion] Payload received: ` +
      `url=${targetUrl}, cookies=${cookies.length}, ` +
      `localStorage=${storage.localStorage ? Object.keys(storage.localStorage).length : 0} keys, ` +
      `sessionStorage=${storage.sessionStorage ? Object.keys(storage.sessionStorage).length : 0} keys`
    );

    // 2. Restore cookies
    if (cookies.length > 0) {
      await restoreCookies(cookies);
    }

    // 3. Mark handoff as active (for the return button)
    if (targetUrl) {
      await setHandoffActive(targetUrl);
    }

    // 4. Navigate to the target URL
    if (targetUrl) {
      await browser.tabs.update(tabId, { url: targetUrl });
      console.log("[ChromiumBridge Gecko Companion] Navigated to:", targetUrl);

      // 5. Inject storage after the target page loads
      if (hasStorageData(storage)) {
        await waitForNavigation(tabId, targetUrl);
        await injectStorage(tabId, storage);
      }
    }
  }

  // ── Payload Fetching ──────────────────────────────────

  async function fetchPayload(handoffUrl) {
    const MAX_RETRIES = 3;
    const RETRY_DELAY_MS = 500;

    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
      try {
        const response = await fetch(handoffUrl, {
          headers: { "X-Bridge-Fetch": "1" }
        });
        if (response.status === 403) {
          console.warn("[ChromiumBridge Gecko Companion] Token rejected (403). May already be consumed.");
          return null;
        }
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return await response.json();
      } catch (err) {
        console.warn(
          `[ChromiumBridge Gecko Companion] Fetch attempt ${attempt}/${MAX_RETRIES} failed:`,
          err.message
        );
        if (attempt < MAX_RETRIES) {
          await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
        }
      }
    }
    return null;
  }

  // ── Cookie Restoration ────────────────────────────────

  async function restoreCookies(cookies) {
    let success = 0;
    let failed = 0;

    for (const cookie of cookies) {
      try {
        const protocol = cookie.secure ? "https" : "http";
        const domain = cookie.domain.startsWith(".")
          ? cookie.domain.slice(1)
          : cookie.domain;
        const cookieUrl = `${protocol}://${domain}${cookie.path || "/"}`;

        const params = {
          url: cookieUrl,
          name: cookie.name,
          value: cookie.value,
        };

        // Domain — pass through (Firefox handles leading dot correctly)
        if (cookie.domain) params.domain = cookie.domain;
        if (cookie.path) params.path = cookie.path;
        if (cookie.secure !== undefined) params.secure = cookie.secure;
        if (cookie.httpOnly !== undefined) params.httpOnly = cookie.httpOnly;

        // SameSite mapping: Chrome string → Firefox string
        if (cookie.sameSite) {
          const sameSiteMap = {
            no_restriction: "no_restriction",
            lax: "lax",
            strict: "strict",
            none: "no_restriction",
            unspecified: "no_restriction",
          };
          const mapped = sameSiteMap[cookie.sameSite.toLowerCase()];
          params.sameSite = mapped || "no_restriction";
        } else {
          params.sameSite = "no_restriction";
        }

        // Expiration: only set for persistent cookies (omit for session cookies)
        if (cookie.expirationDate) {
          params.expirationDate = cookie.expirationDate;
        }

        // Use the default cookie store
        params.storeId = "firefox-default";

        await browser.cookies.set(params);
        success++;
      } catch (err) {
        failed++;
        console.warn(
          `[ChromiumBridge Gecko Companion] Cookie "${cookie.name}" for "${cookie.domain}" failed:`,
          err.message
        );
      }
    }

    console.log(
      `[ChromiumBridge Gecko Companion] Cookies restored: ${success} set, ${failed} failed (of ${cookies.length} total).`
    );
  }

  // ── Storage Injection ─────────────────────────────────

  function hasStorageData(storage) {
    if (!storage) return false;
    const hasLS = storage.localStorage && Object.keys(storage.localStorage).length > 0;
    const hasSS = storage.sessionStorage && Object.keys(storage.sessionStorage).length > 0;
    return hasLS || hasSS;
  }

  function waitForNavigation(tabId, targetUrl) {
    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        browser.webNavigation.onCompleted.removeListener(listener);
        console.warn("[ChromiumBridge Gecko Companion] Navigation timeout — injecting storage anyway.");
        resolve();
      }, 15000);

      function listener(details) {
        if (details.tabId === tabId && details.frameId === 0) {
          clearTimeout(timeout);
          browser.webNavigation.onCompleted.removeListener(listener);
          // Small delay to ensure page scripts have initialized
          setTimeout(resolve, 300);
        }
      }

      browser.webNavigation.onCompleted.addListener(listener, {
        url: [{ urlPrefix: new URL(targetUrl).origin }],
      });
    });
  }

  async function injectStorage(tabId, storage) {
    const lsData = storage.localStorage || {};
    const ssData = storage.sessionStorage || {};
    const targetOrigin = storage.origin || null;

    // Build the injection code as a string with embedded data
    const injectionCode = `
      (function() {
        "use strict";
        var targetOrigin = ${JSON.stringify(targetOrigin)};
        var lsData = ${JSON.stringify(lsData)};
        var ssData = ${JSON.stringify(ssData)};

        // Validate origin if provided
        if (targetOrigin && window.location.origin !== targetOrigin) {
          console.warn("[ChromiumBridge] Origin mismatch: expected " + targetOrigin + ", got " + window.location.origin);
          return { localStorage: 0, sessionStorage: 0, error: "origin_mismatch" };
        }

        var lsCount = 0, ssCount = 0;

        // Inject localStorage
        try {
          var lsKeys = Object.keys(lsData);
          for (var i = 0; i < lsKeys.length; i++) {
            try {
              window.localStorage.setItem(lsKeys[i], lsData[lsKeys[i]]);
              lsCount++;
            } catch(e) { /* QuotaExceeded or SecurityError for individual item */ }
          }
        } catch(e) {
          console.warn("[ChromiumBridge] localStorage injection failed:", e.message);
        }

        // Inject sessionStorage
        try {
          var ssKeys = Object.keys(ssData);
          for (var i = 0; i < ssKeys.length; i++) {
            try {
              window.sessionStorage.setItem(ssKeys[i], ssData[ssKeys[i]]);
              ssCount++;
            } catch(e) { /* QuotaExceeded or SecurityError for individual item */ }
          }
        } catch(e) {
          console.warn("[ChromiumBridge] sessionStorage injection failed:", e.message);
        }

        console.log("[ChromiumBridge] Storage injected: " + lsCount + " localStorage, " + ssCount + " sessionStorage entries.");
        return { localStorage: lsCount, sessionStorage: ssCount };
      })();
    `;

    try {
      const results = await browser.tabs.executeScript(tabId, {
        code: injectionCode,
        runAt: "document_idle",
      });
      if (results && results[0]) {
        console.log("[ChromiumBridge Gecko Companion] Storage injection result:", results[0]);
      }
    } catch (err) {
      console.warn("[ChromiumBridge Gecko Companion] Storage injection failed:", err.message);
    }
  }

  // ── Handoff Active Marker ─────────────────────────────
  // Set by processHandoff so the return-button content script knows to show.

  async function setHandoffActive(targetUrl) {
    try {
      const hostname = new URL(targetUrl).hostname;
      await browser.storage.local.set({
        chromiumbridge_handoff_active: {
          domain: hostname,
          url: targetUrl,
          sourceBrowser: "Chromium",
          timestamp: Date.now(),
        },
      });
    } catch (err) {
      console.warn("[ChromiumBridge Gecko Companion] Could not set handoff marker:", err);
    }
  }

  async function clearHandoffActive() {
    try {
      await browser.storage.local.remove("chromiumbridge_handoff_active");
    } catch {}
  }

  // ── Message Handler ───────────────────────────────────

  browser.runtime.onMessage.addListener((message, sender) => {
    if (message.action === "closeTab" && sender.tab) {
      // Clear the handoff marker before closing
      clearHandoffActive().then(() => {
        browser.tabs.remove(sender.tab.id).catch(() => {});
      });
    }
  });
})();
