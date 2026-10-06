# Friction log

Running log of tool/SDK/platform friction hit while building Replay (plan §9.3). Template
per entry, newest at bottom. Each entry below is grounded in this repo's code/decisions —
see the reference after each title.

### FL-1: Fedora ffmpeg ships with no `libx264` encoder
- Task attempted: encode the ingest mezzanine (`media/wide.mp4`) as H.264 from an uploaded
  clip in `courtcam`'s ingest stage.
- Steps taken: an early version of `ingest.py` hardcoded `-c:v libx264`; also confirmed
  directly with `ffmpeg -hide_banner -encoders` on the dev box.
- Expected: `libx264` available, as on most ffmpeg builds.
- Actual: Fedora's stock ffmpeg package (8.1.2) is built without `libx264` (licensing/
  packaging policy) — `-encoders` lists `libopenh264`, `h264_qsv`, `h264_vaapi`,
  `h264_nvenc`, `h264_amf`, `h264_v4l2m2m`, but no `libx264`. Hardcoding it fails immediately.
- Severity: blocker
- Workaround: `courtcam/courtcam/ingest.py::h264_encoder()` probes `ffmpeg -hide_banner
  -encoders` at run time and picks the first available of `libx264`, `libopenh264`,
  `h264_qsv`, raising a clear `RuntimeError` only if none exist (D-10). Every encode path
  goes through this function; nothing hardcodes `libx264`.
- Suggestion (actionable): document that ffmpeg's H.264 encoder set is a packaging choice,
  not a compile-flag guarantee — any tool that shells out to ffmpeg for H.264 should probe
  `-encoders` rather than assume `libx264` is present.
- Date / platform / SDK version: 2026-09-22 / Fedora Linux (7.1.12-200.fc44.x86_64) /
  ffmpeg 8.1.2

### FL-2: ultralytics/torch have no Python 3.14 wheels
- Task attempted: install `courtcam`'s dependencies (`ultralytics`, `torch`, `torchvision`)
  into the workspace `.venv`.
- Steps taken: ran `uv sync` with the system Python (3.14) as the workspace interpreter.
- Expected: `uv` resolves and installs `ultralytics` + `torch` + `torchvision` like any
  other PyPI package.
- Actual: no compatible wheels exist for Python 3.14 yet, on PyPI or the PyTorch CPU wheel
  index; dependency resolution fails.
- Severity: blocker
- Workaround: pinned `requires-python = ">=3.12,<3.13"` in the root, `courtcam`, and
  `services/api` `pyproject.toml` files, plus a root `.python-version` set to `3.12`, so
  `uv` provisions and uses a 3.12 interpreter automatically regardless of the system
  Python (D-5).
- Suggestion (actionable): torch/ultralytics' release cadence lags new CPython releases by
  months — any project depending on them should pin `requires-python` defensively instead
  of trusting the system interpreter.
- Date / platform / SDK version: 2026-09-22 / Fedora Linux / Python 3.12.13 (pinned),
  ultralytics 8.4.158, torch 2.14.0 (CPU wheel index)

### FL-3: bare `uv sync` at a workspace root with no root dependencies uninstalls members
- Task attempted: run `uv sync` from the repo root to install both workspace members
  (`courtcam`, `services/api`) into one shared `.venv`.
- Steps taken: declared `[tool.uv.workspace] members = ["courtcam", "services/api"]` in the
  root `pyproject.toml` with no `[project.dependencies]` on the root project itself, then
  ran a bare `uv sync`.
- Expected: `uv sync` installs every workspace member into the shared environment.
- Actual: with an empty root dependency list, `uv sync` treats the root project itself as
  the sync target and installs only its (empty) dependency set — packages already present
  for the members get uninstalled, since nothing in the resolved graph depends on them.
- Severity: major
- Workaround: root `pyproject.toml` now declares `dependencies = ["courtcam", "replay-api"]`
  (resolved to the workspace members via `[tool.uv.sources]`) plus a
  `[dependency-groups] dev = ["pytest", "ruff", "httpx"]` group, so a bare `uv sync`
  installs both members and the shared dev tools. Verified: `uv sync --dry-run` at the root
  now reports "Would make no changes" with both `courtcam` and `replay-api` already present
  in `uv pip list`.
- Suggestion (actionable): uv's docs should call out more prominently that a workspace root
  needs its own non-empty `dependencies` (or callers must always pass `--all-packages`) —
  otherwise `uv sync` silently prunes members instead of erroring.
