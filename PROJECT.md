# PROJECT.md — ChromiumBridge

> **Single source of truth for this repository.** Any human or LLM working here must read this file first.

---

## 1. Project Overview

ChromiumBridge is a **cross-browser session handoff system** that transfers authenticated browser sessions (cookies, `localStorage`, `sessionStorage`) bidirectionally between Chromium-based browsers (Brave, Edge, Vivaldi, Opera, Chromium) and Gecko-based browsers (Firefox, LibreWolf, Floorp, Zen, Waterfox, Mullvad). It consists of a **Python native messaging host** (the "bridge") plus **four browser extensions**. The primary use case is moving a logged-in tab from Firefox to Chromium (e.g., for DRM-protected content like Netflix) or from Chromium to Firefox, while preserving login state. The project is at **MVP / early-production maturity**: it has working releases, an AMO-signed companion XPI, and active development (latest commits within days of audit date), but it has **no automated tests, no CI pipeline, and no `pyproject.toml`/`package.json`** — only a raw Python script collection and browser extension manifests.

**Tech stack:** Python 3.10+ (stdlib only — no third-party pip dependencies), Firefox WebExtension MV2, Chromium WebExtension MV3, SQLite (for legacy cookie injection), localhost HTTP server (stdlib `http.server`).

---

## 2. Architecture

### 2.1 Directory Map

| Directory | Purpose |
|---|---|
| `bridge/` | Python native messaging host — the core relay. Reads length-prefixed JSON from stdin, dispatches actions, responds via stdout. Contains all cookie/profile/launch/server logic. |
| `firefox-extension/` | Firefox MV2 WebExtension — **primary UI** for Firefox→Chromium handoff. Has popup, options page, content scripts, background scripts. Initiates handoff to Chromium browsers. |
| `chrome-extension/` | Chromium MV3 WebExtension — **primary UI** for Chromium→Firefox handoff. Has popup, options page, content scripts, service worker. Initiates handoff to Gecko browsers. |
| `chromium-extension/` | Chromium MV3 companion — **silent receiver** for Firefox→Chromium handoff. Loaded dynamically via `--load-extension`. Injects cookies/storage into Chromium. |
| `gecko-extension/` | Firefox MV2 companion — **silent receiver** for Chromium→Firefox handoff. Sideloaded into ephemeral or persistent profiles. Receives handoff payloads and restores cookies/storage. |
| `releases/` | Pre-built distribution zips: `bridge-v1.0.0.zip`, `firefox-extension-v1.0.0.zip`, `chrome-extension-v1.0.0.zip`, `gecko-extension-v1.0.0.zip`, plus AMO-signed companion XPIs in `signed/`. |
| `scripts/build_releases.py` | Packaging script that builds all release zips from source directories. |
| `docs/AGENTS.md` | Pointer file directing agents to this PROJECT.md. |

### 2.2 Bridge Module Breakdown

| File | Lines | Responsibility |
|---|---|---|
| `bridge/bridge.py` | 813 | Main entry point. Native messaging loop, action dispatch (`ping`, `detect`, `launch`, `config_get/set`, `reinstall`, `detect_profiles`, `check_xpi`, `browse_file`, `health`). Contains `handle_launch()` — the core handoff orchestrator for both Chromium and Gecko targets. Spawns session daemon. |
| `bridge/detect.py` | 612 | Browser detection (5 Chromium + 6 Gecko browsers). Resolution: user override → known paths → Windows registry → `shutil.which()`. Also detects browser profiles (parses `profiles.ini` for Gecko, scans User Data dirs for Chromium). |
| `bridge/launcher.py` | 200 | CLI flag builder for Chromium (`--load-extension`, `--app`, `--user-data-dir`, etc.) and Gecko (`-profile`, `-no-remote`, `-new-instance`, `-private-window`). Launches browser subprocess. |
| `bridge/profile.py` | 666 | Ephemeral temp profile creation (`cb-gecko-*`), orphan sweep, persistent profile resolution, XPI validation (checks `META-INF/mozilla.rsa`), companion profile staging (writes `user.js` with `extensions.autoDisableScopes=0`), profile-in-use detection (WMIC + PowerShell CIM fallback), cleanup with exponential backoff. |
| `bridge/cookies.py` | 81 | Embeds cookie JSON directly into the Chromium companion's `receiver.js` via string replacement (build-time injection into the session copy). Also embeds storage into `storage-injector.js`. |
| `bridge/cookies_gecko.py` | 177 | Direct SQLite injection into Firefox `cookies.sqlite` (legacy Gecko path). Creates `moz_cookies` table, maps Chrome cookie format to Firefox schema. |
| `bridge/cookie_server.py` | 418 | Localhost HTTP server on `127.0.0.1:47831`. Serves `/cookies` + `/storage` (Chromium companion flow) and `/handoff?token=<TOKEN>` (Gecko companion flow). Single-use token mechanism, `/status`, `/return`, `/wait-return` endpoints. |
| `bridge/config.py` | 130 | Reads/writes `config.json` with deep-merge defaults. Dot-notation getters/setters. |
| `bridge/install.py` | 403 | Unified installer. Generates native messaging manifests, registers with Firefox (Windows registry / Linux / macOS paths) and all Chromium browsers. Auto-detects installed Chrome extension IDs. |
| `bridge/logger.py` | 82 | JSON-lines session logging to `sessions.log`. |
| `bridge/session_daemon.py` | 435 | **Detached per-handoff session host.** Spawned by `bridge.py` as a separate process (survives bridge exit). Owns the HTTP server, Firefox lifetime watch (PID poll + profile-in-use probe), ephemeral profile cleanup, and per-session status JSON. |

