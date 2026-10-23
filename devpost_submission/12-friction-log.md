# Friction log

One entry per friction point we hit. Dates, versions and numbers come from docs/friction-log.md, docs/fire-tv.md, docs/models.md, docs/decisions.md or our session notes. Prefixes: FT is Fire TV and networking, AWS is AWS and secrets, GPU is the shared GPU workstation and ROCm, BT is build tooling, PR is pipeline realism. FL numbers refer to docs/friction-log.md.

---

## Fire TV Stick and networks

### FT-1: The Stick sleeps when HDMI is unplugged

- **Task:** take screenshots and screen recordings of the app on the Stick from a laptop, with the Stick connected only by USB adb.
- **Steps:** unplugged HDMI, ran `adb shell screencap` and tried playback.
- **Expected:** the display stays on while powered.
- **Actual:** the Stick went to sleep (display off, launcher in focus) and captures failed.
- **Severity:** major (until we knew).
- **Workaround:** `adb shell input keyevent KEYCODE_WAKEUP`, then `am start -n com.replaytv/.MainActivity`. After that, key events, `screencap` and real video playback all work (consecutive frames differ). Verified 2026-10-22. It drops back to sleep when idle, so we wake and relaunch at the start of each session.
- **Suggestion:** document headless behaviour and a supported keep-awake setting for developers.

### FT-2: No Wi-Fi control from adb

- **Task:** move the Stick from one Wi-Fi network to another from the laptop.
- **Steps:** looked for adb Wi-Fi commands.
- **Expected:** an `adb shell` command, as on recent Android.
- **Actual:** Wi-Fi management commands need root, and Fire OS 7 has no `cmd wifi`.
- **Severity:** major.
- **Workaround:** drive the Settings UI with key events, read the screen with `uiautomator dump`, type passwords with `input text`.
- **Suggestion:** a non-root developer interface for joining a network.

### FT-3: Campus eduroam moved to certificate login; the Stick was quarantined

- **Task:** get the Stick onto campus Wi-Fi so the app could reach the AWS API.
- **Steps:** joined eduroam with the username and password (PEAP) profile.
- **Expected:** normal internet.
- **Actual:** the campus network moved to certificate (EAP-TLS) login. The old profile connected but landed in quarantine: HTTP got a 302 to the campus device-registration portal, every DNS name resolved to the portal address, and HTTPS to any host got the campus certificate. The app showed "Replay can't connect – Network request failed" and Settings showed "Not reachable".
- **Severity:** blocker for device tests that day.
- **Workaround:** use the campus guest network (next entry), or a phone hotspot (FT-5).
- **Suggestion:** Fire OS should surface "captive portal / quarantined" state, and support EAP-TLS enrolment for developers.

### FT-4: A captive portal the accessibility tree cannot see

- **Task:** accept the guest-network terms on the Stick.
- **Steps:** opened the guest network; the portal appeared in a WebView; tried `uiautomator dump` and taps.
- **Expected:** UIAutomator lists the page's elements.
- **Actual:** the page was invisible to UIAutomator. ENTER did nothing.
- **Severity:** major.
- **Workaround:** TAB to move, SPACE to tick the terms box, DPAD_CENTER on Connect (a 24-hour visitor pass). We also set `captive_portal_mode` to 1 so portals pop up.
- **Suggestion:** expose WebView content to UIAutomator on Fire OS, or document the key flow.

### FT-5: Phone hotspot with path-MTU problems

- **Task:** use a phone hotspot as a fallback network for the Stick.
- **Steps:** joined a saved hotspot.
- **Expected:** a normal connection.
- **Actual:** path-MTU problems and dropped connections. Our notes also record that the hotspot drops when the phone idles, and in one session the Stick never saw the hotspot in a scan; suggested fixes were 2.4 GHz or "Maximize Compatibility" and keeping the phone near the Stick.
- **Severity:** major.
- **Workaround:** keep the hotspot screen open and the phone close; prefer the guest network when available.
- **Suggestion:** none for Amazon specifically; a developer-mode network diagnostics screen would help.

### FT-6: Hold-to-seek cannot be tested over adb

- **Task:** verify the hold-to-seek tiers and 120 ms key repeat.
- **Steps:** `adb shell input keyevent --longpress`.
- **Expected:** a held key with repeat events.
- **Actual:** it acted as a single tap. Each `adb shell input` call also takes about 1 s (JVM start), so we timed keys from logcat's `injectKeyEvent`.
- **Severity:** minor, but leaves a feature unverified.
- **Workaround:** none; needs a physical remote.
- **Suggestion:** a held-key injection tool.

### FT-7: No remote key reached JavaScript

