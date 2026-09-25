/**
 * options.js — Options page controller for ChromiumBridge (Chromium to Gecko).
 */

(function () {
  "use strict";

  let _detectedBrowsers = [];
  let _rules = {};
  let _settings = {};
  let _defaultBrowser = "firefox";

  // Elements
  const navItems = document.querySelectorAll(".nav-item");
  const tabPanels = document.querySelectorAll(".tab-panel");
  const browserList = document.getElementById("browser-list");
  const btnRescan = document.getElementById("btn-rescan");
  const customBrowserId = document.getElementById("custom-browser-id");
  const customBrowserPath = document.getElementById("custom-browser-path");
  const btnSaveCustomBrowser = document.getElementById("btn-save-custom-browser");

  // Rules elements
  const rulesTbody = document.getElementById("rules-tbody");
  const btnAddRule = document.getElementById("btn-add-rule");
  const btnImportRules = document.getElementById("btn-import-rules");
  const btnExportRules = document.getElementById("btn-export-rules");
  const ruleModal = document.getElementById("rule-modal");
  const modalClose = document.getElementById("modal-close");
  const modalCancel = document.getElementById("modal-cancel");
  const modalSave = document.getElementById("modal-save");
  const ruleDomain = document.getElementById("rule-domain");
  const ruleAction = document.getElementById("rule-action");
  const ruleBrowser = document.getElementById("rule-browser");
  const ruleMode = document.getElementById("rule-mode");
  const ruleProfile = document.getElementById("rule-profile");

  // Session elements
  const sessionProfileMode = document.getElementById("session-profile-mode");
  const sessionDefaultMode = document.getElementById("session-default-mode");
  const sessionCookies = document.getElementById("session-cookies");
  const sessionLocalStorage = document.getElementById("session-localstorage");
  const sessionIncognito = document.getElementById("session-incognito");
  const btnSaveSession = document.getElementById("btn-save-session");

  // Advanced elements
  const healthDot = document.getElementById("health-dot");
  const healthText = document.getElementById("health-text");
  const btnCheckHealth = document.getElementById("btn-check-health");
  const advancedPythonPath = document.getElementById("advanced-python-path");
  const advancedBridgeDir = document.getElementById("advanced-bridge-dir");
  const btnReinstall = document.getElementById("btn-reinstall");
  const reinstallStatus = document.getElementById("reinstall-status");
  const advancedConfig = document.getElementById("advanced-config");
  const btnSaveConfig = document.getElementById("btn-save-config");

  async function init() {
    setupNavigation();
    setupEventListeners();
    await loadAllData();
  }

  function setupNavigation() {
    navItems.forEach((item) => {
      item.addEventListener("click", () => {
        const tabId = item.dataset.tab;
        navItems.forEach((n) => n.classList.toggle("active", n === item));
        tabPanels.forEach((p) => p.classList.toggle("active", p.id === `tab-${tabId}`));
      });
    });
  }

  async function loadAllData() {
    chrome.storage.sync.get("sessionSettings", (res) => {
      _settings = res.sessionSettings || {};
      _defaultBrowser = _settings.default_browser || "firefox";

      if (_settings.profile_mode) sessionProfileMode.value = _settings.profile_mode;
      if (_settings.window_mode) sessionDefaultMode.value = _settings.window_mode;
      if (_settings.port_cookies !== undefined) sessionCookies.checked = _settings.port_cookies;
      if (_settings.port_localstorage !== undefined) sessionLocalStorage.checked = _settings.port_localstorage;
      if (_settings.incognito_passthrough !== undefined) sessionIncognito.checked = _settings.incognito_passthrough;
    });

    await rescanBrowsers();
    await loadRules();
    await checkHealth();
    await loadBridgeConfig();
  }

  async function rescanBrowsers() {
    browserList.innerHTML = `<p class="empty-state">Scanning for Gecko browsers…</p>`;
    chrome.runtime.sendMessage({ action: "detectBrowsers" }, (response) => {
      _detectedBrowsers = response?.browsers || [];
      renderBrowsers(_detectedBrowsers);
      populateRuleBrowserSelect(_detectedBrowsers);
    });
  }

  function renderBrowsers(browsers) {
    browserList.innerHTML = "";

    if (!browsers || browsers.length === 0) {
      browserList.innerHTML = `<p class="empty-state">No Gecko browsers detected. Install Firefox, LibreWolf, Floorp, Zen, or specify a custom path.</p>`;
      return;
    }

    browsers.forEach((b) => {
      const item = document.createElement("div");
      item.className = "browser-item";

      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "default-browser";
      radio.value = b.id;
      radio.checked = b.id === _defaultBrowser;

      radio.addEventListener("change", () => {
        _defaultBrowser = b.id;
        _settings.default_browser = b.id;
        chrome.runtime.sendMessage({ action: "saveSessionSettings", settings: _settings });
      });

      const info = document.createElement("div");
      info.className = "browser-info";

      const name = document.createElement("div");
      name.className = "browser-name";
      name.textContent = `${b.name} ${b.version ? `v${b.version}` : ""}`;

      const path = document.createElement("div");
      path.className = "browser-path";
      path.textContent = b.path;

      info.appendChild(name);
      info.appendChild(path);

      item.appendChild(radio);
      item.appendChild(info);
      browserList.appendChild(item);
    });
  }

  function populateRuleBrowserSelect(browsers) {
    ruleBrowser.innerHTML = `<option value="">Default (${_defaultBrowser})</option>`;
    browsers.forEach((b) => {
      const opt = document.createElement("option");
      opt.value = b.id;
      opt.textContent = b.name;
      ruleBrowser.appendChild(opt);
    });
  }

  async function loadRules() {
    chrome.runtime.sendMessage({ action: "getAllRules" }, (rules) => {
      _rules = rules || {};
      renderRulesTable(_rules);
    });
  }

  function renderRulesTable(rules) {
    rulesTbody.innerHTML = "";
    const domains = Object.keys(rules);

    if (domains.length === 0) {
      rulesTbody.innerHTML = `<tr><td colspan="6" class="empty-cell">No domain rules configured.</td></tr>`;
      return;
    }

    domains.forEach((dom) => {
      const rule = rules[dom];
      const tr = document.createElement("tr");

      tr.innerHTML = `
        <td><strong>${dom}</strong></td>
        <td><span class="badge ${rule.action === "always" ? "badge-always" : "badge-ask"}">${rule.action}</span></td>
        <td>${rule.browser || "Default"}</td>
        <td>${rule.mode || "Default"}</td>
        <td>${rule.profile || "Default"}</td>
        <td><button class="btn btn-outline btn-xs btn-delete" data-domain="${dom}">✕ Delete</button></td>
      `;

      tr.querySelector(".btn-delete").addEventListener("click", () => {
        deleteRule(dom);
      });

      rulesTbody.appendChild(tr);
    });
  }

  function deleteRule(domain) {
    chrome.runtime.sendMessage({ action: "deleteRule", domain }, () => {
      delete _rules[domain];
      renderRulesTable(_rules);
    });
  }

  async function checkHealth() {
    healthDot.className = "health-dot";
    healthText.textContent = "Checking…";

    chrome.runtime.sendMessage({ action: "getPopupData" }, (res) => {
      if (res?.bridgeReady) {
        healthDot.className = "health-dot online";
        healthText.textContent = "Connected to Python Bridge";
      } else {
        healthDot.className = "health-dot offline";
        healthText.textContent = res?.lastError ? `Bridge Offline (${res.lastError})` : "Bridge Offline";
      }
    });
  }

  async function loadBridgeConfig() {
    chrome.runtime.sendMessage({ action: "getBridgeConfig" }, (cfg) => {
      if (cfg && !cfg.error) {
        advancedConfig.value = JSON.stringify(cfg, null, 2);
        if (cfg.python_path) advancedPythonPath.value = cfg.python_path;
        if (cfg.bridge_dir) advancedBridgeDir.value = cfg.bridge_dir;
      }
    });
  }

  function setupEventListeners() {
    btnRescan.addEventListener("click", rescanBrowsers);

    // Save custom browser override
    btnSaveCustomBrowser.addEventListener("click", () => {
      const id = customBrowserId.value.trim();
      const path = customBrowserPath.value.trim();
      if (!id || !path) {
        alert("Please enter both a Browser ID and Path.");
        return;
      }

      chrome.runtime.sendMessage({ action: "getBridgeConfig" }, (cfg) => {
        if (!cfg) cfg = {};
        if (!cfg.browser_overrides) cfg.browser_overrides = {};
        cfg.browser_overrides[id] = path;

        chrome.runtime.sendMessage({ action: "setBridgeConfig", config: cfg }, () => {
          alert(`Saved custom browser ${id}`);
          customBrowserId.value = "";
          customBrowserPath.value = "";
          rescanBrowsers();
        });
      });
    });

    // Rule modal
    btnAddRule.addEventListener("click", () => {
      ruleDomain.value = "";
      ruleAction.value = "always";
      ruleBrowser.value = "";
      ruleMode.value = "";
      ruleProfile.value = "";
      ruleModal.hidden = false;
    });

    modalClose.addEventListener("click", () => (ruleModal.hidden = true));
    modalCancel.addEventListener("click", () => (ruleModal.hidden = true));

    modalSave.addEventListener("click", () => {
      const domain = ruleDomain.value.trim().toLowerCase();
      if (!domain) {
        alert("Please enter a domain.");
        return;
      }

      const rule = {
        action: ruleAction.value,
        browser: ruleBrowser.value || undefined,
        mode: ruleMode.value || undefined,
        profile: ruleProfile.value || undefined,
      };

      chrome.runtime.sendMessage({ action: "saveRule", domain, rule }, () => {
        _rules[domain] = rule;
        renderRulesTable(_rules);
        ruleModal.hidden = true;
      });
    });

    // Export rules
    btnExportRules.addEventListener("click", () => {
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(_rules, null, 2));
      const downloadAnchor = document.createElement("a");
      downloadAnchor.setAttribute("href", dataStr);
      downloadAnchor.setAttribute("download", "chromiumbridge-rules.json");
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    });

    // Import rules
    btnImportRules.addEventListener("click", () => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".json";
      input.onchange = (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (event) => {
          try {
            const imported = JSON.parse(event.target.result);
            chrome.runtime.sendMessage({ action: "importRules", rules: imported }, () => {
              loadRules();
              alert("Rules imported successfully!");
            });
          } catch (err) {
            alert("Failed to parse JSON file.");
          }
        };
        reader.readAsText(file);
      };
      input.click();
    });

    // Session save
    btnSaveSession.addEventListener("click", () => {
      _settings.profile_mode = sessionProfileMode.value;
      _settings.window_mode = sessionDefaultMode.value;
      _settings.port_cookies = sessionCookies.checked;
      _settings.port_localstorage = sessionLocalStorage.checked;
      _settings.incognito_passthrough = sessionIncognito.checked;
      _settings.default_browser = _defaultBrowser;

      chrome.runtime.sendMessage({ action: "saveSessionSettings", settings: _settings }, () => {
        alert("Session settings saved!");
      });
    });

    // Advanced tab
    btnCheckHealth.addEventListener("click", checkHealth);

    btnReinstall.addEventListener("click", () => {
      reinstallStatus.textContent = "Reinstalling…";
      chrome.runtime.sendMessage(
        {
          action: "reinstall",
          pythonPath: advancedPythonPath.value.trim() || undefined,
          bridgeDir: advancedBridgeDir.value.trim() || undefined,
        },
        (res) => {
          if (res?.status === "ok") {
            reinstallStatus.textContent = "Native host reinstalled successfully!";
            checkHealth();
          } else {
            reinstallStatus.textContent = `Reinstall failed: ${res?.error || "Unknown error"}`;
          }
        }
      );
    });

    btnSaveConfig.addEventListener("click", () => {
      try {
        const parsed = JSON.parse(advancedConfig.value);
        chrome.runtime.sendMessage({ action: "setBridgeConfig", config: parsed }, (res) => {
          if (res?.status === "ok") {
            alert("Config saved successfully!");
            loadAllData();
          } else {
            alert(`Error: ${res?.error}`);
          }
        });
      } catch (err) {
        alert("Invalid JSON: " + err.message);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
