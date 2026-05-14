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

  btnRescan.addEventListener("click", async () => {
    btnRescan.disabled = true;
    btnRescan.textContent = "Scanning…";
    const result = await msg({ action: "detectBrowsers" });
    renderBrowsers(result.browsers || []);
    btnRescan.disabled = false;
    btnRescan.textContent = "↻ Re-scan";
  });

  function renderBrowsers(browsers) {
    if (!browsers.length) {
      browserList.innerHTML = '<p class="empty-state">No Chromium browsers detected.</p>';
      return;
    }
    browserList.innerHTML = browsers
      .map(
        (b, i) => `
      <div class="browser-item${i === 0 ? " default" : ""}">
        <div class="browser-info">
          <div>
            <span class="browser-name">${esc(b.name)}</span>
            <span class="browser-version">${esc(b.version || "unknown")}</span>
            <div class="browser-path">${esc(b.path || "")}</div>
          </div>
        </div>
        <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-secondary)">
          <input type="radio" name="default-browser" value="${esc(b.id)}" ${i === 0 ? "checked" : ""}>
          Default
        </label>
      </div>`
      )
      .join("");
  }

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
  const persistentPathGroup = document.getElementById("persistent-path-group");

  sessionProfileMode.addEventListener("change", () => {
    persistentPathGroup.hidden = sessionProfileMode.value !== "persistent";
  });

  document.getElementById("btn-save-session").addEventListener("click", async () => {
    const settings = {
      default_browser: "chrome",
      profile_mode: sessionProfileMode.value,
      persistent_profile_path: document.getElementById("session-persistent-path").value,
      port_cookies: document.getElementById("session-cookies").checked,
      port_localstorage: document.getElementById("session-localstorage").checked,
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
    sessionProfileMode.value = s.profile_mode || "ephemeral";
    persistentPathGroup.hidden = sessionProfileMode.value !== "persistent";
    document.getElementById("session-persistent-path").value = s.persistent_profile_path || "";
    document.getElementById("session-cookies").checked = s.port_cookies !== false;
    document.getElementById("session-localstorage").checked = s.port_localstorage !== false;
    document.getElementById("session-history").checked = s.record_history !== false;
    document.getElementById("session-cleanup").checked = s.cleanup_on_close !== false;
    document.getElementById("session-incognito").checked = s.incognito_passthrough !== false;
    document.getElementById("session-discard").checked = !!s.discard_firefox_tab;
    document.getElementById("session-feedback").checked = s.feedback_prompt !== false;
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