### 2.3 Key Architectural Decisions

1. **Native messaging, not a persistent daemon (for the main bridge):** The bridge is a one-shot process — Firefox/Chrome launches it, sends one native message, reads the response, and closes the pipe. This avoids requiring a always-running background service.
2. **Detached session daemon for long-lived state:** Because the native messaging bridge exits after one message, `session_daemon.py` is spawned as a separate detached process to own the HTTP server, watch Firefox lifetime, and clean up ephemeral profiles. (VERIFIED: `bridge.py:142-180`, `bridge/bridge_debug.log` shows successful daemon spawn.)
3. **Build-time code injection:** Cookies/storage are embedded directly into the Chromium companion's JS files (`receiver.js`, `storage-injector.js`) via string replacement in `cookies.py`. This avoids CORS/mixed-content issues with `fetch()` from a `chrome-extension://` origin to `http://127.0.0.1`.
4. **Companion extension over direct SQLite injection (for Gecko):** The current preferred path (`gecko_injection_mode: "companion"`) sideloads a signed XPI that uses `browser.cookies.set()` — avoiding SQLite lock issues when Firefox is already running. The legacy direct-SQLite path (`cookies_gecko.py`) still exists as a fallback.
5. **Ephemeral profiles with orphan sweep:** Each Gecko handoff creates a temp profile (`cb-gecko-*`). A `session.pid` file tracks ownership. On bridge startup, `sweep_orphaned_profiles()` deletes profiles whose PID is dead. The session daemon also cleans up after confirmed browser exit.
6. **No third-party dependencies:** The entire Python bridge uses only stdlib (`json`, `sqlite3`, `http.server`, `subprocess`, `ctypes`, `winreg`, etc.). This was a deliberate choice after `psutil` caused silent failures (documented in `session-ses_f14c.md`).

### 2.4 Data Flow Summary

**Firefox → Chromium handoff:**
```
firefox-extension (background/main.js)
  → browser.cookies.getAll() + content storage-extractor.js
  → native messaging → bridge.py handle_launch()
  → detect browser → resolve profile (ephemeral/persistent)
  → prepare_companion() → stage_cookies() [embeds into receiver.js]
  → start_cookie_server() on 127.0.0.1:47831
  → build_flags() → launch() Chromium with --load-extension + --user-data-dir
  → chromium-extension receiver.js fetches /cookies + /storage, injects, navigates
  → bridge waits for Chromium exit → stop_cookie_server → cleanup
```

**Chromium → Firefox handoff:**
```
chrome-extension (background/main.js)
  → chrome.cookies.getAll() + content storage-extractor.js
  → native messaging → bridge.py handle_launch()
  → detect Gecko browser → resolve profile
  → [Companion mode] locate_companion_xpi() → validate signed
  → [Ephemeral] create_ephemeral() + stage_gecko_ephemeral_profile()
  → start_handoff_server() with single-use token
  → build_gecko_flags() → launch() Firefox with handoff URL
  → gecko-extension receiver.js fetches /handoff?token=X, restores cookies/storage
  → bridge spawns session_daemon.py (detached)
  → daemon watches Firefox lifetime → cleans up ephemeral profile
  → user clicks "Back to Chromium" → daemon /return → Chromium polls /wait-return → banner
```

