/**
 * detector.js — Content script for smart signal detection.
 * Monitors DRM, HLS, buffering, and security errors.
 * Each detector is individually toggleable via settings.
 * All detectors are disabled by default.
 */

(function () {
  "use strict";

  // Avoid running in iframes
  if (window !== window.top) return;

  let _settings = {
    drm_detection: false,
    hls_detection: false,
    buffering_detection: false,
    security_error_detection: false,
    buffering_threshold: 3,
  };

  let _activeDetectors = new Set();
  let _domain = "";

  try {
    _domain = window.location.hostname;
  } catch {
    return;
  }

  // ── Settings Loader ────────────────────────────────
  async function loadSettings() {
    try {
      const result = await browser.storage.sync.get("signalSettings");
      if (result.signalSettings) {
        _settings = { ..._settings, ...result.signalSettings };
      }
    } catch {
      // Storage not available, stay disabled
    }
    startDetectors();
  }

  // Listen for settings changes in real-time
  browser.storage.onChanged.addListener((changes, area) => {
    if (area === "sync" && changes.signalSettings) {
      _settings = { ..._settings, ...changes.signalSettings.newValue };
      stopDetectors();
      startDetectors();
    }
  });

  // ── Detector Management ────────────────────────────
  function startDetectors() {
    if (_settings.drm_detection && !_activeDetectors.has("drm")) {
      startDRMDetector();
      _activeDetectors.add("drm");
    }
    if (_settings.hls_detection && !_activeDetectors.has("hls")) {
      startHLSDetector();
      _activeDetectors.add("hls");
    }
    if (_settings.buffering_detection && !_activeDetectors.has("buffering")) {
      startBufferingDetector();
      _activeDetectors.add("buffering");
    }
    if (_settings.security_error_detection && !_activeDetectors.has("securityError")) {
      startSecurityErrorDetector();
      _activeDetectors.add("securityError");
    }
  }

  function stopDetectors() {
    // Detectors use passive listeners that are safe to leave running,
    // but we track state so we don't double-attach.
    // For prototype wrapping (DRM), it's a one-time operation.
  }

  // ── Signal Reporter ────────────────────────────────
  function reportSignal(signal) {
    try {
      browser.runtime.sendMessage({
        action: "signal",
        signal,
        domain: _domain,
      });
    } catch {
      // Extension context invalidated
    }
  }

  // ── DRM / Widevine Detector ────────────────────────
  function startDRMDetector() {
    if (!navigator.requestMediaKeySystemAccess) return;

    const original = navigator.requestMediaKeySystemAccess.bind(navigator);
    navigator.requestMediaKeySystemAccess = function (keySystem, configs) {
      console.log("[ChromeBridge] DRM request detected:", keySystem);
      reportSignal("drm");
      return original(keySystem, configs);
    };
  }

  // ── HLS / m3u8 Detector ───────────────────────────
  function startHLSDetector() {
    // Monitor fetch for .m3u8
    const originalFetch = window.fetch;
    window.fetch = function (...args) {
      const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
      if (url.includes(".m3u8")) {
        console.log("[ChromeBridge] HLS stream detected (fetch):", url);
        reportSignal("hls");
      }
      return originalFetch.apply(this, args);
    };

    // Monitor XMLHttpRequest for .m3u8
    const originalOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      if (typeof url === "string" && url.includes(".m3u8")) {
        console.log("[ChromeBridge] HLS stream detected (XHR):", url);
        reportSignal("hls");
      }
      return originalOpen.call(this, method, url, ...rest);
    };

    // Monitor <source> elements with .m3u8
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType !== 1) continue;
          const sources = node.tagName === "SOURCE" ? [node] : node.querySelectorAll?.("source") || [];
          for (const source of sources) {
            const src = source.getAttribute("src") || "";
            if (src.includes(".m3u8")) {
              console.log("[ChromeBridge] HLS stream detected (DOM):", src);
              reportSignal("hls");
            }
          }
        }
      }
    });

    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  // ── Buffering Detector ─────────────────────────────
  function startBufferingDetector() {
    let bufferCount = 0;

    const checkVideos = () => {
      document.querySelectorAll("video").forEach((video) => {
        if (video._chromeBridgeBufferListener) return;
        video._chromeBridgeBufferListener = true;

        video.addEventListener("waiting", () => {
          bufferCount++;
          if (bufferCount >= (_settings.buffering_threshold || 3)) {
            console.log("[ChromeBridge] Buffering threshold reached:", bufferCount);
            reportSignal("buffering");
          }
        });
      });
    };

    // Check existing and watch for new video elements
    checkVideos();
    const observer = new MutationObserver(() => checkVideos());
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  // ── Security Error Detector ────────────────────────
  function startSecurityErrorDetector() {
    window.addEventListener("error", (event) => {
      const msg = event.message || "";
      if (
        msg.includes("SecurityError") ||
        msg.includes("Blocked a frame") ||
        msg.includes("cross-origin")
      ) {
        console.log("[ChromeBridge] SecurityError detected:", msg);
        reportSignal("securityError");
      }
    });
  }

  // ── Start ──────────────────────────────────────────
  loadSettings();
})();