- **Task:** control the first native build with the remote.
- **Steps:** side-loaded the APK and sent keys.
- **Expected:** key events in JS.
- **Actual:** none. Android sends keys down the focused-view chain and nothing in the app was natively focusable.
- **Severity:** blocker.
- **Workaround:** the app root (`App.tsx`) is `focusable` with `hasTVPreferredFocus` on native.
- **Suggestion:** make this a first-page note in the react-native-tvos guide.

### FT-8: First network request waited about 1.9 s

- **Task:** speed up Home loading on the Stick.
- **Steps:** timed the first API request.
- **Expected:** immediate.
- **Actual:** React Native's cookie jar asked WebView's `CookieManager`, which waited for WebView to load.
- **Severity:** minor (1.9 s per cold start).
- **Workaround:** an OkHttp client factory with a no-op cookie jar (`MainApplication.kt`). Cold start to Home dropped from about 6.6 s to about 5 s.
- **Suggestion:** let apps opt out of the WebView cookie jar.

### FT-9: ExoPlayer's controller showed over the black picture

- **Task:** show a clean loading state while video loads.
- **Expected:** a spinner.
- **Actual:** ExoPlayer's own controller (previous, back, play, forward, next) appeared over the black frame, because the patched `PlayerView` started with `useController = true`.
- **Severity:** minor.
- **Workaround:** start it off (`patches/react-native-video@6.19.3.patch`).
- **Suggestion:** default `useController` off in react-native-video when `controls` is false.

### FT-10: App not listed in Your Apps & Channels or the App Library

- **Task:** launch the installed app like a user would.
- **Expected:** it appears in the app list.
- **Actual:** it does not, although `LEANBACK_LAUNCHER` resolves with the banner. Cause unknown.
- **Severity:** minor.
- **Workaround:** `adb shell am start -n com.replaytv/.MainActivity`.
- **Suggestion:** a diagnostic that says why an app is hidden.

### FT-11: Metro cannot bundle shared TypeScript outside the project root

- **Task:** `assembleRelease` for the TV app, which imports `packages/tv-core`.
- **Steps:** added the folder to Metro `watchFolders`.
- **Expected:** that is enough.
- **Actual:** `Unable to resolve module @babel/runtime/helpers/interopRequireDefault`, a module the source never imports (FL-8, 2026-10-06). The debug APK and web build were fine.
- **Severity:** blocker for the release APK.
- **Workaround:** `resolver.nodeModulesPaths: [<app>/node_modules]` in `apps/tv/metro.config.js`.
- **Suggestion:** say in the Metro docs that watched folders also need `nodeModulesPaths`.

---

## AWS, secrets and quotas

### AWS-1: EC2 GPU quota was 0

- **Task:** run the GPU pipeline on AWS.
- **Steps:** checked Service Quotas on 2026-10-22.
- **Expected:** a small G-instance allowance.
- **Actual:** G/VT and P quotas were 0 for on-demand and spot (standard vCPU quota 64). The quota increase request was denied to our agent by the permission system and had to be filed by the account owner.
- **Severity:** blocker for AWS GPU.
- **Workaround:** the GPU stays on a shared AMD GPU workstation as a pull-based runner with no AWS credentials (D-80). Also, an AWS GPU would have used the credit in days.
- **Suggestion:** a small default GPU quota for free-plan accounts.

### AWS-2: Lambda concurrency of 10

- **Task:** open a Watch screen on the TV against the deployed API.
- **Expected:** it loads.
- **Actual:** one Watch open sent 7 to 10 requests at once, and five opens at once returned 429s.
- **Severity:** major (demo risk).
- **Workaround:** D-87: retry on 429/503 with `Retry-After` and jitter (up to 4 tries within 4 s), at most 4 requests in flight per app, extras after the first frame. Peak in flight fell from 7 to 4 in our measurement. We also filed a limit increase request (outcome not in the repo).
- **Suggestion:** a higher default limit for new accounts, and exposing `Retry-After` on Function URL 429s.

### AWS-3: Slow first request on a fresh Lambda instance

- **Task:** open Review, Stats and Watch on the deployed API.
- **Actual:** the storage layer mirrored a whole game (one LIST plus one GET per object) for routes that read two JSON files. Review took about 17 s, `/hype` 10.7 s, `/commentary` 8.4 s; warm requests took 0.3 to 0.6 s.
- **Severity:** major.
- **Workaround:** D-86, each route mirrors only the files it reads.
- **Suggestion:** n/a; a note in Lambda-with-S3 guidance on the cost of per-object mirroring.

### AWS-4: CDK deploy flow