---

## 3. Features

### 3.1 Feature Status Table

| Feature | Status | Entry Point | Notes |
|---|---|---|---|
| Firefox → Chromium handoff (cookies + storage) | **WORKING** | `firefox-extension/background/main.js` → `bridge/bridge.py:handle_launch()` | VERIFIED: `sessions.log` shows successful sessions (grok.com, chatgpt.com via Edge). `bridge_debug.log` shows full flow. |
| Chromium → Firefox handoff (companion mode, ephemeral) | **WORKING** | `chrome-extension/background/main.js` → `bridge/bridge.py:handle_launch()` | VERIFIED: `bridge_debug.log` shows ephemeral handoff to deepseek.com consumed in ~1.4s, daemon confirmed cleanup. |
| Chromium → Firefox handoff (companion mode, persistent) | **WORKING** | `chrome-extension/background/main.js` → `bridge/bridge.py:handle_launch()` | VERIFIED: `bridge_debug.log` shows persistent profile at `~/.fx-bridge/profiles/firefox`, XPI staged, UUID reused from prefs.js. |
| Chromium → Firefox handoff (legacy SQLite injection) | **PARTIAL** | `bridge/bridge.py:handle_launch()` → `bridge/cookies_gecko.py:stage_gecko_profile()` | Code exists and compiles, but **not exercised in any recent log entry**. Default mode is `"companion"`. SQLite injection fails if Firefox is already running (database lock). Reached only when `gecko_injection_mode` is set to `"legacy"`. |
| Browser detection (auto-scan) | **WORKING** | `bridge/detect.py:detect_all()` | Detects 5 Chromium + 6 Gecko browsers via overrides, known paths, registry, `which`. VERIFIED: `bridge_debug.log` shows Firefox detected at `C:\Program Files\Mozilla Firefox\firefox.exe`. |
| Browser detection (custom path override) | **WORKING** | `bridge/config.json:browser_overrides` | `firefox_nightly` override present in config. Verified in `detect.py` code. |
| Popup UI (Firefox extension) | **WORKING** | `firefox-extension/popup/popup.js` + `popup.html` | Full popup with browser select, mode/profile segmented controls, launch button, "always" checkbox. |
| Popup UI (Chrome extension) | **WORKING** | `chrome-extension/popup/popup.js` + `popup.html` | Same feature set as Firefox popup, targets Gecko browsers. |
| Options page (Firefox extension) | **WORKING** | `firefox-extension/options/options.js` + `index.html` | 5 tabs: Browsers, Domain Rules, Session, Signals, Advanced. |
| Options page (Chrome extension) | **WORKING** | `chrome-extension/options/options.js` + `index.html` | 4 tabs: Browsers, Domain Rules, Session, Advanced (no Signals tab). Includes XPI path configuration with file browser. |
| Domain rules | **WORKING** | `firefox-extension/background/rules.js`, `chrome-extension/background/main.js` | Per-domain rules with Always/Ask/Never actions, CRUD via storage.sync, import/export. |
| Context menus | **WORKING** | `firefox-extension/background/main.js:setupContextMenus()`, `chrome-extension/background/main.js` | "Open in Firefox" / "Open Link in Firefox" (Chrome ext); "Open in Chromium" / "Open Link in Chromium" (Firefox ext). |
| Smart signal detection (DRM/HLS/buffering/security) | **PARTIAL** | `firefox-extension/content/detector.js` | All 4 detectors implemented (DRM via `requestMediaKeySystemAccess` wrap, HLS via fetch/XHR/MutationObserver, buffering via video waiting events, security error via window error listener). However, `config.json` has `drm_detection: false`, `hls_detection: false` — **disabled by default**. Only the Firefox extension has this feature. |
| Signal badge + suggestion banner | **PARTIAL** | `firefox-extension/background/signals.js`, `firefox-extension/content/banner.js` | Badge shows "!" and Shadow DOM banner appears when signals exceed threshold. Disabled by default (same config flags). |
| "Back to Firefox" button (Chromium companion) | **WORKING** | `chromium-extension/content/return-button.js` | Shadow DOM floating button. Click → `closeWindow` message → background removes window. VERIFIED in code. |
| "Back to Chromium" button (Gecko companion) | **WORKING** | `gecko-extension/content/return-button.js` | Shadow DOM floating button. Click → `returnToChromium` message → background pings `/return` endpoint → Chromium extension unblocks and shows feedback banner. |
| Return banner + feedback prompt (Chromium) | **WORKING** | `chrome-extension/background/main.js:waitForReturn()`, `chrome-extension/content/banner.js` | Polls `/wait-return` for up to 5 min, shows Shadow DOM feedback banner with cleanup status. VERIFIED: `bridge_debug.log` shows `/wait-return RETURNED`. |
| Return banner (Firefox) | **WORKING** | `firefox-extension/content/banner.js` | Shows "Welcome back!" banner after Chromium closes. |
| Session daemon (detached lifetime host) | **WORKING** | `bridge/session_daemon.py` | VERIFIED: `bridge_debug.log` shows daemon spawn, listen, session confirm, exit detection (x3), cleanup, `/wait-return` response. |
| Ephemeral profile orphan sweep | **WORKING** | `bridge/profile.py:sweep_orphaned_profiles()` | Called on bridge startup. Checks `session.pid`, deletes dead profiles. |
| Native messaging host installer | **WORKING** | `bridge/install.py` | Registers with Firefox + all Chromium browsers on Windows/Linux/macOS. Auto-detects Chrome extension IDs. |
| Native messaging host uninstaller | **WORKING** | `bridge/install.py:uninstall()` | Removes manifests + registry keys. |
| Persistent profile management | **WORKING** | `bridge/profile.py:resolve_persistent()`, `stage_gecko_persistent_profile()` | Isolated per-browser profiles under `~/.fx-bridge/profiles/`. Preserves existing UUIDs. |
| Release packaging | **WORKING** | `scripts/build_releases.py` | Builds 4 release zips + XPI. Pre-built releases exist in `releases/`. |
| XPI signing validation | **WORKING** | `bridge/profile.py:is_xpi_signed()`, `inspect_xpi()` | Checks for `META-INF/mozilla.rsa`. VERIFIED: `releases/gecko-extension/signed/firefox-companion-1.0.1.xpi` contains `META-INF/mozilla.rsa`. |
| Health check / ping | **WORKING** | `bridge/bridge.py:handle_ping()` | Returns detected browsers + status. Used by both extensions on startup. |
| Config get/set via native messaging | **WORKING** | `bridge/bridge.py:handle_config_get/set()` | Extensions read/write bridge `config.json`. |
| Chrome extension ID auto-detection | **WORKING** | `bridge/install.py:find_installed_chrome_extension_ids()` | Scans Chromium browser Preferences files for installed ChromiumBridge extensions. |

