# AWS migration: QR upload and cloud API (D-80)

Goal: no phone app. The TV shows a QR code; the phone opens a plain web page from it,
uploads a video straight to S3, calibrates, and starts processing. The API and both web
frontends run on AWS. GPU stages stay on hfbox (an AWS GPU would burn the $100-$200 free
plan credit in days), so hfbox becomes a pull-based remote worker that needs no AWS
credentials.

## Budget rules

Free plan account, $100 credit plus $20 per finished credit activity. Everything below sits
in always-free or near-zero tiers; target spend is under $2/month.

| Piece                               | Service                                        | Why it is cheap                                        |
| ----------------------------------- | ---------------------------------------------- | ------------------------------------------------------ |
| Web apps (phone page, TV web build) | S3 + CloudFront (OAC)                          | CloudFront always-free 1 TB / 10M requests             |
| API                                 | Lambda (python3.12, arm64, zip) + Function URL | always-free 1M requests / 400k GB-s; no API Gateway    |
| Games, media, jobs                  | one private S3 bucket                          | a few GB; LIST polling every 30 s is about $0.40/month |
| Secrets                             | SSM Parameter Store SecureString (aws/ssm key) | standard parameters are free                           |
| GPU work                            | hfbox remote runner, pulls jobs over HTTPS     | no AWS compute                                         |

Not used: NAT gateways, VPC endpoints, API Gateway, SQS long-poll from Lambda (billed as
Lambda duration), ECR images, RDS/DynamoDB in the request path. A $10/month budget with
email alerts at 50/80/100% actual and 100% forecast exists (`replay-monthly-10usd`).

## Topology

```
TV (Fire TV app / TV web)        phone browser                     hfbox
   | POST /games (X-Replay-Key)     | /u/{id}#t=<token>              | replay remote runner
   | shows QR -> upload_page_url    | multipart PUTs -> S3 presigned | POST /worker/claim (X-Replay-Worker-Key)
   | polls GET /games/{id}          | calibrate, process             | GET inputs, PUT outputs (presigned)
   v                                v                                v
        Lambda Function URL (FastAPI via Mangum, REPLAY_STORAGE=s3, REPLAY_JOBS=s3)
                                    |
                 S3 bucket: games/{id}/..., jobs/..., profiles/...
CloudFront: / -> apps/web build (phone page + /tv routes), /tvapp/ -> apps/tv web build
```

The API is called directly at its Function URL (CORS via `REPLAY_CORS_ORIGINS`), not through
CloudFront: CloudFront OAC to a Lambda URL needs a client-computed payload hash on PUT/POST.

## API contract (cloud mode)

Local mode (`REPLAY_STORAGE=local`, `REPLAY_JOBS=local`) keeps working unchanged, including
every existing route and test. Cloud mode is `REPLAY_STORAGE=s3` + `REPLAY_JOBS=s3`.

### Auth

- `X-Replay-Key`: the existing shared key (`REPLAY_API_KEY`). Required for everything in
  cloud mode except `/healthz`, `/media/...`, routes accepting an upload token, and `/worker/...`.
- `X-Replay-Upload-Token`: per-game capability for the phone page. Token =
  `base64url(game_id "." exp "." HMAC-SHA256(secret, game_id "." exp))`, exp = now + 24 h.
  Accepted (instead of the key) only on routes for that same game: `GET /games/{id}`,
  `GET /games/{id}/jobs` / status, upload init/complete, calibration GET/PUT,
  autocalibrate, process, upload parts (resume). Not `/moments` or `/storyboard`.
- `X-Replay-Worker-Key`: hfbox runner key (`REPLAY_WORKER_KEY`), only on `/worker/...`.
- Secret values come from SSM: `REPLAY_SSM_PREFIX` (e.g. `/replay/`) + `api-key`,
  `worker-key`, `upload-token-secret`, read once per cold start. Local mode reads the
  same three from env (`REPLAY_API_KEY`, `REPLAY_WORKER_KEY`, `REPLAY_UPLOAD_TOKEN_SECRET`).
  Never in git, never in the CloudFormation template.

### Game creation (TV)

`POST /games` (existing body) additionally returns:

- `upload_token`: as above.
- `upload_page_url`: `${REPLAY_PUBLIC_WEB_BASE}/u/{id}#t={upload_token}` (token in the
  fragment so it never reaches CloudFront or S3 logs). Omitted when
  `REPLAY_PUBLIC_WEB_BASE` is unset.
- `upload`: `{"mode": "put", "url": ...}` in local mode (existing PUT route) or
  `{"mode": "multipart"}` in cloud mode.

