# ChromeBridge: Full Development Plan (Revised)

## Vision Statement

**ChromeBridge** is a Firefox extension + Chromium companion + local Python bridge that makes switching to Chromium feel like a native Firefox feature — not an escape hatch. Sessions are ephemeral, purposeful, and smart. Firefox stays your home. Chromium is a tool you reach for without friction.

---

## Corrections & Amendments to Previous Plan

### 1. Cookie Portability — Do Not Write SQLite Directly

The earlier plan stated: *"cookies.py → writes Cookies SQLite into temp profile."* This is broken in practice. Firefox encrypts cookies using OS keychains (DPAPI on Windows, Keychain on macOS, libsecret on Linux). Chromium uses its own encryption scheme. Writing raw bytes from Firefox's `moz_cookies` table into a Chromium `Cookies` SQLite database will either be silently ignored or crash the profile on load.

**The correct approach:** Firefox's `browser.cookies.getAll()` returns already-decrypted cookie objects in JavaScript — the browser handles decryption transparently for extensions. The extension collects these and passes them as a JSON payload to the Python bridge. The bridge forwards them to the Chromium session. The Chromium companion extension then calls `chrome.cookies.set()` for each cookie, which handles Chromium-side encryption automatically. You never touch SQLite on either side. Note, don't pass unnecessary cookies to chromium, only the current site's.

One important permission note: `browser.cookies.getAll()` only returns cookies scoped to the extension's own origin by default. You must declare `<all_urls>` in the Firefox extension's `permissions` array to read cookies across all domains. This is a broad permission and should be disclosed clearly in the extension's store listing.

The `cookies.py` module in the bridge is therefore not a SQLite writer — it becomes a relay: it receives the JSON array from Firefox and holds it until the Chromium companion is ready to consume it, either via a localhost IPC socket or a temp file the companion reads on first load.

### 2. Profile Mode — Persistent vs. Ephemeral

The original plan only described ephemeral temp profiles. A persistent fixed profile is also valuable — particularly for sites where you want Chromium to remember logins, build up a browsing history, or retain extension state across sessions (e.g., a work SSO portal you visit daily).

The bridge should support two profile modes, selectable globally and overridable per domain rule:

- **Ephemeral** (default): Creates `/tmp/fx-bridge-{uuid}/`, wipes on close. Good for one-off streaming or DRM sites.
- **Persistent**: Uses a fixed path like `~/.fx-bridge/profiles/default/` (or a user-defined path). Survives across sessions. Chromium auto-detects an existing persistent profile and skips first-run setup.

Auto-detection: on first run, `detect.py` should check whether any Chromium browser already has a profile at its default location (e.g., `~/.config/google-chrome/Default` on Linux) and offer to register it as a named persistent profile. Users can also set the path manually in the options page under Advanced.

### 3. Custom CLI Arguments in Advanced Mode

The bridge's `launcher.py` builds the flag list programmatically. Power users should be able to inject arbitrary extra flags without editing the config file manually. The options page Advanced tab should expose a freeform text input where additional CLI arguments can be entered (one per line or space-separated), which are appended to the flag list at launch. These are stored under `extra_flags` in `config.json` and applied globally, with an option for per-domain overrides.

### 4. OS-Agnostic Browser Paths

The earlier config example showed hardcoded Linux paths like `/usr/bin/brave-browser`. `config.json` should store a **cross-platform browser identifier** (e.g., `"brave"`, `"chrome"`, `"edge"`) rather than a raw path. The actual path is resolved at runtime by `detect.py` using platform-specific lookup logic.

`detect.py` should resolve paths in this priority order:

1. User-defined override path in config (highest priority, always wins)
2. Known install paths for the current OS (hardcoded candidates per platform)
3. Windows Registry lookup (`HKEY_LOCAL_MACHINE\SOFTWARE\...` for Chrome, Edge)
4. `shutil.which()` fallback for anything in `PATH`

This means `config.json` entries like `"default_browser": "brave"` resolve correctly on any OS without the user knowing or caring about filesystem layout.

### 5. Firefox History Integration

When a URL is handed off to Chromium, that navigation never goes through Firefox's history. The next time you type "netf..." in the Firefox address bar, there's no autocomplete entry for it — even though you visited it yesterday.

The fix is simple and should be added to `background/main.js` immediately after a successful handoff confirmation from the bridge:

```javascript
await browser.history.addUrl({ url: handedOverUrl });
```

