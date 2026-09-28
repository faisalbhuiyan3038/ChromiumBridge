The plan is mostly sound. Route A is the right call, and the profile-dir sideload mechanism still works. Mozilla ended sideloading for add-ons installed by other apps in Firefox 74, and users now need to install extensions explicitly. Mozilla's own tests expect new sideloads to work only in the profile directory, which is exactly your case. I found a few flaws, though.

## 🔴 Real problems

**1. The plan never gets a signed XPI.**
- The on-the-fly packager produces an unsigned XPI. `xpinstall.signatures.required=false` is ignored on release Firefox, so the ephemeral launch fails there.
- It will work on Dev Edition and Nightly, which hides the bug until a release user tries it. The failure looks like a silent 10s timeout.
- Make signing an explicit step: build, upload to AMO unlisted, and ship the signed file. Each upload needs a unique version bump.
- Have the bridge refuse to stage an XPI that lacks `META-INF/mozilla.rsa` when running on a release build, and fail with a clear error.

**2. Pre-seeding `cookies.sqlite` is the riskiest item for the least gain.**
- The schema is Firefox-version-specific, including `originAttributes`, `schemeMap` and `user_version`. A mismatch can make Firefox discard or rename the DB.
- Your companion already sets cookies before navigating to the target, so this step is redundant.
- It also writes live session cookies to disk in plaintext before Firefox even starts. I'd drop it.

**3. `proc.wait()` is not a reliable "Firefox is done" signal.**
- Firefox can restart itself on first run or after an update. `wait()` then returns while the profile is still in use, and your `rmtree` runs against a live profile.
- Wait until no process references the profile path, using `psutil`. A restarted Firefox keeps the same `-profile` argument, so this catches it:

```python
def wait_profile_free(profile, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not any(profile in " ".join(p.info["cmdline"] or [])
                   for p in psutil.process_iter(["cmdline"])):
            return True
        time.sleep(0.5)
    return False
```

- Also lengthen the cleanup backoff. 5 × 0.3s is too short for Windows AV and SQLite locks, so use exponential backoff up to about 10s.

**4. Orphaned profiles leave cookies on disk.**
- A crash, a `taskkill`, or the bridge dying leaves `cb-gecko-*` behind with live cookies inside.
- Write a `session.pid` file into each profile dir. On bridge startup, sweep dirs whose PID is dead.

## 🟡 Worth fixing

- **The 10s timeout is too tight and too destructive.** A cold profile on Windows with AV scanning can take longer, and on timeout the plan kills Firefox and deletes the profile. Use 30s.
- **Check that the daemon watcher thread survives.** It only works if the bridge process outlives the native-messaging port. Chromium terminates the host when the port closes, and MV3 service workers idle out. Your other direction already handles this, so just confirm this path reuses the same mechanism.
- **The handoff token appears on the Firefox command line**, so any local process can read it. Keep it single-use with a short TTL, and check the `Host` header on the server.
- **`extensions.webextensions.uuids` must be double-encoded** (a JSON string inside a pref string), so `<JSON_MAP>` is ambiguous. Use `json.dumps(json.dumps(map))`.
- **Snap Firefox on Linux can't use profiles in `/tmp`.** Ignore this if you're Windows-only.

## ✅ Missing from the verification plan

- Test on **release Firefox**, not just Dev or Nightly.
- Test with **your own Firefox already running**, which is the whole reason for `-no-remote`.
- Test the crash paths: kill Firefox from Task Manager, kill the bridge, and confirm the sweep removes the leftovers.
- Test a slow cold start, for example with AV active.

The search covered the sideloading behavior. The launcher-process, restart and snap points come from my own knowledge, so verify them on your machine. I'd start with fixes 1 and 3.