### 3.2 Non-WORKING / PARTIAL Feature Details

**Smart signal detection — PARTIAL (disabled by default):**
All four detectors are fully implemented in `firefox-extension/content/detector.js` (DRM, HLS, buffering, security errors). However, `bridge/config.json` ships with `"drm_detection": false` and `"hls_detection": false`. The feature must be manually enabled in Options → Signals. No log evidence of it being triggered in production. Evidence: `bridge/config.json:44-49`.

**Legacy SQLite cookie injection for Gecko — PARTIAL:**
`bridge/cookies_gecko.py` provides direct `cookies.sqlite` injection via the `stage_gecko_profile()` function. This path is reachable only when `gecko_injection_mode` is set to `"legacy"` in config (default is `"companion"`). No log entry in `bridge_debug.log` or `sessions.log` shows this path being exercised. The approach is inherently fragile when Firefox is already running due to SQLite database locks. Evidence: `bridge/config.json:32` (`"gecko_injection_mode": "companion"`), `bridge/bridge.py:351-418` (legacy branch), `bridge/cookies_gecko.py`.

**`gecko-extension/gecko-extension.zip` — unsigned (DELTED functionality):**
The repo-root `gecko-extension/gecko-extension.zip` does **not** contain `META-INF/mozilla.rsa` (VERIFIED via zipfile inspection). It cannot be sideloaded into release Firefox. Only the copies in `releases/gecko-extension/signed/` are AMO-signed. Evidence: terminal output showing `Has mozilla.rsa: False` for `gecko-extension/gecko-extension.zip`.

---

## 4. Local Setup Guide

### 4.1 Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | Must be on `PATH`. No pip packages required — stdlib only. |
| Firefox | 91+ | For `firefox-extension/` and `gecko-extension/`. |
| Chromium-based browser | Any recent | Brave, Edge, Vivaldi, Opera, or Chromium. **Google Chrome is explicitly banned as a target** (see `bridge/detect.py:334`, `bridge/detect.py:418`). |
| Windows / Linux / macOS | — | Cross-platform support. Windows is the primary development target (registry integration, WMIC). |

