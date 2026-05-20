# ChromeBridge 🌉

**Seamlessly hand off Firefox tabs to Chromium-based browsers — with your cookies, sessions, and sanity intact.**

Love Firefox as your daily driver but keep hitting sites that just *work better* in Chromium? DRM-locked streaming, HLS players, weird enterprise portals — you know the ones. ChromeBridge lets you stay in Firefox and blast those pages to Brave, Edge, Vivaldi, Opera, or any Chromium browser you like, with your login sessions coming along for the ride. No manual copy-pasting, no "please log in again," no headaches.

---

## What It Does

- **One-click handoff** — Click the toolbar button, right-click a page, or use `Ctrl+Shift+O` to send the current tab to Chromium.
- **Cookie & session porting** — Cookies, localStorage, and sessionStorage travel with you. You stay logged in.
- **Smart detection** — Optional in-page detectors can suggest switching to Chromium when they spot DRM, HLS streams, or repeated video buffering. All disabled by default — you're in control.
- **Domain rules** — Set it and forget it. "Always open netflix.com in Brave in app mode." Done.
- **Ephemeral or persistent profiles** — Use a clean temp session that wipes on close, or tap into your existing Chromium profile.
- **Multiple window modes** — Open in a compact popup, a full normal window, or a minimal app-style window with no URL bar.
- **"Back to Firefox" button** — A floating pill in every Chromium session lets you jump right back when you're done.

> **Note:** Google Chrome is deliberately not supported. Chrome restricts remote session debugging, unpacked extension loading, and local cookie injection when launched via command-line flags. Use Brave, Edge, Vivaldi, Opera, or a standard Chromium build instead.

---

## How It Works (The Short Version)

ChromeBridge is three pieces that talk to each other:

1. **Firefox Extension** — Lives in your toolbar. Collects cookies and session data from the current tab, sends everything to the Python bridge.
2. **Python Bridge** — A local background process (registered as a Firefox native messaging host). Receives the handoff request, creates a session profile, injects your cookies, and launches Chromium with the right flags.
3. **Chromium Companion Extension** — Automatically loaded into each Chromium session. Picks up the injected cookies and session data, navigates to your page, and shows the "Back to Firefox" button.

You never interact with the bridge or companion directly. Install them once, and the Firefox extension handles the rest.

---

## Setup

There are three things to set up. It takes about 5 minutes.

### Prerequisites

- **Firefox** (version 91 or later)
- **Python 3.10+** installed and on your PATH
- A Chromium-based browser: **Brave**, **Microsoft Edge**, **Vivaldi**, **Opera**, or **Chromium**

---

### Step 1: Install the Python Bridge

