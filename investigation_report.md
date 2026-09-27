# ChromiumBridge: Chromium → Firefox Investigation Report

## 1. Repository architecture summary
The ChromiumBridge project enables bidirectional handoff of authenticated browser sessions between Chromium and Gecko-based browsers. It uses a Python-based native messaging host (`bridge.py`) to facilitate communication. 

- **Firefox → Chromium**: A Firefox extension extracts state, sends it to the bridge, and the bridge launches Chromium. A companion Chromium extension (`chromium-extension`) is loaded via CLI flags to receive and inject the state natively.
- **Chromium → Firefox**: A Chromium extension extracts state, sends it to the bridge. The bridge directly manipulates an ephemeral Firefox profile (writing `cookies.sqlite`) and launches Firefox pointing to the target URL. 

## 2. Current Chromium → Firefox data flow
1. **Extraction**: The Chromium extension (`chrome-extension/main.js`) fetches cookies using `chrome.cookies.getAll()` and extracts `localStorage`/`sessionStorage` via a content script.
2. **Transport**: The JSON payload is piped through `sys.stdin` to the Python bridge.
3. **State Injection (Cookies)**: The bridge creates an ephemeral profile directory and uses Python's `sqlite3` to write cookies directly into `cookies.sqlite` (matching the Firefox 104+ schema with `rawSameSite`).
4. **State Injection (Storage)**: The bridge starts a local HTTP server (`127.0.0.1:47831`) which stages `localStorage` and `sessionStorage` at the `/storage` endpoint.
5. **Browser Launch**: Firefox is launched using `-profile <dir> -no-remote -new-instance <url>`.

## 3. Root-cause analysis
The failure of the logged-in state across all sites is due to a complete breakdown in how state is restored on the Gecko side, affecting both cookies and modern web storage:

1. **Cookie Injection Failure**: Although the Python bridge creates `cookies.sqlite` and writes the Chrome cookies using Python's `sqlite3`, this database is either being rejected by modern Firefox (due to silent schema changes, missing WAL files, or integrity checks) or overwritten when Firefox initializes the new ephemeral profile. As a result, even sites relying exclusively on cookies fail to authenticate.
2. **Web Storage Ignored**: `localStorage` and `sessionStorage` are completely lost during the handoff. While the Python bridge successfully stages this storage data on `127.0.0.1:47831/storage`, **there is no mechanism inside the target Firefox instance to fetch and apply this data**. Because Firefox is launched with zero extension dependencies in this direction, the storage data is simply ignored.

Furthermore, if a user attempts to use a persistent profile while Firefox is already running, the `-no-remote -new-instance` flags either fail or the bridge encounters an SQLite lock error because the running Firefox instance holds an exclusive lock on `cookies.sqlite`.

## 4. Missing or unsupported functionality
- **Cookies**: Direct SQLite injection is brittle and currently failing on modern Firefox versions, breaking all cookie-based auth.
- **`localStorage` & `sessionStorage`**: Extracted by Chromium but never restored in Gecko.
- **IndexedDB, Cache Storage, Service Workers**: Not extracted by the source, and not supported by the bridge.
- **Persistent Profiles (Active)**: Fails via SQLite locking if the profile is already in use by a running Firefox instance.
- **Origin Isolation**: Storage injection lacks origin boundaries on the Gecko side because it is fundamentally unimplemented.

---

## 5. Approach A: Persistent Firefox profile (Proposed)
Rework the Chromium → Firefox flow to utilize a persistent profile where the existing `firefox-extension` acts as a bidirectional companion to restore state.

- **Profile & Launch**: The bridge abandons ephemeral profiles for Gecko targets. It starts a localhost server at `127.0.0.1:47831/handoff` serving the state payload, and launches Firefox pointing to this local URL. Crucially, `-no-remote` is removed, allowing the handoff to seamlessly attach to an already-running Firefox instance.
- **Companion Extension**: The user installs the `firefox-extension` in their persistent profile. The extension intercepts navigations to `127.0.0.1:47831/handoff` (or communicates via native messaging/WebSockets).
- **Restoration**: The extension reads the payload. It uses the `browser.cookies.set()` WebExtensions API to safely apply all cookies (including `HttpOnly`). It then navigates the tab to the target URL and injects `localStorage`/`sessionStorage` via `browser.scripting.executeScript()`.
- **Security & Concurrency**: Avoids SQLite database locks. A secure, single-use UUID token in the `/handoff` URL prevents other local processes from stealing the payload.

## 6. Approach B: Alternative design (Ephemeral Profile + Marionette)
Preserve the zero-extension-dependency ephemeral profile model by using Firefox's built-in **Marionette (WebDriver) protocol** to inject state natively.

- **Profile & Launch**: The bridge creates an ephemeral profile. It modifies `user.js` to enable Marionette (`marionette.enabled = true`, port `2828`). Firefox is launched with `-marionette`.
- **Restoration**: The Python bridge implements a minimal TCP socket client. It connects to `127.0.0.1:2828` and initiates a WebDriver session.
- **State Injection**: To avoid race conditions with SPA page loads, the bridge instructs Firefox to navigate to a fast, non-HTML endpoint on the target origin (e.g., `https://example.com/favicon.ico`). Once loaded, the bridge uses the Marionette `WebDriver:AddCookie` API to inject cookies, and sends a `WebDriver:ExecuteScript` command to inject `localStorage` and `sessionStorage`. Finally, it navigates to the actual target URL.
- **Security & Isolation**: Total isolation is maintained via ephemeral profiles. No extension is required. Fails gracefully if the socket connection timeouts.