- **Task:** deploy `ReplayCloud` (Lambda, S3, CloudFront) from CDK.
- **Steps:** per docs/aws-deploy.md and our notes: build the Lambda zip and web builds on the GPU workstation, synthesize `cdk.out` there, copy it back, then the account owner deploys with a pre-synthesized app.
- **Expected:** `cdk deploy` with the CLI login.
- **Actual:** CDK could not read an `aws login` session. The owner ran `eval "$(aws configure export-credentials --profile replay --format env)"` first. The profile has no region, so `AWS_REGION` must be set every time. Our agent was blocked from `cdk bootstrap` and `cdk deploy` by its permission system, so the owner ran them. The laptop had no `infra/node_modules`.
- **Severity:** minor each, but it added a manual hand-off to every deploy.
- **Workaround:** the flow above, recorded in docs/aws-deploy.md.
- **Suggestion:** CDK should accept `aws login` sessions.

### AWS-5: Secrets in an APK

- **Task:** let the Fire TV app call the API.
- **Steps:** the API base and key are baked in at build time with Gradle `buildConfigField`. Resolution order is BuildConfig, then a runtime `config.json`, then a Settings override.
- **Expected:** a key the TV can hold safely.
- **Actual:** the APK contains the key, so anyone with the APK can call the API as the TV. Settings shows only the last four characters. The web builds never bake the key in.
- **Severity:** major for distribution.
- **Workaround:** keep the APK off shared drives and stores; this is why it cannot be published as-is.
- **Suggestion:** a per-device sign-in or a pairing flow that issues a revocable token. TODO(team): note whether the key was rotated before submission.

### AWS-6: Credit activities

- **Task:** unlock free-plan credits.
- **Actual:** the Bedrock-playground activity needed the console; a CLI Converse call did not count. The RDS activity needed the owner to run it.
- **Severity:** minor.
- **Workaround:** the owner completed them in the console. Placeholder EC2 and Lambda resources were torn down.
- **Suggestion:** state which activities are console-only.

---

## Shared GPU workstation and ROCm

### GPU-1: SSH through a Tailscale Funnel dropped

- **Task:** reach the workstation from the laptop.
- **Steps:** `ssh` through a proxy command to a Funnel on the box owner's tailnet.
- **Expected:** a connection.
- **Actual:** `SSL routines::unexpected eof` with TCP open, which means the relay had no live backend. It dropped for about 9 minutes and then recovered on its own (the duration is as we recorded it in our session). A foreground build died with the link in an earlier session (FL-18).
- **Severity:** medium.
- **Workaround:** wait; run long jobs detached under `nohup` or tmux with per-job locks.
- **Suggestion:** a clearer error when a Funnel has no backend.

### GPU-2: MIOpen errors and hangs on gfx1201

- **Task:** run Kokoro TTS and Whisper on the RX 9070 XT (ROCm 7.2, torch 2.14).
- **Actual:** Kokoro's LSTM raised `miopenStatusUnknownError`; the first Whisper call hung at 0% CPU for over 20 minutes while holding the shared GPU lock (FL-9, 2026-10-06).
- **Severity:** high.
- **Workaround:** `torch.backends.cudnn.enabled = False` for every non-YOLO model, and `flock <gpu.lock> timeout N <cmd>` around GPU jobs.
- **Suggestion:** fail fast instead of hanging.

### GPU-3: ROCm memory settings

- **Task:** keep GPU jobs from running out of memory on a shared 16 GB card.
- **Actual:** per our notes, we avoided `PYTORCH_HIP_ALLOC_CONF=expandable_segments` and VAE decode on the GPU, and the card is shared under file locks (a GPU lock for one job at a time). SAM 2.1 in default fp32 was about ten times slower than bf16 (428 vs 39.6 ms per frame, FL-11).
- **Severity:** medium.
- **Workaround:** bf16 for SAM; the choices above; one GPU job at a time.
- **Suggestion:** document known-bad allocator settings for this GPU. TODO(team): the repo does not record why expandable segments and GPU VAE decode were avoided; add the symptom.

### GPU-4: Container memory limit hides behind `free`

- **Task:** run concurrent agent jobs.
- **Actual:** the workstation is a container with a 16 GiB memory limit, while `free` shows the host's 30 GB. On 2026-10-22 at 05:51 UTC the container restarted, likely from out-of-memory under concurrent jobs, and killed every tmux session including the live runner. It has no auto-restart.
- **Severity:** major (the cloud pipeline was down until restarted by hand).
- **Workaround:** jobs over about 3 GB RAM run one at a time under a memory lock; we read `/sys/fs/cgroup/memory.current`; the runner is restarted by hand.
- **Suggestion:** an auto-restart policy for the runner.

### GPU-5: llama.cpp silently ran on CPU

