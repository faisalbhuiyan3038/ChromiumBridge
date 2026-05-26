# ChromeBridge — Implementation Plan

## Goal

Build **ChromeBridge** end-to-end: a Firefox MV2 extension, a Python native messaging bridge, and a Chromium MV3 companion extension. The system lets Firefox users hand off tabs to a Chromium-based browser with cookie portability, ephemeral/persistent profiles, and smart domain rules.

> [!IMPORTANT]
> This plan covers **Phase 1 (Skeleton) + Phase 2 (Session Core) + Phase 3 (Rules & Detection) + Phase 4 (Chromium Companion)** from the dev plan. Phase 5 (Polish) and Phase 6 (Release) are deferred.

---

## Design System — Modern Minimal UI

All extension UI (popup, options, banner) uses a **Modern Minimal** aesthetic — clean lines, generous whitespace, flat surfaces, subtle shadows, no glassmorphism.

### Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `--primary-lighter` | `#C8FAD6` | Hover backgrounds, tag fills, subtle highlights |
| `--primary-light` | `#5BE49B` | Active states, success indicators, badge fills |
| `--primary-main` | `#00A76F` | Primary buttons, links, focus rings, CTA |
| `--primary-dark` | `#007867` | Button hover, active nav items |
| `--primary-darker` | `#004B50` | Text on light backgrounds, headings |
| `--bg-primary` | `#FFFFFF` | Main background |
| `--bg-secondary` | `#F4F6F8` | Card backgrounds, secondary surfaces |
| `--bg-tertiary` | `#F9FAFB` | Input backgrounds, subtle sections |
| `--text-primary` | `#212B36` | Primary text |
| `--text-secondary` | `#637381` | Secondary text, labels, placeholders |
| `--text-disabled` | `#919EAB` | Disabled text |
| `--border` | `#E5E8EB` | Borders, dividers |
| `--error` | `#FF5630` | Error states |
| `--warning` | `#FFAB00` | Warning states |

### Typography
- Font: `Inter, -apple-system, BlinkMacSystemFont, sans-serif` (bundled woff2 subset or system fallback)
- Body: 13px/1.5, headings: 600 weight, body: 400 weight

### Components Style
- **Buttons**: Solid fill `--primary-main`, white text, 8px border-radius, subtle shadow on hover
- **Toggles/Segmented controls**: Pill-shaped, `--bg-secondary` track, `--primary-main` active segment
- **Cards**: `--bg-secondary` fill, 1px `--border` outline, 12px border-radius, 0 2px 4px rgba(0,0,0,0.04) shadow
- **Inputs**: `--bg-tertiary` fill, 1px `--border`, 8px radius
- **Dropdowns**: Flat, bordered, arrow indicator, `--bg-primary` surface
- **Transitions**: 150ms ease on all interactive elements

---

## Proposed Changes

### Component 1: Firefox Extension (`firefox-extension/`)

MV2 WebExtension with native messaging, cookie access, history integration, popup UI, options page, content scripts, and context menus.

Extension ID: **`chromiumbridges@faisalbhuiyan.com`**

---

#### [NEW] [manifest.json](file:///m:/.systemfile/ChromiumBridge/firefox-extension/manifest.json)

MV2 manifest with:
- `browser_specific_settings.gecko.id`: `"chromiumbridges@faisalbhuiyan.com"`
- Permissions: `nativeMessaging`, `cookies`, `history`, `activeTab`, `tabs`, `storage`, `contextMenus`, `<all_urls>`
- Background scripts: `background/main.js`, `background/native.js`, `background/rules.js`, `background/tabs.js`, `background/signals.js`
- Content scripts: `content/detector.js` + `content/banner.js` (match `<all_urls>`)
- Browser action (popup): `popup/popup.html`
- Options page: `options/index.html`
- Commands: `_execute_browser_action` default shortcut `Ctrl+Shift+O`
- Icons: 48px and 96px

---

#### [NEW] [background/native.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/background/native.js)

Native messaging wrapper. Exports:
- `sendMessage(payload)` — sends JSON to `chromiumbridge` native host via `browser.runtime.sendNativeMessage()`, returns the response promise.
- `connect()` — opens a persistent port via `browser.runtime.connectNative()` for long-lived sessions, with `onMessage` and `onDisconnect` handlers.
- `ping()` — health check: sends `{ action: "ping" }`, expects `{ status: "ok", browsers: [...] }`.

---

#### [NEW] [background/rules.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/background/rules.js)

Domain rule engine. Stores rules in `browser.storage.sync` under `domainRules`. Exports:
- `getRuleForDomain(domain)` — returns `{ action, browser, mode, preset, profile }` or `null`.
- `setRule(domain, rule)` — saves/updates a rule.
- `deleteRule(domain)` — removes a rule.
- `getAllRules()` — returns the full map.
- `importRules(json)` / `exportRules()` — import/export as JSON.
- `matchDomain(url)` — extracts domain from URL and finds a matching rule (supports subdomain matching: `video.netflix.com` matches `netflix.com`).

