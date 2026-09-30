# Replay Phase 1 — Product Test Specification

Scope: Phase 1 only (REPLAY_PLAN.md §6; decisions D-1..D-8). Single Vite app: phone
uploader at `/upload`, browser TV client at `/tv` with keyboard D-pad emulation, local
FastAPI backend, progressive MP4 + HTTP range media (not HLS). Contracts in
REPLAY_PLAN.md §4.5 (data) / §4.6 (API) are source of truth; this spec tests against them.
IDs are stable references for future Playwright/pytest test names — do not renumber, only
append.

## 0. Conventions

- **Routes** (assumed; not yet implemented — update this doc if the router differs):
  `/upload` (create game), `/upload/:gameId/calibrate`, `/upload/:gameId/status`,
  `/tv` (library), `/tv/:gameId` (watch: wide + select + follow), `/tv/:gameId/highlights`,
  `/tv/:gameId/review`, `/tv/pair` (phone companion pairing, H4 — `?game=` carries the game
  whose highlights a phone query should open), `/companion` and `/companion/:code` (the
  phone side of H4: touch, not D-pad).
- **Playwright projects**: `chromium` runs `apps/web/e2e/` against the in-browser mock
  (`VITE_MOCK_API=1`); `live` runs `apps/web/e2e-live/` against a real
  `REPLAY_PIPELINE=fake` uvicorn on :8000 with a wiped temp data dir, and covers S-01 end
  to end plus the empty library, the API-unreachable banner, range seeking and S-31 (the
  phone companion, which needs the real WebSocket). Both run from one
  `pnpm exec playwright test`. The `live` project's tests all live in one file and share
  the game S-01 uploads, because `fullyParallel: false` only serialises *within* a file.
  Its uvicorn runs with `REPLAY_FAKE_PIPELINE_DELAY_S=1` so S-08's `running` stage is
  observable (fake mode is otherwise instant). `workers` is pinned to 4 (2 in CI): the
  Playwright default is half the logical cores, which on a 16-core box puts 8 browsers on
  one uvicorn and three vite servers and turns timing assertions into coin flips. Any
  `expect.poll` timeout must be <= the enclosing test's timeout, or the test dies before
  its own assertion can fail — S-04 raises its test timeout to 90 s for the 40 s stage poll.
  The uvicorn launcher is `uv run --package replay-api uvicorn` unless `REPLAY_API_CMD`
  overrides it (the shared GPU box has no uv: `REPLAY_API_CMD="python -m uvicorn"` with
  `PYTHONPATH=<repo>/courtcam:<repo>/services/api`).
- **Selectors**: tests key off `data-testid`. Referenced here as `[data-testid=x]`.
  Implementation must add these hooks; exact naming may be adjusted but must stay documented
  in this file when changed (plan §12 rule 3 applies to test hooks by extension).
- **Additional test hooks added by `apps/web`** (not named in the scenarios below, but
  relied on by `apps/web/e2e/`): `video`, `player-surface`, `player-transform` (the
  transformed `<video>` wrapper whose computed `transform` S-20/S-21 assert on), `seek-bar`,
  `clip-counter`, `review-empty`, `review-action-{made|missed|not-a-shot}`, `shot-marker`,
  `court-dot-{pid}`, `nav-{library|highlights|review}`, `tag-dialog`, `tag-value`,
  `tag-key-{label}`, `pair-code`, `game-title-input`, `create-game`, `file-input`,
  `go-calibrate`, `calib-image`, `calib-prompt` (with `data-target` = the landmark the next
  frame tap or "Not visible" applies to), `calib-undo`, `calib-skip` ("Not visible"),
  `calib-more`, `landmark-{name}`,
  `variant-{name}` (one radio per `profile.variants`; **absent entirely when the profile
  has a single variant** — see §10 bug 1), `calib-worst` (§10 bug 3), `roster-row`, `roster-name-{pid}`, `roster-save-{pid}`,
  `roster-merge-{pid}`, `ask-dialog`, `ask-value`, `ask-key-{label}` (H3 free text — the
  same `TextEntryDialog` the tag dialog uses, with an `ask-` prefix), `heatmap`,
  `heatmap-cell`, `heatmap-player-{pid}` (R2), `rendering-badge` (rendition follow mode),
  `companion-code-input`, `companion-connect`, `companion-query`, `companion-send`,
  `companion-mic`, `companion-status`, `companion-sent`, `companion-error` (H4),
  `follow-frame` with `data-pid` and `data-visible` (W4 follow frame, S-22b).
  Existing hooks also carry data attributes used as assertion
  targets: `data-focused`, `data-player-id`, `data-game-id`, `data-event-id`, `data-type`,
  `data-t-key`, `data-t-start`, `data-confidence`, `data-state`, `data-made`, `data-ok`,
  `data-value` (heatmap cells), `data-chip`, `data-listening`.
- **Extra keys beyond the D-1 remote map** (implemented on `/tv`, documented here rather
  than silently added): `s` toggles the spotlight overlay (W6), `t` opens the tag dialog for
  the focused player (W7), `p` opens the phone-pairing screen for the current game
  (`/tv/pair?game=<id>`, H4) from Watch or Highlights. All three hang off on-screen
  affordances on a real remote.
- **Keyboard map** (D-1, the entire input surface for Phase 1 — no mouse/touch on `/tv`):

  | Key | Action |
  |---|---|
  | `ArrowUp/Down/Left/Right` | D-pad move |
  | `Enter` | Select |
  | `Escape` / `Backspace` | Back |
  | `Space` | Play/Pause |
  | `,` / `.` | Seek −10 s / +10 s |
  | `[` / `]` | Previous / next event |
  | `b` | Bookmark |
  | `s` / `t` / `p` | Spotlight · Tag player · Pair phone (extra keys, above) |

- **Tolerances used throughout**: video time tolerance = ±1 frame (1/30 s ≈ 33 ms) when
  paused, ±100 ms when playing (NF-06); homography reprojection < 5 px (plan §4.4 stage 2);
  crop rect components ∈ [0,1].
- **Event/schema names**: `replay.game.v1`, `replay.tracks.v1`, `replay.crops.v1`,
  `replay.events.v1` (plan §4.5).

---

## 1. Product actions inventory

### 1.1 Phone uploader (`/upload`)
| Action | Detail |
|---|---|
| Create game | Enter title, pick sport (I5) → `POST /games` |
| Upload file | File picker/drag-drop, progress bar, cancel | 
| Calibrate | Click 4 court corners + rim on a extracted frame; half/full selector; see live reprojection error; blocked from proceeding if invalid |
| Start processing | Button enabled only after valid calibration → `POST /games/{id}/process` |
| Watch stage progress | Poll/subscribe to stage list: ingest → detect → track → render → label, each `pending\|running\|done\|partial\|error` |
| Rename/tag players | After `track`/`label` stages produce a roster, rename/merge players from the phone |

### 1.2 TV (`/tv`)
| Action | Detail |
|---|---|
| Library browse | D-pad across game cards (thumbnail, date, duration, status) |
| Open game | Enter on a card → watch screen, loads wide MP4 at t=0 (or resume point) |
| Wide playback transport | Play/pause, ±10 s, scrub via seek bar, seek-bar event markers |
| Select mode | Pause → boxes drawn over on-court players at current timestamp; D-pad moves focus to nearest box in pressed direction; Enter follows |
| Follow mode | Video visually follows selected player (CSS transform per D-6); Back returns to wide at same timestamp |
| Tag player from TV | Preset name list or on-screen keyboard, reachable via D-pad from a focused player box |
| Highlights screen | Per-player reel, query chips (≥3 deterministic), free-text query (P1) |
| Review queue | Confirm/correct low-confidence events via remote (Made / Missed / Not a shot) |
| Bookmarks | `b` during playback creates a `bookmark` event at current time |
| Court inset (W5) | Top-down minimap, selected player highlighted |
| Spotlight overlay (W6) | Dim all but selected player; fallback when CSS transform unsupported |
| Shot chart / heatmap / box score (R1-R3) | Post-game review screens driven by `/games/{id}/stats` |

---

## 2. End-to-end scenarios

