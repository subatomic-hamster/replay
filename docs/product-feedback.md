# Product feedback

One section per tool/API/SDK used, per plan §9.3: what we used it for, what worked, what
needs work, onboarding experience, would we build with it again. Filled sections are drawn
from `docs/friction-log.md` and `docs/decisions.md`; TODO sections are for Phase 2/3 tools
not yet integrated.

## uv (Python packaging / workspace)

- **What we used it for:** the whole Python side — resolving and syncing the two-member
  workspace (`courtcam`, `services/api`) into one shared `.venv`, pinning the interpreter,
  and running everything (`uv run`, `uv run --package <name>`).
- **What worked:** workspace member resolution, the pinned interpreter provisioning (it
  installs Python 3.12 itself rather than fighting the system's 3.14), and `--package` to
  target one member's entry point were all straightforward once set up.
- **What needs work:** a workspace root with no `[project.dependencies]` of its own
  silently drops member packages on a bare `uv sync` instead of erroring — this cost real
  debugging time (see FL-3) before we added root-level `dependencies` + a `dev`
  dependency group.
- **Onboarding experience:** fast for a single package; the workspace-root gotcha above is
  the one sharp edge, and it isn't called out prominently in the docs we read.
- **Would we build with it again:** yes — resolution speed and the built-in interpreter
  management are a clear win over pip/venv, once the workspace-root dependency quirk is
  known.

## ultralytics (YOLO11n detection + tracking)

- **What we used it for:** person detection (`detect` stage) and, via `model.track(tracker="bytetrack.yaml")`,
  the tracklet association step, so `courtcam` never needed a separate ByteTrack dependency.
- **What worked:** the built-in tracker integration meant one dependency covered both
  detection and tracking; `yolo11n.pt` loads and runs with no extra setup beyond the CPU
  torch wheels.
- **What needs work:** no Python 3.14 wheels yet (FL-2, forced a 3.12 pin for the whole
  workspace), and CPU-only inference at imgsz 960 runs roughly 8x slower than realtime
  (FL-5), which caps iteration speed during tuning.
- **Onboarding experience:** the API itself (`model.track(...)`) is simple; the friction
  was entirely in the surrounding Python/CUDA-vs-CPU wheel ecosystem, not the library's
  own interface.
- **Would we build with it again:** yes for the model quality and tracker bundling; we'd
  budget GPU inference (SageMaker Processing) earlier if CPU throughput matters for a demo.

## FastAPI / Starlette `FileResponse` range support

- **What we used it for:** serving progressive MP4 media (`GET /media/games/{id}/{path}`)
  with HTTP Range support (206 partial content), since Phase 1 has no HLS ladder and
  Chromium needs range-seekable MP4 for scrubbing (D-3).
- **What worked:** Starlette's `FileResponse` (`services/api/replay_api/main.py`) handles
  `Range` request headers and returns 206 responses out of the box — no custom range-parsing
  code was needed, just returning `FileResponse(target)` and exposing
  `Content-Range`/`Accept-Ranges`/`Content-Length` through CORS.
- **What needs work:** nothing found yet at Phase 1 scale (single local file, no CDN); this
  is expected to need revisiting once media is served from S3/CloudFront in Phase 2, where
  range support has to be re-verified against a different serving path.
- **Onboarding experience:** effectively zero friction — this "just worked" the first time
  it was tried against a real `<video>` seek in the browser.
- **Would we build with it again:** yes; for local/dev media serving this is the easiest
  range-request implementation of anything in the stack so far.

## Playwright

- **What we used it for:** end-to-end testing of the entire `/tv` and `/upload` surface —
  two projects in one `playwright.config.ts`: `chromium` against an in-browser mock API,
  `live` against a real `REPLAY_PIPELINE=fake` backend.
- **What worked:** running two independently-configured dev servers plus a backend process
  as Playwright `webServer` entries, all from one `pnpm exec playwright test` invocation,
  worked cleanly; keyboard-only interaction (no mouse/touch on `/tv`) is easy to drive since
  the whole product is keyboard-native by design (D-1).
- **What needs work:** Vite's `import.meta.env` is baked in at server start, not read
  per-request, so testing the same screens against two different API bases needs two
  separate dev server processes rather than one server with per-test env overrides (FL-6);
  this is a Vite constraint the config has to route around, not a Playwright limitation.
- **Onboarding experience:** straightforward — the `webServer` array in the config handles
  spinning up and tearing down all three processes (two Vite servers, one uvicorn) without
  extra scripting.
- **Would we build with it again:** yes; multi-project configs with different `webServer`
  entries are a clean way to cover both a fast mock-driven suite and a slower
  real-backend suite from one command.

## Vite / React

- **What we used it for:** the entire `apps/web` app — one Vite + React 19 project serving
  both the phone uploader (`/upload`) and the browser TV client (`/tv`), sharing one dev
  server and one `package.json` (D-2).
- **What worked:** fast dev server startup and HMR, plain `import.meta.env.VITE_*` env vars
  for the two runtime modes (mock vs. real API), and `tsc --noEmit` + `eslint` both ran
  clean against the current codebase with no configuration fights.
- **What needs work:** the same `import.meta.env` bake-in noted under Playwright above —
  it's a build-time substitution, so anything that wants a runtime-configurable value (like
  swapping API bases without a restart) has to work around it rather than through it.
- **Onboarding experience:** minimal — one `pnpm install` and `pnpm dev` gets a working dev
  server; pnpm's build-script approval gate (FL-4) was the only install-time hiccup, and it
  is a pnpm behavior, not a Vite/React one.
- **Would we build with it again:** yes; for a small single-page keyboard-driven app this is
  about as little ceremony as the ecosystem offers.

---

## TODO — not yet integrated (Phase 2/3)

### Vega SDK + simulator
TODO: fill in once the Vega port (plan §8) starts. Groundwork (audit, `PlayerSurface`
compatibility) can start Oct 7 per the schedule but hasn't yet.

### react-native-tvos
TODO: fill in once the RN/Vega port begins. Phase 1 deliberately stays on a browser TV
client (D-1) so this hasn't been touched yet; `PlayerSurface` and `platform/` exist as the
seam it will slot into.

### Fire TV device
TODO: fill in once real Fire TV hardware is in hand and a build has run on it (open
question in plan §14 — hardware not yet confirmed).

### AWS S3
TODO: fill in once Phase 2 storage provider work starts (plan §7).

### AWS CloudFront
TODO: fill in once Phase 2 media delivery work starts.

### AWS Lambda
TODO: fill in once Phase 2 job/processing infra starts.

### AWS API Gateway
TODO: fill in once the API is fronted by API Gateway in Phase 2.

### AWS DynamoDB
TODO: fill in once the index/job-state store moves off local JSON files in Phase 2.

### AWS Step Functions
TODO: fill in once the pipeline is orchestrated as a Step Functions workflow in Phase 2.

### AWS SageMaker (Processing)
TODO: fill in once GPU detection/inference moves to SageMaker Processing in Phase 2 —
likely answer to FL-5's CPU throughput ceiling.

### Bedrock (Nova + Converse)
TODO: fill in once the VLM labeler/query paths are wired to Bedrock Nova via Converse
(plan §4.4 stage 10, §4.7). Phase 1 uses the deterministic heuristic labeler and rule-based
query parser only (plan §12 rule 7).

### Alexa+ MCP
TODO: only if the optional phone-companion voice path (plan §2.1/H4) is built; not started.
