/**
 * tabs.js — Tab lifecycle management for ChromeBridge.
 * Handles tab info retrieval, focus management, and history recording.
 */

const TabManager = (() => {
  /**
   * Get information about the currently active tab.
   * @returns {Promise<{tabId: number, url: string, domain: string, isIncognito: boolean, title: string}>}
   */
  async function getActiveTabInfo() {
    const tabs = await browser.tabs.query({ active: true, currentWindow: true });
    if (!tabs || tabs.length === 0) {
      return null;
    }

    const tab = tabs[0];
    let domain = null;
    try {
      domain = new URL(tab.url).hostname;
    } catch {
      // about:, moz-extension:, etc.
    }

    return {
      tabId: tab.id,
      url: tab.url,
      domain,
      isIncognito: tab.incognito,
      title: tab.title || "",
    };
  }

  /**
   * Refocus a Firefox tab (bring it to front) after Chromium session closes.
   * @param {number} tabId
   */
  async function refocusTab(tabId) {
    try {
      const tab = await browser.tabs.get(tabId);
      if (tab) {
        await browser.tabs.update(tabId, { active: true });
        await browser.windows.update(tab.windowId, { focused: true });
      }
    } catch (err) {
      console.warn("[ChromeBridge] Could not refocus tab:", err);
    }
  }

  /**
   * Discard a tab to free memory (if supported).
   * @param {number} tabId
   */
  async function discardTab(tabId) {
    try {
      if (browser.tabs.discard) {
        await browser.tabs.discard(tabId);
      }
    } catch (err) {
      console.warn("[ChromeBridge] Could not discard tab:", err);
    }
  }

  /**
   * Record a URL in Firefox history so it appears in address bar autocomplete.
   * @param {string} url
   */
  async function recordHandoff(url) {
    try {
      await browser.history.addUrl({ url });
    } catch (err) {
      console.warn("[ChromeBridge] Could not record history:", err);
    }
  }

  return {
    getActiveTabInfo,
    refocusTab,
    discardTab,
    recordHandoff,
  };
})();