Format: Given / When / Then, then **Pass** = concrete assertions.

### S-01 — Happy path: upload → calibrate → process → library → watch → select → follow → back → highlights
Given the API is running and empty, a phone browser open at `/upload`, a synthetic basketball
clip `synth-bball-half-5v5.mp4` available for upload. When the user (1) creates a game
titled "Test Game" sport=basketball, (2) uploads the clip and waits for 100% progress,
(3) clicks corner_nl, corner_nr, corner_fl, corner_fr, rim on the calibration frame with
variant=half, (4) starts processing and waits for all five stages to reach `done`
(or `partial` for render, per plan game.json example), (5) opens `/tv`, (6) opens the game,
(7) lets it play 3 s then pauses, (8) enters select mode, moves focus with arrow keys to a
player box, presses Enter, (9) confirms follow-cam is active, (10) presses Escape, (11)
navigates to Highlights and plays the reel for a tagged player.
**Pass**: `POST /games` returns 201 with `id`; upload progress reaches 100% and
`[data-testid=upload-done]` visible; `[data-testid=calib-error]` shows a numeric value
`< 5`; `[data-testid=calib-image]` is the frame extracted at upload (D-14);
`[data-testid=start-processing]` becomes enabled then clicked triggers
`POST /games/{id}/process` (202); `[data-testid=stage-ingest]` … `[data-testid=stage-label]`
each transition to `done`/`partial` within the polling loop; game card for this id appears
on `/tv` with status text "ready"; clicking it navigates to `/tv/{id}` and `<video>` element
is present with `readyState >= 2`; after pause, `[data-testid^=select-box-]` elements are
visible (count ≥ 1); after Enter, `[data-testid=followcam-active]` is visible and the
`<video>` wrapper's computed `transform` matrix is not `none`/identity; after Escape,
`[data-testid=followcam-active]` is gone and `video.currentTime` equals the pre-follow
timestamp ±1 frame; on Highlights, `[data-testid=reel-clip]` count ≥ 1 and clicking one
sets `video.currentTime` to that clip's `t_start` ±1 frame and starts playback (`paused`
becomes `false`).

### S-02 — Create game (title, sport)
Given `/upload` loaded. When user types "Tuesday Run" and selects sport=basketball, submits.
Then `POST /games` body `{title:"Tuesday Run", sport:"basketball"}`; response `{id, upload_url}`.
**Pass**: response status 201; `id` matches `^g_[a-z0-9]+$`-style non-empty string; page
navigates to `/upload/{id}` (or shows upload widget bound to that id).

### S-03 — Upload file with progress
Given a created game with `upload_url`. When user selects a valid MP4 and upload starts.
**Pass**: `[data-testid=upload-progress]` value increases monotonically from 0 to 100;
network request to `upload_url` observed (PUT/POST per provider); on completion
`[data-testid=upload-done]` visible and "Calibrate" control becomes enabled/reachable.

### S-04 — Calibration: 4 corners + rim, half court
Given calibration frame loaded for a half-court basketball game. When user clicks
corner_nl, corner_nr, corner_fl, corner_fr, rim in order and selects variant=half.
**Pass**: `[data-testid=calib-error]` shows a number `< 5`; `POST /games/{id}/calibration`
carries `sport:"basketball"`, the half-court variant and `landmarks_px` with exactly the
5 keys `corner_nl,corner_nr,corner_fl,corner_fr,rim`. The client-side payload names the
variant `court_variant` (what the mock records); D-13 maps it to `variant` on the wire; `[data-testid=start-processing]` not
disabled.

### S-05 — Calibration: full-court variant
Same as S-04 with variant=full. **Pass**: `landmarks_px` still the 5 basketball landmarks
(rim is one basket); the full-court variant in the request body; reprojection error still shown
and gate behaves identically to S-04.

### S-06 — Calibration validation gate before Start Processing
Given all 5 landmarks clicked with error 3.2 px (< 5). When user clicks Start Processing.
**Pass**: `POST /games/{id}/process` fires only after `POST /games/{id}/calibration`
succeeded (2xx); response 202; UI navigates to `/upload/{id}/status`.

### S-07 — Start processing (enqueue)
Given valid calibration saved. When user clicks Start Processing.
**Pass**: `POST /games/{id}/process` → 202; `game.json.stages.ingest` transitions from
absent/`pending` to `running` within 5 s of enqueue (polled via `GET /games/{id}`).

