# AGENTS.md — ChromiumBridge System Documentation for LLMs

> Canonical, context-optimized technical reference for autonomous coding agents and LLMs.
> Target: Zero-fluff, high token density, exact schemas, strict invariants, and actionable operational protocols.

---

## 1. System Identity & Mission

- **Project**: ChromiumBridge (Bidirectional Browser Bridge)
- **Purpose**: Moves active tabs and their authentication state (cookies, `localStorage`, `sessionStorage`) between Firefox/Gecko and Chromium browsers in a single click or automatically via rules/signals.
  - **Direction A (Firefox → Chromium)**: Handoff from Firefox into Brave, Edge, Vivaldi, Opera, or unbranded Chromium. (Primary: DRM/Widevine media, low-latency HLS, WebGL, PWA app-mode).
  - **Direction B (Chromium → Gecko)**: Handoff from Chrome/Brave/Edge into Firefox, LibreWolf, Floorp, Zen Browser, or Waterfox. (Primary: Anti-fingerprinting, container isolation, Gecko extension ecosystem).
- **Repository Layout**:
  - `bridge/`: Unified Python 3.10+ Native Messaging Host (serves both Firefox and Chromium).
  - `firefox-extension/`: Firefox WebExtension (Manifest V2, Gecko source).
  - `chrome-extension/`: Chromium WebExtension (Manifest V3, Chromium source).
  - `chromium-extension/`: Chromium Companion Extension (Manifest V3, dynamically loaded helper into Chromium target).
  - `scripts/build_releases.py`: Automated release packager for all components.
  - `releases/`: Bundled release zip archives (`bridge/`, `firefox-extension/`, `chrome-extension/`).

---

## 2. Bidirectional Architecture & Roles

```
┌───────────────────────────────────────┐        ┌───────────────────────────────────────┐
│     FIREFOX EXTENSION (Source MV2)    │        │     CHROME EXTENSION (Source MV3)     │
│  ID: chromiumbridges@faisalbhuiyan.com │        │  Chrome, Brave, Edge, Vivaldi, Opera  │
│  • UI: Popup, Options, Context Menu   │        │  • UI: Popup, Options, Context Menu   │
│  • Content: DRM/HLS, Storage Extractor│        │  • Content: Storage Extractor         │
└───────────────────┬───────────────────┘        └───────────────────┬───────────────────┘
                    │                                                │
                    │ Native Messaging (4-byte LE prefix + JSON)     │
                    └───────────────────────┬────────────────────────┘
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        UNIFIED PYTHON BRIDGE (Native Messaging Host)                   │
│  Host Name: chromiumbridge                                                            │
│  • Multi-Host Registration: Mozilla HKCU + Google/Brave/Edge/Vivaldi/Opera HKCU        │
│  • Dual-Family Detection: Chromium targets (Brave, Edge...) & Gecko (Firefox, Zen...)  │
│  • Profile Lifecycle: Ephemeral temp profiles & persistent user data paths             │
│  • Subprocess Execution: Dispatches to Chromium launcher or Gecko launcher            │
└───────────────────────┬────────────────────────────────────────┬───────────────────────┘
                        │ Target: Chromium                       │ Target: Gecko
                        ▼                                        ▼
┌──────────────────────────────────────────────┐ ┌───────────────────────────────────────┐
│         CHROMIUM BROWSER INSTANCE            │ │       FIREFOX / GECKO INSTANCE        │
│  Brave / Edge / Vivaldi / Opera / Chromium   │ │  Firefox / LibreWolf / Floorp / Zen   │
│                                              │ │                                       │
│  • Flags: --load-extension, --app, etc.      │ │  • Flags: -profile, -no-remote, etc.  │
│  • Companion: Injects cookies via service    │ │  • Cookies: Direct SQLite write into  │
│    worker (receiver.js)                      │ │    cookies.sqlite before launch       │
│  • Floating "Back to Firefox" UI button      │ │  • Automation: Clean user.js config   │
└──────────────────────────────────────────────┘ └───────────────────────────────────────┘
```

---

## 3. Codebase File Map

