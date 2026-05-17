/**
 * return-button.js — Floating "Back to Firefox" button for ChromeBridge companion.
 * Injected into all pages in Chromium sessions launched by ChromeBridge.
 * Uses Shadow DOM for complete style isolation.
 */

(function () {
  "use strict";

  // Don't inject in iframes
  if (window !== window.top) return;

  const DISMISS_KEY = "chromiumbridge_return_dismissed";

  // Check if dismissed for this domain
  const domain = window.location.hostname;

  chrome.storage.local.get(DISMISS_KEY, (result) => {
    const dismissed = result[DISMISS_KEY] || {};
    if (dismissed[domain]) return;

    createReturnButton();
  });

  function createReturnButton() {
    const host = document.createElement("chromiumbridge-return");
    const shadow = host.attachShadow({ mode: "closed" });

    shadow.innerHTML = `
      <style>
        :host {
          all: initial;
          position: fixed;
          bottom: 24px;
          right: 24px;
          z-index: 2147483647;
          font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }

        .return-container {
          display: flex;
          align-items: center;
          gap: 0;
          opacity: 0;
          transform: translateY(12px);
          animation: slideIn 0.4s cubic-bezier(0.4, 0, 0.2, 1) 1s forwards;
        }

        @keyframes slideIn {
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .return-btn {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 18px;
          background: #FFFFFF;
          color: #004B50;
          border: 1px solid #E5E8EB;
          border-radius: 24px;
          font-size: 13px;
          font-weight: 600;
          font-family: inherit;
          cursor: pointer;
          box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
          transition: all 200ms ease;
          white-space: nowrap;
        }

        .return-btn:hover {
          background: #004B50;
          color: #FFFFFF;
          border-color: #004B50;
          box-shadow: 0 4px 20px rgba(0, 75, 80, 0.25);
          transform: scale(1.03);
        }

        .return-btn:active {
          transform: scale(0.98);
        }

        .return-icon {
          font-size: 14px;
        }

        .dismiss-btn {
          width: 20px;
          height: 20px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #F4F6F8;
          color: #919EAB;
          border: 1px solid #E5E8EB;
          border-radius: 50%;
          font-size: 10px;
          cursor: pointer;
          margin-left: -6px;
          margin-top: -20px;
          transition: all 150ms ease;
          position: relative;
          z-index: 1;
        }

        .dismiss-btn:hover {
          background: #FF5630;
          color: #fff;
          border-color: #FF5630;
        }
      </style>

      <div class="return-container">
        <button class="return-btn" id="return-btn">
          <span class="return-icon">🦊</span>
          Back to Firefox
        </button>
        <button class="dismiss-btn" id="dismiss-btn" title="Don't show on this site">✕</button>
      </div>
    `;

    document.documentElement.appendChild(host);

    shadow.getElementById("return-btn").addEventListener("click", () => {
      window.close();
    });

    shadow.getElementById("dismiss-btn").addEventListener("click", () => {
      // Remember dismissal for this domain
      chrome.storage.local.get(DISMISS_KEY, (result) => {
        const dismissed = result[DISMISS_KEY] || {};
        dismissed[domain] = true;
        chrome.storage.local.set({ [DISMISS_KEY]: dismissed });
      });
      host.remove();
    });
  }
})();
