/**
 * popup.js — ChromeBridge popup logic.
 * Handles UI state, bridge communication, and user interactions.
 * Persists the last-used browser, mode, and profile to browser.storage.local.
 */

(function () {
  "use strict";

  const POPUP_STATE_KEY = "popupLastState";

  // ── DOM References ─────────────────────────────────
  const statusDot = document.getElementById("status-dot");
  const statusLabel = document.getElementById("status-label");
  const stateOffline = document.getElementById("state-offline");
  const stateReady = document.getElementById("state-ready");
  const domainValue = document.getElementById("domain-value");
  const browserSelect = document.getElementById("browser-select");
  const modeControl = document.getElementById("mode-control");
  const profileControl = document.getElementById("profile-control");
  const btnLaunch = document.getElementById("btn-launch");
  const btnSetup = document.getElementById("btn-setup");
  const chkAlways = document.getElementById("chk-always");
  const alwaysRow = document.getElementById("always-row");
  const handoffStatus = document.getElementById("handoff-status");
  const linkOptions = document.getElementById("link-options");
  const linkHelp = document.getElementById("link-help");

  // ── State ──────────────────────────────────────────
  let _popupData = null;
  let _selectedMode = "popup";
  let _selectedProfile = "ephemeral";
  let _isHandingOff = false;

  // ── Init ───────────────────────────────────────────
  async function init() {
    try {
      _popupData = await browser.runtime.sendMessage({ action: "getPopupData" });
    } catch (err) {
      console.error("[ChromeBridge Popup] Failed to get data:", err);
      showOffline();
      return;
    }

    if (_popupData.bridgeReady) {
      showReady();
    } else {
      showOffline();
    }

    setupEventListeners();
  }

  function showOffline() {
    statusDot.className = "status-dot offline";
    statusLabel.textContent = "Offline";
    stateOffline.hidden = false;
    stateReady.hidden = true;
  }

  async function showReady() {
    statusDot.className = "status-dot online";
    statusLabel.textContent = "Ready";
    stateOffline.hidden = true;
    stateReady.hidden = false;

    // Populate domain
    if (_popupData.tabInfo && _popupData.tabInfo.domain) {
      domainValue.textContent = _popupData.tabInfo.domain;
    } else {
      domainValue.textContent = "—";
      btnLaunch.disabled = true;
    }

    // Populate browser dropdown
    populateBrowsers();

    // Restore last saved state FIRST (before rule overrides)
    await restoreLastState();

    // Then apply existing rule if any (overrides saved state for that domain)
    if (_popupData.currentRule) {
      applyRule(_popupData.currentRule);
    }

    // Check if URL is valid for handoff
    const url = _popupData.tabInfo?.url || "";
    if (!url || url.startsWith("about:") || url.startsWith("moz-extension:")) {
      btnLaunch.disabled = true;
      domainValue.textContent = "Internal page";
    }
  }

  function populateBrowsers() {
    browserSelect.innerHTML = "";

    if (!_popupData.browsers || _popupData.browsers.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No browsers detected";
      browserSelect.appendChild(opt);
      return;
    }

    _popupData.browsers.forEach((b) => {
      const opt = document.createElement("option");
      opt.value = b.id;
      opt.textContent = `${getBrowserEmoji(b.id)} ${b.name}${b.version ? " (" + b.version + ")" : ""}`;
      browserSelect.appendChild(opt);
    });

    // Select default from settings
    const defaultBrowser = _popupData.settings?.default_browser || "chrome";
    const hasDefault = _popupData.browsers.some((b) => b.id === defaultBrowser);
    if (hasDefault) {
      browserSelect.value = defaultBrowser;
    }
  }

  function getBrowserEmoji(id) {
    const emojis = {
      chrome: "🟡",
      brave: "🦁",
      edge: "🔵",
      chromium: "🔷",
      vivaldi: "🔴",
      opera: "🔴",
    };
    return emojis[id] || "🌐";
  }

  function applyRule(rule) {
    if (rule.browser && _popupData.browsers?.some((b) => b.id === rule.browser)) {
      browserSelect.value = rule.browser;
    }
    if (rule.mode) {
      setSegmentedValue(modeControl, rule.mode);
      _selectedMode = rule.mode;
    }
    if (rule.profile) {
      setSegmentedValue(profileControl, rule.profile);
      _selectedProfile = rule.profile;
    }
    if (rule.action === "always") {
      chkAlways.checked = true;
    }
  }

  // ── State Persistence ──────────────────────────────
  async function saveLastState() {
    const state = {
      browser: browserSelect.value,
      mode: _selectedMode,
      profile: _selectedProfile,
    };
    try {
      await browser.storage.local.set({ [POPUP_STATE_KEY]: state });
    } catch {
      // Storage not available
    }
  }

  async function restoreLastState() {
    try {
      const result = await browser.storage.local.get(POPUP_STATE_KEY);
      const state = result[POPUP_STATE_KEY];
      if (!state) return;

      // Restore browser selection
      if (state.browser && _popupData.browsers?.some((b) => b.id === state.browser)) {
        browserSelect.value = state.browser;
      }

      // Restore mode
      if (state.mode) {
        setSegmentedValue(modeControl, state.mode);
        _selectedMode = state.mode;
      }

      // Restore profile
      if (state.profile) {
        setSegmentedValue(profileControl, state.profile);
        _selectedProfile = state.profile;
      }
    } catch {
      // Storage not available
    }
  }

  // ── Event Listeners ────────────────────────────────
  function setupEventListeners() {
    // Segmented controls (save state on change)
    setupSegmentedControl(modeControl, (val) => {
      _selectedMode = val;
      saveLastState();
    });
    setupSegmentedControl(profileControl, (val) => {
      _selectedProfile = val;
      saveLastState();
    });

    // Browser selector (save state on change)
    browserSelect.addEventListener("change", () => {
      saveLastState();
    });

    // Launch button
    btnLaunch.addEventListener("click", handleLaunch);

    // Setup button
    btnSetup.addEventListener("click", () => {
      browser.runtime.openOptionsPage();
      window.close();
    });

    // Footer links
    linkOptions.addEventListener("click", (e) => {
      e.preventDefault();
      browser.runtime.openOptionsPage();
      window.close();
    });

    linkHelp.addEventListener("click", (e) => {
      e.preventDefault();
      browser.tabs.create({ url: "https://github.com/user/chromiumbridge#readme" });
      window.close();
    });
  }

  function setupSegmentedControl(container, onChange) {
    const buttons = container.querySelectorAll(".seg-btn");
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        buttons.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        onChange(btn.dataset.value);
      });
    });
  }

  function setSegmentedValue(container, value) {
    const buttons = container.querySelectorAll(".seg-btn");
    buttons.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.value === value);
    });
  }

  // ── Handoff ────────────────────────────────────────
  async function handleLaunch() {
    if (_isHandingOff || !_popupData?.tabInfo) return;

    _isHandingOff = true;
    btnLaunch.disabled = true;
    handoffStatus.hidden = false;

    // Persist current selections
    await saveLastState();

    // Save "always" rule if checked
    if (chkAlways.checked && _popupData.tabInfo.domain) {
      await browser.runtime.sendMessage({
        action: "saveRule",
        domain: _popupData.tabInfo.domain,
        rule: {
          action: "always",
          browser: browserSelect.value,
          mode: _selectedMode,
          profile: _selectedProfile,
        },
      });
    }

    // Trigger handoff
    const result = await browser.runtime.sendMessage({
      action: "handoff",
      tabId: _popupData.tabInfo.tabId,
      url: _popupData.tabInfo.url,
      overrides: {
        browser: browserSelect.value,
        mode: _selectedMode,
        profile: _selectedProfile,
      },
    });

    if (result.error) {
      handoffStatus.innerHTML = `<span style="color: var(--error)">❌ ${result.error}</span>`;
      btnLaunch.disabled = false;
      _isHandingOff = false;
    } else {
      // Close popup after successful launch
      window.close();
    }
  }

  // ── Start ──────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", init);
})();