### S-08 — Stage progress display, the pipeline's own stages
Given processing enqueued for the synthetic sample. When user watches the status page.
**Pass**: one `[data-testid=stage-{name}]` row per key of the API's `stages`, in that
order — the page hardcodes no list. `POST /process` sets `stages` to the running
pipeline's list (`pipeline_adapter.stage_names`): courtcam's nine
(`ingest calibrate detect track court identity tracks crops events`, from
`courtcam.pipeline.STAGES`), fake mode's five (`ingest detect track render label`). Each
row's `data-state` cycles `pending → running → done` (render may end `partial`) left to
right; no stage shows `done` before its predecessor does; the running row carries
`data-progress` (the job's fraction) and shows it as a percentage; final state
`[data-testid=game-status]` text = "ready". (Before: five hardcoded rows, all `pending`
for a whole real run, because courtcam's stage names are different.)
Tests: `e2e/S-04-calibration.spec.ts` → *S-08 the status page lists the API's own
stages…* (mock, courtcam's nine); `services/api/tests/test_progress.py::
test_process_lists_the_pipelines_own_stages_in_order`, `::test_stage_names_is_courtcams_list_when_courtcam_is_installed`.
**Implemented (services/api + apps/web)**: while a job is queued or running, `GET /games/{id}`
and `GET /games` merge it from `data/jobs.json` (D-9, D-17) — `status: "processing"`, the
job's stage `running`, earlier ones `done`, later ones `pending`, plus an additive
`progress: {stage: fraction}`. `game.json` is never written mid-run. The live S-01 test
asserts one snapshot matches `processing (done,)*running(,pending)*`. `POST /process` is
idempotent while a job is active (`services/api/tests/test_progress.py`).

### S-09 — Sport picker at upload
Given `/upload` loaded and `GET /sports` returns basketball (enabled). When user opens the
sport dropdown. **Pass**: `[data-testid=sport-option-basketball]` visible and selectable;
only sports from `GET /sports` response are listed; selecting one stores it in the create
payload (verified via S-02's request body).

### S-10 — Team split by jersey color shown in UI
Given a processed game with `teams: [{id:0,color_hex}, {id:1,color_hex}]` and players
assigned team ids. When user views the roster or select-mode overlay.
**Pass**: each player box / roster row renders with a border or badge color equal to its
team's `color_hex` (computed style `border-color` or `background-color` matches, case
insensitive hex compare).

### S-11 — Library browse via D-pad
Given `/tv` with 3 ready games. When user presses `ArrowRight` twice then `ArrowLeft` once.
**Pass**: `[data-testid=game-card].focused` count is always exactly 1; the focused card id
sequence matches card 1 → 2 → 3 → 2 in DOM order; no card outside the visible viewport is
focusable (tab order / focus trap holds).

### S-12 — Open game from library
Given a game card focused on `/tv`. When user presses `Enter`.
**Pass**: `page.url()` matches `/tv/{gameId}`; `<video src>` resolves to the game's
`renditions.wide` absolute URL; `video.currentTime === 0` (or last saved position, see E-21).

### S-13 — Wide playback: play/pause
Given `/tv/{gameId}` loaded, video paused at t=0. When user presses `Space`.
**Pass**: `video.paused === false`; after another `Space`, `video.paused === true` and
`video.currentTime` unchanged for ≥1 s after pause (no drift). A `play()` that the
element aborts while it settles on its source (a reload, or not playable yet) must not
lose the keypress: `PlayerSurface` holds the request until `playing`, re-issues it on
`canplay` (or on a 100 ms timer when the element is still ready, max 5 retries), and a
second `Space` while it is pending cancels it. `e2e/S-13-play-pause.spec.ts`.

### S-14 — Wide playback: ±10 s seek
Given video playing at t=50.0. When user presses `,`. **Pass**: `video.currentTime` within
±1 frame of 40.0. When user then presses `.` twice. **Pass**: `video.currentTime` within
±1 frame of 60.0. Seeking past 0 clamps to 0; past duration clamps to duration (no throw).

### S-15 — Wide playback: scrub via seek bar
Given video at t=10. When user focuses the seek bar (D-pad) and presses `ArrowRight` /
activates a scrub-to-point interaction. **Pass**: `video.currentTime` matches the seek bar's
target position within ±1 frame; `[data-testid=seek-bar-thumb]` position (CSS `left`/`transform`)
updates proportionally to `currentTime/duration`.

### S-16 — Seek-bar event markers + prev/next event jump
Given `events.json` has events at t=30, t=95, t=210 and video at t=0. When user presses `]`
three times then `[` once. **Pass**: `[data-testid=event-marker]` count === 3 and each
marker's horizontal position ≈ `t_key/duration` of the seek bar width (±1%); after the three
`]` presses `video.currentTime` within ±1 frame of 210; after `[`, within ±1 frame of 95.

### S-17 — Select mode: pause shows boxes over on-court players
Given video playing over a stretch with ≥2 tracked on-court players. When user presses `Space`
to pause. **Pass**: within one animation frame, `[data-testid^=select-box-]` count equals the
number of players present in the current tracks chunk at that `t` (interpolated); each box's
CSS `left/top/width/height` (or transform) matches the player's `bb` (normalized bbox)
scaled to the video element's rendered rect within 2 px.

### S-18 — Select mode: D-pad spatial focus movement
Given select mode active with 3 boxes at distinct screen positions (e.g. left, center-right,
far-right). When user presses `ArrowRight` from the left box. **Pass**: focus moves to the
nearest box whose center is to the right (smallest angular deviation from the pressed
direction, per `focus/spatial.ts` algorithm intent) — asserted via
`[data-testid=select-box-<id>].focused` toggling to the expected player id; pressing
`ArrowRight` again from the rightmost box leaves focus unchanged (see E-11).

### S-19 — Select mode: Enter triggers follow
Given a player box focused in select mode. When user presses `Enter`.
**Pass**: `page` shows `[data-testid=followcam-active]`; `[data-testid^=select-box-]`
elements are removed/hidden; video resumes playback automatically (`video.paused === false`)
unless product decision says otherwise — assert whichever the implementation defines, but the
transition must complete within 300 ms of keypress.
**Implemented (apps/web)**: entering follow does **not** resume playback. Select mode is only
reachable by pausing, so the user presses `Space` to resume when ready; this keeps
`video.currentTime` provably unchanged across the transition (asserted within ±1 frame in
`e2e/S-19-follow-mode.spec.ts`).

### S-20 — Follow mode visual transform (D-6, client mode)
Given follow mode active on player `p3` whose crop rect at current `t` is
`[0.30, 0.22, 0.5, 0.5]`. **Pass**: the video wrapper's computed `transform` is a `matrix(...)`
or `translate()/scale()` pair consistent with scale ≈ `1/0.5 = 2` and translate consistent
with centering the crop rect's origin in the viewport, recomputed every animation frame
(sampled at 3 distinct `t` values, transform changes each time if the player moved).
**Implemented (apps/web)**: `followcam.mode` is `client` by default and `rendition` when
`VITE_FOLLOWCAM_MODE=rendition`. In `rendition` mode, if `game.renditions.players[pid]`
exists the `<video>` src is swapped to it at the same `currentTime` (PlayerSurface restores
time and play state on a src change) and no transform is applied; otherwise the client
transform still runs and `POST /games/{id}/players/{pid}/render` is fired once, showing
`[data-testid=rendering-badge]` while the API reports a job. The choice is the pure
`followSource()` in `src/playback/followSource.ts`, unit-tested by
`e2e/S-20-rendition-source.spec.ts` (no page — flipping the flag would cost a fourth Vite
server for one boolean).

### S-21 — Follow mode: Back returns to wide at same timestamp
Given follow mode active, `video.currentTime === 120.4`. When user presses `Escape`.
**Pass**: `[data-testid=followcam-active]` gone; video wrapper `transform` returns to `none`/
identity; `video.currentTime` within ±1 frame of 120.4; select-mode boxes are NOT
automatically re-shown (product returns to wide playback, not select mode) unless spec is
amended.

### S-22 — Court inset minimap (W5)
Given a game with `court.variant=half` and ≥1 tracked player. When wide playback is active.
**Pass**: `[data-testid=court-inset]` visible; it renders one dot per on-court player at
positions proportional to each player's `ct` (court meters) mapped into the inset's SVG/canvas
viewBox; the selected player's dot has a distinct class/color when in follow mode.

### S-22b — Follow frame on the selected player (W4)
Appended, not a renumber: S-22 above is the court inset. This covers the amber frame the
followed player carries.
Given a player selected with `Enter`. **Pass**: `[data-testid=follow-frame]` with
`data-pid=<pid>` is visible in follow mode and its bounding-box centre lies inside
`[data-testid=player-surface]` — in follow mode the `<video>` carries the crop transform, so
the track box must be mapped through the same crop rect (`(bb.x - crop.x) / crop.w`, …) to
land on the player; it moves while the video plays; `Escape` back to wide keeps it on the
same player (the selection survives the way out — only another `Enter` or leaving the game
clears `?pid=`) and its centre is within 8 px of where `[data-testid=select-box-<pid>]` sat
at that timestamp; at a time where the player has no track box it fades out over ~300 ms
(`data-visible="false"`, then `visibility: hidden`) and comes back when the box returns.
**Implemented (apps/web)**: `src/components/FollowFrame.tsx`, positioned from a rAF off
`playback/clock.ts` rather than React state so it tracks at the video's frame rate.
`e2e/S-22-follow-frame.spec.ts`. The mock fixture scripts a 1 s occlusion of `p1` over
[12, 13) s in its tracks chunks (MOTION, the crop path and the heatmap stay continuous)
so the fade-out is testable. The W6 spotlight cutout is mapped through the same crop rect.

### S-23 — Spotlight overlay fallback (W6)
Given `followcam.mode` resolves to a state where CSS transform is unavailable (feature-flag
override for test). When user selects a player. **Pass**: instead of a transform, all pixels
outside the selected player's bbox are dimmed (a CSS filter/overlay `<div>` with reduced
opacity covers the frame except a cutout matching `bb`); `[data-testid=spotlight-overlay]`
visible.

### S-24 — Tag player from TV: preset name list
Given select mode with a focused, untagged player box. When user navigates to "Tag player" and
opens the preset name list (roster minus already-tagged names) and selects "Marcus".
**Pass**: `PATCH /games/{id}/players/{pid}` body `{name:"Marcus"}`; `[data-testid=player-label-{pid}]`
updates to "Marcus" without a page reload; subsequent select-mode passes show the persisted name.

### S-25 — Tag player from TV: on-screen keyboard
Given the tag-player screen, preset list has no matching name. When user opens the on-screen
keyboard and types "Zoe" via D-pad + Enter per key, then confirms.
**Pass**: `PATCH /games/{id}/players/{pid}` body `{name:"Zoe"}`; entire flow completable with
only Arrow/Enter/Backspace keys (no text input focus requiring a physical keyboard); a
Backspace on the keyboard screen deletes the last typed character, not "Back" navigation
(document this precedence explicitly since it overloads the global Back key).

### S-26 — Rename/tag player from phone
Given `/upload/{id}` (or a roster-management view reachable from it) shows the processed
game's players. When user renames player `p3` to "Marcus" from the phone.
**Pass**: `PATCH /games/{id}/players/p3` `{name:"Marcus"}` → 200; TV app reflects the new
name on next `GET /games/{id}` (poll or reload), no separate sync channel required in Phase 1.

### S-27 — Highlights: per-player reel (H1)
Given player "Marcus" tagged with ≥2 confirmed made-shot events. When user opens
`/tv/{id}/highlights` and selects Marcus's reel. **Pass**: `[data-testid=reel-clip]` count
equals the number of `shot` events with `player_id="p3"` and `made:true`; playing the reel
advances `video.currentTime` to each clip's `t_start`, plays to `t_end`, then auto-advances to
the next clip (assert on 2 consecutive clip boundaries within ±1 frame).

### S-28 — Highlights: game top plays (H2)
Given events.json has 4 `shot` events with `made:true` at t=10,80,200,300. When user opens the
"Top plays" view. **Pass**: `[data-testid=reel-clip]` order matches ascending `t_start`
(10,80,200,300); count === 4 regardless of `player_id`.

### S-29 — Highlights: query chips, ≥3 deterministic (H3)
Given a processed basketball game with a tagged player and both made/missed shots across two
halves. When user views `/tv/{id}/highlights`. **Pass**: `[data-testid=query-chip]` count ≥ 3;
clicking "All makes" chip → `POST /games/{id}/query {text:"all makes"}` (or equivalent
structured payload) returns clips where every underlying event has `made:true`; clicking the
same chip twice produces byte-identical clip lists (determinism — rule parser only, no LLM).

### S-30 — Highlights: free-text query (H3, P1)
Given the query engine's rule parser cannot match "cool plays from Marcus". When user submits
that free text and an LLM layer (Ollama, per plan §4.7) is configured. **Pass**: request still
returns `{interpretation, clips}` (LLM emits a filter, never raw timestamps, per §4.7);
`[data-testid=query-interpretation]` shows a human-readable restatement; if no LLM is
configured, response is a graceful "no match" (see E-20), never a 500.
**Implemented (apps/web)**: no LLM in Phase 1. The Highlights chip row ends with an "Ask…"
chip (`[data-chip="Ask…"]`) that opens `[data-testid=ask-dialog]` — the same on-screen
keyboard as S-25, extracted as `TextEntryDialog` — and Enter/SAVE submits the typed text to
`POST /query`. Unmatched text returns `{interpretation: "No match", clips: []}` and the
screen shows `[data-testid=no-clips]` (`e2e/S-30-free-text-query.spec.ts`).

### S-31 — Phone companion query (H4, P1)
Given a TV session paired via a 4-digit code (`POST /sessions`, WS `/sessions/{sid}`) and a
phone connected to `/tv/pair`. When user types a query on the phone and submits.
**Pass**: the TV's highlights view updates to the query's results within 2 s without any TV
remote input, driven by the session WebSocket push.
**Implemented (apps/web + services/api)**: the phone page is `/companion` (code entry) /
`/companion/:code`; it connects to `WS /sessions/{code}` directly — the route accepts the
pairing code as well as the session id (D-16) — and sends `{type:"query", text}` from a text
box or the Web Speech API mic button (`[data-testid=companion-mic]`, hidden where
`webkitSpeechRecognition` is absent). On the TV, `p` on Watch/Highlights opens
`/tv/pair?game=<id>`; the Pair screen and Highlights both listen on the session (id kept in
`sessionStorage`), and a push navigates to `/tv/:id/highlights?q=<text>` and runs the query.
Covered live in `e2e-live/S-01-live.spec.ts` with two pages.

### S-32 — Bookmarks (H5)
Given video playing at t=75.0 on `/tv/{id}`. When user presses `b`.
**Pass**: `POST /games/{id}/events` body `{type:"bookmark", t_key:75.0,...}` (t within ±1
frame of press time, accounting for one frame of input latency); `[data-testid=event-marker][data-type=bookmark]`
appears on the seek bar at the corresponding position; the new bookmark is jumpable via `]`/`[`.

### S-33 — Shot chart (R1, P1)
Given `GET /games/{id}/stats` returns shot points with court coordinates. When user opens the
review/shot-chart screen. **Pass**: `[data-testid=shot-chart]` renders one marker per shot
event, positioned via the event's `court` field mapped into the court-diagram SVG viewBox
using the same court template as calibration; made vs. missed shots are visually distinguished
(e.g. filled vs. outline marker).

### S-34 — Position heatmap (R2, P2/P1)
Given stats include a per-player position grid. When user selects a player on the review
screen. **Pass**: `[data-testid=heatmap]` renders a grid whose cell intensities are
monotonically consistent with the stats payload's grid values (higher value → visually denser
cell); switching players re-renders without page reload.
**Implemented (apps/web)**: on the Review screen, below the shot chart. One
`[data-testid=heatmap-cell]` per non-zero cell, `fill-opacity = value / max`, drawn in court
metres over the same court outline as the shot chart (`x_range`/`y_range` from D-12).
`ArrowDown` moves focus from the review answers to the player row
(`[data-testid=heatmap-player-{pid}]`); Left/Right switches the rendered player
(`e2e/S-34-heatmap.spec.ts`).

### S-35 — Box score lite (R3, P1)
Given stats include shots attempted/made per player. When user opens the box score view.
**Pass**: `[data-testid=box-score-row]` count equals roster size; each row shows
attempted/made numbers matching `GET /games/{id}/stats`; every row/table is labeled
"auto-detected" per plan §2.3 R3 (`[data-testid=auto-detected-label]` visible).

### S-36 — Review queue: confirm event (R5)
Given events.json has one `shot` event with `confidence:0.55` (below a confirm threshold) and
`confirmed:false`. When user opens `/tv/{id}/review` and presses the "Made" remote action on
that event. **Pass**: `PATCH /games/{id}/events/{eid}` body includes `{made:true, confirmed:true}` and the
response carries `source:"user"` (the API owns provenance, §4.5);
the event disappears from the pending review list; game stats (R3) recompute to include it.
A third answer, "Not a shot", sends `{dismissed:true, confirmed:true}` (D-11) and the event
drops out of `/query` and `/stats` while staying in `events.json`.

### S-37 — Review queue: correct event (R5)
Given the same low-confidence event, this time the heuristic said `made:true` but the user
selects "Missed". **Pass**: `PATCH` body `{made:false, confirmed:true}`; the
per-player highlight reel (S-27) no longer includes this clip on next load.

---

## 3. Edge and failure cases

| ID | Case | Expected behavior | Pass criteria |
|---|---|---|---|
| E-01 | No games in library | Empty-state message, no crash | `[data-testid=library-empty]` visible; zero `[data-testid=game-card]` |
| E-02 | Game still processing | Card shows status, not openable (or opens to a limited/read-only status view) | Card text shows stage e.g. "detecting…"; `Enter` on it does not navigate to `/tv/{id}` watch surface (navigates to a status view or is a no-op) |
| E-03 | Upload of non-video file | Rejected client- and/or server-side | Client: file input rejects by `accept` MIME filter or shows `[data-testid=upload-error]`; if it reaches the API, `POST` returns 400 with an error body, not 500 |
| E-04 | Upload interrupted (network drop mid-transfer) | Resumable or clearly failed, no silent partial file used downstream | `[data-testid=upload-error]` visible with a retry action; `game.stages` never advances past `ingest` with a partial file |
| E-05 | Calibration with < 4 points | Start Processing stays disabled | `[data-testid=start-processing]` disabled; `[data-testid=calib-error]` shows "need N more points" or similar, not a stale/zero error value |
| E-06 | Calibration collinear points | Homography undefined/degenerate — rejected, not silently accepted | `[data-testid=calib-error]` shows a failure state (e.g. "invalid points") instead of a numeric px value; `POST /games/{id}/calibration` returns 400 if submitted anyway |
| E-07 | Calibration points outside frame | Click coordinates clamped or rejected before reaching the request | Click outside the `<img>`/`<canvas>` bounds does not register a landmark (no out-of-[0,width]×[0,height] pixel in the payload) |
| E-08 | Reprojection error over threshold (≥5 px) | Start Processing blocked; user can re-click points | `[data-testid=calib-error]` shows the numeric value ≥5 in an error style (e.g. red text/class); `[data-testid=start-processing]` disabled |
| E-09 | Zero detected players (e.g. empty court clip) | Game still reaches `ready`; UI communicates "no players found" instead of crashing | `game.players` = `[]`; Library shows the game; select mode on it shows `[data-testid=select-empty]` instead of throwing |
| E-10 | Select mode when no player at current timestamp | No boxes drawn, no crash, D-pad has nothing to move to | Pause at a `t` with zero tracked players → `[data-testid^=select-box-]` count 0; arrow keys are no-ops |
| E-11 | D-pad press with no target in that direction | Focus stays on current box | Press `ArrowRight` from the rightmost box → focused box id unchanged before/after |
| E-12 | Follow mode at video end | Playback stops cleanly, follow overlay doesn't error past last crop frame | At `t = duration`, `video.ended === true`; no console error from crop-path lookup past its last rect (index clamps to last known rect) |
| E-13 | Seeking while in follow mode | Crop path re-syncs to new `t` without visual jump-to-wrong-player | After a `,`/`.` seek in follow mode, the applied transform corresponds to the *same* `player_id`'s crop rect at the new `t` (not the previous frame's stale rect) within one animation frame |
| E-14 | Back on library | No-op or stays on library (nothing above library to go back to) | `Escape`/`Backspace` on `/tv` keeps `page.url()` at `/tv`; no navigation, no error |
| E-15 | Rapid key repeat (e.g. holding `ArrowRight` / OS key-repeat firing `Space` rapidly) | Debounced/queued, no state corruption (e.g. play/pause doesn't desync from actual video state) | After 10 rapid `Space` presses, `video.paused` matches the actual parity of presses (even count → back to original state); no duplicate overlapping network requests fired per keystroke where one suffices (e.g. tagging) |
| E-16 | Very long titles | UI truncates, no layout break | Title > 100 chars: `[data-testid=game-card-title]` has `text-overflow:ellipsis` (or equivalent) applied via computed style, card height unchanged from a normal-title card |
| E-17 | Two players merged by user | `PATCH .../players/{pid} {merge_into:pid2}` collapses tracks/events under one id | After merge, `game.players` no longer lists the merged-away id; `events.json` entries previously citing it now cite `pid2`; highlight reel for `pid2` includes clips from both original tracklets |
| E-18 | Renaming to a duplicate name | Either allowed with a disambiguator or rejected with a clear message — pick one and assert it | If rejected: `PATCH` returns 400 and `[data-testid=rename-error]` visible; if allowed: both players show the same name plus a distinguishing marker (e.g. team color) — whichever the implementation chooses, the test asserts no two roster rows are indistinguishable in the UI |
| E-19 | Event with low confidence in review queue | Shown with a visible confidence indicator, distinct from confirmed events | `[data-testid=review-item][data-confidence]` renders the numeric confidence; items below the confirm threshold and `confirmed:false` are the *only* ones listed on `/tv/{id}/review` |
| E-20 | Query chip with zero results | "No clips" state, not a blank/broken screen | `[data-testid=no-clips]` visible when a chip's filter matches 0 events; reel/player area does not render an empty `<video>` |
| E-21 | Page reload mid-playback | Defines and meets a stated recovery expectation | Minimum bar: reload navigates back to Library (`/tv`), not a blank page — state is NOT required to persist in Phase 1 (no client storage requirement stated in plan); if the implementation does persist `currentTime`/mode via `localStorage` or a query param, test asserts restoration within ±1 s instead. **Implemented (apps/web)**: `/tv/:id` mirrors `?mode=&pid=&t=` into the URL at 1 Hz and restores all three on load (`e2e/S-19-follow-mode.spec.ts`). |
| E-22 | API unreachable | Visible error state, no white screen | Stop the API process; any screen making a request shows `[data-testid=api-error]` with a retry affordance; `document.body.innerText` is non-empty (no blank render) |

---

## 4. Pipeline (`courtcam`) acceptance checks

Run on `samples/synthetic/synth-bball-half-5v5` (CI, deterministic ground truth) **and** on
one real clip from `samples/real/` (local-only, manual/nightly — see §8).

| ID | Check | Synthetic pass criteria | Real-clip pass criteria |
|---|---|---|---|
| PC-01 | `game.json` conforms to `replay.game.v1` | All required top-level keys present (`schema,id,title,status,stages,video,sport,court,renditions,players,teams,tracks,croppaths,events_url`); `schema == "replay.game.v1"`; types match plan §4.5 | Same |
| PC-02 | `tracks/{chunk}.json` conforms to `replay.tracks.v1` | Every chunk has `schema,t0,rate_hz,frames[]`; each frame has `t` and `p[]` with `id,bb,ct,c`; `bb` values ∈ [0,1]; chunk count matches `tracks.chunks` in game.json | Same, plus: no chunk file missing for `[0, chunks)` |
| PC-03 | `crops/{player_id}.json` conforms to `replay.crops.v1` | `schema,player_id,rate_hz,t0,rects[]` present; one file per player in `game.players` | Same |
| PC-04 | `events.json` conforms to `replay.events.v1` | `schema,events[]`; each event has `id,type,t_start,t_key,t_end,confidence,source,confirmed`; `type` ∈ profile's declared set | Same |
| PC-05 | Track count within expected range for player count | Exactly matches the synthetic generator's known ellipse count (ground truth) after on-court filtering | Within ±1 of a manual headcount from the source video (documented in the real-clip's MANIFEST entry) |
| PC-06 | On-court filter removes off-court people | Synthetic decoy ellipses placed outside the court polygon are absent from `game.players` | Any spectators/bench visible in frame are absent from `game.players` (spot-checked manually against timestamps in MANIFEST) |
| PC-07 | Crop rects within [0,1] and smooth | Every `rects[]` component ∈ [0,1] for every player/frame; max per-frame delta (L2 on the 4-tuple) ≤ a documented bound (start at 0.05/frame at 30 Hz; tune and record the actual bound used in `courtcam/croppath.py`) | Same bound applies |
| PC-08 | Homography reprojection error < 5 px | Reprojecting the generator's known landmark pixel coords through computed `H` and back yields error < 5 px per landmark | Reprojecting the calibration-clicked landmarks yields error < 5 px (same check as calibration UI gate, S-06/E-08, run standalone against the pipeline's stored `H`) |
| PC-09 | Determinism | Two full pipeline runs on the same input produce: identical track count, identical event count, and crop-rect max delta between runs ≤ 1e-3 (or documented epsilon if any stochastic stage — e.g. YOLO batching — is in play); golden files under `samples/synthetic/` diff-clean within tolerance (plan §7.4) | Not CI-gated (real clips are local-only, D-7); run manually before demo, log the diff |
| PC-10 | CLI runnable per stage | `courtcam run --input synth-bball-half-5v5.mp4 --calib calib.json --out out/` exits 0 and produces every file referenced by `game.json` (plan §12 rule 4); each of the 10 named stages (§4.4) is independently invocable (`courtcam <stage> ...`) if the CLI exposes sub-stages | Same, on the real clip |
| PC-11 | No sport-name branches in core pipeline | `grep -rn 'sport ==' courtcam/*.py` (excluding `courtcam/sports/*` profile loader) returns no hits outside profile-loading code (plan §12 rule 6) | N/A (static check, not per-clip) |

---

## 5. API contract checks (§4.6)

Auth: `X-Replay-Key` is only enforced when `REPLAY_API_KEY` is set (plan §12 rule 8); AC rows
below marked "if auth enabled" are conditional on that env var being set in the test run.

| ID | Route | Checks |
|---|---|---|
| AC-01 | `POST /games` | 201 with `{id, upload_url}`; 400 if `title` or `sport` missing/empty; 400 if `sport` not in `GET /sports`; 401 if auth enabled and header missing/wrong |
| AC-02 | `GET /sports` | 200; bare array (no envelope, D-13) of profiles each with `id, display_name, tier, landmarks, variants, court, sport_ui`; basketball always present in Phase 1 |
| AC-03 | `POST /games/{id}/calibration` | 200 on valid payload (≥4 landmarks, non-collinear, reprojection computed); 400 on missing landmarks, malformed variant, or degenerate points (E-05/E-06); 404 for unknown `{id}` |
| AC-04 | `POST /games/{id}/process` | 202 (enqueued) once calibration exists; 400 if no calibration saved yet; 404 unknown `{id}`; idempotent — a second call while the job is queued/running returns 202 with the *same* `job_id` and queues nothing (D-17) |
| AC-05 | `GET /games` | 200; bare array (D-13), each item has `id, title, status, stages, duration_s, thumb_url, recorded_at, sport` (plus `progress` only while that game has a job running, D-17); empty array when no games exist (E-01) |
| AC-06 | `GET /games/{id}` | 200 with full `game.json`, media URLs resolved to absolute (not relative paths), plus `thumb_url`, `calib_url` (D-14) and `sport_ui`; while a job runs, `stages`/`status` come from the job record and an additive `progress` object is present (D-17); 404 unknown `{id}` |
| AC-07 | `PATCH /games/{id}/players/{pid}` | 200 on rename or merge; request body validated (`name` non-empty string, or `merge_into` a valid existing `pid`); 404 unknown `{id}`/`{pid}`; 400 on self-merge (`merge_into === pid`) |
| AC-08 | `POST /games/{id}/players/{pid}/render` | 202 (lazy rendition render queued); 404 unknown ids |
| AC-09 | `PATCH /games/{id}/events/{eid}` | 200 on confirm/correct; response reflects `confirmed:true, source:"user"`; accepts `dismissed` (D-11); 404 unknown `{id}`/`{eid}`; 400 on an unsupported field |
| AC-10 | `POST /games/{id}/events` | 201 creating a bookmark from `{t}`; response has `id` and the derived `t_start`/`t_key`/`t_end`; 422 if `t` < 0 |
| AC-11 | `POST /games/{id}/query` | 200 with `{interpretation, clips[]}`; 400 if `text` missing; empty `clips` array (not error) when nothing matches (E-20); repeated identical requests return identical `clips` (determinism, rule-parser path) |
| AC-12 | `GET /games/{id}/stats` | 200 with `{box_score, shots, heatmap, totals}` (D-12), dismissed events excluded; 404 unknown `{id}`; empty/zeroed structures (not error) for a game with zero events |
| AC-13 | `POST /sessions` / WS `/sessions/{sid}` | `POST` 201 with `{id, code}`, a 4-digit pairing code; WS connect with a valid `sid` **or** its 4-digit code succeeds and fans out between them (D-16); invalid/expired `sid` closes the socket or rejects the upgrade |
| AC-14 | Media serving (`renditions.wide` MP4 URL, D-3) | `GET` with `Range: bytes=0-1023` → 206 with `Content-Range` and `Accept-Ranges: bytes` headers, body length 1024; full `GET` without Range → 200; `Content-Type: video/mp4` |
| AC-15 | CORS | Preflight `OPTIONS` and actual requests from the web app's dev origin (e.g. `http://localhost:5173`) receive `Access-Control-Allow-Origin` matching that origin (or `*` if that's the chosen policy — assert whichever is implemented, but assert it explicitly, not implicitly) |
| AC-16 | Auth (if enabled) | Any mutating route without `X-Replay-Key` → 401; with correct key → normal response; game IDs alone are not treated as sufficient auth (plan §4.6 "unguessable" is a mitigation, not a substitute, when the env var is set) |

---

## 6. Non-functional

| ID | Requirement | Pass criteria |
|---|---|---|
| NF-01 | 10-foot UI text sizing | Every visible text node on `/tv/*` screens has computed `font-size >= 24px` at a 1920×1080 viewport |
| NF-02 | Visible focus ring on every focusable | For each `data-testid` matching an interactive element on `/tv/*`, focusing it via keyboard yields a computed `outline` (or box-shadow/border) that differs from the unfocused state — `outline: none` with no substitute fails |
| NF-03 | Full D-pad + Back reachability | Every screen listed in §0 Routes is reachable and exitable using only `Arrow*`, `Enter`, `Escape`/`Backspace` — a scripted traversal from `/tv` visits Library → Watch → Select → Follow → Back → Highlights → Review → back to Library without any non-keyboard input |
| NF-04 | No hover-only affordances | No interactive element's visibility/actionability depends on a CSS `:hover` rule without an equivalent `:focus`/`:focus-visible` rule (static CSS check + keyboard-only traversal confirms every action is reachable per NF-03) |
| NF-05 | Overlay/video sync at pause | With video paused, a select-mode box position matches the player's `bb` for that exact `t` within < 1 frame (33 ms) of visual/time error — i.e. no interpolation drift once paused |
| NF-06 | Overlay/video sync while playing (client follow mode) | Sampling `video.currentTime` and the applied CSS transform at 5 points over a 3 s follow-mode playback, the transform's implied crop-rect timestamp is within ≤ 100 ms of `video.currentTime` |
| NF-07 | Processing time budget | A 5-minute 1080p clip on a 16-core CPU box: detect + track stages combined complete in ≤ 2× realtime (≤ 10 minutes wall clock), measured by wrapping those stages with a timer in the pipeline harness; stated as a target — record actual measured ratio in `docs/decisions.md` once measured, and revisit if consistently missed |

---

## 7. Traceability

| Feature | Scenarios | Priority | Phase 1 in-scope |
|---|---|---|---|
| W1 Library screen | S-01, S-11, S-12 | P0 | Yes |
| W2 Wide playback transport | S-01, S-13, S-14, S-15 | P0 | Yes |
| W3 Select mode | S-01, S-17, S-18, S-19 | P0 | Yes |
| W4 Follow mode | S-01, S-19, S-20, S-21, S-22b | P0 | Yes |
| W5 Court inset | S-22 | P1 | Yes |
| W6 Spotlight overlay | S-23 | P1 | Yes |
| W7 Player roster tagging | S-08, S-24, S-25, S-26 | P0 | Yes |
| W8 Event markers / FF-RW jump | S-16 | P1 | Yes |
| H1 Per-player highlight reel | S-01, S-27 | P0 | Yes |
| H2 Game top plays | S-28 | P1 | Yes |
| H3 Query chips + free text | S-01, S-29, S-30 | P0 (chips) / P1 (free text) | Yes |
| H4 Phone companion query | S-31 | P1 | Yes |
| H5 Bookmarks | S-32 | P1 | Yes |
| H6 Export clip MP4 | — | P2 | No (deferred) |
| R1 Shot chart | S-33 | P1 | Yes |
| R2 Position heatmap | S-34 | P2 | Yes (time-permitting, ordered last in §6.1) |
| R3 Box score lite | S-35 | P1 | Yes |
| R4 Distance covered | — | P2 | No (deferred) |
| R5 Review queue | S-36, S-37 | P1 | Yes |
| I1 Web uploader | S-01, S-02, S-03 | P0 | Yes |
| I2 Court calibration | S-01, S-04, S-05, S-06 | P0 | Yes |
| I3 Processing status | S-01, S-07, S-08 | P0 | Yes |
| I4 Team split by jersey color | S-10 | P1 | Yes |
| I5 Sport picker at upload | S-09 | P0 (basketball) | Yes |

Edge/failure cases (E-01..E-22), pipeline checks (PC-01..PC-11), API checks (AC-01..AC-16),
and non-functional checks (NF-01..NF-07) apply across the above features per §3–§6 and are
not re-listed per-feature here to avoid duplication.

---

## 8. Test data

`samples/real/` is gitignored and local-only (D-7); CI runs only against `samples/synthetic/`.
Fixtures below do not yet exist in the repo (only `samples/real/.gitkeep` is present as of
this spec) — they are prerequisites for the scenarios/checks listed, to be produced by the
synthetic generator (plan §7.4) and by filming (plan §5, footage schedule).

| Fixture | Description | Used by |
|---|---|---|
| `synth-bball-half-5v5.mp4` + golden outputs | Synthetic half-court basketball, 5v5, known ground-truth ellipse positions, ≥2 off-court decoys, 1 scripted made shot, 1 scripted missed shot, ~60–120 s | S-01, S-04–S-08, S-16–S-21, S-27–S-29, S-33, S-35–S-37, PC-01–PC-10, E-16 (title is separate input) |
| `synth-bball-zero-players.mp4` | Same court/camera, no person ellipses | E-09, E-10 |
| `synth-bball-collinear-calib.json` | A landmark-click fixture with 3+ collinear points, for calibration validation | E-06 |
| `synth-bball-few-points-calib.json` | Landmark set with only 2–3 of the 5 required points | E-05 |
| `non-video.txt`, `truncated.mp4` | Invalid-upload fixtures | E-03, E-04 |
| `real-bball-clip-01` (local, MANIFEST entry) | ≥5 min real basketball footage, tripod, elevated, consenting adults, per §5 filming plan | PC-01–PC-10 (real-clip column), Phase 1 DoD manual pass, S-01 manual walkthrough with real footage |
| Mock API-down harness | Test config that stops/blocks the API process, no video fixture | E-22 |
| Duplicate-name roster fixture | A processed game with ≥2 untagged players, no separate media needed (reuses `synth-bball-half-5v5`) | E-17, E-18 |
| Low-confidence event fixture | `events.json` override with a `confidence:0.55, confirmed:false` shot event | S-36, S-37, E-19 |
| Query-with-zero-results fixture | A processed game/roster with no misses (or no 2nd-half events) so a "misses" or "2nd half" chip returns `clips: []` | E-20 |

Real clips are never committed; each one referenced above must have a corresponding entry in
`samples/real/MANIFEST.md` (source, license/consent note, why it matches target framing) per D-7
before it is used in any check in this spec.

---

## 9. Auto-calibration (D-23) — appended

`POST /games/{id}/calibration/auto` asks a Claude vision model where the court landmarks
are and the calibration page draws the answer as dots the user accepts or drags. The
proposal is **never** the calibration: `POST /games/{id}/calibration` stays the commit
step, and the manual walk of §4 (S-04..S-06) stays reachable and unchanged. Everything
below therefore tests an *accelerator*, and every failure mode of it must land the user
back on the manual path with the gate shut.

### 9.1 Scenarios

| ID | Scenario | Steps | Expected | Priority |
|---|---|---|---|---|
| S-04b-1 | A proposal appears by itself | Upload a clip, open `/upload/:id/calibrate` | `[data-testid=autocalib-status]` reads "Finding the court…" with a spinner over the frame; `[data-testid=autocalib-busy]` is click-through so the manual walk still works underneath; when the proposal lands the status names how many points were found and the reprojection error | P1 |
| S-04b-2 | Accept | With a proposal on screen, press `[data-testid=autocalib-accept]` | Exactly one `POST /calibration` is sent, carrying only the landmarks at confidence >= 0.5; `[data-testid=calib-error]` goes `data-ok="true"` and `start-processing` is enabled | P1 |
| S-04b-3 | Adjust and drag | Press `[data-testid=autocalib-adjust]`, drag `[data-testid=landmark-handle-corner_nl]` 30 px | Every landmark gets a >= 44 px handle; the dot follows the pointer; releasing re-POSTs `/calibration` and the error text changes | P1 |
| S-04b-4 | Low-confidence points are the user's job | Inspect the dots of a proposal with a landmark under 0.5 | That dot renders hollow (`.landmark.hollow`), is excluded from the accepted set, and can be dragged into place | P1 |
| S-04b-5 | Opt out | Press `[data-testid=autocalib-manual]` | The proposed dots disappear, the walk restarts at the first landmark, and S-04's flow passes unchanged | P1 |
| S-04b-7 | Correct a proposal in place | In Adjust, press the chip `[data-testid=calib-point-corner_fl]`, then `[data-testid=calib-skip]`; tap the pending hollow `rim`'s handle; tap `landmark-handle-corner_nr` and then the frame | The chip selects (`aria-pressed="true"` on chip and handle, `calib-prompt[data-target=corner_fl]`) without moving the point; "Not visible" removes it and the walk never asks for it again; the walk carries on with what the proposal left uncommitted (the hollow `rim`). While a point is pending, a tap (no drag) on any handle is a frame tap for *that* point — two badminton landmarks sit 15 px apart, inside one 44 px handle; with nothing pending it selects the handle's point, and a frame tap re-places a selected one. Before: after Adjust the walk cursor was parked past the end, so "Not visible" was disabled. Handles are clamped inside the frame so an off-frame proposed point stays grabbable | P1 |
| S-04b-8 | 1080p fits | 1920×1080, proposal panel up | Frame, the three proposal buttons, the actions and `start-processing` all end ≤ 1080 px, no page scroll, frame ≥ 700 px tall. At ≥ 1100 px wide the controls take a 420 px side column; narrower, the page stacks (S-04b-9, 390×844: no horizontal scroll, prompt above the frame) | P1 |
| S-04b-6 | Nothing is committed until the user says so | Wait for a proposal, then `GET /games/{id}` | `court` is still absent and `POST /process` is still 400 | P0 |

### 9.2 API checks

| ID | Check | Expected |
|---|---|---|
| AC-17 | `POST /games/{id}/calibration/auto` before any upload | 400, "no calibration frame yet — upload the video first" |
| AC-18 | `POST .../calibration/auto` with an unknown sport | 400; a missing `variant` is 422 |
| AC-19 | `POST .../calibration/auto` while one is queued or running | 202 with the *same* `job_id` — one model call per game at a time |
| AC-20 | `GET .../calibration/auto` before anything was asked | `{"status": "idle", "ok": false}` |
| AC-21 | `GET .../calibration/auto` after it finishes | `{"status": "done", "ok": …, "proposal": {landmarks_px, confidence, snapped, source, notes}, "reprojection_error_px": …}` |
| AC-22 | Either call on a game that does not exist | 404 |

### 9.3 Pipeline checks (`courtcam/tests/test_autocalib.py`, no model call)

| ID | Check | Expected |
|---|---|---|
| PC-12 | `gridded()` on a 2560x960 frame | Long side is 1568 px, aspect preserved, grid labelled in *source* pixels |
| PC-13 | Prompt construction | Carries the profile's `landmark_descriptions` and `orientation_hint`; asks only for `court.landmarks` unless `--ask-optional`; never names a landmark the variant's template lacks |
| PC-14 | Two-pass agreement | Landmarks the straight and mirrored passes agree on within 3 % of the image width survive with `confidence = 1 - d/tol`; the rest are dropped, with the disagreement distance in `notes` |
| PC-15 | Model failure | A backend that raises returns an empty `Proposal` with a note — never an exception |
| PC-16 | `LineSnapper.snap` | Pulls a point onto the nearest line intersection within 40 px; returns the point untouched when there is no line |
| PC-17 | Handedness | A globally left/right-swapped labelling (which the court's own mirror symmetry makes fit *equally well*) is detected from the winding of three landmarks and corrected |
| PC-18 | `--backend auto` resolution | `ANTHROPIC_API_KEY` -> `vlm`; else a `claude` on PATH -> `claude-cli`; else `lines` |

### 9.4 Accuracy check (manual, real footage)

`courtcam autocalib-eval` scores the proposal against the hand-made
`samples/real/*.landmarks.json` ground truth and prints per-landmark pixel error, the mean,
and the fraction within 20 px. It is **not** a CI gate: it costs money, takes minutes per
clip, and `samples/real/` is gitignored (D-7). It writes an overlay per clip to
`samples/real/frames/autocalib_<clip>.jpg` and caches each proposal next to it, so
`--reuse` re-scores for free.

### 9.5 New test hooks

Added to `apps/web`: `autocalib-status` (with `data-state` = `queued|running|done|failed|applied|manual`),
`autocalib-busy`, `autocalib-accept`, `autocalib-adjust`, `autocalib-manual`,
`landmark-handle-{name}` (with `aria-pressed` when selected, S-04b-7), `calib-point-{name}`
(Adjust only: one chip per point, selects it), and `data-confidence`
on the existing `landmark-{name}`. Status rows `stage-{name}` carry `data-progress`.

---

## 10. Fix-up wave after multi-sport + auto-calibration — appended

Six defects found by driving the pickleball profile (D-21..D-23) through screens that had
only ever seen basketball. Each has a named regression test; nothing below changes a
contract in §4.5/§4.6 except the two additive response fields called out.

| # | Where | Defect | Fix | Regression test |
|---|---|---|---|---|
| 1 | `apps/web/src/screens/Upload.tsx` (Calibrate) | `useState("half")` hardcoded basketball's variant: a profile whose `variants` are `["doubles"]` showed no checked radio and still posted `variant:"half"`, which the API 400s | the variant is derived — picked value, else `profile.variants[0]` — and the radio group is not rendered at all when a profile has exactly one variant | `e2e/S-04-calibration.spec.ts` → *S-05b a single-variant sport hides the picker and posts its own variant* |
| 2 | `services/api/replay_api/main.py` `calibrate_auto` | only the sport was validated, so a wrong variant was swallowed and surfaced much later as a failed proposal | both routes now go through `_court_or_400(sport, variant)`, so a bad variant is a 400 on `POST /calibration/auto` exactly as on `POST /calibration` | `services/api/tests/test_calibration_auto.py::test_auto_validates_the_variant` |
| 3 | `courtcam/courtcam/calibrate.py` | `findHomography(src, dst, RANSAC, 3.0)` had `dst` in **metres**, so the threshold meant "3 court metres" and rejected nothing | the fit runs metres→pixels (threshold `MAX_RANSAC_PX = 4.0` px) and is inverted; RANSAC only above `RANSAC_MIN_POINTS = 6`, plain least squares below it; clicks that are collinear are rejected explicitly because OpenCV only checks the *source* set. `reproj_error_px` is now the worst residual among the points RANSAC kept, and every residual is reported | `courtcam/tests/test_calibrate.py::test_ransac_votes_out_one_badly_placed_click`, `::test_with_five_points_a_bad_click_still_fails_the_gate`; `services/api/tests/test_routes.py::test_calibration_reports_per_landmark_residuals` |
| 4 | `apps/web/src/screens/Review.tsx` | `sport_ui.review` was ignored, so a net sport declaring `review: [heatmap]` still drew an empty shot chart and an empty box score | only the listed panels render (`shot_chart`, `heatmap`, `box_score`; names normalised case/punctuation-insensitively). Absent field ⇒ all panels. The **review queue is not a panel** — it is the screen's job and renders for every sport, which is why no profile lists it | `e2e/S-36-review-queue.spec.ts` → *S-33/S-35 only the panels in sport_ui.review are rendered* |
| 5 | `services/api/replay_api/stats.py` | `HEATMAP_BINS = (15, 14)` was a FIBA half court, so a 6.1 × 13.41 m pickleball court got basketball's grid | bins come from the court's own `x_range`/`y_range` at ~1 m per cell, floored at `MIN_HEATMAP_BINS = 4`. Basketball is unchanged at (15, 14); pickleball is (6, 13). The TV reads `cols`/`rows` off the response, so no consumer assumed the counts | `services/api/tests/test_stats.py::test_heatmap_bins_follow_the_court_not_a_basketball_constant` |
| 6 | `e2e/S-04-calibration.spec.ts`, `e2e-live/S-01-live.spec.ts`, `playwright.config.ts` | a 40 s `expect.poll` inside a 30 s test; the live spec hardcoded "rim" as point 5; `workers` defaulted to half the cores | test timeout raised above the poll; the live spec reads the click order from `GET /sports` → `landmarks` (D-13) and asserts "point *n* of *N*" from it; `workers: 4` | the same specs (see §0) |

### 10.1 Additive response fields

- `POST /games/{id}/calibration` → 200 now also carries
  `residuals_px: {landmark: px}`, the per-landmark reprojection error. Needed because #3
  lets RANSAC vote a bad click out of the fit: the single `reprojection_error_px` is then
  the *fit's* quality and no longer points at the bad click. The calibrate page renders the
  worst one as `[data-testid=calib-worst]`.
- `courtcam`'s `calib.json` (`courtcam.calib.v1`) carries the same `residuals_px` map.
  Both fields are optional and additive; nothing reads them but the uploader.

### 10.2 Mock fixtures added (`apps/web/src/api/mock.ts`)

`GET /sports` serves basketball **and** pickleball (`variants: ["doubles"]`,
`sport_ui.review: ["heatmap"]`, six landmarks), and the seeded library gains
`g_pickle4` ("Sunday doubles — court 3"), exported from `e2e/helpers.ts` as `NET_GAME_ID`.
Library card counts in S-11/S-12 are 4, and S-02 expects two sport radios.

---

## 11. Lens model and the RANSAC fallback (D-25) — appended

### 11.1 Additive response fields

- `POST /games/{id}/calibration` → 200 now also carries `k1: number` (0.0 when the lens
  model did not fire) and `lens_rms_px: [before, after] | null`, the reprojection RMS the
  `k1` fit started from and ended at. Both are additive and optional; the web client
  ignores them. They exist because the preview used to call the *lens-free* fit while the
  pipeline ran the lens-aware one — so AC-03's "reprojection computed" now means
  `pipeline.calibrate_lens`, the same fit the run will use. Frame size comes from the
  game's `video` record when it is populated, else from `media/calib.jpg` (D-14 grabs the
  frame at upload but does not probe it, so on the pre-processing path it is the JPEG).
- `courtcam`'s `calib.json` (`courtcam.calib.v1`) carries `k1`, `image_size` and
  `lens_rms_px` on the same terms, and `court_polygon_px` is a 0.25 m polyline rather than
  4 corners once `k1 != 0`.

### 11.2 `calib-worst` and the honest error

`calibrate.homography()` keeps its RANSAC consensus only when it holds **all but at most
two** landmarks; past that it refits by least squares over every landmark and reports
*that* fit's worst residual. It also seeds `cv2.setRNGSeed(0)`, so the same clicks give
the same calibration every run. Consequence for S-04/E-08 and `[data-testid=calib-worst]`:
on a barrelled frame `reprojection_error_px` and the worst residual now agree to within
one excused click instead of differing by two orders of magnitude (measured: 1.5 px
reported against a 167 px worst landmark, before).

| ID | Check | Expected |
|---|---|---|
| PC-19 | `homography()` on the 12 badminton-auditorium landmarks, `k1 = 0` | worst residual **≥ 40 px** and `fit_error_px` reports it — not a 5-point consensus's 1.5 px (`courtcam/tests/test_calibrate.py::test_barrelled_frame_reports_its_worst_landmark_not_a_five_point_consensus`) |
| PC-20 | Same landmarks, three calls | Identical residuals every time (`::test_the_barrelled_fit_is_deterministic`) |
| AC-03b | `POST /calibration` with those landmarks and a 1920×1080 `media/calib.jpg` | 200; `k1 < -0.5`, `lens_rms_px` ≈ `[14.6, 2.5]`, `reprojection_error_px < 6` (`services/api/tests/test_routes.py::test_calibration_reports_the_lens_model_the_pipeline_will_run`) |
| AC-03c | `POST /calibration` with the 5-landmark basketball fixture | `k1 == 0.0` — under `distortion.MIN_POINTS`, so the payload is the pre-D-25 one (`::test_an_undistorted_lens_reports_k1_zero`) |

## 12. Rally segmentation and the one-court badminton profile — appended

| ID | Check | Expected |
|---|---|---|
| PC-21 | `events.detect_rallies` on synthetic tracks: 4 players still (1 cm jitter), three bursts of ~2.5 m/s movement, one player strolling between two of them | exactly three `rally` events, each IoU ≥ 0.6 with its burst and starting no later than 0.5 s after it (the serve is inside the clip), for both the badminton and pickleball profiles (`courtcam/tests/test_events.py`) |
| PC-22 | Same, everyone still / no players | no events (`::test_still_players_and_no_players_give_no_rallies`) |
| PC-23 | Net-sport synth run | every event is a `rally` inside `[0, duration]` (`test_net_sports.py::test_only_rally_events_inside_the_clip`) |
| PC-24 | Real clips (manual, local-only labels `samples/real/*.rallies.json`) | rally P/R at IoU ≥ 0.5 as recorded in `samples/real/RESULTS.md` "Rally segmentation"; `badminton_auditorium_smoke.mp4` must give ≥ 1 rally |
| PC-25 | Badminton profile | `court.variants == ["doubles"]` (so S-05b applies: no picker); `template("singles")` still loads the doubles template; unknown variants still raise (`test_net_sports.py::test_badminton_is_one_court_and_singles_still_loads`) |
| AC-03d | `POST /calibration` with `sport: badminton, variant: singles` | 200 — the retired name is a `court.variant_aliases` key; `GET /sports` badminton `variants == ["doubles"]` (`services/api/tests/test_routes.py::test_badminton_is_one_court_and_the_retired_singles_name_still_posts`) |