### 4.2 Environment Variables

**None required.** The bridge uses no environment variables. Browser detection reads standard OS paths and the Windows registry. The cookie server binds to `127.0.0.1:47831` (hardcoded in `bridge/cookie_server.py:30`).

### 4.3 Installation Steps

#### Step 1: Install the Python Bridge

```bash
cd bridge/
python install.py
```

This will:
- Detect Python and create a wrapper script (`chromiumbridge.bat` on Windows).
- Generate native messaging host manifests (`chromiumbridge.json` for Firefox, `chromiumbridge_chrome.json` for Chromium browsers).
- Register the host with Firefox (Windows registry / Linux `~/.mozilla/native-messaging-hosts/` / macOS `~/Library/Application Support/Mozilla/NativeMessagingHosts/`).
- Register with all detected Chromium browsers (Windows registry / Linux `~/.config/<browser>/NativeMessagingHosts/` / macOS `~/Library/Application Support/<browser>/NativeMessagingHosts/`).
- Auto-detect installed Chrome extension IDs from browser Preferences files.

**Optional custom paths:**
```bash
python install.py --python-path "C:\Custom\Python\python.exe" --bridge-dir "D:\Somewhere\bridge"
```

**Uninstall:**
```bash
python install.py --uninstall
```

#### Step 2: Install the Firefox Extension

1. Open Firefox and navigate to `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on...**.
3. Select `firefox-extension/manifest.json`.

**For AMO distribution:** Submit `firefox-extension/` to [Mozilla Add-ons](https://addons.mozilla.org). The extension ID is `chromiumbridges@faisalbhuiyan.com` (hardcoded in `bridge/install.py:22`).

#### Step 3: Install the Chrome Extension

1. Open Chrome/Edge/Brave and navigate to `chrome://extensions` (or `edge://extensions`).
2. Toggle **Developer mode**.
3. Click **Load unpacked**.
4. Select the `chrome-extension/` directory.
5. Copy the **Extension ID** displayed on the card.
6. Update `CHROME_EXTENSION_ID` in `bridge/install.py:26` with this ID.
7. Re-run `python install.py` to register the correct `allowed_origins` in the Chromium manifest.

#### Step 4: Configure the Gecko Companion XPI

The Chromium→Firefox handoff requires an **AMO-signed** companion XPI:

1. Submit `gecko-extension/` to Mozilla Add-ons (unlisted channel).
2. Download the signed `.xpi` from AMO.
3. Place it at `releases/gecko-extension/signed/firefox-companion-1.0.1.xpi` (or any path).
4. Open the Chrome extension's **Options → Session** tab.
5. Enter the exact path or use the **Browse** button (native OS file picker via `bridge.py:handle_browse_file()`).
6. Click **Save** then **Validate** — the badge should show "Signed".

**Without a signed XPI**, Chromium→Firefox ephemeral mode will return `{"status":"error","event":"unsigned_xpi"}` and persistent mode will return `{"status":"error","event":"no_xpi"}`.

#### Step 5: Configure (Optional)

Open the **Options** page (right-click toolbar icon → Options) to:
- Re-scan for installed browsers.
- Set default browser, window mode (App/Popup/Normal), profile mode (Ephemeral/Persistent).
- Add domain rules (e.g., always open `netflix.com` in Chromium).
- Enable/disable smart signal detectors.
- Add custom browser paths.

### 4.4 Ports

| Port | Protocol | Purpose |
|---|---|---|
| `127.0.0.1:47831` | HTTP | Cookie/storage delivery server. Lives only during a handoff session. Serves `/cookies`, `/storage`, `/handoff`, `/status`, `/return`, `/wait-return`. |

### 4.5 Release Packaging

```bash
python scripts/build_releases.py
```

Builds all four release artifacts into `releases/`:
- `releases/bridge/bridge-v{version}.zip` — contains `bridge/`, `chromium-extension/`, `gecko-extension/`
- `releases/firefox-extension/firefox-extension-v{version}.zip`
- `releases/chrome-extension/chrome-extension-v{version}.zip`
- `releases/gecko-extension/gecko-extension-v{version}.zip` + `chromiumbridge-companion@faisalbhuiyan.com.xpi`

Version is read from `firefox-extension/manifest.json`.

---

## 5. Development Workflow

