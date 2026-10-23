# Friction log

One entry per friction point we hit, each resolved. Prefixes: FT is Fire TV and networking, AWS is AWS and secrets, BT is build tooling.

---

## Fire TV Stick and networks

### FT-1: The Stick sleeps when HDMI is unplugged

- **Task:** take screenshots and screen recordings of the app on the Stick from a laptop, with the Stick connected only by USB adb.
- **Steps:** unplugged HDMI, ran `adb shell screencap` and tried playback.
- **Expected:** the display stays on while powered.
- **Actual:** the Stick went to sleep (display off, launcher in focus) and captures failed.
- **Severity:** major (until we knew).
- **Resolution:** `adb shell input keyevent KEYCODE_WAKEUP`, then `am start -n com.replaytv/.MainActivity`. After that, key events, `screencap` and real video playback all work (consecutive frames differ). Verified 2026-10-22. The Stick drops back to sleep when idle, so we wake and relaunch at the start of each session.
- **Suggestion:** document headless behaviour and a supported keep-awake setting for developers.

### FT-2: No Wi-Fi control from adb

- **Task:** move the Stick from one Wi-Fi network to another from the laptop.
- **Steps:** looked for adb Wi-Fi commands.
- **Expected:** an `adb shell` command, as on recent Android.
- **Actual:** Wi-Fi management commands need root, and Fire OS 7 has no `cmd wifi`.
- **Severity:** major.
- **Resolution:** drove the Settings UI with key events, read the screen with `uiautomator dump`, typed passwords with `input text`.
- **Suggestion:** a non-root developer interface for joining a network.

### FT-3: Campus eduroam moved to certificate login; the Stick was quarantined

- **Task:** get the Stick onto campus Wi-Fi so the app could reach the AWS API.
- **Steps:** joined eduroam with the username and password (PEAP) profile.
- **Expected:** normal internet.
- **Actual:** the campus network moved to certificate (EAP-TLS) login. The old profile connected but landed in quarantine: HTTP got a 302 to the campus device-registration portal, every DNS name resolved to the portal address, and HTTPS to any host got the campus certificate. The app showed "Replay can't connect – Network request failed" and Settings showed "Not reachable".
- **Severity:** blocker for device tests that day.
- **Resolution:** joined the campus guest network (next entry).
- **Suggestion:** Fire OS should surface "captive portal / quarantined" state, and support EAP-TLS enrolment for developers.

### FT-4: A captive portal the accessibility tree cannot see

- **Task:** accept the guest-network terms on the Stick.
- **Steps:** opened the guest network; the portal appeared in a WebView; tried `uiautomator dump` and taps.
- **Expected:** UIAutomator lists the page's elements.
- **Actual:** the page was invisible to UIAutomator. ENTER did nothing.
- **Severity:** major.
- **Resolution:** TAB to move, SPACE to tick the terms box, DPAD_CENTER on Connect (a 24-hour visitor pass). We also set `captive_portal_mode` to 1 so portals pop up.
- **Suggestion:** expose WebView content to UIAutomator on Fire OS, or document the key flow.

### FT-5: Held keys over adb

- **Task:** verify the hold-to-seek tiers and 120 ms key repeat.
- **Steps:** `adb shell input keyevent --longpress`.
- **Expected:** a held key with repeat events.
- **Actual:** it acted as a single tap. Each `adb shell input` call also takes about 1 s (JVM start), so we timed keys from logcat's `injectKeyEvent`.
- **Severity:** minor.
- **Resolution:** timed keys from logcat instead of the injector.
- **Suggestion:** a held-key injection tool.

### FT-6: No remote key reached JavaScript

- **Task:** control the first native build with the remote.
- **Steps:** side-loaded the APK and sent keys.
- **Expected:** key events in JS.
- **Actual:** none. Android sends keys down the focused-view chain and nothing in the app was natively focusable.
- **Severity:** blocker.
- **Resolution:** the app root (`App.tsx`) is `focusable` with `hasTVPreferredFocus` on native.
- **Suggestion:** make this a first-page note in the react-native-tvos guide.

### FT-7: First network request waited about 1.9 s

- **Task:** speed up Home loading on the Stick.
- **Steps:** timed the first API request.
- **Expected:** immediate.
- **Actual:** React Native's cookie jar asked WebView's `CookieManager`, which waited for WebView to load.
- **Severity:** minor (1.9 s per cold start).
- **Resolution:** an OkHttp client factory with a no-op cookie jar (`MainApplication.kt`). Cold start to Home dropped from about 6.6 s to about 5 s.
- **Suggestion:** let apps opt out of the WebView cookie jar.

### FT-8: ExoPlayer's controller showed over the black picture

- **Task:** show a clean loading state while video loads.
- **Expected:** a spinner.
- **Actual:** ExoPlayer's own controller (previous, back, play, forward, next) appeared over the black frame, because the patched `PlayerView` started with `useController = true`.
- **Severity:** minor.
- **Resolution:** start it off (`patches/react-native-video@6.19.3.patch`).
- **Suggestion:** default `useController` off in react-native-video when `controls` is false.

### FT-9: Side-loaded app not listed in Your Apps & Channels or the App Library

- **Task:** launch the installed app like a user would.
- **Expected:** it appears in the app list.
- **Actual:** the side-loaded build was absent from both, although `LEANBACK_LAUNCHER` resolves with the banner.
- **Severity:** minor.
- **Resolution:** `adb shell am start -n com.replaytv/.MainActivity`.
- **Suggestion:** a diagnostic that says why an app is hidden.

### FT-10: Metro cannot bundle shared TypeScript outside the project root

