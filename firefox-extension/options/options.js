/**
 * options.js — ChromeBridge options page logic.
 */
(function () {
  "use strict";

  // ── Tab Navigation ─────────────────────────────────
  const navItems = document.querySelectorAll(".nav-item");
  const tabPanels = document.querySelectorAll(".tab-panel");

  navItems.forEach((item) => {
    item.addEventListener("click", () => {
      const tab = item.dataset.tab;
      navItems.forEach((n) => n.classList.remove("active"));
      tabPanels.forEach((p) => p.classList.remove("active"));
      item.classList.add("active");
      document.getElementById("tab-" + tab).classList.add("active");
    });
  });

  // ── Helpers ────────────────────────────────────────
  async function msg(payload) {
    return browser.runtime.sendMessage(payload);
  }

  // ── Browsers Tab ───────────────────────────────────
  const browserList = document.getElementById("browser-list");
  const btnRescan = document.getElementById("btn-rescan");
  let _detectedBrowsers = [];
  let _defaultBrowser = "brave";

  btnRescan.addEventListener("click", async () => {
    btnRescan.disabled = true;
    btnRescan.textContent = "Scanning…";
    const result = await msg({ action: "detectBrowsers" });
    _detectedBrowsers = result.browsers || [];
    renderBrowsers(_detectedBrowsers);
    await renderPersistentProfiles(_detectedBrowsers);
    btnRescan.disabled = false;
    btnRescan.textContent = "↻ Re-scan";
  });

  function renderBrowsers(browsers) {
    if (!browsers.length) {
      browserList.innerHTML = '<p class="empty-state">No Chromium browsers detected.</p>';
      return;
    }

    if (_defaultBrowser && !browsers.some((b) => b.id === _defaultBrowser)) {
      _defaultBrowser = browsers[0].id;
    }

    browserList.innerHTML = browsers
      .map(
        (b) => `
      <div class="browser-item${b.id === _defaultBrowser ? " default" : ""}">
        <div class="browser-info">
          <div>
            <span class="browser-name">${esc(b.name)}</span>
            <span class="browser-version">${esc(b.version || "unknown")}</span>
            <div class="browser-path">${esc(b.path || "")}</div>
          </div>
        </div>
        <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-secondary)">
          <input type="radio" name="default-browser" value="${esc(b.id)}" ${b.id === _defaultBrowser ? "checked" : ""}>
          Default
        </label>
      </div>`
      )
      .join("");

    // Save on change
    browserList.querySelectorAll('input[name="default-browser"]').forEach((radio) => {
      radio.addEventListener("change", async () => {
        _defaultBrowser = radio.value;
        browserList.querySelectorAll(".browser-item").forEach((el) => el.classList.remove("default"));
        radio.closest(".browser-item").classList.add("default");
        const result = await browser.storage.sync.get("sessionSettings");
        const s = result.sessionSettings || {};
        s.default_browser = _defaultBrowser;
        await browser.storage.sync.set({ sessionSettings: s });
        showToast(`Default browser: ${radio.value}`);
      });
    });
  }

  // Custom Browser
  document.getElementById("btn-save-custom-browser").addEventListener("click", async () => {
    const idInput = document.getElementById("custom-browser-id");
    const pathInput = document.getElementById("custom-browser-path");
    const id = idInput.value.trim().toLowerCase();
    const path = pathInput.value.trim();

    if (!id || !path) {
      alert("Both Browser ID and Absolute Path are required.");
      return;
    }

    // Get current config to merge
    const config = await msg({ action: "getBridgeConfig" });
    const overrides = config.browser_overrides || {};
    overrides[id] = path;

    await msg({ action: "setBridgeConfig", config: { browser_overrides: overrides } });
    showToast(`Custom browser '${id}' saved.`);
    
    // Clear inputs and rescan
    idInput.value = "";
    pathInput.value = "";
    btnRescan.click();
  });

  // ── Domain Rules Tab ───────────────────────────────
  const rulesTbody = document.getElementById("rules-tbody");
  const ruleModal = document.getElementById("rule-modal");

  document.getElementById("btn-add-rule").addEventListener("click", () => {
    clearRuleForm();
    ruleModal.hidden = false;
  });
  document.getElementById("modal-close").addEventListener("click", () => (ruleModal.hidden = true));
  document.getElementById("modal-cancel").addEventListener("click", () => (ruleModal.hidden = true));

  document.getElementById("modal-save").addEventListener("click", async () => {
    const domain = document.getElementById("rule-domain").value.trim();
    if (!domain) return;
    const rule = {
      action: document.getElementById("rule-action").value,
      browser: document.getElementById("rule-browser").value || undefined,
      mode: document.getElementById("rule-mode").value || undefined,
      profile: document.getElementById("rule-profile").value || undefined,
    };
    await msg({ action: "saveRule", domain, rule });
    ruleModal.hidden = true;
    loadRules();
  });

  document.getElementById("btn-export-rules").addEventListener("click", async () => {
    const rules = await msg({ action: "exportRules" });
    const blob = new Blob([JSON.stringify(rules, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "chromiumbridge-rules.json"; a.click();
    URL.revokeObjectURL(url);
  });

  document.getElementById("btn-import-rules").addEventListener("click", () => {
    const input = document.createElement("input");
    input.type = "file"; input.accept = ".json";
    input.addEventListener("change", async () => {
      const file = input.files[0];
      if (!file) return;
      const text = await file.text();
      try {
        const rules = JSON.parse(text);
        const result = await msg({ action: "importRules", rules });
        alert(`Imported ${result.count} rules.`);
        loadRules();
      } catch { alert("Invalid JSON file."); }
    });
    input.click();
  });

  async function loadRules() {
    const rules = await msg({ action: "getAllRules" });
    const entries = Object.entries(rules || {});
    if (!entries.length) {
      rulesTbody.innerHTML = '<tr class="empty-row"><td colspan="6" class="empty-cell">No domain rules.</td></tr>';
      return;
    }
    rulesTbody.innerHTML = entries
      .map(
        ([domain, r]) => `
      <tr>
        <td><strong>${esc(domain)}</strong></td>
        <td>${esc(r.action || "—")}</td>
        <td>${esc(r.browser || "default")}</td>
        <td>${esc(r.mode || "default")}</td>
        <td>${esc(r.profile || "default")}</td>
        <td><button class="btn btn-outline btn-sm btn-delete-rule" data-domain="${esc(domain)}">✕</button></td>
      </tr>`
      )
      .join("");
    rulesTbody.querySelectorAll(".btn-delete-rule").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await msg({ action: "deleteRule", domain: btn.dataset.domain });
        loadRules();
      });
    });
  }

  function clearRuleForm() {
    document.getElementById("rule-domain").value = "";
    document.getElementById("rule-action").value = "always";
    document.getElementById("rule-browser").value = "";
    document.getElementById("rule-mode").value = "";
    document.getElementById("rule-profile").value = "";
  }

  // ── Session Tab ────────────────────────────────────
  const sessionProfileMode = document.getElementById("session-profile-mode");
  const persistentProfilesCard = document.getElementById("persistent-profiles-card");
  const persistentProfilesList = document.getElementById("persistent-profiles-list");

  // Track per-browser profile paths and detected profiles cache
  let _persistentProfiles = {};
  let _detectedProfiles = {};  // browserId -> [{id, name, path}]

  sessionProfileMode.addEventListener("change", () => {
    // Show/hide per-browser profile paths based on mode
    // Always show — user might use persistent for specific domain rules
  });

  async function renderPersistentProfiles(browsers) {
    if (!browsers || !browsers.length) {
      persistentProfilesList.innerHTML = '<p class="empty-state">Detect browsers first to configure per-browser profiles.</p>';
      return;
    }

    // Fetch detected profiles for all browsers
    try {
      const result = await msg({ action: "detectProfiles" });
      _detectedProfiles = result.profiles || {};
    } catch {
      _detectedProfiles = {};
    }

    persistentProfilesList.innerHTML = browsers
      .map((b) => {
        const profiles = _detectedProfiles[b.id] || [];
        let optionsHtml = `<option value="">Default (~/.fx-bridge/profiles/${esc(b.id)})</option>`;
        profiles.forEach((p) => {
          optionsHtml += `<option value="${esc(p.path)}">${esc(p.name)} (${esc(p.id)})</option>`;
        });
        optionsHtml += `<option value="__custom__">Custom path…</option>`;

        return `
        <div class="form-group profile-group" data-browser="${esc(b.id)}">
          <label class="form-label">${esc(b.name)} profile</label>
          <select class="form-select profile-select" data-browser="${esc(b.id)}">
            ${optionsHtml}
          </select>
          <input type="text" class="form-input persistent-profile-input"
                 data-browser="${esc(b.id)}"
                 placeholder="Enter absolute path to profile directory"
                 style="margin-top:6px;display:none">
        </div>`;
      })
      .join("");

    // Explicitly set values and bind events
    persistentProfilesList.querySelectorAll(".profile-select").forEach((select) => {
      const browserId = select.dataset.browser;
      const customInput = persistentProfilesList.querySelector(
        `.persistent-profile-input[data-browser="${browserId}"]`
      );

      // Restore saved value
      const currentPath = _persistentProfiles[browserId] || "";
      const profiles = _detectedProfiles[browserId] || [];
      const matchesDetected = profiles.some((p) => p.path === currentPath);

      if (currentPath) {
        if (matchesDetected) {
          select.value = currentPath;
        } else {
          select.value = "__custom__";
          customInput.value = currentPath;
          customInput.style.display = "";
        }
      } else {
        select.value = "";
      }

      // Handle change event
      select.addEventListener("change", () => {
        if (select.value === "__custom__") {
          customInput.style.display = "";
          customInput.focus();
        } else {
          customInput.style.display = "none";
          customInput.value = "";
        }
      });
    });
  }

  document.getElementById("btn-save-session").addEventListener("click", async () => {
    // Collect per-browser profile paths from dropdowns/custom inputs
    const profileGroups = document.querySelectorAll(".profile-group");
    const persistentProfiles = {};
    profileGroups.forEach((group) => {
      const browserId = group.dataset.browser;
      const select = group.querySelector(".profile-select");
      const customInput = group.querySelector(".persistent-profile-input");
      let path = "";
      if (select) {
        if (select.value === "__custom__") {
          path = customInput ? customInput.value.trim() : "";
        } else {
          path = select.value;
        }
      }
      if (path) {
        persistentProfiles[browserId] = path;
      }
    });

    const settings = {
      default_browser: _defaultBrowser,
      profile_mode: sessionProfileMode.value,
      default_mode: document.getElementById("session-default-mode").value,
      persistent_profile_path: "",
      persistent_profiles: persistentProfiles,
      port_cookies: document.getElementById("session-cookies").checked,
      port_localstorage: document.getElementById("session-localstorage").checked,
      port_sessionstorage: document.getElementById("session-sessionstorage").checked,
      record_history: document.getElementById("session-history").checked,
      cleanup_on_close: document.getElementById("session-cleanup").checked,
      incognito_passthrough: document.getElementById("session-incognito").checked,
      discard_firefox_tab: document.getElementById("session-discard").checked,
      feedback_prompt: document.getElementById("session-feedback").checked,
    };
    await msg({ action: "saveSessionSettings", settings });
    showToast("Session settings saved.");
  });

  async function loadSessionSettings() {
    const data = await msg({ action: "getPopupData" });
    const s = data?.settings || {};
    _defaultBrowser = s.default_browser || "brave";
    sessionProfileMode.value = s.profile_mode || "ephemeral";
    document.getElementById("session-default-mode").value = s.default_mode || "popup";
    _persistentProfiles = s.persistent_profiles || {};
    document.getElementById("session-cookies").checked = s.port_cookies !== false;
    document.getElementById("session-localstorage").checked = s.port_localstorage !== false;
    document.getElementById("session-sessionstorage").checked = s.port_sessionstorage !== false;
    document.getElementById("session-history").checked = s.record_history !== false;
    document.getElementById("session-cleanup").checked = s.cleanup_on_close !== false;
    document.getElementById("session-incognito").checked = s.incognito_passthrough !== false;
    document.getElementById("session-discard").checked = !!s.discard_firefox_tab;
    document.getElementById("session-feedback").checked = s.feedback_prompt !== false;

    // Load browsers to populate profile paths
    if (data?.browsers?.length) {
      _detectedBrowsers = data.browsers;
      renderBrowsers(data.browsers);
      await renderPersistentProfiles(data.browsers);
    }
  }

  // ── Signals Tab ────────────────────────────────────
  const bufThresholdRange = document.getElementById("signal-buffering-threshold");
  const bufThresholdValue = document.getElementById("buffering-threshold-value");
  bufThresholdRange.addEventListener("input", () => {
    bufThresholdValue.textContent = bufThresholdRange.value;
  });

  document.getElementById("btn-save-signals").addEventListener("click", async () => {
    const settings = {
      drm_detection: document.getElementById("signal-drm").checked,
      hls_detection: document.getElementById("signal-hls").checked,
      buffering_detection: document.getElementById("signal-buffering").checked,
      security_error_detection: document.getElementById("signal-security").checked,
      buffering_threshold: parseInt(bufThresholdRange.value, 10),
    };
    await msg({ action: "saveSignalSettings", settings });
    showToast("Signal settings saved.");
  });

  async function loadSignalSettings() {
    const settings = await msg({ action: "getSignalSettings" });
    document.getElementById("signal-drm").checked = !!settings.drm_detection;
    document.getElementById("signal-hls").checked = !!settings.hls_detection;
    document.getElementById("signal-buffering").checked = !!settings.buffering_detection;
    document.getElementById("signal-security").checked = !!settings.security_error_detection;
    bufThresholdRange.value = settings.buffering_threshold || 3;
    bufThresholdValue.textContent = settings.buffering_threshold || 3;
  }

  // ── Advanced Tab ───────────────────────────────────
  document.getElementById("btn-check-health").addEventListener("click", checkHealth);

  document.getElementById("btn-save-config").addEventListener("click", async () => {
    const raw = document.getElementById("advanced-config").value;
    try {
      const config = JSON.parse(raw);
      await msg({ action: "setBridgeConfig", config });
      showToast("Config saved.");
    } catch { alert("Invalid JSON."); }
  });

  // Reinstall native host with updated paths
  document.getElementById("btn-reinstall").addEventListener("click", async () => {
    const btn = document.getElementById("btn-reinstall");
    const status = document.getElementById("reinstall-status");
    const pythonPath = document.getElementById("advanced-python-path").value.trim();
    const bridgeDir = document.getElementById("advanced-bridge-dir").value.trim();

    btn.disabled = true;
    status.textContent = "Reinstalling…";
    status.style.color = "var(--text-secondary)";

    try {
      // First save the paths to config
      const configUpdate = {};
      if (pythonPath) configUpdate.python_path = pythonPath;
      if (bridgeDir) configUpdate.bridge_dir = bridgeDir;
      if (Object.keys(configUpdate).length > 0) {
        await msg({ action: "setBridgeConfig", config: configUpdate });
      }

      // Then trigger reinstall
      const result = await msg({
        action: "reinstall",
        pythonPath: pythonPath || undefined,
        bridgeDir: bridgeDir || undefined,
      });

      if (result.status === "ok") {
        status.textContent = "✓ Reinstalled successfully";
        status.style.color = "var(--success, #00A76F)";
        showToast("Native host reinstalled.");
      } else {
        status.textContent = "✕ " + (result.error || "Failed");
        status.style.color = "var(--error, #FF5630)";
      }
    } catch (err) {
      status.textContent = "✕ " + err.message;
      status.style.color = "var(--error, #FF5630)";
    }

    btn.disabled = false;
    setTimeout(() => (status.textContent = ""), 5000);
  });

  async function checkHealth() {
    const dot = document.getElementById("health-dot");
    const text = document.getElementById("health-text");
    text.textContent = "Checking…";
    dot.className = "health-dot";
    const result = await msg({ action: "refreshBridge" });
    if (result.bridgeReady) {
      dot.className = "health-dot ok";
      text.textContent = `Connected — ${(result.browsers || []).length} browser(s) detected`;
    } else {
      dot.className = "health-dot fail";
      text.textContent = "Bridge not responding. Check installation.";
    }
  }

  async function loadAdvanced() {
    checkHealth();
    const config = await msg({ action: "getBridgeConfig" });
    if (config && !config.error) {
      document.getElementById("advanced-config").value = JSON.stringify(config, null, 2);
      const flags = config.extra_flags || [];
      document.getElementById("advanced-flags").value = flags.join("\n");

      // Populate bridge path fields
      document.getElementById("advanced-python-path").value = config.python_path || "";
      document.getElementById("advanced-bridge-dir").value = config.bridge_dir || "";
    }
  }

  // ── Toast ──────────────────────────────────────────
  function showToast(message) {
    let toast = document.querySelector(".toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "toast";
      toast.style.cssText =
        "position:fixed;bottom:24px;right:24px;padding:10px 20px;background:#004B50;" +
        "color:#fff;border-radius:8px;font-size:13px;font-weight:500;z-index:9999;" +
        "opacity:0;transition:opacity 0.3s;font-family:inherit;";
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.style.opacity = "1";
    setTimeout(() => (toast.style.opacity = "0"), 2500);
  }

  // ── Escape HTML ────────────────────────────────────
  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  // ── Init ───────────────────────────────────────────
  async function init() {
    loadRules();
    loadSessionSettings();
    loadSignalSettings();
    loadAdvanced();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
