# replay-api

FastAPI backend for Replay, Phase 1 (plan §4.2 "local" column): local disk storage, an
in-process job worker, the heuristic labeler and the rule-based query parser. Cloud mode
(D-80, `REPLAY_STORAGE=s3` + `REPLAY_JOBS=s3`, [below](#cloud-mode-d-80)) runs the same
app on Lambda over one S3 bucket, with jobs run by a remote runner on hfbox.

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

| Var                            | Default                                      | Meaning                                                                                                                                                                                                                                                                                                                                        |
| ------------------------------ | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `REPLAY_API_KEY`               | _(unset)_                                    | unset ⇒ auth disabled; set ⇒ `X-Replay-Key` required                                                                                                                                                                                                                                                                                           |
| `REPLAY_STORAGE`               | `local`                                      | `local`, or `s3` (cloud mode, with `REPLAY_JOBS=s3`)                                                                                                                                                                                                                                                                                           |
| `REPLAY_JOBS`                  | `local`                                      | `local`, or `s3` (cloud mode, with `REPLAY_STORAGE=s3`)                                                                                                                                                                                                                                                                                        |
| `REPLAY_UPLOAD_TOKEN_SECRET`   | random per process                           | HMAC key of the per-game upload tokens (`POST /games`)                                                                                                                                                                                                                                                                                         |
| `REPLAY_PUBLIC_WEB_BASE`       | _(unset)_                                    | phone page origin; set ⇒ `POST /games` returns `upload_page_url`                                                                                                                                                                                                                                                                               |
| `REPLAY_LABELER`               | `heuristic`                                  | clip labeler provider                                                                                                                                                                                                                                                                                                                          |
| `REPLAY_QUERY`                 | `rules`                                      | query engine provider                                                                                                                                                                                                                                                                                                                          |
| `REPLAY_DATA_DIR`              | `<repo>/data`                                | games live in `<data>/games/{id}/`, jobs in `<data>/jobs.json`                                                                                                                                                                                                                                                                                 |
| `REPLAY_CORS_ORIGINS`          | `*`                                          | comma-separated origins                                                                                                                                                                                                                                                                                                                        |
| `REPLAY_PIPELINE`              | `courtcam`                                   | `fake` copies a fixture output tree instead of running the pipeline; `worker` runs courtcam through services/worker (content-hash cache, GPU lock), falling back to `courtcam` if `replay_worker` is not importable                                                                                                                            |
| `REPLAY_PROVIDER_<NAME>`       | `local`                                      | `local` or `aws` per provider (storage, index, jobs, labeler, query, tts, llm, embeddings, face, speaker); AWS ones are stubs (docs/aws-integrations.md)                                                                                                                                                                                       |
| `REPLAY_FAKE_PIPELINE_DIR`     | `fixtures/fake_game`                         | the tree fake mode copies                                                                                                                                                                                                                                                                                                                      |
| `REPLAY_FAKE_PIPELINE_DELAY_S` | `0`                                          | fake mode only: seconds each stage stays `running` (S-08)                                                                                                                                                                                                                                                                                      |
| `REPLAY_DETECTOR`              | `yolo`                                       | passed through to courtcam                                                                                                                                                                                                                                                                                                                     |
| `REPLAY_MODEL_VENVS`           | _(unset)_                                    | dir holding the model venvs (`tts` Kokoro, `emb` SigLIP, `speaker` ECAPA; box: `/workspace/wt/replay-env/venvs`, docs/models.md). Unset ⇒ those providers raise `NotConfiguredError` naming this variable: search answers 503, the worker's `commentary` stage writes a text-only script (`tts.skipped`), `embeddings` fails with that message |
| `REPLAY_MODEL_DEVICE`          | `cuda`                                       | `cpu` runs the model venvs without the GPU lock                                                                                                                                                                                                                                                                                                |
| `REPLAY_LLM_URL`               | _(unset)_                                    | llama.cpp server for LLM paraphrases / query filters (providers/llm.py); unset ⇒ templates only                                                                                                                                                                                                                                                |
| `REPLAY_GPU_LOCK`              | `/workspace/airtools/.gpu.lock` if it exists | lock file the model runner and worker take around GPU work                                                                                                                                                                                                                                                                                     |

User corrections (event PATCHes, bookmarks, roster names / merges / profile links, clip
trims, tap triggers, score entries) are recorded in `<game>/edits.json` and applied on
top of the pipeline's files, so they survive any re-run (D-61, `replay_api/edits.py`).

If `import courtcam` fails at runtime, the API logs a warning and falls back to fake mode
and a static basketball profile, so the web app still works.

## Routes (plan §4.6)

| Method | Path                                                  | Notes                                                                                                                                                                                                                 |
| ------ | ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/healthz`                                            | no auth; reports the active providers                                                                                                                                                                                 |
| GET    | `/sports`                                             | JSON array of courtcam profiles (`id, display_name, tier, landmarks, variants, court, sport_ui`)                                                                                                                      |
| POST   | `/games`                                              | `{title, sport}` → `201 {id, upload_url, upload_token, upload_page_url?, upload: {mode}}` (`put` + `url` locally, `multipart` in cloud mode)                                                                          |
| GET    | `/games/{id}/jobs`                                    | the game's jobs, oldest first                                                                                                                                                                                         |
| POST   | `/games/{id}/upload/multipart`, `/complete`, `/abort` | cloud mode only (`409` locally); see Cloud mode                                                                                                                                                                       |
| PUT    | `/games/{id}/upload`                                  | streams the request body to disk → `{id, size, status}`; also grabs `media/calib.jpg` (D-14)                                                                                                                          |
| POST   | `/games/{id}/upload`                                  | same, multipart `file` field (browsers)                                                                                                                                                                               |
| POST   | `/games/{id}/calibration`                             | `{sport, variant, landmarks_px}`; ≥ 4 landmarks the template knows — `landmarks` ∪ `landmarks_optional`, no specific ones required (D-19); returns `reprojection_error_px`, `400` if courtcam rejects the clicks      |
| POST   | `/games/{id}/process`                                 | `202 {job_id, status}`; needs an upload + calibration; idempotent while a job is queued/running (D-17)                                                                                                                |
| GET    | `/games`                                              | JSON array: id, title, status, stages, duration_s, thumb_url, recorded_at, sport (+ `progress` while processing)                                                                                                      |
| GET    | `/games/{id}`                                         | `game.json` with media/tracks/crops/events URLs resolved absolute, plus `thumb_url`, `calib_url`, `sport_ui` (built from _this game's_ court variant), and live `stages`/`progress` merged from the job record (D-17) |
| PATCH  | `/games/{id}/players/{pid}`                           | `{name?, merge_into?}`; merge rewrites ids in tracks + events                                                                                                                                                         |
| POST   | `/games/{id}/players/{pid}/render`                    | `202`, lazy rendition render                                                                                                                                                                                          |
| PATCH  | `/games/{id}/events/{eid}`                            | confirm/correct; sets `confirmed`, `source:"user"` on a change; `{"dismissed": true}` is "not a shot" (D-11)                                                                                                          |
| POST   | `/games/{id}/events`                                  | `{t}` → bookmark `t−3 / t / t+2`                                                                                                                                                                                      |
| POST   | `/games/{id}/query`                                   | `{text}` → `{interpretation, clips[]}`                                                                                                                                                                                |
| GET    | `/games/{id}/stats`                                   | `{box_score, shots, heatmap, totals}` (D-12); dismissed events excluded                                                                                                                                               |
| POST   | `/sessions`                                           | `201 {id, code}` (4-digit pairing code)                                                                                                                                                                               |
| WS     | `/sessions/{sid}`                                     | in-memory fan-out, phone → TV (`{type:"query", text}`); `{sid}` may be the session id or its 4-digit code (D-16)                                                                                                      |
| GET    | `/media/games/{id}/{path}`                            | static files with HTTP Range (206), no auth, no traversal                                                                                                                                                             |

Errors are `{"detail": "..."}`: `404` unknown game/player/event, `400`/`422` bad input.

With `REPLAY_API_KEY` set, `X-Replay-Upload-Token` (from `POST /games`, 24 h) stands in for
the key on that one game's phone routes: `GET /games/{id}`, `GET /games/{id}/jobs`,
`/upload*`, `/calibration*`, `/process`, plus `GET /sports`.

## Cloud mode (D-80)

Contract: [docs/aws-migration.md](../../docs/aws-migration.md). Lambda entry:
`replay_api.lambda_handler.handler` (Mangum). Needs boto3 and, for the calibration frame,
`opencv-python-headless` in the bundle.

| Var                                             | Meaning                                                                                                                                                                                                             |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `REPLAY_STORAGE=s3`, `REPLAY_JOBS=s3`           | both, or neither                                                                                                                                                                                                    |
| `REPLAY_S3_BUCKET`                              | games in `games/{id}/`, jobs in `jobs/`, profiles in `profiles/profiles.sqlite`                                                                                                                                     |
| `REPLAY_SSM_PREFIX`                             | e.g. `/replay/`: `api-key`, `worker-key`, `upload-token-secret` are read from SSM once per cold start; unset ⇒ `REPLAY_API_KEY`, `REPLAY_WORKER_KEY`, `REPLAY_UPLOAD_TOKEN_SECRET` from env. All three are required |
| `REPLAY_DATA_DIR`                               | scratch mirror, default `/tmp/replay`                                                                                                                                                                               |
| `REPLAY_PUBLIC_WEB_BASE`, `REPLAY_CORS_ORIGINS` | as above                                                                                                                                                                                                            |

How it works (`replay_api/cloud.py`): routes keep using local Paths. `storage.path(id, rel)`
lists that prefix in S3 (once per request) and downloads what changed since this instance
last saw it, by ETag, so JSON state is never stale across instances; video/audio and
anything over 64 MiB become sparse stubs of the right size. When the request ends, files
it changed are uploaded and files it deleted are deleted. `/media/games/...` answers `302`
to a presigned GET (1 h; S3 serves Range). Jobs are `jobs/{job_id}.json` plus a queue
marker; only `process` and `autocalib` exist in cloud mode (others `503`), and none runs
in Lambda. `/sessions` is `501`; LLM, TTS, embeddings, face and speaker answer `503`.

| Method | Path                                | Notes                                                                                                                                   |
| ------ | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/games/{id}/upload/multipart`      | `{size, content_type}` → `{upload_id, part_size, parts: [{n, url}]}`; 16 MiB parts (grown to stay ≤ 1000), 6 h presigned PUTs, ≤ 20 GiB |
| POST   | `/games/{id}/upload/complete`       | `{upload_id, parts: [{n, etag}]}` → the game, `status: uploaded`, `calib_url` (OpenCV reads the frame through a presigned GET)          |
| POST   | `/games/{id}/upload/abort`          | `{upload_id}`                                                                                                                           |
| POST   | `/worker/claim`                     | `X-Replay-Worker-Key`; `204`, or `{job, game_id, files: [{path, url, size}]}` (claim = S3 conditional write, one runner per job)        |
| POST   | `/worker/jobs/{job_id}/progress`    | `{stage, fraction, ...}` merged into the running job                                                                                    |
| POST   | `/worker/jobs/{job_id}/upload-urls` | `{paths}` → `{path: presigned PUT}`; a path leaving the game folder is `400`                                                            |
| POST   | `/worker/jobs/{job_id}/finish`      | `{ok, error?}` → `done` / `failed`                                                                                                      |

Remote runner on hfbox (no AWS credentials; in a named tmux session):

```bash
tmux new -d -s replay-runner -e REPLAY_WORKER_KEY=... -e REPLAY_DATA_DIR=/workspace/wt/replay-mirror \
  -e REPLAY_PIPELINE=worker 'python -m replay_api.remote_runner --api https://<function-url>'
```

It polls every 30 s (`--interval`, `--once` for one claim), mirrors the game folder
(same size ⇒ skipped), runs the job through `main._process_task` / `_autocalib_task`
exactly as the local API does, posts progress, uploads new or changed files (game.json
last) and finishes the job. HTTP failures are retried with backoff; a job it cannot
finish stays `running` in S3 (logged), never silently dropped.

## Layout

```
replay_api/
  config.py            env -> Settings
  main.py              app factory, routes, job tasks
  auth.py              per-game upload tokens, constant-time key compares (D-80)
  cloud.py             cloud mode: S3 mirror storage, S3 index/jobs/profiles, SSM secrets
  cloud_routes.py      multipart upload + /worker routes
  remote_runner.py     hfbox runner for cloud-mode jobs
  lambda_handler.py    Lambda entry (Mangum)
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
