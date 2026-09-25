/**
 * main.js — Background Service Worker for ChromiumBridge (Chromium to Gecko).
 * Orchestrates sending active tabs, cookies, and session data to Firefox-based browsers.
 */

const HOST_NAME = "chromiumbridge";

let _bridgeReady = false;
let _detectedGeckoBrowsers = [];
let _activeHandoffs = new Map();

// ── Native Messaging Wrapper ───────────────────────────
function sendNativeMessage(payload) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendNativeMessage(HOST_NAME, payload, (response) => {
        if (chrome.runtime.lastError) {
          resolve({ error: chrome.runtime.lastError.message });
        } else {
          resolve(response || { error: "Empty response from bridge" });
        }
      });
    } catch (err) {
      resolve({ error: err.message || "Failed to send native message" });
    }
  });
}

// ── Health Check ───────────────────────────────────────
async function checkBridgeHealth() {
  const response = await sendNativeMessage({ action: "ping", target_type: "gecko" });
  if (response && response.status === "ok") {
    _bridgeReady = true;
    _detectedGeckoBrowsers = response.gecko_browsers || response.browsers || [];
    console.log("[ChromiumBridge] Bridge is ready. Detected Gecko browsers:", _detectedGeckoBrowsers);
  } else {
    _bridgeReady = false;
    _detectedGeckoBrowsers = [];
    console.warn("[ChromiumBridge] Bridge not available:", response?.error || response);
  }
}

// ── Context Menus ──────────────────────────────────────
function setupContextMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "chromiumbridge-open-tab",
      title: "Open in Firefox",
      contexts: ["page"],
    });

    chrome.contextMenus.create({
      id: "chromiumbridge-open-link",
      title: "Open Link in Firefox",
      contexts: ["link"],
    });
  });

  chrome.contextMenus.onClicked.addListener(async (info, tab) => {
    if (info.menuItemId === "chromiumbridge-open-tab" && tab) {
      await performHandoff(tab.id, tab.url);
    } else if (info.menuItemId === "chromiumbridge-open-link" && tab) {
      await performHandoff(tab.id, info.linkUrl);
    }
  });
}

// ── Domain Rules ───────────────────────────────────────
function extractDomain(url) {
  try {
    const hostname = new URL(url).hostname;
    const parts = hostname.split(".");
    if (parts.length <= 2) return hostname;
    const doubleTLDs = ["co.uk", "com.au", "co.jp", "co.kr", "com.br", "co.in", "org.uk"];
    const lastTwo = parts.slice(-2).join(".");
    if (doubleTLDs.includes(lastTwo)) {
      return parts.slice(-3).join(".");
    }
    return parts.slice(-2).join(".");
  } catch {
    return null;
  }
}

async function getStoredRules() {
  const data = await chrome.storage.sync.get("domainRules");
  return data.domainRules || {};
}

async function matchDomainRule(url) {
  const domain = extractDomain(url);
  if (!domain) return null;

  const rules = await getStoredRules();
  if (rules[domain]) {
    return { domain, rule: rules[domain] };
  }

  const hostname = new URL(url).hostname;
  for (const ruleDomain of Object.keys(rules)) {
    if (hostname === ruleDomain || hostname.endsWith("." + ruleDomain)) {
      return { domain: ruleDomain, rule: rules[ruleDomain] };
    }
  }
  return null;
}

// ── Session Settings ───────────────────────────────────
async function getSessionSettings() {
  const result = await chrome.storage.sync.get("sessionSettings");
  return result.sessionSettings || {
    default_browser: "firefox",
    profile_mode: "ephemeral",
    window_mode: "normal",
    port_cookies: true,
    port_localstorage: true,
    incognito_passthrough: true,
    record_history: true,
  };
}

