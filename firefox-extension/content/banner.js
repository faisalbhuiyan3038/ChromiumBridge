/**
 * banner.js — Suggestion banner for ChromeBridge.
 * Injects a non-intrusive banner when a signal is detected.
 * Uses Shadow DOM for style isolation.
 */

(function () {
  "use strict";

  // Avoid running in iframes
  if (window !== window.top) return;

  // Only show one banner per page load
  let _bannerShown = false;

  const SIGNAL_MESSAGES = {
    drm: "🔒 DRM content detected — this may work better in Chromium",
    hls: "📺 HLS stream detected — Chromium may offer better playback",
    buffering: "⏳ Repeated buffering detected — try Chromium for smoother playback",
    securityError: "⚠️ Cross-origin restrictions detected — Chromium may handle this better",
  };

  // ── Message Listener ───────────────────────────────
  browser.runtime.onMessage.addListener((message) => {
    if (message.action === "showBanner" && !_bannerShown) {
      _bannerShown = true;
      showBanner(message.signal, message.domain);
    }

    if (message.action === "showFeedbackPrompt") {
      showFeedbackBanner(message.domain, message.duration);
    }
  });

  // ── Banner Creation ────────────────────────────────
  function showBanner(signal, domain) {
    const host = document.createElement("chromiumbridge-banner");
    const shadow = host.attachShadow({ mode: "closed" });

    shadow.innerHTML = `
      <style>${getBannerStyles()}</style>
      <div class="cb-banner" id="cb-banner">
        <div class="cb-accent"></div>
        <div class="cb-content">
          <span class="cb-message">${SIGNAL_MESSAGES[signal] || "ChromeBridge suggestion"}</span>
          <div class="cb-actions">
            <button class="cb-btn cb-btn-primary" id="cb-open">Open in Chromium</button>
            <button class="cb-btn cb-btn-secondary" id="cb-always">Always for this site</button>
            <button class="cb-btn cb-btn-ghost" id="cb-dismiss">Dismiss</button>
          </div>
        </div>
        <button class="cb-close" id="cb-close">✕</button>
      </div>
    `;

    document.documentElement.appendChild(host);

    // Trigger animation
    requestAnimationFrame(() => {
      const banner = shadow.getElementById("cb-banner");
      if (banner) banner.classList.add("visible");
    });

    // Event handlers
    shadow.getElementById("cb-open").addEventListener("click", () => {
      browser.runtime.sendMessage({ action: "bannerOpen" });
      removeBanner(host, shadow);
    });

    shadow.getElementById("cb-always").addEventListener("click", () => {
      browser.runtime.sendMessage({ action: "bannerAlways", domain });
      removeBanner(host, shadow);
    });

    shadow.getElementById("cb-dismiss").addEventListener("click", () => {
      removeBanner(host, shadow);
    });

    shadow.getElementById("cb-close").addEventListener("click", () => {
      removeBanner(host, shadow);
    });
  }

  // ── Feedback Banner (after Chromium closes) ────────
  function showFeedbackBanner(domain, duration) {
    const host = document.createElement("chromiumbridge-feedback");
    const shadow = host.attachShadow({ mode: "closed" });

    const durationText = duration ? `(${Math.round(duration / 1000)}s session)` : "";

    shadow.innerHTML = `
      <style>${getBannerStyles()}</style>
      <div class="cb-banner" id="cb-banner">
        <div class="cb-accent"></div>
        <div class="cb-content">
          <span class="cb-message">Welcome back! Always open <strong>${domain}</strong> in Chromium? ${durationText}</span>
          <div class="cb-actions">
            <button class="cb-btn cb-btn-primary" id="cb-yes">Yes, always</button>
            <button class="cb-btn cb-btn-ghost" id="cb-no">Not now</button>
          </div>
        </div>
        <button class="cb-close" id="cb-close">✕</button>
      </div>
    `;

    document.documentElement.appendChild(host);

    requestAnimationFrame(() => {
      const banner = shadow.getElementById("cb-banner");
      if (banner) banner.classList.add("visible");
    });

    shadow.getElementById("cb-yes").addEventListener("click", () => {
      browser.runtime.sendMessage({
        action: "saveRule",
        domain,
        rule: { action: "always" },
      });
      removeBanner(host, shadow);
    });

    shadow.getElementById("cb-no").addEventListener("click", () => {
      removeBanner(host, shadow);
    });

    shadow.getElementById("cb-close").addEventListener("click", () => {
      removeBanner(host, shadow);
    });

    // Auto-dismiss after 8 seconds
    setTimeout(() => {
      if (host.isConnected) removeBanner(host, shadow);
    }, 8000);
  }

  // ── Remove Banner ──────────────────────────────────
  function removeBanner(host, shadow) {
    const banner = shadow.getElementById("cb-banner");
    if (banner) {
      banner.classList.remove("visible");
      banner.classList.add("hiding");
      setTimeout(() => host.remove(), 300);
    } else {
      host.remove();
    }
  }

  // ── Banner Styles ──────────────────────────────────
  function getBannerStyles() {
    return `
      :host {
        all: initial;
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 2147483647;
        font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }

      .cb-banner {
        display: flex;
        align-items: center;
        background: #FFFFFF;
        border-bottom: 1px solid #E5E8EB;
        box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
        padding: 0;
        transform: translateY(-100%);
        transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
      }

      .cb-banner.visible {
        transform: translateY(0);
      }

      .cb-banner.hiding {
        transform: translateY(-100%);
      }

      .cb-accent {
        width: 4px;
        align-self: stretch;
        background: #00A76F;
        flex-shrink: 0;
      }

      .cb-content {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 12px 16px;
        flex: 1;
        flex-wrap: wrap;
      }

      .cb-message {
        font-size: 13px;
        color: #212B36;
        line-height: 1.5;
        flex: 1;
        min-width: 200px;
      }

      .cb-message strong {
        font-weight: 600;
      }

      .cb-actions {
        display: flex;
        gap: 8px;
        flex-shrink: 0;
      }

      .cb-btn {
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 600;
        font-family: inherit;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        transition: all 150ms ease;
        white-space: nowrap;
      }

      .cb-btn-primary {
        color: #fff;
        background: #00A76F;
      }

      .cb-btn-primary:hover {
        background: #007867;
      }

      .cb-btn-secondary {
        color: #004B50;
        background: #C8FAD6;
      }

      .cb-btn-secondary:hover {
        background: #5BE49B;
      }

      .cb-btn-ghost {
        color: #637381;
        background: transparent;
      }

      .cb-btn-ghost:hover {
        color: #212B36;
        background: #F4F6F8;
      }

      .cb-close {
        position: absolute;
        top: 50%;
        right: 12px;
        transform: translateY(-50%);
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        color: #919EAB;
        background: none;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        transition: all 150ms ease;
      }

      .cb-close:hover {
        color: #212B36;
        background: #F4F6F8;
      }
    `;
  }
})();