This requires the `history` permission in `manifest.json`. The entry is added with the current timestamp and will appear in Firefox's history and address bar autocomplete like any other visit. Optionally, you could also call `browser.history.addUrl` again when the Chromium session closes (the bridge sends a close event), so the "last visited" timestamp reflects when you actually finished, not when you handed off.

### 6. URL Parameter Stripping — Removed

Removed from the feature set. Stripping tracking parameters (`utm_*`, `fbclid`, etc.) risks breaking site functionality — some platforms use query parameters for session routing, referral validation, or deep-link state that looks superficially like tracking. The risk of silent breakage outweighs the privacy benefit, especially since the handoff URL is going to Chromium anyway, not being shared externally.

---

## Feature Registry

Every planned feature, categorized and prioritized.

### P0 — Foundation (Extension is useless without these)

| ID | Feature | Component |
|---|---|---|
| F01 | Send current tab to Chromium | Firefox ext + Bridge |
| F02 | Native messaging host setup | Bridge |
| F03 | Browser auto-detection (OS-agnostic, runtime path resolution) | Bridge |
| F04 | Ephemeral temp profile creation + cleanup | Bridge |
| F05 | Configurable default browser | Firefox ext + Bridge |
| F06 | Right-click → "Open in Chromium" on tab + link | Firefox ext |

### P1 — Core Experience (Makes it actually good)

| ID | Feature | Component |
|---|---|---|
| F07 | Per-domain rules (always/never/ask) | Firefox ext |
| F08 | Window mode per domain (app/popup/normal) | Bridge |
| F09 | Cookie portability via extension API + companion injection | Firefox ext + Bridge + Chromium ext |
| F10 | Extension whitelist presets per domain | Bridge |
| F11 | Keyboard shortcut (Ctrl+Shift+O) | Firefox ext |
| F12 | Chromium companion extension — handoff receiver | Chromium ext |
| F13 | Session close → refocus Firefox + feedback prompt | Bridge + Firefox ext |
| F14 | Incognito passthrough | Firefox ext + Bridge |
| F15 | Firefox history entry on handoff | Firefox ext |
| F16 | Persistent profile mode (global + per-domain) | Bridge |
| F17 | Custom CLI arguments in Advanced options | Bridge + Firefox ext |

### P2 — Smart Detection (Makes it proactive)

| ID | Feature | Component |
|---|---|---|
| F18 | DRM signal detection (Widevine request) | Firefox content script |
| F19 | HLS/m3u8 stream detection | Firefox content script |
| F20 | Repeated video buffering detection | Firefox content script |
| F21 | Console SecurityError detection | Firefox content script |
| F22 | Toolbar badge state (signal detected) | Firefox ext |
| F23 | Auto-suggest banner (non-intrusive) | Firefox content script |

### P3 — Session Quality (Makes it seamless)

| ID | Feature | Component |
|---|---|---|
| F24 | localStorage portability | Firefox ext + Chromium ext |
| F25 | Floating "Back to Firefox" button | Chromium content script |
| F26 | Tab discard before handoff | Firefox ext |
| F27 | Multi-tab / tab group send | Firefox ext + Bridge |
| F28 | Per-browser extension presets (streaming/work/minimal) | Bridge |

### P4 — Polish (Makes it delightful)

| ID | Feature | Component |
|---|---|---|
| F29 | Bridge health indicator in toolbar | Firefox ext |
| F30 | First-run setup wizard | Firefox ext options |
| F31 | Launch time logging per browser | Bridge |
| F32 | Domain rules import/export (JSON) | Firefox ext options |
| F33 | Community broken-sites list (GitHub JSON, auto-fetched) | Firefox ext |
| F34 | Contextual link menu domain badge | Firefox ext |
| F35 | Session history log | Bridge + Firefox ext |
| F36 | "Did it work?" feedback loop → auto-rule creation | Firefox ext |

---

## Component Architecture