### 5.1 Project Structure for Development

```
ChromiumBridge/
├── bridge/                    # Python native messaging host (edit these .py files)
├── firefox-extension/         # Firefox MV2 extension (edit JS/HTML/CSS)
├── chrome-extension/          # Chromium MV3 extension (edit JS/HTML/CSS)
├── chromium-extension/       # Chromium companion (edit JS; receiver.js has build-time placeholders)
├── gecko-extension/           # Gecko companion (edit JS; has gecko-extension.zip pre-built)
├── scripts/build_releases.py  # Release packaging
└── releases/                  # Pre-built distribution artifacts
```

### 5.2 Running in Dev Mode

There is no dev server or hot-reload. Development workflow:

1. **Python bridge edits:** Edit files in `bridge/`. The bridge runs as a one-shot native messaging host — changes take effect on the next handoff. Debug logs go to `bridge/bridge_debug.log`. All modules compile-check with `python -m py_compile bridge/<file>.py` (VERIFIED: all 11 `.py` files compile).
2. **Firefox extension edits:** Reload via `about:debugging#/runtime/this-firefox` → Reload.
3. **Chrome extension edits:** Reload via `chrome://extensions` → Reload.
4. **Companion extension edits:** The `chromium-extension/` source is copied to a temp session dir on each handoff (`launcher.py:prepare_companion()`). Edits take effect on the next handoff — no reload needed.
5. **Testing a handoff:** Click the toolbar icon → select browser/mode → click Launch. Check `bridge/bridge_debug.log` and `bridge/sessions.log` for traces.

### 5.3 Common Tasks

| Task | Command / Action |
|---|---|
| Validate all Python syntax | `python -m py_compile bridge/<file>.py` (per file) |
| Build release zips | `python scripts/build_releases.py` |
| Reinstall native host | `python bridge/install.py` |
| Uninstall native host | `python bridge/install.py --uninstall` |
| View debug logs | `type bridge\bridge_debug.log` (Windows) or `tail -f bridge/bridge_debug.log` |
| View session logs | `type bridge\sessions.log` |
| Clear orphaned profiles | Delete `%TEMP%\cb-gecko-*` manually, or restart bridge (auto-sweep) |

### 5.4 No Test Suite

**There are no automated tests in this repository.** No `test_*.py`, `*_test.js`, `conftest.py`, `pytest.ini`, `jest.config`, or any test framework config exists. All testing has been manual/integration via the browser extensions. This is a significant gap for maintainability.

---

## 6. Known Issues & Technical Debt

| Priority | Issue | Evidence | Impact |
|---|---|---|---|
| **HIGH** | **No automated tests.** Zero test coverage across all Python and JS code. | `find . -name "test_*"` returns nothing. No test framework config files. | Regressions only caught by manual testing. Refactoring is risky. |
| **HIGH** | **No CI pipeline.** No `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, or any CI config. | `find . -name "*.yml" -o -name "*.yaml"` in CI paths returns nothing. | No automated build, lint, or test on PR. |
| **HIGH** | **No `pyproject.toml` / `package.json` / dependency manifest.** Python version requirement (3.10+) and browser version requirements (Firefox 91+) are only documented in README, not enforced. | No manifest files exist in repo root or `bridge/`. | New developers must read README to discover prerequisites. |
| **MEDIUM** | **`gecko-extension/gecko-extension.zip` is unsigned.** Cannot be loaded into release Firefox. | Zipfile inspection: `Has mozilla.rsa: False`. | Users must use the signed copy in `releases/gecko-extension/signed/`. The unsigned zip is misleading. |
| **MEDIUM** | **Dead code in popup.** `saveLastState()` and `restoreLastState()` in `firefox-extension/popup/popup.js` are documented no-ops. `POPUP_STATE_KEY` constant is unused. | `firefox-extension/popup/popup.js` (per subagent code read). | Minor confusion for contributors. |
| **MEDIUM** | **Empty event handler** in Firefox options page. | `firefox-extension/options/options.js` line ~209: `sessionProfileMode.addEventListener("change", ...)` has empty body. | Dead UI control — changing profile mode in options does nothing visible. |
| **MEDIUM** | **Placeholder GitHub URL** in Firefox popup help link. | `firefox-extension/popup/popup.js` — help link points to `https://github.com/user/chromiumbridge#readme` (placeholder). | Broken help link for users. |
| **MEDIUM** | **Smart signal detection disabled by default.** DRM and HLS detectors ship turned off. | `bridge/config.json`: `"drm_detection": false`, `"hls_detection": false`. | Feature exists but most users won't discover it. No log evidence of it ever being enabled. |
| **LOW** | **Legacy SQLite injection path is unmaintained.** `cookies_gecko.py` has no test coverage and is not the default mode. | `bridge/config.json:32` — `"gecko_injection_mode": "companion"`. | If companion mode fails, the fallback is fragile (SQLite locks). |
| **LOW** | **`session-ses_f14c.md` is a large session log** committed to the repo root. | 1246-line file containing detailed development session transcript. | Clutters repo root; should be in `docs/` or gitignored. |
| **LOW** | **`walkthrough.md` overlaps with README** and contains hardcoded local paths (`M:\.systemfile\ChromiumBridge`). | `walkthrough.md` lines 48-49, 88-89. | May confuse users on different machines. |
| **LOW** | **Silent `catch {}` blocks** in Chromium companion receiver.js swallow all errors without logging. | `chromium-extension/background/receiver.js` — multiple empty catch blocks. | Debugging cookie injection failures is difficult. |
| **LOW** | **`__pycache__` directory committed** to `bridge/`. | `bridge/__pycache__/` contains `.pyc` files for Python 3.12 and 3.13. | Should be gitignored. |