---

#### [NEW] [background/tabs.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/background/tabs.js)

Tab lifecycle management. Exports:
- `getActiveTabInfo()` — returns `{ tabId, url, domain, isIncognito }`.
- `refocusTab(tabId)` — brings the Firefox tab back to focus after Chromium closes.
- `discardTab(tabId)` — discards the tab to free memory (if user preference enabled).
- `recordHandoff(tabId, url)` — calls `browser.history.addUrl({ url })`.

---

#### [NEW] [background/signals.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/background/signals.js)

Signal aggregation from content scripts. Listens for messages from `detector.js`:
- Tracks signals per tab/domain: `{ drm, hls, buffering, securityError }`.
- On threshold hit (e.g., 3+ buffering events): sets badge text `"!"` + badge color `--primary-main`.
- Sends message to content script to show suggestion banner.
- Tracks which domains have already been suggested this session (avoids repeat).
- **Respects per-signal enable/disable settings** from `browser.storage.sync`.

---

#### [NEW] [background/main.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/background/main.js)

Background entry point. Orchestrates:

1. **Toolbar button click** (`browser.browserAction.onClicked`) — opens popup.
2. **Keyboard shortcut** — `Ctrl+Shift+O` triggers the popup.
3. **Context menu** setup — `"Open in Chromium"` on pages and links.
4. **Handoff flow** (called from popup or context menu):
   - Get active tab info via `tabs.js`.
   - Check domain rules via `rules.js`.
   - Collect cookies via `browser.cookies.getAll({ url })`.
   - Record in history via `tabs.js.recordHandoff()`.
   - Build payload: `{ action: "launch", url, cookies, domain, mode, profile, browser, incognito }`.
   - Send to bridge via `native.js.sendMessage()`.
   - On response `{ event: "closed" }`: refocus tab, show feedback prompt.
5. **Message listener** for popup ↔ background communication.
6. **Message listener** for content script signals (routed to `signals.js`).

---

#### [NEW] [popup/popup.html](file:///m:/.systemfile/ChromiumBridge/firefox-extension/popup/popup.html) + [popup/popup.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/popup/popup.js) + [popup/popup.css](file:///m:/.systemfile/ChromiumBridge/firefox-extension/popup/popup.css)

Popup UI matching the dev plan wireframe with **Modern Minimal** styling:
- Header: "🌉 ChromeBridge" + health indicator dot (green/red via `--primary-main`/`--error`).
- Domain display for current tab.
- Browser picker dropdown (populated from bridge detection).
- Mode toggle (segmented control): App / Popup / Normal.
- Profile toggle (segmented control): Ephemeral / Persistent.
- Primary CTA button: "🚀 Open in Chromium" — `--primary-main` solid fill.
- Checkbox: "Always open this domain here".
- Footer links: Options / History / Help.
- Width: 360px, white background, clean card layout.

---

#### [NEW] [content/detector.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/content/detector.js)

Content script running on all pages. **Each detector is individually toggleable** — on load, reads enabled states from `browser.storage.sync` (key: `signalSettings`). Only active detectors run.

Detectable signals (all disabled by default):
1. **DRM / Widevine** (`drm_detection`): Monitors `navigator.requestMediaKeySystemAccess()` calls via prototype wrapping.
2. **HLS / m3u8** (`hls_detection`): Watches for `<source>` elements with `.m3u8` URLs and XHR/fetch requests to `.m3u8` endpoints.
3. **Buffering** (`buffering_threshold`): Monitors `<video>` elements for repeated `waiting` events (threshold configurable, default 3).
4. **Console SecurityError** (`security_error_detection`): Listens for `error` events on `window` for cross-origin SecurityError.

Each detection sends a message to background: `{ type: "signal", signal: "drm"|"hls"|"buffering"|"securityError", domain }`.

Listens for `storage.onChanged` to update enabled states in real-time without page reload.

---

#### [NEW] [content/banner.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/content/banner.js)

Injected suggestion banner. On message from background `{ action: "showBanner", signal, domain }`:
- Creates a fixed-top banner with shadow DOM for style isolation.
- Clean minimal design: white background, left green accent bar (`--primary-main`), Inter font.
- Text: "🔒 DRM detected — open in Chromium?" (varies by signal type).
- Three buttons: **Open** (triggers handoff), **Always for this site** (saves rule + handoff), **Dismiss** (hides, remembers per session).
- Smooth slide-down animation, dismissible with ✕.

---

