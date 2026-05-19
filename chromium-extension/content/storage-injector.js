/**
 * storage-injector.js — Injects localStorage and sessionStorage for ChromeBridge companion.
 * Runs as a content script at document_start in Chromium so storage is available
 * before page scripts execute.
 *
 * Storage data is fetched from the bridge's localhost cookie server (/storage endpoint)
 * or from inline injection (INJECTED_STORAGE placeholder replaced by bridge/cookies.py).
 */

(function () {
  "use strict";

  // Only run in top-level frames
  if (window !== window.top) return;

  const STORAGE_SERVER_URL = "http://127.0.0.1:47831/storage";
  const DONE_KEY = "_cb_storage_done";

  async function injectStorage() {
    // Check if already injected this session
    try {
      const s = await chrome.storage.session.get(DONE_KEY);
      if (s[DONE_KEY]) return;
    } catch { /* session storage unavailable */ }

    let storageData = null;

    // Try fetching from the bridge's localhost server
    try {
      const response = await fetch(STORAGE_SERVER_URL);
      if (response.ok) {
        storageData = await response.json();
      }
    } catch {
      // Server not available — no storage to inject
      return;
    }

    if (!storageData) return;

    const currentOrigin = window.location.origin;
    const targetOrigin = storageData.origin || "";

    // Only inject if we're on the correct origin
    if (targetOrigin && currentOrigin !== targetOrigin) return;

    // Inject localStorage
    if (storageData.localStorage && typeof storageData.localStorage === "object") {
      try {
        const entries = Object.entries(storageData.localStorage);
        for (const [key, value] of entries) {
          try {
            window.localStorage.setItem(key, value);
          } catch {
            // QuotaExceeded or SecurityError for individual item
          }
        }
        console.log(`[ChromeBridge Companion] Injected ${entries.length} localStorage entries.`);
      } catch (err) {
        console.warn("[ChromeBridge Companion] localStorage injection failed:", err.message);
      }
    }

    // Inject sessionStorage
    if (storageData.sessionStorage && typeof storageData.sessionStorage === "object") {
      try {
        const entries = Object.entries(storageData.sessionStorage);
        for (const [key, value] of entries) {
          try {
            window.sessionStorage.setItem(key, value);
          } catch {
            // QuotaExceeded or SecurityError for individual item
          }
        }
        console.log(`[ChromeBridge Companion] Injected ${entries.length} sessionStorage entries.`);
      } catch (err) {
        console.warn("[ChromeBridge Companion] sessionStorage injection failed:", err.message);
      }
    }

    // Mark done so we don't re-inject
    try {
      await chrome.storage.session.set({ [DONE_KEY]: true });
    } catch {}
  }

  // Run immediately at document_start
  injectStorage();
})();
