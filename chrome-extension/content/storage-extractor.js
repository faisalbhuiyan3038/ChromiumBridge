/**
 * storage-extractor.js — Content script for ChromeBridge Chromium extension.
 * Extracts localStorage and sessionStorage for the active page when requested by main.js.
 */

(function () {
  "use strict";

  if (window !== window.top) return;

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.action !== "extractStorage") return;

    const result = {
      origin: window.location.origin,
      localStorage: null,
      sessionStorage: null,
    };

    try {
      if (window.localStorage && window.localStorage.length > 0) {
        const lsData = {};
        for (let i = 0; i < window.localStorage.length; i++) {
          const key = window.localStorage.key(i);
          lsData[key] = window.localStorage.getItem(key);
        }
        result.localStorage = lsData;
      }
    } catch (err) {
      console.warn("[ChromiumBridge] Could not read localStorage:", err.message);
    }

    try {
      if (window.sessionStorage && window.sessionStorage.length > 0) {
        const ssData = {};
        for (let i = 0; i < window.sessionStorage.length; i++) {
          const key = window.sessionStorage.key(i);
          ssData[key] = window.sessionStorage.getItem(key);
        }
        result.sessionStorage = ssData;
      }
    } catch (err) {
      console.warn("[ChromiumBridge] Could not read sessionStorage:", err.message);
    }

    sendResponse(result);
  });
})();