- Date / platform / SDK version: 2026-09-22 / Fedora Linux / uv 0.11.11

### FL-4: pnpm 11 exits non-zero on the ignored esbuild postinstall until `pnpm approve-builds`
- Task attempted: `pnpm install` in `apps/web` after `esbuild` (a transitive `vite`
  dependency) entered the lockfile.
- Steps taken: ran `pnpm install` fresh.
- Expected: install completes; `esbuild`'s postinstall script (which fetches its native
  binary) runs like any other dependency's install script.
- Actual: pnpm 11's default supply-chain hardening blocks dependency install/postinstall
  scripts unless explicitly approved; `pnpm install` reports the ignored build script, and
  `esbuild` has no downloaded binary until a human runs `pnpm approve-builds` interactively
  — which breaks non-interactive CI.
- Severity: major
- Workaround: `apps/web/pnpm-workspace.yaml` sets `allowBuilds: { esbuild: true }`,
  allow-listing the build script non-interactively so fresh clones and CI don't need the
  interactive prompt.
- Suggestion (actionable): pnpm should make it easy for scaffolds/templates to ship a
  committed, lockfile-adjacent `allowBuilds` from day one, since the interactive
  `approve-builds` flow is fundamentally incompatible with non-interactive CI.
- Date / platform / SDK version: 2026-09-22 / Fedora Linux / pnpm 11.19.0, node v22.23.1

### FL-5: CPU-only YOLO11n at imgsz 960 is roughly 8x slower than realtime
- Task attempted: run `courtcam`'s `detect` stage (YOLO11n person detection at stride 2 =
  15 Hz, imgsz 960) over real footage on the dev box, which has no NVIDIA GPU.
- Steps taken: ran the pipeline's detect stage end to end on a real basketball clip and
  compared wall-clock time to the clip's duration.
- Expected: detection runs close to real time, or fast enough to iterate on quickly while
  tuning thresholds.