- **Task:** serve Qwen3-4B with `-ngl 99` from the ROCm release.
- **Actual:** CPU at 11 tokens per second and no error; the HIP libraries were "not found" in `ldd` (no `/opt/rocm` in the container). FL-10.
- **Severity:** medium.
- **Workaround:** link the ROCm libraries bundled with torch; then 93 to 131 tokens per second.
- **Suggestion:** warn when GPU offload is requested but no backend loads.

### GPU-6: Shared tmux leaked our environment

- **Task:** run the demo build and the test gate on one shared box.
- **Actual:** the first tmux session started the server, which copied our variables into tmux's global environment. Later sessions, including other agents', inherited them, and two API tests failed (FL-17).
- **Severity:** medium.
- **Workaround:** strip variables with `env -u` and pass them per session with `tmux new-session -e`.
- **Suggestion:** none beyond a note in the box's setup file.

### GPU-7: `uv` on PATH was a shim

- **Task:** regenerate `uv.lock` on the box.
- **Actual:** the `uv` first on PATH was a 4-line shim that only understood `uv run`, so `uv lock` ran a command named `lock` (FL-13).
- **Severity:** medium.
- **Workaround:** call the real `uv` by full path.
- **Suggestion:** name the shim `uv-run`.

---

## Build tooling

### BT-1: Fedora ffmpeg has no `libx264`

- **Task:** encode the ingest mezzanine as H.264.
- **Actual:** Fedora's ffmpeg 8.1.2 has no `libx264`; hardcoding it failed (FL-1, 2026-09-22).
- **Severity:** blocker.
- **Workaround:** `h264_encoder()` probes `ffmpeg -encoders` and picks the first available (D-10).
- **Suggestion:** probe encoders instead of assuming.

### BT-2: No Python 3.14 wheels for torch and ultralytics

- **Actual:** dependency resolution failed on the system Python 3.14 (FL-2).
- **Severity:** blocker.
- **Workaround:** `requires-python = ">=3.12,<3.13"` and a `.python-version`.

### BT-3: `uv sync` silently dropped workspace members

- **Actual:** a root with no dependencies made a bare `uv sync` prune member packages (FL-3).
- **Severity:** major.
- **Workaround:** the root now declares the members as dependencies and a `dev` group.
- **Suggestion:** error or warn in `uv`, and call this out in the docs.

### BT-4: pnpm 11 blocks build scripts until approved

- **Actual:** `esbuild` had no binary until `pnpm approve-builds` ran interactively (FL-4).
- **Severity:** major (CI).
- **Workaround:** a committed `allowBuilds: { esbuild: true }`.

### BT-5: Vite bakes environment variables at server start

- **Actual:** one dev server cannot serve two API bases for different tests (FL-6).
- **Severity:** minor.
- **Workaround:** separate `webServer` entries in the Playwright config; deployed builds read `config.json` at runtime.

### BT-6: yt-dlp stalled on a blackholed IPv6 route

- **Actual:** 60 to 120 s stall per request (FL-7). **Workaround:** `-4`. **Severity:** major.

---

## Pipeline realism

### PR-1: A real kit game broke our synthetic-era assumptions (D-97)

- **Task:** box players on the right team on a CC BY Nottingham game, 24 to 50 s, scored against a hand-labelled truth (14 instants, every 2 s; 113 players, 25 referees).
- **Actual:** player recall 0.73 after identity. The detector was not the problem (94.7% at 960 px). The identity stage capped live people at 10 and referees took three slots; red and dark kits fell into one team bin (team agreement 0.695).
- **Severity:** major.
- **Workaround:** an officials allowance, hue-saturation-value kit bins, the detector's free boxes for gaps, and no guessed bridges over 2 s. Recall 0.73 to 0.88, team accuracy 0.70 to 0.98; ghost boxes per instant 1.43 to 0.64. A 2v2 clip where everyone wears dark tops got worse (64.1% to about 59% right-person); we accepted it.
- **Suggestion:** n/a (our own pipeline). A public labelled amateur-basketball set with kits and referees would help many teams.

### PR-2: The demo game (D-98)

- **Task:** score the owner's 2v2 game against a hand list of nine moments.
- **Actual:** the baseline missed the teams, 3 of 5 X signs, two shooters and the "lost his man" moment. The court labels we tapped were mirrored against the image.
- **Severity:** major.
- **Workaround:** trust tapped court labels and un-mirror them; teams from who guards whom; X signs count only facing the camera; shooter = the player at the start of the ball's path back from the rim. Now 5 of 5 X signs with 0 false, 25 of 25 shot precision, two shooters still wrong. The thresholds were tuned on this one video.
- **Suggestion:** n/a.
