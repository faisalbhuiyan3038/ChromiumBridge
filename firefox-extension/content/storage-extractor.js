/**
 * storage-extractor.js — Extracts localStorage and sessionStorage for ChromeBridge handoff.
 * Runs as a content script in Firefox. Responds to "extractStorage" messages
 * from the background script with serialized storage data for the current origin.
 */

(function () {
  "use strict";

  // Only run in top-level frames
  if (window !== window.top) return;

  browser.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.action !== "extractStorage") return;

    const result = { localStorage: null, sessionStorage: null, origin: window.location.origin };

    // Extract localStorage
    try {
      if (window.localStorage && window.localStorage.length > 0) {
        const data = {};
        for (let i = 0; i < window.localStorage.length; i++) {
          const key = window.localStorage.key(i);
          data[key] = window.localStorage.getItem(key);
        }
        result.localStorage = data;
      }
    } catch (err) {
      // SecurityError if blocked by privacy settings
      console.warn("[ChromeBridge] Could not read localStorage:", err.message);
    }

    // Extract sessionStorage
    try {
      if (window.sessionStorage && window.sessionStorage.length > 0) {
        const data = {};
        for (let i = 0; i < window.sessionStorage.length; i++) {
          const key = window.sessionStorage.key(i);
          data[key] = window.sessionStorage.getItem(key);
        }
        result.sessionStorage = data;
      }
    } catch (err) {
      console.warn("[ChromeBridge] Could not read sessionStorage:", err.message);
    }

    sendResponse(result);
  });
})();
