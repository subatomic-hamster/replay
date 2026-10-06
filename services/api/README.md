# replay-api

FastAPI backend for Replay, Phase 1 (plan §4.2 "local" column): local disk storage, an
in-process job worker, the heuristic labeler and the rule-based query parser. No AWS code.

## Run

```bash
uv sync                                     # from the repo root
uv run --package replay-api uvicorn replay_api.main:app --host 0.0.0.0 --port 8000 --reload
```

Without the YOLO model (web app, Playwright, CI):

```bash
REPLAY_PIPELINE=fake uv run --package replay-api uvicorn replay_api.main:app --port 8000
```

Tests (never need the model):

```bash
uv run --package replay-api pytest services/api/tests -q
```

## Environment (plan §12 rule 8)

| Var | Default | Meaning |
|---|---|---|
| `REPLAY_API_KEY` | *(unset)* | unset ⇒ auth disabled; set ⇒ `X-Replay-Key` required |
| `REPLAY_STORAGE` | `local` | Phase 1 supports `local` only |
| `REPLAY_JOBS` | `local` | Phase 1 supports `local` only |
| `REPLAY_LABELER` | `heuristic` | clip labeler provider |
| `REPLAY_QUERY` | `rules` | query engine provider |
| `REPLAY_DATA_DIR` | `<repo>/data` | games live in `<data>/games/{id}/`, jobs in `<data>/jobs.json` |
| `REPLAY_CORS_ORIGINS` | `*` | comma-separated origins |
| `REPLAY_PIPELINE` | `courtcam` | `fake` copies a fixture output tree instead of running the pipeline; `worker` runs courtcam through services/worker (content-hash cache, GPU lock), falling back to `courtcam` if `replay_worker` is not importable |
| `REPLAY_PROVIDER_<NAME>` | `local` | `local` or `aws` per provider (storage, index, jobs, labeler, query, tts, llm, embeddings, face, speaker); AWS ones are stubs (docs/aws-integrations.md) |
| `REPLAY_FAKE_PIPELINE_DIR` | `fixtures/fake_game` | the tree fake mode copies |
| `REPLAY_FAKE_PIPELINE_DELAY_S` | `0` | fake mode only: seconds each stage stays `running` (S-08) |
| `REPLAY_DETECTOR` | `yolo` | passed through to courtcam |

If `import courtcam` fails at runtime, the API logs a warning and falls back to fake mode
and a static basketball profile, so the web app still works.

## Routes (plan §4.6)

| Method | Path | Notes |
|---|---|---|
| GET | `/healthz` | no auth; reports the active providers |
| GET | `/sports` | JSON array of courtcam profiles (`id, display_name, tier, landmarks, variants, court, sport_ui`) |
| POST | `/games` | `{title, sport}` → `201 {id, upload_url}` |
| PUT | `/games/{id}/upload` | streams the request body to disk → `{id, size, status}`; also grabs `media/calib.jpg` (D-14) |
| POST | `/games/{id}/upload` | same, multipart `file` field (browsers) |
| POST | `/games/{id}/calibration` | `{sport, variant, landmarks_px}`; ≥ 4 landmarks the template knows — `landmarks` ∪ `landmarks_optional`, no specific ones required (D-19); returns `reprojection_error_px`, `400` if courtcam rejects the clicks |
| POST | `/games/{id}/process` | `202 {job_id, status}`; needs an upload + calibration; idempotent while a job is queued/running (D-17) |
| GET | `/games` | JSON array: id, title, status, stages, duration_s, thumb_url, recorded_at, sport (+ `progress` while processing) |
| GET | `/games/{id}` | `game.json` with media/tracks/crops/events URLs resolved absolute, plus `thumb_url`, `calib_url`, `sport_ui` (built from *this game's* court variant), and live `stages`/`progress` merged from the job record (D-17) |
| PATCH | `/games/{id}/players/{pid}` | `{name?, merge_into?}`; merge rewrites ids in tracks + events |
| POST | `/games/{id}/players/{pid}/render` | `202`, lazy rendition render |
| PATCH | `/games/{id}/events/{eid}` | confirm/correct; sets `confirmed`, `source:"user"` on a change; `{"dismissed": true}` is "not a shot" (D-11) |
| POST | `/games/{id}/events` | `{t}` → bookmark `t−3 / t / t+2` |
| POST | `/games/{id}/query` | `{text}` → `{interpretation, clips[]}` |
| GET | `/games/{id}/stats` | `{box_score, shots, heatmap, totals}` (D-12); dismissed events excluded |
| POST | `/sessions` | `201 {id, code}` (4-digit pairing code) |
| WS | `/sessions/{sid}` | in-memory fan-out, phone → TV (`{type:"query", text}`); `{sid}` may be the session id or its 4-digit code (D-16) |
| GET | `/media/games/{id}/{path}` | static files with HTTP Range (206), no auth, no traversal |

Errors are `{"detail": "..."}`: `404` unknown game/player/event, `400`/`422` bad input.

## Layout

```
replay_api/
  config.py            env -> Settings
  main.py              app factory, routes, job tasks
  pipeline_adapter.py  the ONLY module that imports courtcam (+ fake mode)
  stats.py             derived stats
  providers/           one module per provider (Protocol + local impl): storage, index,
                       jobs, labeler, query, tts, llm, embeddings, face, speaker;
                       aws.py = every AWS stub; __init__.py = REPLAY_PROVIDER_* selection
fixtures/
  fake_game/           schema-valid output tree (2 players, 20 s @ 10 Hz, 4 events)
  tiny.mp4             20 s 1280×720 30 fps test video
```

`game.json` on disk is the source of truth; the index just enumerates `data/games/*/game.json`
(no SQLite — one process, tens of games, and a second copy would only drift). Phase 2 swaps
each provider for an AWS one; routes only see the Protocol.

While the pipeline runs, **courtcam owns `game.json`** (it rewrites it after every stage), so
the API writes it only at job start and at completion; per-stage progress goes to the job
record in `data/jobs.json` and is merged back in on read (D-17): the read path turns the
job's `{stage, fraction}` into `stages` + `progress` and forces `status: "processing"`.
