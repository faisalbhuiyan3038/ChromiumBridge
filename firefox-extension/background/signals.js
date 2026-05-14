/**
 * signals.js — Signal aggregation for ChromeBridge.
 * Collects detection signals from content scripts (DRM, HLS, buffering, errors)
 * and manages badge state + banner trigger logic.
 */

const SignalManager = (() => {
  // Per-tab signal state: tabId → { drm: count, hls: count, buffering: count, securityError: count }
  const _tabSignals = new Map();

  // Domains already suggested this browser session (avoid repeat nagging)
  const _suggestedDomains = new Set();

  // Badge color matching the primary-main palette
  const BADGE_COLOR = "#00A76F";

  /**
   * Get the current signal settings (which detectors are enabled).
   * @returns {Promise<Object>}
   */
  async function getSignalSettings() {
    const result = await browser.storage.sync.get("signalSettings");
    return result.signalSettings || {
      drm_detection: false,
      hls_detection: false,
      buffering_detection: false,
      security_error_detection: false,
      buffering_threshold: 3,
      perf_longtask_threshold: 5,
    };
  }

  /**
   * Save signal settings.
   * @param {Object} settings
   */
  async function saveSignalSettings(settings) {
    await browser.storage.sync.set({ signalSettings: settings });
  }

  /**
   * Record a signal from a content script.
   * @param {number} tabId
   * @param {string} signal - "drm", "hls", "buffering", "securityError"
   * @param {string} domain
   */
  async function recordSignal(tabId, signal, domain) {
    const settings = await getSignalSettings();

    // Check if this signal type is enabled
    const signalToSetting = {
      drm: "drm_detection",
      hls: "hls_detection",
      buffering: "buffering_detection",
      securityError: "security_error_detection",
    };
    const settingKey = signalToSetting[signal];
    if (!settingKey || !settings[settingKey]) {
      return; // Signal type is disabled
    }

    // Initialize tab signal tracking
    if (!_tabSignals.has(tabId)) {
      _tabSignals.set(tabId, { drm: 0, hls: 0, buffering: 0, securityError: 0 });
    }
    const tabState = _tabSignals.get(tabId);
    tabState[signal] = (tabState[signal] || 0) + 1;

    // Check if threshold is met
    let thresholdMet = false;
    if (signal === "drm" || signal === "hls" || signal === "securityError") {
      thresholdMet = tabState[signal] >= 1; // Single detection is enough
    } else if (signal === "buffering") {
      thresholdMet = tabState[signal] >= (settings.buffering_threshold || 3);
    }

    if (thresholdMet && !_suggestedDomains.has(domain)) {
      _suggestedDomains.add(domain);
      await showBadge(tabId);
      await triggerBanner(tabId, signal, domain);
    }
  }

  /**
   * Set the toolbar badge to indicate a signal was detected.
   * @param {number} tabId
   */
  async function showBadge(tabId) {
    await browser.browserAction.setBadgeText({ text: "!", tabId });
    await browser.browserAction.setBadgeBackgroundColor({ color: BADGE_COLOR, tabId });
  }

  /**
   * Clear the toolbar badge for a tab.
   * @param {number} tabId
   */
  async function clearBadge(tabId) {
    await browser.browserAction.setBadgeText({ text: "", tabId });
  }

  /**
   * Send a message to the content script to show the suggestion banner.
   * @param {number} tabId
   * @param {string} signal
   * @param {string} domain
   */
  async function triggerBanner(tabId, signal, domain) {
    try {
      await browser.tabs.sendMessage(tabId, {
        action: "showBanner",
        signal,
        domain,
      });
    } catch (err) {
      console.warn("[ChromeBridge] Could not trigger banner:", err);
    }
  }

  /**
   * Clean up signal state when a tab is closed.
   * @param {number} tabId
   */
  function clearTab(tabId) {
    _tabSignals.delete(tabId);
  }

  /**
   * Reset all signal state (e.g., on extension restart).
   */
  function resetAll() {
    _tabSignals.clear();
    _suggestedDomains.clear();
  }

  return {
    getSignalSettings,
    saveSignalSettings,
    recordSignal,
    showBadge,
    clearBadge,
    clearTab,
    resetAll,
  };
})();