Download the `bridge` folder from the [GitHub Releases](https://github.com/yourusername/ChromiumBridge/releases) page and extract it somewhere permanent — you'll want to leave it in one place. Something like `C:\ChromiumBridge\bridge\` on Windows or `~/.chromiumbridge/bridge/` on Linux/macOS.

Then open a terminal, navigate to that folder, and run:

```bash
python install.py
```

That's it. This script:
- Detects your Python interpreter automatically
- Creates a `.bat` wrapper on Windows (Firefox can't run `.py` files directly)
- Writes the native messaging host manifest
- Registers it with Firefox via the Windows registry (or the appropriate `native-messaging-hosts` directory on Linux/macOS)

**Custom paths?** If your Python or bridge folder is in a non-standard location:

```bash
python install.py --python-path "C:\Custom\Python\python.exe" --bridge-dir "D:\Somewhere\bridge"
```

**Want to uninstall?**

```bash
python install.py --uninstall
```

---

### Step 2: Install the Firefox Extension

Download the `firefox-extension` folder (or `.xpi` file) from [GitHub Releases](https://github.com/yourusername/ChromiumBridge/releases).

**For development / sideloading:**
1. Open `about:debugging` in Firefox
2. Click **"This Firefox"** in the sidebar
3. Click **"Load Temporary Add-on..."**
4. Navigate to the `firefox-extension` folder and select `manifest.json`

**For a packaged `.xpi`:**
1. Download the `.xpi` from Releases
2. Drag it into any Firefox tab, or go to `about:addons` → gear icon → **"Install Add-on From File..."**
3. Confirm the install

Once installed, you'll see the ChromeBridge icon in your toolbar. Click it to open the popup.

---

### Step 3: Load the Chromium Companion Extension

This one's a bit different — the companion extension doesn't need to be installed permanently in your Chromium browser. The Python bridge automatically copies it into a temporary session folder and loads it via `--load-extension` every time you hand off a tab.

**You don't need to do anything here.** Just make sure the `chromium-extension` folder is present alongside the bridge folder. The bridge finds it automatically.

If you're curious, the companion handles:
- Injecting your Firefox cookies into Chromium via `chrome.cookies.set()`
- Injecting localStorage and sessionStorage at `document_start`
- Showing the "Back to Firefox" floating button

---

### Step 4: Configure

Open the ChromeBridge **Options page** (right-click the toolbar icon → Options, or click "Options" in the popup). Here's what to do:

1. **Click "Re-scan"** — The extension will detect all Chromium browsers on your system.
2. **Pick your default browser** — Click the radio button next to your preferred browser.
3. **Choose your session mode** — Ephemeral (clean temp session, wiped on close) or Persistent (uses your existing Chromium profile).
4. **Set up domain rules (optional)** — Want Netflix to always open in Brave as an app? Add a rule. You can also set this from the popup with the "Always open this domain here" checkbox.

That's it. You're ready to go.

---

## Using ChromeBridge

### The Popup

Click the toolbar icon (or press `Ctrl+Shift+O`). You'll see:

- **Bridge status** — Green dot means connected, red means the Python bridge isn't running.
- **Current domain** — The site you're looking at.
- **Browser picker** — Choose which Chromium browser to use.
- **Window mode** — App (no URL bar), Popup (compact window), or Normal (full browser).
- **Profile mode** — Ephemeral or Persistent.
- **"Open in Chromium"** — Hit it and go.
- **"Always open this domain here"** — Check this to save a domain rule instantly.

### Context Menus

Right-click anywhere on a page → **"Open in Chromium"**. Right-click a link → **"Open Link in Chromium"**. Same handoff, fewer clicks.

### Smart Detection (Optional)

In the Options page → Signals tab, you can enable detectors that watch for:
- **DRM / Widevine** — Sites requesting media keys (Netflix, Spotify, etc.)
- **HLS / m3u8 streams** — Live video streams
- **Video buffering** — Repeated stalling events (configurable threshold)
- **SecurityError** — Cross-origin errors that Chromium handles better

When a detector triggers, you'll see a subtle toolbar badge (`!`) and an in-page banner suggesting you switch to Chromium. All detectors are **off by default**.

---

## Supported Browsers

| Browser | Supported |
|---------|-----------|
| Brave | ✅ |
| Microsoft Edge | ✅ |
| Vivaldi | ✅ |
| Opera | ✅ |
| Chromium (open-source) | ✅ |
| Google Chrome | ❌ Deliberately excluded — see note above |

**Custom browser?** In the Options page → Browsers tab, you can add any Chromium-based browser by providing its ID and absolute executable path.

---

## Project Structure

```
ChromiumBridge/
├── bridge/                      # Python native messaging host
│   ├── bridge.py                # Main entry point (stdio JSON dispatcher)
│   ├── detect.py                # Browser detection and path resolution
│   ├── launcher.py              # CLI flag builder and subprocess manager
│   ├── profile.py               # Ephemeral/persistent profile management
│   ├── cookies.py               # Cookie relay (inline injection)
│   ├── cookie_server.py         # Localhost HTTP server for cookie delivery
│   ├── config.py                # Configuration management
│   ├── config.json              # User configuration
│   ├── install.py               # Native messaging host installer
│   ├── logger.py                # Session logging
│   └── manifest.json            # Native messaging host manifest template
│
├── firefox-extension/           # Firefox WebExtension (MV2)
│   ├── manifest.json
│   ├── background/              # Background scripts
│   │   ├── main.js              # Orchestrator and message router
│   │   ├── native.js            # Native messaging wrapper
│   │   ├── rules.js             # Domain rule engine
│   │   ├── tabs.js              # Tab lifecycle management
│   │   └── signals.js           # Signal aggregation
│   ├── popup/                   # Toolbar popup
│   ├── options/                 # Settings page
│   ├── content/                 # Content scripts
│   │   ├── detector.js          # Smart signal detection
│   │   ├── banner.js            # Suggestion/feedback banners
│   │   └── storage-extractor.js # localStorage/sessionStorage extraction
│   └── icons/
│
└── chromium-extension/          # Chromium companion (MV3, loaded dynamically)
    ├── manifest.json
    ├── background/
    │   └── receiver.js          # Cookie/session injection service worker
    └── content/
        ├── storage-injector.js  # localStorage/sessionStorage injection
        └── return-button.js     # "Back to Firefox" floating button
```

---

## Release Distribution

This project is distributed via **GitHub Releases**. Each release contains three assets:

| Asset | Contents |
|-------|----------|
| `bridge-vX.X.X.zip` | Python bridge folder — extract and run `python install.py` |
| `firefox-extension-vX.X.X.xpi` | Packaged Firefox extension — install via `about:addons` |
| `chromium-extension-vX.X.X.zip` | Chromium companion extension — placed alongside the bridge folder |

The bridge and companion extension should be extracted to the **same parent directory** so the bridge can find the companion automatically.

---

## Troubleshooting

**Red dot in the popup ("Bridge not connected")**
- Make sure you ran `python install.py` successfully
- Check that the registry key exists at `HKCU\Software\Mozilla\NativeMessagingHosts\chromiumbridge` (Windows)
- Try clicking "Check Now" in the Options page → Advanced tab

**Chromium opens but my cookies aren't there**
- Make sure you're logged into the site in Firefox first
- Some sites use `SameSite=Strict` cookies that can't be read cross-tab — try navigating to the page in Firefox first, then hand off

**Chromium opens a blank page**
- Check the Options page → Advanced tab → Raw Config for any malformed JSON
- Try a different window mode (Normal instead of App)

**"No Chromium browsers detected"**
- Click "Re-scan" in the Options page
- If your browser is in a custom location, add it via the "Custom Browser Path" section
- Google Chrome is deliberately not supported — use Brave, Edge, Vivaldi, Opera, or Chromium

**Companion extension not loading**
- Make sure the `chromium-extension` folder exists alongside the bridge folder
- Check that `--enable-extensions` is in your CLI flags (it's added by default)

---

## Privacy

ChromeBridge runs **entirely locally**. No data leaves your machine. Cookies and session data are passed directly from Firefox to Chromium via a local process — no cloud, no servers, no tracking. The localhost cookie server (port 47831) only binds to `127.0.0.1` and shuts down when the Chromium session closes.

---

## License

MIT — do whatever you want with it.

---

## Contributing

Found a bug? Want a feature? Open an issue or PR. All contributions welcome.
