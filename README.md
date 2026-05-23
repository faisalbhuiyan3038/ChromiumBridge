# ChromiumBridge

A Firefox extension to seamlessly move tabs to Chromium-based browsers (Brave, Edge, Vivaldi, etc.) while preserving cookies, session data, and login states. Ideal for DRM-protected content (Netflix, Spotify), HLS streams, or performance-heavy sites.

## Features

### Core Functionality
- **One-Click Handoff**: Open the current tab in Chromium with a single click or keyboard shortcut (`Ctrl+Shift+O`).
- **Cookie & Session Portability**: Transfers cookies, `localStorage`, and `sessionStorage` to Chromium, keeping you logged in.
- **Smart Detection**: Optional detectors identify DRM content, HLS streams, buffering, or security errors and suggest switching to Chromium.
- **Domain Rules**: Configure rules to always open specific domains (e.g., `netflix.com`) in Chromium with custom settings.

### Customization
- **Window Modes**: Choose between `App` (minimal, PWA-style), `Popup` (960x640), or `Normal` (maximized).
- **Profile Modes**: Use an `Ephemeral` (temporary) or `Persistent` (saved) Chromium profile.
- **Context Menus**: Right-click on a page or link to open in Chromium.
- **"Back to Firefox" Button**: Floating button in Chromium to return to the original Firefox tab.

### Technical Features
- **Native Messaging Host**: Python-based bridge communicates between Firefox and Chromium.
- **Local Cookie Server**: Temporary HTTP server delivers cookies and storage data to Chromium.
- **Dynamic Extension Loading**: Chromium companion extension is loaded automatically for each session.
- **Cross-Platform**: Works on Windows, Linux, and macOS.

## How to Use

### Quick Start
1. Open a tab in Firefox (e.g., Netflix, a DRM-protected site, or a performance-heavy page).
2. Click the toolbar icon or press `Ctrl+Shift+O` to open the popup.
3. Select a Chromium browser, window mode, and profile mode.
4. Click **"Open in Chromium"**. The tab will load in Chromium with your session intact.
5. Use the **"Back to Firefox"** button in Chromium to return to the original tab.

### Smart Detection
Enable detectors in **Options → Signals** to monitor:
- DRM/Widevine requests (e.g., Netflix, Spotify).
- HLS/m3u8 streams (e.g., live video).
- Video buffering (configurable threshold).
- Cross-origin errors (`SecurityError`).

A toolbar badge (`!`) and in-page banner will suggest switching to Chromium when issues are detected.

### Domain Rules
1. Open **Options → Domain Rules**.
2. Click **"Add Rule"** and enter a domain (e.g., `netflix.com`).
3. Select a browser, window mode, and profile mode.
4. Choose an action (`Always`, `Ask`, or `Never`).
5. Click **"Save"**. The rule will apply automatically for future visits.

## Setup

### Prerequisites
- Firefox (v91+).
- Python 3.10+ (installed and on `PATH`).
- A Chromium-based browser: Brave, Edge, Vivaldi, Opera, or Chromium (Google Chrome is **not** supported).

### Step 1: Install the Python Bridge
1. Download `bridge-vX.X.X.zip` from [GitHub Releases](https://github.com/faisalbhuiyan3038/ChromiumBridge/releases).
2. Extract both the `bridge` and `chromium-extension` folders to a permanent location (e.g., `C:\ChromiumBridge\bridge` or `~/.chromiumbridge/bridge`).
3. Open a terminal in the `bridge` folder and run:
   ```bash
   python install.py
   ```
   - This will:
     - Detect Python and create a wrapper script (`.bat` on Windows, executable on Linux/macOS).
     - Generate a native messaging host manifest.
     - Register the host with Firefox.
4. **Custom Paths** (optional):
   ```bash
   python install.py --python-path "C:\Custom\Python\python.exe" --bridge-dir "D:\Somewhere\bridge"
   ```
5. **Uninstall**:
   ```bash
   python install.py --uninstall
   ```

### Step 2: Install the Firefox Extension
1. Download the firefox extension from [Mozilla Add-ons](https://addons.mozilla.org/en-US/firefox/addon/chromiumbridge/).

### Step 3: Load the Chromium Companion Extension
- No manual installation required. The Python bridge automatically:
  1. Copies the `chromium-extension` folder to a temporary directory.
  2. Loads it into Chromium via `--load-extension` when launching.
- Ensure the `chromium-extension` folder is in the same parent directory as the `bridge` folder.

### Step 4: Configure
1. Open the **Options page** (right-click the toolbar icon → **Options**).
2. **Re-scan** to detect installed Chromium browsers.
3. **Set Defaults**:
   - Default browser (e.g., Brave).
   - Default window mode (e.g., App for streaming sites).
   - Default profile mode (Ephemeral/Persistent).
4. **Domain Rules**: Add rules to auto-open specific domains in Chromium.
5. **Signals**: Enable/disable smart detectors (e.g., DRM detection).

## File Structure
```
ChromiumBridge/
├── bridge/                      # Python native messaging host
│   ├── bridge.py                # Main entry point
│   ├── detect.py                # Browser detection
│   ├── launcher.py              # CLI flag builder
│   ├── profile.py               # Profile management
│   ├── cookies.py               # Cookie relay
│   ├── cookie_server.py         # Local cookie server
│   ├── config.py                # Configuration management
│   ├── config.json              # User configuration
│   ├── install.py               # Native host installer
│   └── manifest.json            # Native messaging host manifest
│
├── firefox-extension/           # Firefox WebExtension (MV2)
│   ├── manifest.json            # Extension manifest
│   ├── background/              # Background scripts
│   ├── popup/                   # Toolbar popup UI
│   ├── options/                 # Settings page
│   ├── content/                 # Content scripts
│   └── icons/                   # Extension icons
│
└── chromium-extension/          # Chromium companion (MV3)
    ├── manifest.json            # Companion manifest
    ├── background/              # Service worker
    └── content/                 # Content scripts
```

## Firefox vs. Chromium
| Feature                | Firefox                          | Chromium                          |
|------------------------|----------------------------------|-----------------------------------|
| **Extension Type**     | MV2                              | MV3 (loaded dynamically)          |
| **Installation**       | Manual (`.xpi` or sideload)      | Automatic (copied by bridge)      |
| **User Interaction**   | Full UI (popup, options, rules)  | Silent (no UI)                    |
| **Purpose**            | Initiates handoff                | Receives handoff                  |
| **Cookie Handling**    | Extracts cookies                 | Injects cookies                   |

## Troubleshooting
| Issue                                  | Solution                                                                                     |
|----------------------------------------|----------------------------------------------------------------------------------------------|
| Bridge not connected (red dot)         | Run `python install.py`, check registry (Windows) or `native-messaging-hosts` (Linux/macOS). |
| Cookies not ported                     | Ensure you’re logged in on Firefox; avoid `SameSite=Strict` cookies.                         |
| Blank page in Chromium                 | Try a different window mode (e.g., Normal instead of App).                                   |
| No browsers detected                   | Click "Re-scan" in Options or add a custom browser path.                                   |
| Companion extension not loading        | Ensure `chromium-extension` folder exists alongside `bridge`.                                |

## Privacy and Security
- **Local-Only**: No data leaves your machine. Cookies and session data are transferred directly via a local process.
- **Temporary Server**: The localhost cookie server (`127.0.0.1:47831`) shuts down when the Chromium session closes.
- **No Tracking**: No analytics or telemetry.

## License
MIT © [Faisal Bhuiyan]

---
**Download**: [GitHub Releases](https://github.com/yourusername/ChromiumBridge/releases)