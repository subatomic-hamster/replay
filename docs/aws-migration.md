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
  cloud mode except `/healthz`, `/config`, `/media/...`, routes accepting an upload or phone
  token, and `/worker/...`.
- `X-Replay-Upload-Token`: per-game capability for the phone page. Token =
  `base64url(game_id "." exp "." HMAC-SHA256(secret, game_id "." exp))`, exp = now + 24 h.
  Accepted (instead of the key) only on routes for that same game: `GET /games/{id}`,
  `GET /games/{id}/jobs` / status, upload init/complete, calibration GET/PUT,
  autocalibrate, process, upload parts (resume). Not `/moments` or `/storyboard`.
- `X-Replay-Phone-Token`: per-game capability for the "do it on your phone" pages (clip,
  tag, review, search). Token = `base64url("phone." game_id "." exp "." HMAC-SHA256(secret,
"phone." game_id "." exp))`, exp = now + 24 h, same `upload-token-secret`. The kind is
  inside the signed body, so a phone token never passes as an upload token or the other
  way round. Accepted (instead of the key) only on this allowlist (`auth.PHONE_ROUTES`;
  `{g}` must be the token's game):
  - `GET /sports`, `GET /profiles`, `POST /profiles` (name only: a `photo_url` is 403)
  - `POST /profiles/{pid}/links` (body `game_id` must be the token's game, else 403),
    `DELETE /profiles/{pid}/links/{g}/{player_id}`
  - `GET /games/{g}` and its `/moments`, `/storyboard`, `/plays`, `/triggers`, `/clips`,
    `/score`, `/stats`, `/renditions`, `/review/queue`, `/exports/vertical`,
    `/exports/vertical/{vid}`, `/exports/reel`, `/exports/reel/{rid}`
  - `POST /games/{g}/triggers` (make a clip), `PATCH /games/{g}/clips/{cid}` (trim),
    `POST /games/{g}/exports/vertical` (9:16 aspect), `POST /games/{g}/exports/reel`
    (highlight reel)
  - `PATCH /games/{g}/players/{player_id}` (name, merge), `PATCH /games/{g}/events/{eid}`
    (review answers)
  - `POST /games/{g}/search`, `POST /games/{g}/query` (search's fallback)

  Never: uploads, calibration, process, bookmarks, `GET /games`, other games, phone-link,
  `GET/PATCH/DELETE /profiles/{pid}`, profile photo/face/card, `/worker`, `/sessions`.
  Events come from the game's `events_url` (under `/media`, open as before).

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

### Phone pages (TV "do it on your phone")

- `GET /config` (public, no key, local and cloud): `{"web_base": str | null}` from
  `REPLAY_PUBLIC_WEB_BASE`, trailing slash stripped. Nothing secret.
- `POST /games/{id}/phone-link` (X-Replay-Key) `{"job": "clip"|"tag"|"review"|"search"|"reel",
"t": number|null}` -> `{"url", "token", "expires_at"}`. `url` =
  `{web_base}/p/{id}?job={job}[&t={t}]#k={token}` (t without trailing zeros), null when
  `REPLAY_PUBLIC_WEB_BASE` is unset; `expires_at` is unix seconds. 404 unknown game, 422
  bad job or negative t. The phone sends the token as `X-Replay-Phone-Token`. Plain HTTP
  only (no WebSocket), so it works on Lambda.

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

`GET /media/games/{id}/{path}[?v=<etag>]` -> 302 to a presigned S3 GET in cloud mode.
Video elements follow redirects and keep Range support.

Caching (2026-10-22): the presigned URL is signed at the start of the current hour
(`REPLAY_MEDIA_SIGN_WINDOW_S`, default 3600) and valid for two windows, so every request
in that hour gets the same URL. The 302 says `Cache-Control: public, max-age=<seconds left
in the window>`, so the TV's HTTP stack and browsers skip the Lambda hop while it holds.
The API names images (thumb, hero, moment thumbs, storyboard sheets, calibration frame)
with `?v=<first 16 chars of the S3 ETag>`: a re-process that changes a picture changes
its URL (the TV's image cache is keyed by URL), and the version also shifts the signing
time by up to 10 min, so the S3 URL differs too. S3 answers versioned images with
`Cache-Control: public, max-age=7200, immutable` (`response-cache-control`, signed into
the URL, so existing objects need no re-upload) and everything else (video, JSON) with
`no-cache` (revalidated with the ETag, never served stale; a stable URL with no header
would let browsers cache heuristically). `REPLAY_MEDIA_SIGN_WINDOW_S=0` restores a fresh
URL per request and `Cache-Control: no-store` on the 302.

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
tmux session and takes the GPU lock through the worker as today. Its log never holds a
presigned query (security token, signature): `httpx`/`httpcore` log at WARNING, the runner
logs `GET`/`PUT` with the URL path only, and HTTP errors name the path only.

### Highlight reel (local and cloud, 2026-10-22)

One shareable MP4 of a game: the user's clips first (voice "Replay, clip that", the X
sign, phone taps, bookmarks), then the top plays (hype candidates by score, else the
replay-angle highlight selection), overlaps over half dropped, at most 90 s, in game
order, a 0.3 s dip to black at each join, a caption per segment (from the events only)
and a tag `YOUR CLIP (VOICE) 2/5` / `TOP PLAY 3/5`; the game title is the caption's
second line (it carries the CC BY attribution on the real game). Rendered by the worker's
`reel` stage (`replay_render.reel`); in cloud mode by the hfbox runner (job kind
`reel:<rid>`, `params.stage = "reel"`).

- `POST /games/{id}/exports/reel` `{"aspect": "16:9" | "9:16"}` (default 16:9; key or
  phone token) -> `{id, aspect, created_at, status, url, job_id?, error?}`. `id` =
  `r_` + 12 hex of a hash of the aspect and the files the plan reads (game, events, plays,
  hype, clips, triggers): asking again before anything changed is the same reel (200 with
  its status), a new clip or an edit is a new reel (202, `status: "queued"`). 1280x720 or
  720x1280, H.264 + AAC.
- `GET /games/{id}/exports/reel` -> `{game_id, reels: [...]}`, newest first.
- `GET /games/{id}/exports/reel/{rid}` -> `status` `queued | running | done | failed |
missing | none`; when `done`: `url` (under `/media`, the download), `duration_s` and
  `segments: [{t_start, t_end, kind: "clip" | "top", tag, caption, player_id, ref,
reel_t}]` (`reel_t` = where it starts in the reel). 404 for an unknown or malformed id.
- Phone: `POST /games/{id}/phone-link {"job": "reel"}` -> `{web_base}/p/{id}?job=reel#k=..`;
  the phone page POSTs the reel and polls `GET .../exports/reel/{rid}` until `done`, then
  offers `url`.

### The user's clips as moments (2026-10-22)

`GET /games/{id}/moments` also lists every trigger (`triggers.json`: voice, gesture, tap)
as a moment of the existing kind `bookmark`, id = the trigger id (`tr_...`), label
`Your clip (voice)` / `Your clip (X sign)` / `Your clip` (`, <name>` when the voice named
a tagged player), `t_start`/`t_end` = its clip (the play it resolved to), `t` = that play's
end; a trigger with no play covers the 8 s before it. Voice and gesture keep `source:
"heuristic"` and the detector's `confidence` (they are detected); a tap is `source:
"user"`, `confirmed: true`. Additive keys: `trigger: "voice" | "gesture" | "tap"` and
`clip_id` (null when unresolved). Thumbs come from the `moments` stage like any moment.
No TV contract change is required; a client that wants a distinct icon reads `trigger`.

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
