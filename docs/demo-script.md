# Demo script

Adapted from the plan §13 outline (< 3 min, lead with the best material) to what actually
exists right now: a **browser-based TV client** (`/tv`, keyboard D-pad emulation, D-1), a
local FastAPI backend, and `courtcam` running **basketball only** — no other sport profile
is implemented yet (`courtcam/courtcam/sports/` has `basketball.yaml` only), no Vega/Fire TV
build, no AWS pipeline, no Bedrock/Nova. Beats below are marked **[NOW]** (works today, safe
to record) or **[LATER]** (plan §13 content that needs work still in flight before it can be
filmed). Use this to rehearse today and as the skeleton for the real submission cut.

## Footage: what to actually film

**Every real footage clip currently in this repo (`samples/real/*.mp4`) is local-testing
only per D-7** — unverified-license YouTube content, gitignored, never committed, and never
allowed in the public repo or the submission video (plan §12 rule 1; plan §1 footage scope
requires self-recorded, consented adults). Use those clips to rehearse the walkthrough and
check timing on your own machine. **The actual demo recording needs a self-filmed clip**:
one phone, tripod, fixed elevated position, whole court in frame, consenting adult players —
`basketball_parkwide_240s.mp4`'s framing (fixed sideline mount, both hoops, full baseline to
baseline in one shot — see `samples/real/MANIFEST.md` #1) is the shape to imitate when you
film your own.

## Setup before recording

1. Backend: `REPLAY_PIPELINE=courtcam uv run --package replay-api uvicorn replay_api.main:app --port 8000`
   (real pipeline — needed so processing/calibration/events are genuine, not fixture data).
2. Web: `cd apps/web && VITE_REPLAY_API_BASE=http://localhost:8000 pnpm dev`, open `/tv` at
   1920×1080 (the UI is designed and tested at that viewport — `playwright.config.ts`).
3. Pre-process one real (self-filmed) game through `/upload` before recording, so the watch
   beats don't sit on a processing spinner; keep a second, unprocessed upload ready for the
   "loop" beat.

## Beats

### 1. 0:00–0:25 — Wide shot → pick a player → follow-cam **[NOW]**
Plan §13 beat 1, unchanged — this is the core novelty and it works today.
- On `/tv`, open the pre-processed game (library card → `Enter`).
- Let the wide shot play a few seconds, chaotic full-court action.
- `Space` to pause.
- `ArrowLeft` / `ArrowRight` / `ArrowUp` / `ArrowDown` to hop the focus box between on-court
  players (S-18: spatial focus, nearest-in-direction).
- `Enter` on one player → follow-cam (client-mode CSS transform crop, D-6).
- `Space` to resume play. No narration needed — let the transform speak.

### 2. 0:25–0:55 — Highlights: query chip → shots reel → shot chart **[NOW]**
Plan §13 beat 2, trimmed (no phone-query voice path yet — that's H4/Alexa+ MCP, not built).
- `Escape` back to the watch screen, then navigate to Highlights (`nav-highlights`, or the
  route `/tv/:gameId/highlights`).
- Select a query chip (rule-based query parser, `REPLAY_QUERY=rules`) for the followed
  player's made shots.
- Step through the resulting clip reel; show the court inset and shot chart rendering real
  `stats.shots` / `stats.heatmap` data from `GET /games/{id}/stats`.

### 3. 0:55–1:10 — Other sports **[LATER — do not film yet]**
Plan §13 beat 3 (pickleball/badminton condensed replay, rally browser, volleyball follow-cam)
has nothing to show: only the basketball sport profile exists. Cut this beat entirely from
the current rehearsal cut. Revisit once a second sport clears Tier 1 (plan §10 schedule:
Oct 9–14) — `team_rule: net_side` currently raises `NotImplementedError`, so pickleball/
badminton/volleyball aren't functional yet either.

### 4. 1:10–1:30 — Post-game review: box score + review-queue correction **[NOW]**
Plan §13 beat 4, unchanged.
- Navigate to Review (`nav-review`, route `/tv/:gameId/review`).
- Show the box-score-lite table and an auto-detected, unconfirmed shot event
  (`data-confidence`, labelled "auto-detected").
- `ArrowUp`/`ArrowDown` to the review queue's first item; use the on-screen Made/Missed/
  Not-a-shot actions (`review-action-{made|missed|not-a-shot}`) via `Enter` — a "not a shot"
  answer sets the additive `dismissed` flag rather than relabelling the event (D-11).
- Cut back to the box score to show it recompute after the correction (R3).

### 5. 1:30–1:55 — The loop: upload → calibrate → process → library **[NOW]**
Plan §13 beat 5, unchanged — this is the second unprocessed game queued in setup.
- `/upload`: type a title, pick "Basketball," pick the local video file
  (`create-game`, `file-input`, `go-calibrate`).
- Calibration screen: click the four court corners plus the rim on the extracted
  `calib.jpg` frame (`landmark-{name}` hooks); show the reprojection-error gate before
  "Start Processing" is enabled (S-06).
- `POST /games/{id}/process` kicks off the job; show the stage progress display advancing
  through ingest → calibrate → detect → track → court/identity/crops/events (S-08).
- Cut to `/tv` library — the game now appears as a card once processing completes.

### 6. 1:55–2:15 — Architecture, as it actually stands today **[NOW, adapted content]**
Plan §13 beat 6 assumes a Vega app, an AWS pipeline, and Nova — none of that exists yet.
Show the real current architecture instead: phone → `apps/web` uploader → local FastAPI
(`services/api`) → `courtcam` pipeline (calibrate → detect (YOLO11n) → track (ByteTrack) →
identity → crops → events) writing to local disk → the same `apps/web` app's browser-based
`/tv` client rendering the result with keyboard D-pad emulation standing in for a real
remote. One sentence on prior art: player tracking and court projection are established
hackathon mechanisms (Project Horizon, Baddy Buddy!) — Replay's contribution is the
TV-native pick-a-player experience and the complete phone-to-living-room loop, all built in
the hackathon window (plan §1).

### 7. 2:15–2:30 — What's next **[NOW]**
Plan §13 beat 7, unchanged in spirit: Fire TV / Vega port (`PlayerSurface` + `platform/`
already seam it off, D-1), AWS backend (S3/CloudFront/Lambda/API Gateway/DynamoDB/Step
Functions/SageMaker), Bedrock Nova for shot labeling and natural-language query, and the
remaining sport profiles (pickleball, badminton, volleyball).

## Total runtime (current cut)

~2:30 with beat 3 cut, vs. the plan's < 3:00 budget with all seven beats — there's room to
add pickleball/badminton back in once a second sport profile works, without going over.