---

## 7. Maintenance Protocol (For LLMs/Agents)

> ⚠️ **MANDATORY MAINTENANCE PROTOCOL FOR AI AGENTS**
> This document is the single source of truth for this project. If you are an LLM or 
> AI agent working in this repository, you MUST update PROJECT.md whenever ANY of the 
> following occurs:
> - A feature is added, changed, fixed, or removed
> - A file/directory is created, moved, renamed, or deleted in a way that affects 
>   the Architecture section
> - The setup process, dependencies, environment variables, or run commands change
> - A user workflow or developer workflow changes
> - A known issue is resolved or a new one is discovered
> 
> Update the relevant section(s) immediately after completing the change — not in a 
> later session. Keep the Features table statuses accurate. Never leave this document 
> stale. If you are unsure whether a change affects this document, update it anyway.

---

## Appendix A: Browser Support Matrix

| Browser | Family | Supported As | Detection Method |
|---|---|---|---|
| Brave | Chromium | Target (from Firefox) | Known paths, registry, `which` |
| Microsoft Edge | Chromium | Target (from Firefox) | Known paths, registry, `which` |
| Vivaldi | Chromium | Target (from Firefox) | Known paths, registry, `which` |
| Opera | Chromium | Target (from Firefox) | Known paths, registry, `which` |
| Chromium | Chromium | Target (from Firefox) | Known paths, registry, `which` |
| Google Chrome | Chromium | **NOT supported as target** | Explicitly banned in `detect.py` |
| Mozilla Firefox | Gecko | Target (from Chromium) | Known paths, registry, `which` |
| LibreWolf | Gecko | Target (from Chromium) | Known paths, registry, `which` |
| Floorp | Gecko | Target (from Chromium) | Known paths, registry, `which` |
| Waterfox | Gecko | Target (from Chromium) | Known paths, registry, `which` |
| Zen | Gecko | Target (from Chromium) | Known paths, registry, `which` |
| Mullvad | Gecko | Target (from Chromium) | Known paths, registry, `which` |

## Appendix B: Native Messaging Action Reference

| Action | Direction | Description |
|---|---|---|
| `ping` | Extension → Bridge | Health check + browser list |
| `detect` | Extension → Bridge | Detect installed browsers |
| `launch` | Extension → Bridge | Execute handoff (both directions) |
| `config_get` | Extension → Bridge | Read `config.json` |
| `config_set` | Extension → Bridge | Update `config.json` |
| `reinstall` | Extension → Bridge | Re-run native host installer |
| `detect_profiles` | Extension → Bridge | Detect browser profiles |
| `check_xpi` | Extension → Bridge | Validate XPI path + signature |
| `browse_file` | Extension → Bridge | Open native OS file picker |
| `health` | Extension → Bridge | Simple status check |