```
ChromeBridge/
├── firefox-extension/
│   ├── manifest.json
│   ├── background/
│   │   ├── main.js              # Service worker entry
│   │   ├── native.js            # Native messaging wrapper
│   │   ├── rules.js             # Domain rule engine
│   │   ├── tabs.js              # Tab lifecycle management
│   │   └── signals.js           # Aggregates content script signals
│   ├── content/
│   │   ├── detector.js          # DRM, HLS, perf, error signals
│   │   └── banner.js            # Suggestion UI injected into page
│   ├── options/
│   │   ├── index.html
│   │   ├── options.js
│   │   └── options.css
│   ├── popup/
│   │   ├── popup.html
│   │   ├── popup.js
│   │   └── popup.css
│   └── icons/
│
├── chromium-extension/
│   ├── manifest.json
│   ├── background/
│   │   └── receiver.js          # Parses handoff, injects cookies via chrome.cookies.set()
│   └── content/
│       └── return-button.js     # Floating "Back to Firefox" UI
│
└── bridge/
    ├── bridge.py                # Main entry — reads stdin, dispatches actions
    ├── detect.py                # OS-agnostic browser detection + path resolution
    ├── cookies.py               # Relay: receives decrypted JSON, stages for companion
    ├── profile.py               # Ephemeral + persistent profile management
    ├── launcher.py              # Flag builder + subprocess manager
    ├── config.py                # Config read/write
    ├── logger.py                # Session + launch time logging
    ├── manifest.json            # Native messaging host manifest
    ├── install.py               # One-shot installer (registers host manifest)
    └── config.json              # User config (auto-generated on first run)
```

---

## Revised Cookie Portability Flow

```
Firefox extension
  browser.cookies.getAll({ url: currentUrl })   ← requires <all_urls> permission
  → array of plain decrypted CookieObjects
  → sent as JSON via native message to bridge.py

bridge.py (cookies.py)
  → writes cookie JSON to a temp file: /tmp/fx-bridge-{uuid}/cookies.json
  → passes file path to Chromium via --load-extension + custom flag, or
    exposes a localhost socket the companion reads from

Chromium companion (receiver.js) on first tab load
  → reads cookie payload (from temp file or socket)
  → calls chrome.cookies.set() for each cookie
    (Chromium handles its own encryption internally)
  → deletes the temp file after injection
  → sends "cookies_injected" message back through the session
```

This approach avoids all SQLite manipulation and works across all OS/encryption combinations.

---

## Config Schema

```json
{
  "version": 2,
  "default_browser": "brave",
  "browsers": {
    "brave":    { "id": "brave", "version": "1.65.0" },
    "chrome":   { "id": "chrome", "version": "124.0.0" },
    "chromium": { "id": "chromium", "version": "123.0.0" }
  },
  "window_modes": {
    "default": "popup",
    "app_domains": ["netflix.com", "youtube.com", "figma.com"]
  },
  "session": {
    "profile_mode": "ephemeral",
    "persistent_profile_path": "~/.fx-bridge/profiles/default",
    "port_cookies": true,
    "port_localstorage": true,
    "cleanup_on_close": true,
    "incognito_passthrough": true,
    "discard_firefox_tab": false,
    "record_history": true
  },
  "extension_presets": {
    "streaming": ["cjpalhdlnbpafiamejdnhcphjbkeiagm"],
    "work":      ["cjpalhdlnbpafiamejdnhcphjbkeiagm", "grammarly-id"],
    "minimal":   []
  },
  "extra_flags": [
    "--disable-infobars",
    "--disable-sync"
  ],
  "domain_rules": {
    "netflix.com":  { "action": "always", "browser": "chrome", "mode": "app", "preset": "streaming", "profile": "ephemeral" },
    "figma.com":    { "action": "always", "browser": "brave",  "mode": "app", "preset": "work",      "profile": "persistent" },
    "example.com":  { "action": "never" }
  },
  "signals": {
    "drm_detection": true,
    "hls_detection": true,
    "buffering_threshold": 3,
    "perf_longtask_threshold": 5
  },
  "ui": {
    "show_banner": true,
    "show_badge": true,
    "badge_color": "#FF6611",
    "feedback_prompt": true
  }
}
```

---

## Data Flow

### Standard Handoff

```
User clicks toolbar button / presses Ctrl+Shift+O
        │
        ▼
background/main.js
  - Gets active tab URL + domain
  - Checks rules.js → domain rule exists?
  - Reads cookies via browser.cookies.getAll() [requires <all_urls>]
  - Calls browser.history.addUrl({ url }) immediately
  - Sends native message: { action, url, cookies[], domain, mode, profile }
        │
        ▼
bridge.py (stdin)
  - Parses message
  - Loads config.json → resolves browser path via detect.py, flags, preset
  - profile.py → ephemeral: creates /tmp/fx-bridge-{uuid}/
               → persistent: resolves fixed path, creates if missing
  - cookies.py → writes cookies.json to session temp dir
  - launcher.py → builds full flag list including extra_flags, spawns subprocess
  - Waits for process exit
  - cleanup() → removes temp dir (ephemeral only; persistent profile kept)
  - Sends response: { event: "closed", domain, duration }
        │
        ▼
background/main.js
  - Receives close event
  - Refocuses original Firefox tab
  - Shows feedback prompt if domain not in rules
```

