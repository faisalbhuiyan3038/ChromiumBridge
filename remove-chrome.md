# Exclude Google Chrome from ChromiumBridge

Google Chrome has security limitations and incompatibility issues with session/extension loading via native messaging command-line injection. This plan outlines how to remove Google Chrome from the supported browsers list and prevent loading it under any circumstances, while adding a user-facing explanation in the settings UI.

## Proposed Changes

---

### Python Bridge Component

#### [MODIFY] [detect.py](file:///m:/.systemfile/ChromiumBridge/bridge/detect.py)
- Remove the `"chrome"` block from the `BROWSER_DEFS` mapping.
- Add safeguard blocks inside `_find_single_browser` and `resolve_browser`:
  ```python
  if browser_id == "chrome":
      return None
  ```
- Remove the `"chrome"` key from the `_USER_DATA_DIRS` dictionary to clean up references.

#### [MODIFY] [config.py](file:///m:/.systemfile/ChromiumBridge/bridge/config.py)
- Change `DEFAULT_CONFIG["default_browser"]` from `"chrome"` to `"brave"`.

#### [MODIFY] [config.json](file:///m:/.systemfile/ChromiumBridge/bridge/config.json)
- Update `"default_browser"` to `"brave"`.

---

### Firefox Extension Component

#### [MODIFY] [main.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/background/main.js)
- Update the default browser fallback to `"brave"` instead of `"chrome"`:
  ```javascript
  const browserTarget = overrides.browser || rule.browser || settings.default_browser || "brave";
  ```
  and:
  ```javascript
  async function getSessionSettings() {
    const result = await browser.storage.sync.get("sessionSettings");
    return result.sessionSettings || {
      default_browser: "brave",
      ...
    }
  }
  ```

#### [MODIFY] [options.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/options/options.js)
- Update `_defaultBrowser` initialization and fallbacks to `"brave"` instead of `"chrome"`.
- In `renderBrowsers(browsers)`, if `_defaultBrowser` is not in the list of detected browsers (e.g. if it was previously set to `"chrome"`), automatically fallback to the first detected browser's ID to ensure a seamless migration.

#### [MODIFY] [popup.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/popup/popup.js)
- Update default browser fallback to `"brave"` instead of `"chrome"`.

---

### User Interface Component

#### [MODIFY] [index.html](file:///m:/.systemfile/ChromiumBridge/firefox-extension/options/index.html)
- Add a beautiful warning/notice block immediately below the `#browser-list` container inside the "Detected Browsers" card:
  ```html
  <div class="chrome-notice">
    <div class="chrome-notice-icon">⚠️</div>
    <div class="chrome-notice-body">
      <div class="chrome-notice-title">Google Chrome is Deliberately Excluded</div>
      Google Chrome is not supported because it restricts remote session debugging, unpacked extension loading, and local cookie injection when launched via command-line flags. To use ChromiumBridge, please use fully-supported browsers such as Brave, Microsoft Edge, Vivaldi, Opera, or a standard Chromium build.
    </div>
  </div>
  ```

#### [MODIFY] [options.css](file:///m:/.systemfile/ChromiumBridge/firefox-extension/options/options.css)
- Add premium CSS styles for `.chrome-notice` that align perfectly with the modern options page theme.
- CSS styling details:
  ```css
  .chrome-notice {
    background: rgba(255, 171, 0, 0.08);
    border: 1px solid rgba(255, 171, 0, 0.24);
    border-radius: var(--radius-md);
    padding: 14px 16px;
    margin-top: 16px;
    display: flex;
    gap: 12px;
  }
  .chrome-notice-icon {
    font-size: 20px;
    line-height: 1;
    margin-top: 2px;
  }
  .chrome-notice-body {
    font-size: 13px;
    line-height: 1.5;
    color: #8C5B00;
  }
  .chrome-notice-title {
    font-weight: 600;
    margin-bottom: 4px;
    color: #664200;
  }
  ```

---

## Verification Plan

### Automated/Code Verification
- Verify that `bridge/detect.py` does not return `"chrome"` in `detect_all()`.
- Verify that running the bridge with a manual `"chrome"` request returns `None` or fails gracefully instead of launching Chrome.

### Manual Verification
- Open the Options page in Firefox → verify that "Google Chrome" is not in the list of detected browsers.
- Verify that the beautiful Chrome Exclusion Notice is rendered correctly.
- Verify that the default browser falls back to a detected browser (such as Brave or Edge) instead of remaining stuck on Chrome.
- Try to manually launch handoff to a custom browser named `"chrome"` → verify it is blocked.