- Actual: CPU-only inference at imgsz 960 runs about 8x slower than the clip's real
  duration (see courtcam's README "Known ceilings" / detection cost note) — a 4-minute
  clip takes over half an hour to detect.
- Severity: minor (slows iteration and rules out any near-live processing story; does not
  block correctness of a finished run)
- Workaround: the detect stage samples every 2nd frame by default (stride 2, the sport
  profile's default); day-to-day development iterates on the short smoke clips
  (`samples/real/*_smoke.mp4`, ~30–45 s) instead of the full 240 s clips, and `--max-frames`
  truncates a run for quick checks.
- Suggestion (actionable): budget GPU inference (SageMaker Processing, or an EC2 GPU
  instance) for Phase 2 rather than relying on CPU throughput; a smaller `imgsz` (640) is a
  speed/recall tradeoff knob worth exposing for users who don't need small-player recall.
- Date / platform / SDK version: 2026-09-22 / Fedora Linux, CPU-only (no NVIDIA GPU) /
  ultralytics 8.4.158, torch 2.14.0 (CPU), `yolo11n.pt`

### FL-6: Vite bakes `import.meta.env` at server start, so per-test API base changes need separate servers
- Task attempted: run one Playwright suite that exercises the TV client against both the
  in-browser mock API and a real (fake-pipeline-mode) backend, by varying
  `VITE_MOCK_API` / `VITE_REPLAY_API_BASE` per test.
- Steps taken: tried pointing a single running `vite` dev server at different API bases per
  test file via env vars.
- Expected: each test could point the same running app at a different API base by setting
  an env var before that test runs.
- Actual: Vite substitutes `import.meta.env.*` (`apps/web/src/config.ts` reads
  `VITE_REPLAY_API_BASE` and `VITE_MOCK_API` this way) at bundle/server-start time, not
  per-request — a single running dev server is locked to whatever those variables were when
  it started. Changing them requires restarting the server.
- Severity: minor
- Workaround: `apps/web/playwright.config.ts` runs three separate `webServer` entries: one
  Vite server on port 5177 with `VITE_MOCK_API=1` for the `chromium` project (`apps/web/e2e/`),
  one Vite server on port 5178 with `VITE_REPLAY_API_BASE` set for the `live` project
  (`apps/web/e2e-live/`), and one `uvicorn` process (`REPLAY_PIPELINE=fake`, a wiped temp
  data dir) for that `live` project to talk to. All three start from one
  `pnpm exec playwright test` invocation.
- Suggestion (actionable): apps that need a runtime-configurable API base (not just a
  build-time one) should read it from a small `window.__CONFIG__` script tag or a runtime
  `fetch('/config.json')` instead of `import.meta.env`, so one running dev server can serve
  more than one test configuration.
- Date / platform / SDK version: 2026-09-22 / Fedora Linux / vite ^7.1.0,
  @playwright/test 1.60.0

### FL-7: yt-dlp hangs on IPv6-first DNS when the IPv6 route is blackholed
- Task attempted: download test clips with yt-dlp
- Steps taken: `yt-dlp <url>` from the dev box
- Expected: download starts within seconds
- Actual: every request stalled 60–120 s before falling back to IPv4
- Severity: major
- Workaround: pass `-4` to every yt-dlp call
- Suggestion (actionable): none for the project; environment issue worth remembering
- Date / platform / SDK version: 2026-09-22 / Fedora Linux / yt-dlp 2026.08.19

### FL-8: Metro cannot bundle shared TS outside the RN project root without `nodeModulesPaths`
- Task attempted: `./gradlew assembleRelease` for apps/tv (react-native-tvos 0.87.1-1), whose
  screens import pure TS from `packages/tv-core/` (shared with apps/web by relative path).
- Steps taken: added `packages/tv-core` to Metro `watchFolders` (the documented step for
  files outside the root); debug build (no JS bundling) succeeded, release bundling ran.
- Expected: `watchFolders` is enough for plain TS with no imports of its own.
- Actual: `createBundleReleaseJsAndAssets` failed with `Unable to resolve module
  @babel/runtime/helpers/interopRequireDefault from packages/tv-core/src/display.ts` —
  Babel injects runtime-helper imports into every transformed file, and Metro resolves them
  from the file's own directory upward, where there is no node_modules.
- Severity: blocker (release APK only; the debug APK and the web build were unaffected)
- Workaround: `resolver.nodeModulesPaths: [<app>/node_modules]` in `apps/tv/metro.config.js`.
- Suggestion (actionable): Metro's "files outside the project root" docs should say that
  watched folders without their own node_modules also need `nodeModulesPaths` because of
  injected Babel helpers; the error names a module the source never imports.
- Date / platform / SDK version: 2026-10-06 / hfbox Ubuntu, Node 22.23, JDK 17.0.20.1 /
  react-native-tvos 0.87.1-1, Metro 0.87, Gradle 9.4.1, AGP (RN 0.87 default)

## FL-9 — MIOpen on gfx1201 breaks or hangs torch models (2026-10-06)
- Task: run Kokoro TTS and transformers Whisper on the RX 9070 XT (ROCm 7.2, torch 2.14).
- Steps: default torch settings, model on `cuda`.
- Expected: speech / transcripts.
- Actual: Kokoro's `nn.LSTM` raises `miopenStatusUnknownError`; the first Whisper call hung at 0 % CPU for 20+ min while holding the box-wide GPU lock.
- Severity: high (a hang blocks every other GPU user of a shared box).
- Workaround: `torch.backends.cudnn.enabled = False` for every non-ultralytics model; wrap GPU jobs as `flock <gpu.lock> timeout N <cmd>`.
- Suggestion: ROCm/MIOpen should fail fast instead of hanging; the box READY notes should carry the workaround.

## FL-10 — llama.cpp ROCm release silently runs on CPU (2026-10-06)
- Task: serve Qwen3-4B with `llama-server -ngl 99` from the prebuilt ROCm tarball.
- Expected: GPU offload. Actual: CPU at 11 tok/s, no error; `ldd` shows the HIP libs "not found" (no /opt/rocm in the container).
- Severity: medium. Workaround: symlink torch's bundled ROCm libs into a dir on `LD_LIBRARY_PATH` (`--list-devices` then shows ROCm0; 93–131 tok/s).
- Suggestion: llama.cpp should warn loudly when `-ngl` is requested but no GPU backend loads.

## FL-11 — SAM 2.1 default dtype is 10× slower on ROCm (2026-10-06)
- Task: box-prompted video propagation with `transformers.Sam2VideoModel`.
- Expected: < 100 ms/frame. Actual: 428 ms/frame (small) in fp32. Severity: medium.
- Workaround: bf16 → 39.6 ms/frame. Also `pip install git+…/sam2` pulls CUDA torch through build isolation; use `--no-build-isolation --no-deps` with `SAM2_BUILD_CUDA=0`.

## FL-12 — Static ffmpeg build core-dumps on https inputs (2026-10-06)
- Task: cut CC clips straight from URLs. Actual: segfault. Severity: low. Workaround: download first, then cut.