---

## 7. Comparison table

| Feature / Metric | Approach A (Persistent + Ext) | Approach B (Ephemeral + Marionette) |
|------------------|-------------------------------|-------------------------------------|
| **Persistent profile support** | Excellent (Attaches to running instances) | Poor (SQLite locking issues) |
| **Temporary profile support** | Lost (Requires user setup) | Excellent (Zero manual setup) |
| **Cookie fidelity** | High (via `browser.cookies.set`) | High (via WebDriver API) |
| **HttpOnly cookie support** | Yes (Extension API supports it) | Yes (WebDriver API supports it) |
| **localStorage support** | Yes (Content script injection) | Yes (Marionette JS execution) |
| **sessionStorage support** | Yes (Content script injection) | Yes (Marionette JS execution) |
| **IndexedDB support** | Possible (via JS execution) | Possible (via JS execution) |
| **Service-worker/cache support**| Unlikely / Highly complex | Unlikely / Highly complex |
| **Security risk** | Low (Tokenized localhost handoff) | Low (Localhost Marionette port) |
| **User-data isolation** | Relies on standard Firefox profiles | Strict ephemeral isolation |
| **Cross-platform complexity** | Low | Medium (Requires TCP/JSON protocol implementation) |
| **Firefox-version sensitivity**| Low (Standard WebExtensions API) | Medium (Marionette API changes) |
| **Startup performance** | Fast (Instantly opens in running FF) | Slower (Cold boot + Socket handshake) |
| **Reliability** | High | Medium (Network routing race conditions) |
| **Required architecture changes**| High (Bidirectional extension logic) | Medium (Marionette client in Python) |
| **Long-term maintainability** | Excellent | Moderate |

---

## 8. Recommended approach and justification
**I recommend Approach A (Persistent Firefox profile).**

While Approach B is technically impressive and preserves ephemeral profiles, Approach A solves multiple critical flaws simultaneously:
1. It replaces the broken, brittle `cookies.sqlite` direct database injection with the stable, officially supported `browser.cookies.set()` WebExtensions API.
2. It solves the inability to hand off tabs to an *already running* Firefox instance by avoiding SQLite lock contention entirely. 

Since the project already has a Firefox extension codebase, converting it into a bidirectional receiver consolidates the logic and guarantees long-term maintainability against Firefox internal changes.

## 9. Phased implementation plan

**Phase 1: Minimal proof of concept**
- Modify `cookie_server.py` to serve a basic HTML page with the JSON payload embedded.
- Manually open Firefox, use the DevTools console to parse the payload, set a test cookie, and write to `localStorage`.

**Phase 2: State-transfer protocol changes (Bridge)**
- Update `cookie_server.py` to generate a one-time UUID token (`/handoff?token=XYZ`).
- Modify `launcher.py` to remove `-no-remote -new-instance` when launching Gecko targets.
- Launch Firefox pointing to `http://127.0.0.1:47831/handoff?token=XYZ`.

**Phase 3: Companion extension changes (Firefox)**
- Update `firefox-extension/manifest.json` to require `cookies` and `scripting` (or `tabs`) permissions.
- Add logic in the background script to detect navigation to `http://127.0.0.1:47831/handoff`.

**Phase 4: State Restoration (Cookies, localStorage, sessionStorage)**
- Implement payload fetching inside the extension.
- Use `browser.cookies.set()` in a loop to restore cookies.
- Execute a content script using `browser.scripting.executeScript()` to inject `localStorage` and `sessionStorage` into the target origin window.
- Redirect the tab to the final destination URL.

**Phase 5: Error handling and cleanup**
- Implement a 10-second timeout on the Python localhost server. Shut it down immediately after the extension successfully fetches the payload.
- Add fallback UI on the `/handoff` page directing the user to install the extension if it is missing.

## 10. Test plan
- **Automated Tests**: Unit tests in Python for the tokenized `/handoff` URL generation.
- **Manual Verification**: 
  1. Handoff a logged-in React SPA (e.g., a site heavily reliant on `localStorage`) from Chrome to Firefox.
  2. Verify handoff works when Firefox is completely closed (Cold Start).
  3. Verify handoff works when Firefox is already running (Warm Start).
  4. Verify the localhost server shuts down after handoff.
- **Rollback Strategy**: Maintain the existing `sqlite3` injection in `cookies_gecko.py` behind a configuration toggle (`"gecko_injection_mode": "legacy"`) during the rollout phase.

## 11. Security review
- **Risk**: Local processes stealing session data from `127.0.0.1:47831`.
  - **Mitigation**: The URL includes a cryptographically secure UUID (`/handoff?token=...`). The server rejects requests without the exact token and shuts down after a single successful read.
- **Risk**: Origin misattribution (writing `localStorage` to the wrong site).
  - **Mitigation**: The extension explicitly validates the target URL and only executes the `localStorage` content script against the parsed target domain.
- **Risk**: Cross-Site Scripting (XSS) via payload.
  - **Mitigation**: Data is injected strictly using browser storage APIs (`setItem`), never evaluated as DOM HTML.

## 12. Questions requiring user input
1. Are you comfortable abandoning ephemeral profiles for Firefox targets, requiring users to install the Firefox extension to receive handoffs?
2. Should we keep the legacy SQLite injection code as a fallback for users who don't want to install the extension (knowing they will only get cookie support)?
3. May I proceed with implementing **Phase 1 & 2** of Approach A?
