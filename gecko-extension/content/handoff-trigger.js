/**
 * handoff-trigger.js — Instant handoff trigger content script for Gecko Companion.
 * Injected at document_start into http://127.0.0.1:47831/handoff*
 * Immediately notifies the background script so cold starts never miss the navigation event.
 */

(function () {
  "use strict";

  if (window !== window.top) return;

  function notifyBackground() {
    try {
      browser.runtime.sendMessage({
        action: "handoffTrigger",
        url: window.location.href,
      }).catch((err) => {
        console.warn("[ChromiumBridge Gecko Companion] Trigger message failed:", err.message);
      });
    } catch (_) {}
  }

  // Notify immediately at document_start
  notifyBackground();

  // Re-notify at DOMContentLoaded in case background script was still initializing
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", notifyBackground, { once: true });
  }
})();
