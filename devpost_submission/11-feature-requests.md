# Feature requests

Requests to the platform and tool makers, not our own roadmap. Each says what we would want built, why it matters, and how urgent it is. Urgency is our view from this project: critical means it blocked or nearly blocked us.

## Amazon Fire TV

### 1. A supported way to keep the device awake for headless testing over adb

- **Want:** a documented developer setting, or an adb command, that keeps a Fire TV Stick awake and its display on when HDMI is unplugged, or that wakes it reliably before `screencap` and `screenrecord`.
- **Why:** with HDMI unplugged the Stick sleeps. We found `KEYCODE_WAKEUP` brings the display on, then screencap and video playback work, and the Stick falls back to sleep when idle. Automated device checks need this to be a known behaviour, not a discovery.
- **Urgency:** important.

### 2. Wi-Fi and network management for developers without root

- **Want:** a Fire OS developer interface (adb command or intent) to join a Wi-Fi network, including WPA2 and captive-portal guest networks, and to read connection and captive-portal state.
- **Why:** Fire OS 7 has no `cmd wifi`, and network changes from adb need root. We drove the Settings screens with key events, read them with `uiautomator dump`, and typed passwords with `input text`. A device that can only be tested after hand-driving menus is slow to iterate on.
- **Urgency:** critical for anyone testing on campus or office networks.

### 3. Real long-press and key-repeat in `adb shell input`

- **Want:** a way to inject a held remote key with repeat events.
- **Why:** `input keyevent --longpress` acted as a tap for us, so hold-to-seek tiers and key repeat cannot be tested without a physical remote.
- **Urgency:** important.

### 4. Captive-portal pages that expose an accessibility tree

- **Want:** the captive-portal WebView on Fire OS to be readable by UIAutomator, or to be completed with a documented keyboard flow.
- **Why:** the guest-portal page rendered in a WebView UIAutomator could not see. We completed it with TAB, SPACE and DPAD_CENTER; ENTER did nothing.
- **Urgency:** important.

### 5. Clear diagnostics for apps that do not show in the launcher

- **Want:** a logcat or `dumpsys` message that says why a side-loaded app with a `LEANBACK_LAUNCHER` intent and a banner is missing from Your Apps & Channels and the App Library.
- **Why:** ours resolves in `LEANBACK_LAUNCHER` but does not appear in either place. We still do not know why and start it with `am start`.
- **Urgency:** nice-to-have.

### 6. Developer-friendly handling of enterprise Wi-Fi (EAP-TLS) on the Stick

- **Want:** a documented path for certificate-based networks such as modern eduroam, which currently fail for the username and password profile.
- **Why:** the Stick's PEAP profile landed in a quarantine VLAN behind a captive portal, with every DNS name resolving to the portal and HTTPS intercepted. The app reported only "Network request failed".
- **Urgency:** important.

## AWS

### 7. Lambda concurrency limits that fit a new account's first deploy

- **Want:** a higher default account concurrency, or faster approval for hackathon accounts, with the limit shown in the Lambda console next to the function.
- **Why:** our limit was 10. One TV screen made about nine parallel requests, so we shipped client-side retry and a concurrency cap (D-87) and filed an increase request.
- **Urgency:** critical.

### 8. GPU instance quota for new and free-plan accounts

- **Want:** a documented path to a small non-zero G-instance quota for credit-funded accounts.
- **Why:** G and P instance quotas were 0 (on-demand and spot), so GPU processing ran on a machine outside AWS. A hackathon cannot wait on a manual quota request.
- **Urgency:** critical.

### 9. WebSocket and long-poll support on Lambda Function URLs

- **Want:** WebSocket or response streaming that works with a standard ASGI adapter.
- **Why:** Function URLs have no WebSockets, so we dropped the live companion channel in cloud mode and replaced it with QR links and polling.
- **Urgency:** important.

### 10. CDK that can use `aws login` sessions

- **Want:** CDK and its asset publishing should read the same credential source as the current AWS CLI login.
- **Why:** CDK could not read an `aws login` session, so the account owner exported credentials with `aws configure export-credentials` before each deploy.
- **Urgency:** important.

### 11. CORS control on Lambda's own 429 responses

- **Want:** let Function URL error responses (throttles) carry the configured CORS and `Retry-After` headers.
- **Why:** Lambda answers its 429 before our code runs, so a browser client cannot read `Retry-After` unless the Function URL CORS config exposes it. We did not change that, to avoid an AWS change, and used jittered backoff.
- **Urgency:** nice-to-have.

### 12. Programmatic completion of credit activities

- **Want:** every free-plan credit activity should be completable from the CLI or documented as console-only.
- **Why:** one activity required the console playground, and a CLI call did not count.
- **Urgency:** nice-to-have.

## Tooling vendors

### 13. ROCm and MIOpen: fail fast, document supported GPUs

- **Want:** MIOpen should return an error instead of hanging, and gfx1201 (RX 9070 XT) should have a documented list of known-bad ops.
- **Why:** an LSTM raised `miopenStatusUnknownError` and a Whisper conv call sat at 0% CPU for over 20 minutes while holding a shared GPU lock. We turn off cuDNN/MIOpen for non-YOLO models.
- **Urgency:** important.

### 14. llama.cpp: warn when GPU offload was requested and no GPU backend loaded

- **Want:** a loud warning.
- **Why:** the ROCm release ran on CPU at 11 tokens per second with no error until we fixed the library path (93 to 131 tokens per second afterwards).
- **Urgency:** nice-to-have.

### 15. Ultralytics: do not write user-level config on import

- **Want:** respect a project-local directory by default.
- **Why:** import wrote a settings file outside the venv on a shared home directory.
- **Urgency:** nice-to-have.

### 16. react-native-tvos and Metro: documentation for remote keys and shared packages

- **Want:** document that the app root must be focusable to receive remote keys, and that watched folders outside the project root need `nodeModulesPaths`.
- **Why:** both cost us time (FL-8 and the device bug in docs/fire-tv.md).
- **Urgency:** important.

### 17. Tailscale Funnel: say when the backend host is down

- **Want:** a clearer client error than "SSL routines::unexpected eof" when a Funnel has no live backend.
- **Why:** it looks like a TLS problem on our side and sends you debugging the wrong layer.
- **Urgency:** nice-to-have.