| File Path | Role & Summary | Key Functions / Exports |
|-----------|----------------|-------------------------|
| `bridge/bridge.py` | Unified native messaging loop & dispatcher | `read_message()`, `send_message()`, `handle_launch()`, `handle_ping()`, `handle_detect()`, `main()` |
| `bridge/detect.py` | OS-agnostic browser & profile detection | `detect_all()`, `resolve_browser()`, `detect_profiles()`, `get_browser_family()`, `BROWSER_DEFS` |
| `bridge/launcher.py` | Flag assembly, staging, subprocess runner | `build_flags()`, `build_gecko_flags()`, `prepare_companion()`, `launch()`, `wait_and_cleanup()` |
| `bridge/cookies.py` | In-place code injection into companion | `stage_cookies(cookies, target_url, companion_dir)` |
| `bridge/cookies_gecko.py` | Direct SQLite writer for Firefox targets | `stage_gecko_profile()`, `inject_gecko_cookies()` |
| `bridge/cookie_server.py` | Transient HTTP server (`127.0.0.1:47831`) | `start_cookie_server()`, `stop_cookie_server()`, `_CookieHandler` |
| `bridge/profile.py` | Ephemeral & persistent profile lifecycle | `create_ephemeral()`, `resolve_persistent()`, `validate_profile()`, `cleanup()` |
| `bridge/config.py` | Config reader/writer (`bridge/config.json`) | `load_config()`, `save_config()`, `get_config_value()`, `set_config_value()` |
| `bridge/install.py` | Multi-browser host manifest installer | `install()`, `uninstall()`, `reinstall_from_config()`, `generate_mozilla_manifest()`, `generate_chromium_manifest()` |
| `bridge/logger.py` | JSON-lines session telemetry | `log_session()`, `log_launch_time()`, `get_recent()` |
| `firefox-extension/` | Source extension for Firefox (MV2) | `manifest.json`, `background/`, `content/`, `popup/`, `options/` |
| `chrome-extension/` | Source extension for Chromium (MV3) | `manifest.json`, `background/main.js`, `content/storage-extractor.js`, `popup/`, `options/` |
| `chromium-extension/` | Injected companion for Chromium targets (MV3) | `manifest.json`, `background/receiver.js`, `content/return-button.js` |
| `scripts/build_releases.py` | Automated release zip packager | Builds `releases/bridge/`, `releases/firefox-extension/`, `releases/chrome-extension/` |

---

## 4. End-to-End Execution Flows

### A. Firefox → Chromium Flow
1. User clicks "Open in Chromium" (or triggered by DRM/rule) in `firefox-extension/`.
2. `main.js` collects cookies and storage, sends `{ action: "launch", browser: "brave", ... }` via native messaging.
3. Bridge detects target family is `"chromium"`:
   - Stages companion extension into `%TEMP%\cb-sessions\<uuid>\companion_ext`.
   - Injects cookies into `receiver.js` and starts HTTP server on `127.0.0.1:47831`.
   - Launches Chromium with flags (`--load-extension`, `--disable-background-mode`, etc.).
   - Companion extension service worker sets cookies via `chrome.cookies.set()` and redirects.
4. User closes Chromium window -> bridge detects exit, cleans up temp profile, refocuses Firefox tab.

### B. Chromium → Gecko/Firefox Flow
1. User clicks "Open in Firefox" (or rule match) in `chrome-extension/`.
2. Service worker `main.js` collects cookies (`chrome.cookies.getAll`) and storage, sends `{ action: "launch", browser: "firefox", ... }`.
3. Bridge detects target family is `"gecko"`:
   - Creates ephemeral profile directory (`tempfile.mkdtemp(prefix="fx-gecko-")`).
   - Writes `user.js` (suppressing first-run, telemetry, and default browser prompts).
   - Writes cookies directly into `cookies.sqlite` using Python's built-in `sqlite3` (`moz_cookies` table).
   - Launches Firefox with flags (`-profile <dir> -no-remote -new-instance <url>`).
   - Firefox starts up fully authenticated instantly—zero extension dependency in target!
4. User closes Firefox window -> bridge detects process termination, removes temp profile directory, refocuses original Chromium tab.

---

## 5. IPC & Native Messaging Protocols

- **Transport**: Standard input (`sys.stdin.buffer`) / Standard output (`sys.stdout.buffer`).
- **Framing**: Exact 4-byte unsigned integer (little-endian `=I`) representing byte length of JSON payload, followed immediately by UTF-8 encoded JSON.
- **Shebang**: `#!/usr/bin/env python3 -u` (Unbuffered mode is mandatory; stdout must be explicitly flushed).

### Host Registration Matrix
- **Mozilla Firefox**:
  - Windows: `HKCU\Software\Mozilla\NativeMessagingHosts\chromiumbridge` → `chromiumbridge.json`
  - Linux: `~/.mozilla/native-messaging-hosts/chromiumbridge.json`
  - macOS: `~/Library/Application Support/Mozilla/NativeMessagingHosts/chromiumbridge.json`
