All of this is from my own knowledge of Firefox internals, not a fresh search, so I've flagged the parts worth verifying.

## The core problem

Firefox has no `--load-extension`. Release builds also refuse unsigned add-ons, and `xpinstall.signatures.required=false` is ignored there. So you have three real routes:

| Route | Needs signing? | Automation fingerprint | Verdict |
|---|---|---|---|
| **A. Pre-signed XPI dropped into the profile** | Yes (once, free) | None | ✅ Best |
| **B. Temporary add-on via remote debugging** | No | Depends on protocol | ✅ Good fallback |
| **C. Unsigned on Dev/Nightly/ESR** | No | None | ⚠️ Only if users have those builds |

## A. Sign once, sideload into the temp profile

1. Give the addon a fixed ID: `browser_specific_settings.gecko.id` in the manifest.
2. Submit it to AMO on the **unlisted** channel. It's free and auto-signed in minutes, and it doesn't go public. Ship the resulting `.xpi` with your bridge.
3. For each temp session, copy it to `<profile>/extensions/<addon-id>.xpi`. The filename must match the ID exactly.
4. In the profile's `user.js`, set `extensions.autoDisableScopes` to `0`. Without that, Firefox treats profile-dir add-ons as sideloaded and disables them pending user approval. This one pref is the whole trick.

```python
import json, pathlib, shutil, subprocess, tempfile, uuid

USER_JS = """
user_pref("extensions.autoDisableScopes", 0);
user_pref("extensions.webextensions.uuids", %s);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.tabs.warnOnClose", false);
"""

def launch_temp_firefox(firefox_exe, xpi, addon_id, url):
    prof = pathlib.Path(tempfile.mkdtemp(prefix="cb-ff-"))
    (prof / "extensions").mkdir()
    shutil.copy(xpi, prof / "extensions" / f"{addon_id}.xpi")
    # Pin the moz-extension:// UUID so the bridge knows the addon's internal URL
    uuids = json.dumps(json.dumps({addon_id: str(uuid.uuid4())}))
    (prof / "user.js").write_text(USER_JS % uuids)
    try:
        subprocess.run([firefox_exe, "-profile", str(prof),
                        "-no-remote", "-new-window", url])
    finally:
        shutil.rmtree(prof, ignore_errors=True)
```

The same signed XPI can install into your persistent profile the same way. That way both modes need no manual addon install.

## Gotchas

- **`-no-remote` is mandatory.** If any Firefox is already running, a plain launch hands off to it and your `subprocess.run` returns instantly. Your cleanup would then delete the profile mid-session.
- **MV3 host permissions:** Firefox doesn't grant them by default, and I'm unsure whether sideloaded installs get them silently. Your companion needs host access to set cookies for arbitrary domains, so test this. **MV2** sidesteps the question.
- **Windows file locks:** if `rmtree` hits locked files right after exit, retry with a short backoff.