### Signal-Triggered Suggestion

```
content/detector.js (running on every page)
  - Monitors: DRM calls, HLS tags, buffering events, console errors
  - On signal threshold hit → sends message to background
        │
        ▼
background/signals.js
  - Aggregates signal type + domain
  - Checks: already in rules? already suggested this session?
  - If not → sets toolbar badge ("!") + sends message to content
        │
        ▼
content/banner.js
  - Injects dismissible suggestion banner at top of page
  - "Widevine DRM detected — open in Chromium?"
  - [Open] [Always for this site] [Dismiss]
```

---

## UI Walkthrough

### Toolbar Popup

```
┌─────────────────────────────────────┐
│  🌉 ChromeBridge          ● Live    │
├─────────────────────────────────────┤
│  netflix.com                        │
│  ┌─────────────────────────────┐   │
│  │  🦁 Brave  (default)    ▾  │   │  ← browser picker dropdown
│  └─────────────────────────────┘   │
│                                     │
│  Mode:  [App] [Popup] [Normal]      │  ← toggle
│  Profile: [Ephemeral] [Persistent]  │  ← toggle
│                                     │
│  ┌───────────────────────────────┐  │
│  │   🚀 Open in Chromium         │  │  ← primary action
│  └───────────────────────────────┘  │
│                                     │
│  □ Always open this domain here     │
│                                     │
│  ⚙ Options    📋 History    ❓ Help │
└─────────────────────────────────────┘
```

---

### Options Page — Tabs

**Tab 1: Browsers**
- Auto-detected list with version numbers, radio for default
- Manual path override input per browser
- "Re-scan for browsers" button
- Per-browser: test launch button, assign label/nickname

**Tab 2: Domain Rules**
- Table: Domain / Action / Browser / Mode / Profile / Preset / Delete
- Add rule manually or import from JSON
- Export all rules as JSON
- Toggle: "Use community broken-sites list"

**Tab 3: Session**
- Profile mode: Ephemeral / Persistent (global default)
- Persistent profile path: auto-detected or manually set
- Toggles: port cookies, port localStorage, cleanup on close, incognito passthrough, discard Firefox tab, record in Firefox history
- Extension presets editor (streaming / work / minimal) — list extensions by ID with add/remove

**Tab 4: Signals**
- Toggle each signal type on/off
- Slider for buffering threshold and perf threshold
- Preview what the suggestion banner looks like

**Tab 5: Advanced**
- Extra CLI flags input (freeform, one per line) — appended to every launch
- Bridge health check with green/red status + last ping time
- Path to native host manifest
- Re-run install wizard
- Raw `config.json` editor (for power users)
- Session log viewer (last 50 sessions: domain, browser, duration, outcome)

---

## Development Phases

### Phase 1 — Skeleton (Week 1–2)

Get the pipeline working end to end with no features, just plumbing.

- [ ] `manifest.json` (MV2, Firefox, native messaging + cookies + history permissions)
- [ ] `background/main.js` — toolbar button click → native message → log response
- [ ] `bridge.py` — reads stdin, prints "received", responds
- [ ] `install.py` — registers native host manifest on Linux/Windows/macOS
- [ ] `detect.py` — OS-agnostic browser detection, returns resolved paths
- [ ] Options page shell with browser list populated from detection

**Milestone:** Click toolbar button → Chromium opens with the current URL → closes → Firefox gets notified.

---

### Phase 2 — Session Core (Week 3–4)

- [ ] `profile.py` — ephemeral temp dir creation; persistent path resolution
- [ ] Cookie flow: `browser.cookies.getAll()` → JSON → bridge relay → companion `chrome.cookies.set()`
- [ ] `launcher.py` — full flag builder (mode, profile dir, extensions, `extra_flags`)
- [ ] Cleanup on process exit (ephemeral only)
- [ ] `browser.history.addUrl()` called on every successful handoff
- [ ] Window mode switching (app / popup / normal) from popup UI
- [ ] Keyboard shortcut wired up

**Milestone:** Open Netflix in Chromium app mode, logged in via ported cookies, visit recorded in Firefox history, window closes clean, temp dir gone.

---

### Phase 3 — Rules + Smart Detection (Week 5–6)

