# Replay

Turn a phone video of a rec-league court-sport game — basketball first, then
pickleball, badminton and volleyball — into a follow-cam replay on your TV:
pick any player with the remote, watch the game centered on them, and pull up
their highlights and post-game review. Player tracking and court projection
are established hackathon mechanisms (see prior work like Project Horizon and
Baddy Buddy!); Replay does not claim novelty there — its contribution is the
TV-native pick-a-player experience and the complete phone-to-living-room loop
(full detail: `REPLAY_PLAN.md` §1).

Built for the Amazon Developer Hackathon (Fire TV track, AWS Builder and Open
Source mini challenges). `REPLAY_PLAN.md` is the execution spec; `docs/decisions.md`
is the running decision log; `docs/test-spec.md` is the Phase 1 test spec.

## Repo layout

```
courtcam/         MIT-licensed pipeline package (own repo, subtree-split later): calibrate,
                   detect, track, identify, crop-path, and event-detect a fixed wide-shot
                   court video. CLI: `courtcam run/calibrate/synth/overlay/render/sports`.
services/api/     FastAPI backend (Phase 1: local disk + in-process job worker, no AWS).
apps/web/         One Vite + React app: phone uploader (`/upload`) and browser-based TV
                   client (`/tv`) driven by keyboard D-pad emulation (see D-1).
docs/             decisions.md, test-spec.md, friction-log.md, product-feedback.md,
                   demo-script.md.
samples/          synthetic/ (generated CI fixture) and real/ (gitignored real footage;
                   see samples/real/MANIFEST.md for what's there and where it's from).
```

## Phase 1 status

Phase 1 targets a **browser-based TV client**, not `react-native-tvos` — there's no Fire
TV hardware yet, so `/tv` is a keyboard-driven web app behind the same `PlayerSurface` /
`platform/` seam the eventual RN/Vega port will reuse (D-1). Media is progressive MP4 with
HTTP range requests, not HLS (D-3). `courtcam` runs on CPU (YOLO11n + Ultralytics'
built-in ByteTrack) since there's no NVIDIA GPU on the dev box (D-5).

## Run it locally

### Backend (FastAPI)

```sh
uv sync                                     # from the repo root — installs courtcam +
                                             # replay-api + the dev group in one shared .venv
uv run --package replay-api uvicorn replay_api.main:app --host 0.0.0.0 --port 8000 --reload
```

Without the YOLO model — faster startup, used by the web app and CI:

```sh
REPLAY_PIPELINE=fake uv run --package replay-api uvicorn replay_api.main:app --port 8000
```

Env vars (default in parens, full table in `services/api/README.md`):

| Var | Meaning |
|---|---|
| `REPLAY_PIPELINE` | `courtcam` (real, default) or `fake` (copies a fixture output tree) |
| `REPLAY_DETECTOR` | passed through to courtcam, default `yolo` |
| `REPLAY_API_KEY` | unset ⇒ auth disabled; set ⇒ `X-Replay-Key` required |
| `REPLAY_DATA_DIR` | default `<repo>/data`; games in `<data>/games/{id}/` |
| `REPLAY_STORAGE` / `REPLAY_JOBS` | Phase 1 only supports `local` |
| `REPLAY_CORS_ORIGINS` | comma-separated origins, default `*` |

### Web (uploader + TV client)

```sh
cd apps/web && pnpm install && pnpm dev
```

- Mock mode (no backend needed): `VITE_MOCK_API=1 pnpm dev` — serves `/tv` and `/upload`
  against an in-browser fake of the API (`apps/web/src/api/mock.ts`).
- Real mode: `VITE_REPLAY_API_BASE=http://localhost:8000 pnpm dev` — point it at a running
  `services/api` (see above). Default base is `http://localhost:8000` if unset.

### Tests

```sh
uv run pytest courtcam/tests services/api/tests -q
cd apps/web && pnpm typecheck && pnpm lint && pnpm exec playwright test
```

`pnpm exec playwright test` runs two projects in one invocation: `chromium` (against
`VITE_MOCK_API=1`) and `live` (against a real `REPLAY_PIPELINE=fake` API on a wiped temp
data dir) — see `apps/web/playwright.config.ts`.

### Keyboard map (the entire input surface on `/tv` — no mouse/touch)

| Key | Action |
|---|---|
| `ArrowUp/Down/Left/Right` | D-pad move |
| `Enter` | Select |
| `Escape` / `Backspace` | Back |
| `Space` | Play/Pause |
| `,` / `.` | Seek −10 s / +10 s |
| `[` / `]` | Previous / next event |
| `b` | Bookmark |

Extra (not on a real remote's default map, hang off on-screen affordances): `s` toggles
the spotlight overlay, `t` opens the tag dialog for the focused player.

### Process a real clip from the CLI

```sh
uv run courtcam run \
    --input samples/real/basketball_parkwide_smoke.mp4 \
    --calib samples/synthetic/basketball_half/landmarks.json \
    --sport basketball --variant half \
    --out out/
```

`--calib` needs real landmark clicks for a real clip (four court corners plus the rim) —
the synthetic landmarks file above is just a shape example. See `courtcam/README.md` for
the full CLI reference, output layout, and how to add a sport. Real clips live only under
`samples/real/` (gitignored, local-only, see `samples/real/MANIFEST.md`) and need `ffmpeg`
on `PATH`; the H.264 encoder is picked at run time since not every distro ships `libx264`.