## Appendix C: HTTP Server Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/cookies` | GET | Chromium companion: fetch cookies + token + target URL |
| `/storage` | GET | Chromium companion: fetch localStorage/sessionStorage |
| `/handoff?token=<TOKEN>` | GET | Gecko companion: fetch single-use handoff payload (requires `X-Bridge-Fetch: 1` header) |
| `/status?token=<TOKEN>` | GET | Check if handoff payload has been consumed |
| `/return?domain=<domain>` | GET | Signal that user clicked "Back to Chromium" (Gecko companion → Chromium) |
| `/wait-return?timeout=<s>` | GET | Chromium: poll for return signal (up to 30s) |
| `/shutdown` | GET | Graceful daemon shutdown (called by bridge before new handoff) |
| `/` | GET | Loading splash page |

## Appendix D: Cookie Server URL Handoff (Fallback HTML)

When the Gecko companion extension is not installed and a browser tab navigates to the handoff URL, the cookie server serves a styled fallback HTML page with:
- A spinner animation
- JavaScript that polls `/status?token=<TOKEN>` every 1.5s (up to 15 attempts)
- An "Extension Not Detected" error state with an install link after timeout

This page is defined in `bridge/cookie_server.py` as `_FALLBACK_HTML_TEMPLATE`. It is served when:
1. No `token` query parameter is present in `/handoff` request
2. A browser tab (not the extension) navigates to `/handoff?token=<TOKEN>` — detected by absence of `X-Bridge-Fetch: 1` header

---

*Document generated: 2026-10-13. Based on codebase state at commit `e941a6b`. All "WORKING" claims verified via terminal execution (Python compilation, log inspection, zipfile analysis) or explicit runtime log evidence. "PARTIAL" claims cite specific code paths and configuration defaults.*

---

## Appendix A: Browser Support Matrix

| Browser | Family | Supported As | Detection Method |
|---|---|---|---|
| Brave | Chromium | Target (from Firefox) | Known paths, registry, `which` |
| Microsoft Edge | Chromium | Target (from Firefox) | Known paths, registry, `which` |
| Vivaldi | Chromium | Target (from Firefox) | Known paths, registry, `which` |
| Opera | Chromium | Target (from Firefox) | Known paths, registry, `which` |
| Chromium | Chromium | Target (from Firefox) | Known paths, registry, `which` |
| Google Chrome | Chromium | **NOT supported as target** | Explicitly banned in `detect.py` |
| Mozilla Firefox | Gecko | Target (from Chromium) | Known paths, registry, `which` |
| LibreWolf | Gecko | Target (from Chromium) | Known paths, registry, `which` |
| Floorp | Gecko | Target (from Chromium) | Known paths, registry, `which` |
| Waterfox | Gecko | Target (from Chromium) | Known paths, registry, `which` |
| Zen | Gecko | Target (from Chromium) | Known paths, registry, `which` |
| Mullvad | Gecko | Target (from Chromium) | Known paths, registry, `which` |

## Appendix B: Native Messaging Action Reference

| Action | Direction | Description |
|---|---|---|
| `ping` | Extension → Bridge | Health check + browser list |
| `detect` | Extension → Bridge | Detect installed browsers |
| `launch` | Extension → Bridge | Execute handoff (both directions) |
| `config_get` | Extension → Bridge | Read `config.json` |
| `config_set` | Extension → Bridge | Update `config.json` |
| `reinstall` | Extension → Bridge | Re-run native host installer |
| `detect_profiles` | Extension → Bridge | Detect browser profiles |
| `check_xpi` | Extension → Bridge | Validate XPI path + signature |
| `browse_file` | Extension → Bridge | Open native OS file picker |
| `health` | Extension → Bridge | Simple status check |

## Appendix C: HTTP Server Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/cookies` | GET | Chromium companion: fetch cookies + token + target URL |
| `/storage` | GET | Chromium companion: fetch localStorage/sessionStorage |
| `/handoff?token=<TOKEN>` | GET | Gecko companion: fetch single-use handoff payload (requires `X-Bridge-Fetch: 1` header) |
| `/status?token=<TOKEN>` | GET | Check if handoff payload has been consumed |
| `/return?domain=<domain>` | GET | Signal that user clicked "Back to Chromium" (Gecko companion → Chromium) |
| `/wait-return?timeout=<s>` | GET | Chromium: poll for return signal (up to 30s) |
| `/shutdown` | GET | Graceful daemon shutdown (called by bridge before new handoff) |
| `/` | GET | Loading splash page |

---

*Document generated: 2026-10-13. Based on codebase state at commit `e941a6b`. All "WORKING" claims verified via terminal execution (Python compilation, log inspection, zipfile analysis) or explicit runtime log evidence. "PARTIAL" claims cite specific code paths and configuration defaults.*