- **Chromium Browsers (Google Chrome, Brave, Edge, Chromium, Vivaldi, Opera)**:
  - Windows:
    - `HKCU\Software\Google\Chrome\NativeMessagingHosts\chromiumbridge`
    - `HKCU\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\chromiumbridge`
    - `HKCU\Software\Microsoft\Edge\NativeMessagingHosts\chromiumbridge`
    - `HKCU\Software\Chromium\NativeMessagingHosts\chromiumbridge`
    - `HKCU\Software\Vivaldi\NativeMessagingHosts\chromiumbridge`
    - `HKCU\Software\Opera Software\NativeMessagingHosts\chromiumbridge`
  - Linux: `~/.config/{google-chrome,chromium,BraveSoftware/Brave-Browser,microsoft-edge}/NativeMessagingHosts/chromiumbridge.json`
  - macOS: `~/Library/Application Support/{Google/Chrome,Chromium,BraveSoftware/Brave-Browser,Microsoft Edge}/NativeMessagingHosts/chromiumbridge.json`

---

## 6. Launch Flags & Sandboxing Matrix

| Target Family | CLI Flags | Purpose |
|---------------|-----------|---------|
| **Chromium** | `--user-data-dir=<path>` | Base user data directory. |
| **Chromium** | `--profile-directory=<dir>` | Subdirectory if targeting specific profile. |
| **Chromium** | `--app=<url>` | PWA minimal window (no address bar). |
| **Chromium** | `--new-window --window-size=960,640 --window-position=X,Y` | Centered popup window. |
| **Chromium** | `--load-extension=<path>` | Loads staged companion extension. |
| **Chromium** | `--disable-background-mode` | Forces process exit on window close. |
| **Chromium** | `--no-first-run --no-default-browser-check` | Suppresses onboarding dialogs. |
| **Gecko / Firefox** | `-profile <path>` | Targets ephemeral or custom profile folder. |
| **Gecko / Firefox** | `-no-remote -new-instance` | Allows concurrent isolated instances without attaching to existing Firefox. |
| **Gecko / Firefox** | `-width 960 -height 640` | Sizing for popup mode. |
| **Gecko / Firefox** | `-private-window` | Passthrough for incognito browsing. |

---

## 7. Storage & Configuration Schemas

### `bridge/config.json`
```json
{
  "version": 2,
  "default_browser": "brave",
  "default_gecko_browser": "firefox",
  "chrome_extension_id": "",
  "python_path": "",
  "bridge_dir": "",
  "browser_overrides": {
    "<browser_id>": "<absolute_executable_path>"
  },
  "window_modes": {
    "default": "popup",
    "app_domains": ["netflix.com", "youtube.com", "figma.com"]
  },
  "session": {
    "profile_mode": "ephemeral",
    "persistent_profile_path": "",
    "persistent_profiles": {},
    "port_cookies": true,
    "port_localstorage": true,
    "port_sessionstorage": true,
    "cleanup_on_close": true,
    "incognito_passthrough": true,
    "discard_firefox_tab": false,
    "record_history": true
  },
  "extra_flags": ["--disable-infobars", "--disable-sync"],
  "extra_gecko_flags": [],
  "domain_rules": {}
}
```

---

## 8. Critical Architectural Invariants & Edge Cases

1. **Google Chrome Deliberately Excluded as TARGET**:
   - `chrome` is explicitly blocked in `bridge/detect.py` as a target browser because Chrome restricts automated unpacked extension loading and local cookie injection via CLI flags.
   - Google Chrome IS fully supported as a **SOURCE** browser running `chrome-extension/`.
2. **Companion Staging to Real Local Filesystem**:
   - `--load-extension` fails on mapped virtual drives. `launcher.py` stages companion into `%TEMP%\cb-sessions\<id>\companion_ext`.
3. **Gecko Direct SQLite Injection**:
   - Firefox target uses direct SQLite writing into `cookies.sqlite` before launch (`moz_cookies` table). No unpacked extension signing issues.
4. **Gecko Process Isolation**:
   - Always pass `-no-remote -new-instance` when launching Firefox targets, preventing Firefox from silently handing the URL to an existing open browser process and ignoring the custom profile.
5. **Native Messaging Buffer Flush**:
   - `sys.stdout.buffer.flush()` must follow every write in Python.

---

## 9. Build & Release Automation

Run the unified packager script:
```bash
python scripts/build_releases.py
```
Outputs:
- `releases/bridge/bridge-v1.0.0.zip`: Python bridge + companion extension + installer.
- `releases/firefox-extension/firefox-extension-v1.0.0.zip`: Ready for Mozilla Add-ons (AMO).
- `releases/chrome-extension/chrome-extension-v1.0.0.zip`: Ready for Chrome Web Store / Edge Add-ons.