### Multipart upload (phone, cloud mode; also allowed in local mode returning 409)

- `POST /games/{id}/upload/multipart` `{size, content_type}` ->
  `{upload_id, part_size, parts: [{n, url}]}`. Part size 16 MiB (grow it so parts <= 1000),
  presigned PUT URLs valid 6 h, max object 20 GiB.
- `POST /games/{id}/upload/complete` `{upload_id, parts: [{n, etag}]}` -> completes the
  upload into `games/{id}/source.mp4`, grabs the calibration frame (`media/calib.jpg`, via
  OpenCV reading a presigned GET URL, no ffmpeg binary), sets status `uploaded`, returns
  the game.
- `POST /games/{id}/upload/abort` `{upload_id}`.
- `GET /games/{id}/upload/parts?upload_id=&size=` (token allowed) ->
  `{upload_id, part_size, done: [{n, etag, size}], parts: [{n, url}]}`: resume. `done` lists the full-size parts S3
  holds (a part cut short goes again), `parts` fresh URLs for the rest; 404 once the upload
  is completed or aborted. The upload id only names an upload of this game's source key.
  The phone keeps `{upload_id, part_size, name, size, etags}` in localStorage under
  `replay.upload.<game id>`; re-picking the same file (name + size) after a reload or a
  dropped connection sends only the missing parts. Only Cancel aborts.
- Bucket CORS allows PUT from the web origin and exposes `ETag`.

### Media

`GET /media/games/{id}/{path}` -> 302 to a presigned S3 GET (1 h) in cloud mode.
Video elements follow redirects and keep Range support.

### Jobs and the remote worker

Cloud-mode jobs are stored in S3 (`jobs/{job_id}.json`, queue marker `jobs/queue/{ts}-{job_id}`)
with the same shape and the same kinds (`process`, `autocalib`) as `LocalJobs`; nothing
runs in Lambda. Claiming uses S3 conditional writes (`If-None-Match: *` on
`jobs/claims/{job_id}`), so two runners never take the same job.

- `POST /worker/claim` -> 204, or `{job: {...}, game_id, files: [{path, url, size}]}`:
  presigned GETs for every object under `games/{id}/` (the runner skips files it has with
  the same size).
- `POST /worker/jobs/{job_id}/progress` `{stage, done, total, ...}` -> merged into the job.
- `POST /worker/jobs/{job_id}/upload-urls` `{paths: [...]}` -> `{path: presigned PUT}`.
  Paths are relative to `games/{id}/` and must stay inside it.
- `POST /worker/jobs/{job_id}/finish` `{ok, error?}` -> job `done`/`failed`; the runner has
  already uploaded `game.json`.

Runner on hfbox: `python -m replay_api.remote_runner --api <base>` (env
`REPLAY_WORKER_KEY`, `REPLAY_DATA_DIR` as its local mirror). It polls every 30 s, mirrors
the game folder, runs the job with the same local code paths (`pipeline_adapter`, the
autocalib task), uploads new or changed files, and finishes the job. While a process job
runs, files under `media/` and `storyboard/` go up after every stage (background thread),
so the TV can play the mezzanine (`watchable`) and scrub before the run ends. It runs in a named
tmux session and takes the GPU lock through the worker as today.

### Cloud-mode gaps (documented, not hidden)

- `/sessions` WebSocket (phone companion query channel): 501 in cloud mode. The QR page
  replaces the companion upload; Lambda URLs have no WebSockets.
- Profiles: SQLite file mirrored to `profiles/profiles.sqlite` in S3, write-through on
  change; one writer assumed. Face and voice data stay enrolled-and-consenting only.
- Providers that need hfbox-local services (LLM_URL, ECAPA, face models) return 503 in
  cloud mode until their AWS provider lands.

## Phone and TV UX

- TV: "Add game" picks a sport, calls `POST /games`, shows the QR (rendered from
  `upload_page_url` as a grid of Views; works on native and web) plus the short URL, then
  polls the game: waiting for upload, uploaded, calibrating, processing with stage
  progress, ready (opens the game).
- Phone `/u/{id}#t=...`: pick video, multipart upload with progress and per-part retry
  (3 parts in flight), calibration (existing screen, token auth), process, status.

## Testing rules

- Cloud tests use synthetic clips only. `samples/real` stays off S3 (D-7, D-76).
- API cloud mode is unit-tested against a fake S3 (moto, dev dependency only).
- Every stage keeps `scripts/box-test.sh` ALL GREEN.
