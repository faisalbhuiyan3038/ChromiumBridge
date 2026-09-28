/**
 * main.js — Background Service Worker for ChromiumBridge (Chromium to Gecko).
 * Orchestrates sending active tabs, cookies, and session data to Firefox-based browsers.
 */

const HOST_NAME = "chromiumbridge";

let _bridgeReady = false;
let _lastBridgeError = null;
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
    _lastBridgeError = null;
    _detectedGeckoBrowsers = response.gecko_browsers || response.browsers || [];
    console.log("[ChromiumBridge] Bridge is ready. Detected Gecko browsers:", _detectedGeckoBrowsers);
  } else {
    _bridgeReady = false;
    _lastBridgeError = response?.error || "Unable to connect to bridge host";
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

  // 1. Collect cookies for target URL and domain
  let cookies = [];
  if (settings.port_cookies !== false) {
    try {
      // Collect cookies for exact URL
      const urlCookies = await chrome.cookies.getAll({ url });
      const seen = new Set();
      for (const c of urlCookies) {
        const key = `${c.name}||${c.domain}||${c.path}`;
        if (!seen.has(key)) { seen.add(key); cookies.push(c); }
      }

      // Also collect for the naked domain (catches subdomain cookies)
      try {
        const parsed = new URL(url);
        const domainCookies = await chrome.cookies.getAll({ domain: parsed.hostname });
        for (const c of domainCookies) {
          const key = `${c.name}||${c.domain}||${c.path}`;
          if (!seen.has(key)) { seen.add(key); cookies.push(c); }
        }
      } catch (_) {}

      console.log(`[ChromiumBridge] Collected ${cookies.length} cookies for ${url}`);
      if (cookies.length === 0) {
        console.warn("[ChromiumBridge] No cookies found. The site may not be logged in, or Edge privacy settings block cookie access.");
      }
    } catch (err) {
      console.warn("[ChromiumBridge] Could not read cookies:", err);
    }
  }

  // 2. Collect localStorage & sessionStorage from content script with timeout
  let storageData = { localStorage: null, sessionStorage: null, origin: null };
  if (settings.port_localstorage !== false && tabId) {
    try {
      const storageResponse = await Promise.race([
        chrome.tabs.sendMessage(tabId, { action: "extractStorage" }),
        new Promise((_, reject) => setTimeout(() => reject(new Error("Storage extraction timed out")), 3000)),
      ]);
      if (storageResponse) {
        storageData.origin = storageResponse.origin || null;
        storageData.localStorage = storageResponse.localStorage || null;
        storageData.sessionStorage = storageResponse.sessionStorage || null;
        const lsKeys = storageData.localStorage ? Object.keys(storageData.localStorage).length : 0;
        const ssKeys = storageData.sessionStorage ? Object.keys(storageData.sessionStorage).length : 0;
        console.log(`[ChromiumBridge] Storage extracted: localStorage=${lsKeys} keys, sessionStorage=${ssKeys} keys`);
      }
    } catch (err) {
      console.warn("[ChromiumBridge] Could not extract storage data:", err.message);
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

  console.log(`[ChromiumBridge] Dispatching handoff to bridge. Cookies: ${cookies.length}, localStorage: ${storageData.localStorage ? Object.keys(storageData.localStorage).length : 0} keys`);
  const response = await sendNativeMessage(payload);

  _activeHandoffs.delete(tabId);

  if (response && (response.event === "launched" || response.event === "closed" || response.status === "ok")) {
    if (response.event === "launched") {
      // In companion mode: do NOT refocus Chromium window now!
      // Let Firefox keep the OS window focus.
      // Launch background listener waiting for "Back to Chromium" button click.
      let windowId = null;
      try {
        const tab = await chrome.tabs.get(tabId);
        windowId = tab?.windowId || null;
      } catch {}

      waitForReturn(domain, tabId, windowId);
      return { success: true, duration: response.duration };
    }

    // Legacy mode: Firefox process has fully exited
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

/**
 * Polls the bridge cookie server waiting for the user to click "Back to Chromium" in Firefox.
 * When triggered, refocuses the Chromium window/tab and displays the feedback/welcome banner.
 */
async function waitForReturn(domain, tabId, windowId) {
  console.log(`[ChromiumBridge] Starting return listener for domain=${domain}, tabId=${tabId}, windowId=${windowId}`);
  const maxAttempts = 75; // 75 * 4s = 300 seconds (5 min)

  for (let i = 0; i < maxAttempts; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:47831/wait-return?domain=${encodeURIComponent(domain || "")}&timeout=4`, {
        cache: "no-store",
      });
      if (!res.ok) {
        console.log("[ChromiumBridge] /wait-return returned HTTP", res.status);
        break;
      }
      const data = await res.json();
      if (data && data.returned) {
        console.log(`[ChromiumBridge] User returned from Firefox for domain: ${domain}`, data);

        // 1. Refocus window
        try {
          if (windowId) {
            await chrome.windows.update(windowId, { focused: true });
          }
        } catch (wErr) {
          console.warn("[ChromiumBridge] Could not refocus windowId:", wErr.message);
        }

        // 2. Refocus tab if still alive, otherwise pick active tab in window
        let targetTabId = tabId;
        try {
          const tab = await chrome.tabs.get(tabId);
          if (tab) {
            await chrome.tabs.update(tabId, { active: true });
          } else {
            throw new Error("Tab not found");
          }
        } catch {
          try {
            const queryOpts = windowId ? { active: true, windowId } : { active: true, currentWindow: true };
            const [activeTab] = await chrome.tabs.query(queryOpts);
            targetTabId = activeTab?.id || null;
          } catch {}
        }

        // 3. Display the feedback banner on the target tab
        if (targetTabId) {
          await triggerFeedbackBanner(targetTabId, data.domain || domain, data.duration);
        }
        break;
      }
    } catch (err) {
      // Normal when cookie server terminates or user closes Firefox window
      console.log("[ChromiumBridge] Return listener finished:", err.message);
      break;
    }
  }
}

/**
 * Triggers the welcome/feedback banner in the specified tab.
 * Attempts tabs.sendMessage first; if content script is missing or inactive,
 * injects banner.js and invokes the display function directly via scripting.
 */
async function triggerFeedbackBanner(tabId, domain, duration) {
  console.log(`[ChromiumBridge] Triggering feedback banner on tab ${tabId} for domain ${domain}`);

  try {
    const res = await chrome.tabs.sendMessage(tabId, {
      action: "showFeedbackPrompt",
      domain,
      duration,
    });
    if (res?.received) return;
  } catch (err) {
    console.log("[ChromiumBridge] tabs.sendMessage did not receive response, injecting banner.js...", err.message);
  }

  // Fallback: inject content/banner.js dynamically and invoke directly
  try {
    if (chrome.scripting) {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ["content/banner.js"],
      });
      await chrome.scripting.executeScript({
        target: { tabId },
        func: (dom, dur) => {
          if (typeof window.showChromiumBridgeFeedback === "function") {
            window.showChromiumBridgeFeedback(dom, dur);
          }
        },
        args: [domain, duration],
      });
      console.log("[ChromiumBridge] Feedback banner successfully injected via scripting API");
    }
  } catch (injectErr) {
    console.warn("[ChromiumBridge] Could not inject banner script into tab:", injectErr.message);
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
          lastError: _lastBridgeError,
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
          _bridgeReady = true;
          _lastBridgeError = null;
          _detectedGeckoBrowsers = result.gecko_browsers || result.browsers;
          return { browsers: _detectedGeckoBrowsers, bridgeReady: true };
        }
        _bridgeReady = false;
        _lastBridgeError = result?.error || "Detection failed";
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