// ── Core Handoff Flow ──────────────────────────────────
async function performHandoff(tabId, url, overrides = {}) {
  await checkBridgeHealth();

  if (!_bridgeReady) {
    return { error: "Bridge not connected. Please run 'python install.py' in the bridge directory." };
  }

  if (!url || url.startsWith("chrome://") || url.startsWith("chrome-extension://") || url.startsWith("edge://")) {
    return { error: "Cannot hand off internal browser pages." };
  }

  const domain = extractDomain(url);
  if (!domain) {
    return { error: "Could not extract domain from URL." };
  }

  const ruleMatch = await matchDomainRule(url);
  const rule = ruleMatch ? ruleMatch.rule : {};
  const settings = await getSessionSettings();

  const browserTarget = overrides.browser || rule.browser || settings.default_browser || "firefox";
  const mode = overrides.mode || rule.mode || settings.window_mode || "normal";
  const profile = overrides.profile || rule.profile || settings.profile_mode || "ephemeral";

  // 1. Collect cookies for target URL
  let cookies = [];
  if (settings.port_cookies !== false) {
    try {
      cookies = await chrome.cookies.getAll({ url });
    } catch (err) {
      console.warn("[ChromiumBridge] Could not read cookies:", err);
    }
  }

  // 2. Collect localStorage & sessionStorage from content script
  let storageData = { localStorage: null, sessionStorage: null, origin: null };
  if (settings.port_localstorage !== false && tabId) {
    try {
      const response = await chrome.tabs.sendMessage(tabId, { action: "extractStorage" });
      if (response) {
        storageData.origin = response.origin || null;
        storageData.localStorage = response.localStorage || null;
        storageData.sessionStorage = response.sessionStorage || null;
      }
    } catch (err) {
      console.warn("[ChromiumBridge] Could not extract storage data:", err);
    }
  }

  // 3. Check incognito state
  let isIncognito = false;
  try {
    const tab = await chrome.tabs.get(tabId);
    isIncognito = Boolean(tab?.incognito);
  } catch {}

  // 4. Build payload
  const payload = {
    action: "launch",
    url,
    domain,
    cookies,
    storage: storageData,
    browser: browserTarget,
    mode,
    profile,
    incognito: settings.incognito_passthrough && isIncognito,
  };

  _activeHandoffs.set(tabId, { url, domain, startTime: Date.now() });

  console.log("[ChromiumBridge] Dispatching handoff to bridge:", payload);
  const response = await sendNativeMessage(payload);

  _activeHandoffs.delete(tabId);

  if (response && response.event === "closed") {
    // Refocus original Chromium window/tab
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab) {
        await chrome.tabs.update(tabId, { active: true });
        await chrome.windows.update(tab.windowId, { focused: true });
      }
    } catch {}

    return { success: true, duration: response.duration };
  } else {
    console.error("[ChromiumBridge] Handoff failed:", response);
    return { error: response?.error || "Handoff failed" };
  }
}

// ── Message Router ─────────────────────────────────────
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const handle = async () => {
    switch (message.action) {
      case "getPopupData": {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        const ruleMatch = tab?.url ? await matchDomainRule(tab.url) : null;
        const settings = await getSessionSettings();
        await checkBridgeHealth();

        return {
          tabInfo: tab ? { tabId: tab.id, url: tab.url, domain: extractDomain(tab.url) } : null,
          bridgeReady: _bridgeReady,
          browsers: _detectedGeckoBrowsers,
          currentRule: ruleMatch?.rule || null,
          settings,
        };
      }

      case "handoff": {
        return performHandoff(message.tabId, message.url, message.overrides || {});
      }

      case "detectBrowsers": {
        const result = await sendNativeMessage({ action: "detect", target_type: "gecko" });
        if (result && (result.gecko_browsers || result.browsers)) {
          _detectedGeckoBrowsers = result.gecko_browsers || result.browsers;
          return { browsers: _detectedGeckoBrowsers };
        }
        return result;
      }

      case "detectProfiles": {
        return sendNativeMessage({ action: "detect_profiles", browser_id: message.browserId });
      }

      case "saveRule": {
        const rules = await getStoredRules();
        rules[message.domain] = { ...message.rule, updatedAt: Date.now() };
        await chrome.storage.sync.set({ domainRules: rules });
        return { success: true };
      }

      case "deleteRule": {
        const rules = await getStoredRules();
        delete rules[message.domain];
        await chrome.storage.sync.set({ domainRules: rules });
        return { success: true };
      }

      case "getAllRules": {
        return getStoredRules();
      }

      case "importRules": {
        const rules = await getStoredRules();
        let count = 0;
        for (const [dom, r] of Object.entries(message.rules || {})) {
          rules[dom] = { ...r, updatedAt: Date.now() };
          count++;
        }
        await chrome.storage.sync.set({ domainRules: rules });
        return { success: true, count };
      }

      case "exportRules": {
        return getStoredRules();
      }

      case "saveSessionSettings": {
        await chrome.storage.sync.set({ sessionSettings: message.settings });
        return { success: true };
      }

      case "getBridgeConfig": {
        return sendNativeMessage({ action: "config_get" });
      }

      case "setBridgeConfig": {
        return sendNativeMessage({ action: "config_set", config: message.config });
      }

      case "reinstall": {
        return sendNativeMessage({
          action: "reinstall",
          python_path: message.pythonPath,
          bridge_dir: message.bridgeDir,
        });
      }

      default:
        return { error: "Unknown action: " + message.action };
    }
  };

  handle().then(sendResponse).catch((err) => sendResponse({ error: err.message }));
  return true;
});

// ── Startup & Init ─────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  setupContextMenus();
  checkBridgeHealth();
});

chrome.runtime.onStartup.addListener(() => {
  checkBridgeHealth();
});

setupContextMenus();
checkBridgeHealth();
