/**
 * popup.js — Popup UI logic for ChromiumBridge (Chromium to Gecko).
 */

(function () {
  "use strict";

  let _tabInfo = null;
  let _currentRule = null;
  let _settings = null;
  let _selectedMode = "normal";
  let _selectedProfile = "ephemeral";

  // Elements
  const statusDot = document.getElementById("status-dot");
  const statusLabel = document.getElementById("status-label");
  const stateOffline = document.getElementById("state-offline");
  const stateReady = document.getElementById("state-ready");
  const domainValue = document.getElementById("domain-value");
  const browserSelect = document.getElementById("browser-select");
  const modeControl = document.getElementById("mode-control");
  const profileControl = document.getElementById("profile-control");
  const btnLaunch = document.getElementById("btn-launch");
  const chkAlways = document.getElementById("chk-always");
  const handoffStatus = document.getElementById("handoff-status");
  const linkOptions = document.getElementById("link-options");
  const linkHelp = document.getElementById("link-help");
  const btnRetry = document.getElementById("btn-retry");
  const btnSetup = document.getElementById("btn-setup");
  const offlineTitle = document.getElementById("offline-title");
  const offlineDesc = document.getElementById("offline-desc");

  async function init() {
    try {
      setupEventListeners();
    } catch (err) {
      console.error("[ChromiumBridge] Error setting up event listeners:", err);
    }
    await loadData();
  }

  async function loadData() {
    statusDot.className = "status-dot";
    statusLabel.textContent = "Checking…";

    chrome.runtime.sendMessage({ action: "getPopupData" }, (response) => {
      if (chrome.runtime.lastError || !response) {
        setBridgeOffline("Bridge offline", chrome.runtime.lastError?.message || "Failed to communicate with extension worker");
        return;
      }

      _tabInfo = response.tabInfo;
      _currentRule = response.currentRule;
      _settings = response.settings || {};

      if (response.bridgeReady) {
        setBridgeOnline();
        renderBrowsers(response.browsers || []);
        renderTabInfo();
        applyPreferences();
      } else {
        setBridgeOffline("Bridge not connected", response.lastError || "Could not connect to native messaging host. Run python bridge/install.py to register.");
      }
    });
  }

  function setBridgeOnline() {
    statusDot.className = "status-dot online";
    statusLabel.textContent = "Connected";
    stateOffline.hidden = true;
    stateReady.hidden = false;
  }

  function setBridgeOffline(title, desc) {
    statusDot.className = "status-dot offline";
    statusLabel.textContent = title;
    if (offlineTitle) offlineTitle.textContent = title;
    if (offlineDesc && desc) offlineDesc.textContent = desc;
    stateOffline.hidden = false;
    stateReady.hidden = true;
  }

  function renderBrowsers(browsers) {
    browserSelect.innerHTML = "";

    if (!browsers || browsers.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No Gecko browsers detected";
      browserSelect.appendChild(opt);
      btnLaunch.disabled = true;
      return;
    }

    btnLaunch.disabled = false;
    const defaultBrowser = _currentRule?.browser || _settings?.default_browser || "firefox";

    browsers.forEach((b) => {
      const opt = document.createElement("option");
      opt.value = b.id;
      opt.textContent = `${b.name}${b.version ? ` (${b.version})` : ""}`;
      if (b.id === defaultBrowser) {
        opt.selected = true;
      }
      browserSelect.appendChild(opt);
    });

    if (!browserSelect.value && browsers.length > 0) {
      browserSelect.value = browsers[0].id;
    }
  }

  function renderTabInfo() {
    if (_tabInfo?.domain) {
      domainValue.textContent = _tabInfo.domain;
    } else {
      domainValue.textContent = "Internal page";
      btnLaunch.disabled = true;
    }
  }

  function applyPreferences() {
    _selectedMode = _currentRule?.mode || _settings?.window_mode || "normal";
    _selectedProfile = _currentRule?.profile || _settings?.profile_mode || "ephemeral";

    updateSegmented(modeControl, _selectedMode);
    updateSegmented(profileControl, _selectedProfile);

    if (_currentRule?.action === "always") {
      chkAlways.checked = true;
    }
  }

  function updateSegmented(control, activeValue) {
    control.querySelectorAll(".seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.value === activeValue);
    });
  }

  function setupEventListeners() {
    // Mode switcher
    modeControl.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      _selectedMode = btn.dataset.value;
      updateSegmented(modeControl, _selectedMode);
    });

    // Profile switcher
    profileControl.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      _selectedProfile = btn.dataset.value;
      updateSegmented(profileControl, _selectedProfile);
    });

    // Launch button
    btnLaunch.addEventListener("click", async () => {
      if (!_tabInfo?.url) return;

      btnLaunch.disabled = true;
      handoffStatus.hidden = false;

      const browserTarget = browserSelect.value || "firefox";

      // Save rule if "Always" checked
      if (chkAlways.checked && _tabInfo.domain) {
        chrome.runtime.sendMessage({
          action: "saveRule",
          domain: _tabInfo.domain,
          rule: {
            action: "always",
            browser: browserTarget,
            mode: _selectedMode,
            profile: _selectedProfile,
          },
        });
      }

      // Execute handoff
      chrome.runtime.sendMessage(
        {
          action: "handoff",
          tabId: _tabInfo.tabId,
          url: _tabInfo.url,
          overrides: {
            browser: browserTarget,
            mode: _selectedMode,
            profile: _selectedProfile,
          },
        },
        (response) => {
          handoffStatus.hidden = true;
          btnLaunch.disabled = false;

          if (response?.error) {
            alert(`Handoff failed: ${response.error}`);
          } else {
            window.close();
          }
        }
      );
    });

    // Re-scan
    linkHelp.addEventListener("click", (e) => {
      e.preventDefault();
      loadData();
    });

    btnRetry?.addEventListener("click", () => {
      loadData();
    });

    // Options links
    linkOptions.addEventListener("click", (e) => {
      e.preventDefault();
      chrome.runtime.openOptionsPage();
    });

    btnSetup?.addEventListener("click", () => {
      chrome.runtime.openOptionsPage();
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