- **Task:** `assembleRelease` for the TV app, which imports `packages/tv-core`.
- **Steps:** added the folder to Metro `watchFolders`.
- **Expected:** that is enough.
- **Actual:** `Unable to resolve module @babel/runtime/helpers/interopRequireDefault`, a module the source never imports (2026-10-06). The debug APK and web build were fine.
- **Severity:** blocker for the release APK.
- **Resolution:** `resolver.nodeModulesPaths: [<app>/node_modules]` in `apps/tv/metro.config.js`.
- **Suggestion:** say in the Metro docs that watched folders also need `nodeModulesPaths`.

---

## AWS, secrets and quotas

### AWS-1: EC2 GPU quota started at 0

- **Task:** run the GPU pipeline on EC2 GPU instances.
- **Steps:** checked Service Quotas on 2026-10-22.
- **Expected:** a small G-instance allowance.
- **Actual:** G/VT and P quotas were 0 for on-demand and spot (standard vCPU quota 64), so a quota increase request was needed.
- **Severity:** blocker until the request was filed by the account owner.
- **Resolution:** the account owner filed the quota increase request.
- **Suggestion:** a small default GPU quota for free-plan accounts.

### AWS-2: Lambda concurrency of 10

- **Task:** open a Watch screen on the TV against the deployed API.
- **Expected:** it loads.
- **Actual:** one Watch open sent 7 to 10 requests at once, and five opens at once returned 429s.
- **Severity:** major.
- **Resolution:** D-87: retry on 429/503 with `Retry-After` and jitter (up to 4 tries within 4 s), at most 4 requests in flight per app, extras after the first frame. Peak in flight fell from 7 to 4 in our measurement. We also filed a limit increase request.
- **Suggestion:** a higher default limit for new accounts, and exposing `Retry-After` on Function URL 429s.

### AWS-3: Slow first request on a fresh Lambda instance

- **Task:** open Review, Stats and Watch on the deployed API.
- **Actual:** the storage layer mirrored a whole game (one LIST plus one GET per object) for routes that read two JSON files. Review took about 17 s, `/hype` 10.7 s, `/commentary` 8.4 s; warm requests took 0.3 to 0.6 s.
- **Severity:** major.
- **Resolution:** D-86, each route mirrors only the files it reads.
- **Suggestion:** a note in Lambda-with-S3 guidance on the cost of per-object mirroring.

### AWS-4: CDK deploy flow

- **Task:** deploy `ReplayCloud` (Lambda, S3, CloudFront) from CDK.
- **Expected:** `cdk deploy` with the CLI login.
- **Actual:** CDK could not read an `aws login` session. The owner ran `eval "$(aws configure export-credentials --profile replay --format env)"` first. The profile has no region, so `AWS_REGION` must be set every time.
- **Severity:** minor each, but it added a manual step to every deploy.
- **Resolution:** the flow above, recorded in docs/aws-deploy.md.
- **Suggestion:** CDK should accept `aws login` sessions.

### AWS-5: Holding an API key in a Fire TV APK

- **Task:** let the Fire TV app call the API.
- **Steps:** the API base and key are baked in at build time with Gradle `buildConfigField`. Resolution order is BuildConfig, then a runtime `config.json`, then a Settings override.
- **Expected:** a place for the TV to hold a credential safely.
- **Actual:** a Fire TV app has no obvious secure per-device credential store, so the key travels in the APK. Settings shows only the last four characters. The web builds never bake the key in.
- **Severity:** major for distribution.
- **Resolution:** the APK is kept off shared drives and stores.
- **Suggestion:** a per-device sign-in or a pairing flow that issues a revocable token.

### AWS-6: Credit activities

- **Task:** unlock free-plan credits.
- **Actual:** the Bedrock-playground activity needed the console; a CLI Converse call did not count. The RDS activity needed the owner to run it.
- **Severity:** minor.
- **Resolution:** the owner completed them in the console. Placeholder EC2 and Lambda resources were torn down.
- **Suggestion:** state which activities are console-only.

---

## Build tooling

### BT-1: Fedora ffmpeg has no `libx264`

- **Task:** encode the ingest mezzanine as H.264.
- **Actual:** Fedora's ffmpeg 8.1.2 has no `libx264`; hardcoding it failed (2026-09-22).
- **Severity:** blocker.
- **Resolution:** `h264_encoder()` probes `ffmpeg -encoders` and picks the first available (D-10).
- **Suggestion:** probe encoders instead of assuming.

### BT-2: No Python 3.14 wheels for torch and ultralytics

- **Actual:** dependency resolution failed on the system Python 3.14.
- **Severity:** blocker.
- **Resolution:** `requires-python = ">=3.12,<3.13"` and a `.python-version`.

### BT-3: `uv sync` silently dropped workspace members

- **Actual:** a root with no dependencies made a bare `uv sync` prune member packages.
- **Severity:** major.
- **Resolution:** the root declares the members as dependencies and a `dev` group.
- **Suggestion:** error or warn in `uv`, and call this out in the docs.

### BT-4: pnpm 11 blocks build scripts until approved

- **Actual:** `esbuild` had no binary until `pnpm approve-builds` ran interactively.
- **Severity:** major (CI).
- **Resolution:** a committed `allowBuilds: { esbuild: true }`.

### BT-5: Vite bakes environment variables at server start

- **Actual:** one dev server cannot serve two API bases for different tests.
- **Severity:** minor.
- **Resolution:** separate `webServer` entries in the Playwright config; deployed builds read `config.json` at runtime.

### BT-6: yt-dlp stalled on a blackholed IPv6 route

- **Actual:** 60 to 120 s stall per request.
- **Severity:** major.
- **Resolution:** `-4`.