- [ ] `rules.js` — domain rule engine, storage in `browser.storage.sync`
- [ ] Domain rules options table (CRUD)
- [ ] `content/detector.js` — DRM, HLS, buffering signals
- [ ] `content/banner.js` — suggestion UI, dismiss/always/open actions
- [ ] Toolbar badge states
- [ ] "Did it work?" prompt on Chromium close → one-click rule creation
- [ ] Incognito passthrough
- [ ] Per-domain profile mode override

**Milestone:** Visit Netflix → DRM banner → click Open → app mode Chromium with cookies → closes → "Always open Netflix here?" → confirm → rule saved.

---

### Phase 4 — Chromium Companion (Week 7)

- [ ] Chromium extension `manifest.json` (MV3)
- [ ] `receiver.js` — reads cookie payload, calls `chrome.cookies.set()` for each, injects localStorage
- [ ] `return-button.js` — floating "← Firefox" button, dismissible, remembers per domain
- [ ] Session close message back to Firefox via native host

**Milestone:** Full round-trip. Firefox → Chromium (with session data) → back to Firefox with one click.

---

### Phase 5 — Polish (Week 8–9)

- [ ] Bridge health indicator in toolbar
- [ ] First-run setup wizard (detects bridge, walks through install if missing)
- [ ] Launch time logging + display in options
- [ ] Multi-tab send
- [ ] Tab discard option
- [ ] Community broken-sites JSON (hosted, auto-fetched on startup)
- [ ] Import/export domain rules
- [ ] Session history log in options
- [ ] Custom CLI flags UI in Advanced tab

**Milestone:** Extension feels complete. New user installs, wizard walks through bridge setup, first handoff works within 2 minutes.

---

### Phase 6 — Release Prep (Week 10)

- [ ] Package Firefox extension (`.xpi`)
- [ ] Package Chromium extension (unpacked with install instructions, Chrome Web Store submission)
- [ ] `install.py` tested on Linux, Windows, macOS
- [ ] README with full setup guide
- [ ] Submit to Firefox Add-ons (AMO)
- [ ] GitHub release with PyInstaller binary option (`.exe` / `.bin`) for non-Python users

---

## Full User Journey

### First Install

1. User installs Firefox extension from AMO.
2. Popup opens → bridge not detected → **Setup Wizard launches**.
3. Wizard: "Download the ChromeBridge bridge" → one click downloads platform binary.
4. Wizard runs `install.py` (or guides through manual steps on Windows).
5. Wizard detects installed Chromium browsers, user picks default, sets profile preference.
6. Wizard: "Install the Chromium companion?" → link to Chrome Web Store.
7. Done — toolbar icon turns green.

---

### Daily Use — Manual

1. Hit a streaming site in Firefox that lags.
2. Press `Ctrl+Shift+O` (or click toolbar button).
3. Popup shows current domain, pre-selected browser, mode, and profile mode.
4. Press Enter / click "Open in Chromium."
5. Chromium opens in app mode, cookies ported, site loads logged in.
6. Watch / do the thing.
7. Close Chromium window.
8. Firefox refocuses the original tab.
9. Small prompt: "Always open this site in Chromium?" → Yes / No / Ask me later.

---

### Daily Use — Automatic (Domain in Rules)

1. Navigate to Netflix.com (already in domain rules as always + app mode).
2. No prompt — bridge triggers immediately in background.
3. Chromium app window opens, Netflix loads ready to play.
4. Firefox tab quietly discards itself (if option enabled).

---

### Daily Use — Signal Triggered

1. Open an obscure streaming site Firefox has never seen.
2. Site tries Widevine → `detector.js` catches it.
3. Toolbar badge lights up orange.
4. Subtle banner at top of page: "DRM detected · Open in Chromium? [Open] [Always] [Dismiss]"
5. Click "Open" → Chromium handles it.
6. On close: "Add this site to your always list?" — one click.

---

## Tech Stack Summary

| Layer | Technology | Why |
|---|---|---|
| Firefox extension | JS, MV2, WebExtensions API | Best native messaging support, MV2 stability in Firefox |
| Chromium extension | JS, MV3 | Chrome Web Store requires MV3 |
| Bridge | Python 3.8+ | Cross-platform, good subprocess control, easy JSON handling |
| Distribution (non-devs) | PyInstaller | Single binary, no Python install required |
| Config | JSON | Human-editable, no dependencies |
| Cookie transport | JSON over native messaging | Avoids all SQLite/encryption manipulation |
| Profile management | `tempfile` + `shutil` (stdlib) | Reliable cross-platform ephemeral dirs |
| Session comms | Native Messaging (stdin/stdout) | Only sanctioned Firefox↔local bridge method |
