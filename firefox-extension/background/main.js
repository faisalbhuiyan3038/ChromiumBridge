/**
 * main.js — Background entry point for ChromeBridge.
 * Orchestrates handoff flow, context menus, and message routing.
 */

(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────
  let _bridgeReady = false;
  let _detectedBrowsers = [];
  let _activeHandoffs = new Map(); // tabId → { url, domain, startTime }

  // ── Initialization ─────────────────────────────────────
  async function init() {
    setupContextMenus();
    setupTabListeners();
    await checkBridgeHealth();
  }

  /**
   * Check bridge health on startup.
   */
  async function checkBridgeHealth() {
    const response = await NativeHost.ping();
    if (response && response.status === "ok") {
      _bridgeReady = true;
      _detectedBrowsers = response.browsers || [];
      console.log("[ChromeBridge] Bridge is ready. Browsers:", _detectedBrowsers);
    } else {
      _bridgeReady = false;
      _detectedBrowsers = [];
      console.warn("[ChromeBridge] Bridge not available:", response);
    }
  }

  // ── Context Menus ──────────────────────────────────────
  function setupContextMenus() {
    browser.contextMenus.create({
      id: "chromiumbridge-open-tab",
      title: "Open in Chromium",
      contexts: ["page"],
    });

    browser.contextMenus.create({
      id: "chromiumbridge-open-link",
      title: "Open Link in Chromium",
      contexts: ["link"],
    });

    browser.contextMenus.onClicked.addListener(async (info, tab) => {
      if (info.menuItemId === "chromiumbridge-open-tab") {
        await performHandoff(tab.id, tab.url);
      } else if (info.menuItemId === "chromiumbridge-open-link") {
        await performHandoff(tab.id, info.linkUrl);
      }
    });
  }

  // ── Tab Listeners ──────────────────────────────────────
  function setupTabListeners() {
    // Clean up signal state when tabs close
    browser.tabs.onRemoved.addListener((tabId) => {
      SignalManager.clearTab(tabId);
      _activeHandoffs.delete(tabId);
    });
  }

  // ── Core Handoff Flow ──────────────────────────────────
  /**
   * Perform the full handoff: collect data → send to bridge → wait for close → refocus.
   * @param {number} tabId - The Firefox tab ID.
   * @param {string} url - The URL to hand off.
   * @param {Object} [overrides] - Optional overrides for browser, mode, profile.
   */
  async function performHandoff(tabId, url, overrides = {}) {
    if (!_bridgeReady) {
      console.error("[ChromeBridge] Bridge not ready. Cannot hand off.");
      return { error: "Bridge not connected. Run the setup wizard from Options." };
    }

    // Validate URL
    if (!url || url.startsWith("about:") || url.startsWith("moz-extension:")) {
      return { error: "Cannot hand off internal browser pages." };
    }

    const domain = DomainRules.extractDomain(url);
    if (!domain) {
      return { error: "Could not extract domain from URL." };
    }

    // Check domain rules
    const ruleMatch = await DomainRules.matchDomain(url);
    const rule = ruleMatch ? ruleMatch.rule : {};

    // Determine handoff parameters (overrides > rule > defaults)
    const settings = await getSessionSettings();
    const browserTarget = overrides.browser || rule.browser || settings.default_browser || "chrome";
    const mode = overrides.mode || rule.mode || "popup";
    const profile = overrides.profile || rule.profile || settings.profile_mode || "ephemeral";
    const incognito = settings.incognito_passthrough || false;

    // Collect cookies for the target URL
    let cookies = [];
    if (settings.port_cookies !== false) {
      try {
        cookies = await browser.cookies.getAll({ url });
      } catch (err) {
        console.warn("[ChromeBridge] Could not read cookies:", err);
      }
    }

    // Collect localStorage and sessionStorage from the tab's content script
    let storageData = { localStorage: null, sessionStorage: null, origin: null };
    if (settings.port_localstorage !== false || settings.port_sessionstorage !== false) {
      try {
        const response = await browser.tabs.sendMessage(tabId, { action: "extractStorage" });
        if (response) {
          storageData.origin = response.origin || null;
          if (settings.port_localstorage !== false) {
            storageData.localStorage = response.localStorage || null;
          }
          if (settings.port_sessionstorage !== false) {
            storageData.sessionStorage = response.sessionStorage || null;
          }
        }
      } catch (err) {
        console.warn("[ChromeBridge] Could not extract storage data:", err);
      }
    }

    // Record in Firefox history
    if (settings.record_history !== false) {
      await TabManager.recordHandoff(url);
    }

    // Build the launch payload
    const payload = {
      action: "launch",
      url,
      domain,
      cookies,
      storage: storageData,
      browser: browserTarget,
      mode,
      profile,
      incognito: incognito && (await TabManager.getActiveTabInfo())?.isIncognito,
    };

    // Track this handoff
    _activeHandoffs.set(tabId, { url, domain, startTime: Date.now() });

    // Discard Firefox tab if option enabled
    if (settings.discard_firefox_tab) {
      await TabManager.discardTab(tabId);
    }

    // Send to bridge (this blocks until Chromium closes)
    console.log("[ChromeBridge] Launching handoff:", payload);
    const response = await NativeHost.sendMessage(payload);

    // Handle response
    _activeHandoffs.delete(tabId);

    if (response && response.event === "closed") {
      // Chromium session ended
      await TabManager.refocusTab(tabId);

      // Update history with close timestamp
      if (settings.record_history !== false) {
        await TabManager.recordHandoff(url);
      }

      // Show feedback prompt if domain not in rules
      if (!ruleMatch && settings.feedback_prompt !== false) {
        try {
          await browser.tabs.sendMessage(tabId, {
            action: "showFeedbackPrompt",
            domain,
            duration: response.duration,
          });
        } catch {
          // Tab might not be ready
        }
      }

      return { success: true, duration: response.duration };
    } else {
      console.error("[ChromeBridge] Handoff failed:", response);
      return { error: response?.error || "Handoff failed" };
    }
  }

  /**
   * Get session settings from storage.
   */
  async function getSessionSettings() {
    const result = await browser.storage.sync.get("sessionSettings");
    return result.sessionSettings || {
      default_browser: "chrome",
      profile_mode: "ephemeral",
      port_cookies: true,
      port_localstorage: true,
      cleanup_on_close: true,
      incognito_passthrough: true,
      discard_firefox_tab: false,
      record_history: true,
      feedback_prompt: true,
    };
  }

  // ── Message Router ─────────────────────────────────────
  browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
    const handler = async () => {
      switch (message.action) {
        // Popup requests
        case "getPopupData": {
          const tabInfo = await TabManager.getActiveTabInfo();
          const ruleMatch = tabInfo?.url ? await DomainRules.matchDomain(tabInfo.url) : null;
          const settings = await getSessionSettings();
          return {
            tabInfo,
            bridgeReady: _bridgeReady,
            browsers: _detectedBrowsers,
            currentRule: ruleMatch?.rule || null,
            settings,
          };
        }

        case "handoff": {
          return performHandoff(message.tabId, message.url, message.overrides || {});
        }

        case "saveRule": {
          await DomainRules.setRule(message.domain, message.rule);
          return { success: true };
        }

        case "deleteRule": {
          await DomainRules.deleteRule(message.domain);
          return { success: true };
        }

        case "getAllRules": {
          return DomainRules.getAllRules();
        }

        case "importRules": {
          const count = await DomainRules.importRules(message.rules);
          return { success: true, count };
        }

        case "exportRules": {
          return DomainRules.exportRules();
        }

        case "saveSessionSettings": {
          await browser.storage.sync.set({ sessionSettings: message.settings });
          // Also push persistent_profiles to bridge config so Python can resolve them
          if (message.settings.persistent_profiles) {
            try {
              await NativeHost.setConfig({
                session: {
                  persistent_profiles: message.settings.persistent_profiles,
                  persistent_profile_path: message.settings.persistent_profile_path || "",
                  profile_mode: message.settings.profile_mode || "ephemeral",
                },
              });
            } catch (err) {
              console.warn("[ChromeBridge] Could not sync persistent profiles to bridge:", err);
            }
          }
          return { success: true };
        }

        case "saveSignalSettings": {
          await SignalManager.saveSignalSettings(message.settings);
          return { success: true };
        }

        case "getSignalSettings": {
          return SignalManager.getSignalSettings();
        }

        case "refreshBridge": {
          await checkBridgeHealth();
          return { bridgeReady: _bridgeReady, browsers: _detectedBrowsers };
        }

        case "getBridgeConfig": {
          return NativeHost.getConfig();
        }

        case "setBridgeConfig": {
          return NativeHost.setConfig(message.config);
        }

        case "detectBrowsers": {
          const result = await NativeHost.detectBrowsers();
          if (result.browsers) _detectedBrowsers = result.browsers;
          return result;
        }

        case "reinstall": {
          return NativeHost.reinstall(message.pythonPath, message.bridgeDir);
        }

        case "detectProfiles": {
          return NativeHost.detectProfiles(message.browserId);
        }

        // Content script signals
        case "signal": {
          if (sender.tab) {
            await SignalManager.recordSignal(sender.tab.id, message.signal, message.domain);
          }
          return { received: true };
        }

        // Banner actions (from content script)
        case "bannerOpen": {
          if (sender.tab) {
            return performHandoff(sender.tab.id, sender.tab.url);
          }
          return { error: "No tab context" };
        }

        case "bannerAlways": {
          if (sender.tab) {
            const domain = DomainRules.extractDomain(sender.tab.url);
            if (domain) {
              await DomainRules.setRule(domain, { action: "always" });
            }
            return performHandoff(sender.tab.id, sender.tab.url);
          }
          return { error: "No tab context" };
        }

        default:
          return { error: "Unknown action: " + message.action };
      }
    };

    // Return true to indicate async response
    handler().then(sendResponse).catch((err) => {
      sendResponse({ error: err.message });
    });
    return true;
  });

  // ── Init ───────────────────────────────────────────────
  init();
})();
