Viewed launcher.py:80-160
Viewed launcher.py:160-201
Viewed bridge.py:150-250
Viewed bridge.py:120-155
Viewed manifest.json:1-39
Viewed receiver.js:1-100

Here is the complete step-by-step walkthrough to set up the bridge, install both extensions, and execute a logged-in state transfer from Chrome to Firefox, followed by an explanation of what happens when Firefox is already open.

---

# Complete Walkthrough: Chrome → Firefox State Transfer

```
┌───────────────────────────┐      Native Messaging      ┌───────────────────────────┐
│     CHROME / BRAVE / EDGE │  ────────────────────────► │       PYTHON BRIDGE       │
│ • Extension: chrome-ext/  │   (cookies + localStorage) │ • Native Messaging Host   │
│ • Logged-in session       │                            │ • Tokenized HTTP Server   │
└───────────────────────────┘                            └─────────────┬─────────────┘
                                                                       │ Subprocess CLI
                                                                       ▼
                                                         ┌───────────────────────────┐
                                                         │      FIREFOX / GECKO      │
                                                         │ • Extension: gecko-ext/   │
                                                         │ • Receives & sets cookies │
                                                         │ • Navigates to target URL │
                                                         └───────────────────────────┘
```

---

## 1. Prerequisites
- **Python 3.10+** installed and added to `PATH`.
- **Google Chrome** (or Edge, Brave, Vivaldi, Opera).
- **Mozilla Firefox** (or LibreWolf, Zen, Floorp).

---

## 2. Step 1: Install the Chrome Extension

The source extension extracts your active tab's URL, cookies, and `localStorage`:

1. Open Chrome (or Edge/Brave) and navigate to `chrome://extensions` (or `edge://extensions`).
2. Toggle on **Developer mode** in the top right corner.
3. Click **Load unpacked**.
4. Select the directory:
   ```
   M:\.systemfile\ChromiumBridge\chrome-extension
   ```
5. Copy the **Extension ID** displayed on the extension card (e.g., `gkmimgmenjencipgjlojgdkfcomioeah`).

---

## 3. Step 2: Configure & Register the Native Host Bridge

The bridge acts as the IPC connector between Chrome and Firefox:

1. Open [bridge/install.py](file:///m:/.systemfile/ChromiumBridge/bridge/install.py#L24) in your editor.
2. Confirm or paste your extension ID in `CHROME_EXTENSION_ID` on line 24:
   ```python
   CHROME_EXTENSION_ID = "gkmimgmenjencipgjlojgdkfcomioeah"
   ```
3. Open a terminal, change to the bridge directory, and run the installer:
   ```bash
   cd M:\.systemfile\ChromiumBridge\bridge
   python install.py
   ```
4. Verify the output confirms:
   - `Mozilla manifest written to: ...\chromiumbridge.json`
   - `Chromium manifest written to: ...\chromiumbridge_chrome.json`
   - `Chromium allowed origins: ['chrome-extension://<your-id>/']`
   - `[OK] Chromium registry registered: HKCU\Software\Google\Chrome\...`
   - `[OK] Firefox registry registered: HKCU\Software\Mozilla\...`

---

## 4. Step 3: Install the Firefox Companion Extension

Firefox needs the companion extension ([gecko-extension](file:///m:/.systemfile/ChromiumBridge/gecko-extension/)) to receive the handoff, apply cookies via `browser.cookies.set()`, and inject storage:

1. Open Firefox and navigate to:
   ```text
   about:debugging#/runtime/this-firefox
   ```
2. Click **Load Temporary Add-on...**.
3. Browse to and select:
   ```
   M:\.systemfile\ChromiumBridge\gecko-extension\manifest.json
   ```
4. *(Optional — for two-way handoff back to Chrome)*: Click **Load Temporary Add-on...** again and select:
   ```
   M:\.systemfile\ChromiumBridge\firefox-extension\manifest.json
   ```

---

## 5. Step 4: Test the Live Handoff

1. In Chrome, log into any website (e.g., GitHub, Reddit, Wikipedia, or an authenticated intranet).
2. Click the **ChromiumBridge** extension icon in Chrome's toolbar (or right-click → *Open tab in Firefox*).
3. Select **Firefox** as target (or click *Launch*).
4. **What happens automatically:**
   - Chrome sends cookies + `localStorage` to the Python bridge.
   - The bridge spins up a local tokenized handoff server (`127.0.0.1:47831`).
   - Firefox opens the tokenized handoff URL.
   - The Firefox companion extension intercepts the URL, injects the cookies via `browser.cookies.set()`, redirects to the site, and populates `localStorage`.
   - The page loads in Firefox **fully logged in**.

---

## What Happens If Firefox Is Already Running in Another Window?

When Firefox is already running and you trigger a handoff from Chrome:

### 1. No Process Conflict (Single-Instance IPC)
In companion mode, the bridge launches Firefox with the target handoff URL **without** passing `-no-remote` or `-new-instance`. 
- Firefox detects that an instance is already running on your machine.
- Instead of starting a separate duplicate process or colliding over locked SQLite files, the newly invoked CLI command delegates the URL directly to the existing Firefox process via OS IPC and immediately terminates.

### 2. A New Tab Opens in Your Existing Firefox Window
- The handoff URL (`http://127.0.0.1:47831/handoff?token=...`) opens as a **new tab** inside your active Firefox window.
- Your existing windows, open tabs, active downloads, and unrelated browsing sessions remain completely intact and undisturbed.

### 3. Warm-Start Watchdog Protection
Because the launcher command exits immediately when delegating to an existing Firefox process, the bridge detects a "warm start" (execution time < 2 seconds). Rather than prematurely shutting down, the bridge keeps the tokenized handoff server alive until the Firefox companion extension finishes consuming the auth payload or a 35-second safety timeout elapses.

### 4. Zero SQLite Database Lock Collisions
Earlier legacy approaches attempted to inject cookies directly into Firefox's `cookies.sqlite` file on disk while Firefox was closed. If Firefox was already running, SQLite would lock `cookies.sqlite`, resulting in `OperationalError: database is locked` or silent failure. 
With the companion extension, cookie injection happens cleanly in-memory via the Firefox WebExtension API (`browser.cookies.set()`), completely bypassing filesystem lock limitations.