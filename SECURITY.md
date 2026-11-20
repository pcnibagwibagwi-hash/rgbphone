# RGB Phone 2.0 – security fixes (what, why, how)

## How it works now
```
Phone app --TLS 1.2+, pinned certificate, per-device secret--> RGB Gateway (PC, port 6743)
                                                                    |  localhost only
                                                                    v
                                                           OpenRGB SDK (127.0.0.1:6742)
```
OpenRGB's SDK has **no password and no encryption**, so it must never be reachable from the network.
Before: a Windows port-forward exposed it to the whole Wi-Fi. Now only the gateway is reachable, and it
checks who you are first.

## The 8 requested fixes

| # | Request | What was wrong | Fix (file) |
|---|---------|----------------|-----------|
| 1 | PIN reset bypass | "PIN bhool gaye" wiped the PIN with no check, so anyone holding the unlocked-looking phone could set their own PIN. | Reset now needs the **recovery code** (20 chars, 100 bits, shown once at setup, stored only as a hash, replaced by a new one after use). Changing PIN, changing PC/pairing and making a new recovery code all need the **current PIN**. No "free" reset remains. Forgot both = clear app data in Android settings (this also deletes the pairing, so lights can't be controlled until re-paired). (`app/security.py`, `app/rgbcore.py`) |
| 2 | Repeated wrong PINs | Unlimited guesses; a 4-digit PIN fell in seconds. | PIN must be 6–12 digits, not like 123456/111111. 5 wrong tries, then lock 30 s, doubling each time, max 1 h. Attempt is counted **before** checking and saved to disk, so killing the app does not reset it. PIN and recovery code share one counter. PIN hashed with PBKDF2-SHA256, 600,000 rounds, constant-time compare. Old v1 hashes are upgraded on next unlock. App auto-locks when it goes to background. |
| 3 | Network security | Plain, unauthenticated TCP, anyone could send commands and sniff. | TLS 1.2+ between phone and PC. The app pins the gateway certificate fingerprint (given in the pairing code) and checks it **before** sending any secret, so a fake PC on Wi-Fi is refused. The app only connects to private/LAN addresses (never a public IP). OpenRGB inside the app is reached through a single-use random-port localhost tunnel. (`app/tunnel.py`, `pc_gateway/rgb_gateway.py`) |
| 4 | Only trusted devices | Any device on the Wi-Fi could control the lights. | Each phone gets its own 160-bit secret (`add-device`). PC stores only its SHA-256, so a stolen PC file can't impersonate a phone. `revoke NAME` blocks a phone instantly. Per-IP lockout against guessing, max 4 simultaneous sessions, idle timeout, optional IP allow-list (`allow-ip`), Windows firewall rule limited to your local subnet, activity log. Gateway accepts only LAN source IPs. |
| 5 | Android backup | App data (PIN hash, pairing secret) could be copied via backup/adb. | `android.allow_backup = False` in `buildozer.spec`. |
| 6 | Dependencies | See table below. | Versions pinned; unused ones not included; CI pins tool versions; `pip-audit` clean for PyPI packages. |
| 7 | Permissions | – | Only `INTERNET` (needed). No storage, location, camera, etc. were or are requested. |
| 8 | Signed release | Debug-signed APK. | CI builds `buildozer android release` with **your own** key from GitHub Secrets, verifies with `apksigner`, and removes the key from the runner. Key is never in the repo or in the uploaded files. |

Nothing was removed from the app: colour ring, brightness, 8 presets, Rainbow, Off, auto Direct mode all work (tested).

## Dependency review
| Component | Version | Notes |
|---|---|---|
| kivy | 2.3.0 (pinned) | Needed for UI. No known advisories (pip-audit). |
| openrgb-python | 0.3.8 (pinned) | Pure Python, no further dependencies; unauthenticated protocol, hence the gateway. |
| python-for-android | tag v2024.01.21 | Pinned; newer master broke the build. |
| CPython in p4a | 3.11.5 | **Older**, not scanned by pip-audit. Mitigated: app has no untrusted-file parsing; only talks to your PC. |
| OpenSSL in p4a | 1.1.1 series | **End-of-life.** Used for TLS to your own PC with a pinned cert and TLS ≥1.2, limits exposure, but upgrading p4a when a working newer tag builds is recommended. |
| buildozer 1.6.0, cython 0.29.36 | pinned | Build-time only, not in the APK. |
| cryptography (PC `init` + keystore tool) | 50.0.1 tested | PC/dev only, not in the APK. pip-audit clean. |
| GitHub Actions | checkout@v4, setup-python@v5, setup-java@v4 | Version tags, not commit hashes. Workflow permissions: `contents: read`. The unmaintained third-party buildozer action was removed. |

## Version 2.1: "simple password" mode (chosen by the owner for convenience)
The owner asked for less friction (share with friends, no long codes). What changed and what did NOT:
* **Removed from the app:** PIN, recovery code, app lock. Anyone holding the phone can use the lights.
* **Phone login:** PC IP + one short shared password (6-24 chars). Stored on the PC only as a salted
  PBKDF2-SHA256 hash (`password.json`, owner-only). The gateway still locks an address out after 5 wrong tries
  (60 s doubling up to 1 h) - but a short password is guessable by someone on your Wi-Fi who waits out the locks.
  Use something not obvious (not `123456`).
* **Certificate:** the app remembers the PC's certificate fingerprint after the first accepted login
  (trust on first use). Anyone impersonating the PC on that very first connect could read the password; after
  that, a different PC is refused.
* **Unchanged:** TLS 1.2+, LAN-only (public IPs refused), OpenRGB itself stays on 127.0.0.1, signed APK,
  backups off, only the INTERNET permission, strict `add_device.bat` mode still works.
* Password reset on the PC: run `set_password.bat` again (takes effect immediately).

## Honest limits (please read)
* I could **not** build or sign the Android APK, or run the Windows `.bat` files, in my environment. Python logic, gateway, tunnel and UI were tested (32 automated tests + 22 UI checks). The first GitHub build is the real test.
* Phone clock changed backwards can shorten a lockout.
* Pairing secret sits in plain text inside the app's private storage (Android sandbox). Needs a rooted phone to read. Android Keystore would be stronger but needs more native code.
* Anyone who gets the **pairing code** can control lights until you `revoke` it. Treat it like a password.
* Someone who already controls your PC can do more than change lights, no design can fix that.
* This does not add security for the rest of your Wi-Fi/PC.