#### [NEW] [options/index.html](file:///m:/.systemfile/ChromiumBridge/firefox-extension/options/index.html) + [options/options.js](file:///m:/.systemfile/ChromiumBridge/firefox-extension/options/options.js) + [options/options.css](file:///m:/.systemfile/ChromiumBridge/firefox-extension/options/options.css)

Full options page with 5 tabs, Modern Minimal styling:

| Tab | Contents |
|-----|----------|
| **Browsers** | Auto-detected browser list with versions, radio for default, manual path override, "Re-scan" button, test launch |
| **Domain Rules** | CRUD table, import/export JSON, community list toggle |
| **Session** | Profile mode, persistent path, cookie/localStorage/history/incognito toggles, extension presets editor |
| **Signals** | **Individual on/off toggle for each signal type** (DRM, HLS, Buffering, SecurityError), sliders for thresholds, banner preview |
| **Advanced** | Extra CLI flags textarea, bridge health check, native host path, raw config editor, session log viewer |

---

### Component 2: Python Bridge (`bridge/`)

Native messaging host, pure Python 3.8+ with no external dependencies.

---

#### [NEW] [bridge/bridge.py](file:///m:/.systemfile/ChromiumBridge/bridge/bridge.py)

Main entry point. Reads length-prefixed JSON from stdin, dispatches:
- `action: "ping"` → responds with bridge status + detected browsers.
- `action: "launch"` → orchestrates: detect browser → create profile → **copy companion extension to profile dir** → write cookies into companion copy → build flags → spawn subprocess → wait → cleanup → respond.
- `action: "detect"` → returns list of detected browsers.
- `action: "config_get"` / `action: "config_set"` → read/write config.
- `action: "health"` → basic health check with timestamp.

Uses `struct.pack('=I', ...)` for native messaging protocol.
Shebang: `#!/usr/bin/env python3 -u` (unbuffered mode required).

---

#### [NEW] [bridge/detect.py](file:///m:/.systemfile/ChromiumBridge/bridge/detect.py)

OS-agnostic browser detection. Resolution priority:
1. User-defined override path in config.
2. Known install paths per OS (hardcoded candidates):
   - **Windows**: `Program Files`, `Program Files (x86)`, `AppData\Local` paths for Chrome, Edge, Brave, Chromium, Vivaldi, Opera.
   - **Linux**: `/usr/bin/`, `/usr/local/bin/`, snap paths, flatpak paths.
   - **macOS**: `/Applications/*.app/Contents/MacOS/` paths.
3. **Windows Registry** lookup (`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}`).
4. `shutil.which()` fallback.

Exports:
- `detect_all()` → `[{ id, name, path, version }]`.
- `resolve_browser(browser_id, config)` → resolved absolute path or error.
- `get_version(path)` → runs `browser --version`, parses output.

---

#### [NEW] [bridge/profile.py](file:///m:/.systemfile/ChromiumBridge/bridge/profile.py)

Profile management:
- `create_ephemeral()` → creates a temp dir (`tempfile.mkdtemp(prefix="fx-bridge-")`), returns path.
- `resolve_persistent(path)` → ensures the persistent profile dir exists, creates if missing.
- `cleanup(profile_path, mode)` → if ephemeral, `shutil.rmtree()`; if persistent, no-op.

---

#### [NEW] [bridge/cookies.py](file:///m:/.systemfile/ChromiumBridge/bridge/cookies.py)

Cookie relay:
- `stage_cookies(cookies_json, companion_dir)` → writes `cookies.json` into the session-local companion extension copy.
- No SQLite manipulation. Pure JSON file write.

---

#### [NEW] [bridge/launcher.py](file:///m:/.systemfile/ChromiumBridge/bridge/launcher.py)

Flag builder + subprocess manager:
- `prepare_companion(profile_dir)` → copies the bundled `chromium-extension/` directory into `{profile_dir}/companion_ext/`, returns the copy path.
- `build_flags(config, options)` → assembles CLI arguments:
  - `--user-data-dir={profile_path}`
  - `--app={url}` or `--window-size=...` depending on mode
  - `--load-extension={profile_dir}/companion_ext/` (session-local copy)
  - `--no-first-run`, `--no-default-browser-check`
  - User's `extra_flags` from config
  - `--incognito` if incognito passthrough
- `launch(browser_path, flags)` → `subprocess.Popen()`, returns process handle.
- `wait_and_cleanup(process, profile_path, mode)` → waits for exit, calls `profile.cleanup()`.

---

#### [NEW] [bridge/config.py](file:///m:/.systemfile/ChromiumBridge/bridge/config.py)

Config management:
- `load()` → reads `config.json` from the bridge directory, returns dict. Creates default if missing.
- `save(config)` → writes config with pretty-print JSON.
- `get(key)` / `set(key, value)` — dot-notation access (e.g., `session.port_cookies`).
- Default config matches the schema in the dev plan.

---

#### [NEW] [bridge/logger.py](file:///m:/.systemfile/ChromiumBridge/bridge/logger.py)

Session logging:
- `log_session(domain, browser, duration, outcome)` → appends to `sessions.log` (JSON lines).
- `get_recent(n=50)` → returns last N sessions.
- `log_launch_time(browser, seconds)` → tracks launch performance.

---

#### [NEW] [bridge/install.py](file:///m:/.systemfile/ChromiumBridge/bridge/install.py)

One-shot installer for registering the native messaging host:
- **Windows**: Creates registry key at `HKCU\Software\Mozilla\NativeMessagingHosts\chromiumbridge` pointing to the host manifest JSON.
- **Linux**: Symlinks/copies manifest to `~/.mozilla/native-messaging-hosts/`.
- **macOS**: Symlinks/copies manifest to `~/Library/Application Support/Mozilla/NativeMessagingHosts/`.
- Generates `manifest.json` for the native host with the correct absolute path to `bridge.py`.
- Accepts `--uninstall` flag to remove registration.

---

#### [NEW] [bridge/manifest.json](file:///m:/.systemfile/ChromiumBridge/bridge/manifest.json)

Template native messaging host manifest:
```json
{
  "name": "chromiumbridge",
  "description": "ChromeBridge native messaging host",
  "path": "<ABSOLUTE_PATH_TO_BRIDGE_PY>",
  "type": "stdio",
  "allowed_extensions": ["chromiumbridges@faisalbhuiyan.com"]
}
```
`install.py` replaces `<ABSOLUTE_PATH_TO_BRIDGE_PY>` with the actual path at install time.

---

### Component 3: Chromium Companion Extension (`chromium-extension/`)

MV3 extension **bundled with the bridge**, loaded into Chromium sessions via `--load-extension`. Never installed from a browser store. Before each launch, the bridge copies this directory into the session's profile dir, writes `cookies.json` into the copy, and points Chromium at the copy. This keeps the original source immutable.

---

#### [NEW] [chromium-extension/manifest.json](file:///m:/.systemfile/ChromiumBridge/chromium-extension/manifest.json)

MV3 manifest:
- Permissions: `cookies`, `storage`
- Host permissions: `<all_urls>`
- Background service worker: `background/receiver.js`
- Content scripts: `content/return-button.js` (match `<all_urls>`)

---

#### [NEW] [chromium-extension/background/receiver.js](file:///m:/.systemfile/ChromiumBridge/chromium-extension/background/receiver.js)

On install/startup:
1. Reads `cookies.json` from its own extension directory via `fetch(chrome.runtime.getURL('cookies.json'))`.
2. For each cookie: calls `chrome.cookies.set({ url, name, value, domain, path, secure, httpOnly, sameSite, expirationDate })`.
3. After all cookies injected, reloads the current tab so the site sees the cookies.
4. Logs `"cookies_injected"` status to console.

---

#### [NEW] [chromium-extension/content/return-button.js](file:///m:/.systemfile/ChromiumBridge/chromium-extension/content/return-button.js)

Floating "← Back to Firefox" button:
- Fixed position, bottom-right corner.
- Styled with shadow DOM for isolation.
- Modern Minimal: white pill with `--primary-main` text and border, subtle shadow.
- On click: sends message to close the window (`window.close()`).
- Dismissible, remembers preference per domain in `chrome.storage.local`.
- Subtle, semi-transparent, expands on hover.

---

### Component 4: Extension Icons

#### [NEW] [firefox-extension/icons/](file:///m:/.systemfile/ChromiumBridge/firefox-extension/icons/)

Generated bridge-themed icons at 48px and 96px sizes using the `--primary-main` (#00A76F) color.

---

## Verification Plan

### Automated Tests
1. **Bridge unit tests**: `python -m pytest bridge/tests/` — test `detect.py` resolution logic, `config.py` read/write, `profile.py` creation/cleanup, native message encoding/decoding.
2. **Extension lint**: `npx web-ext lint` in `firefox-extension/` directory.

### Manual Verification
1. Run `python bridge/install.py` → verify native host registration (Windows registry key exists).
2. Load extension in Firefox via `about:debugging` → click toolbar icon → verify popup renders with correct Modern Minimal styling and green color palette.
3. Click "Open in Chromium" → verify Chromium launches with correct URL.
4. Verify cookie portability: log into a site in Firefox, hand off, check if Chromium session is authenticated.
5. Close Chromium → verify Firefox refocuses and temp profile is cleaned up.
6. Test context menu "Open in Chromium" on links.
7. Test domain rules: add a rule, navigate to the domain, verify auto-handoff.
8. Test signal toggles: enable DRM detection in settings, visit a DRM page, verify badge + banner appear. Disable it, verify no detection.
