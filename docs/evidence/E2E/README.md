# E2E: recorded end-to-end run of the redesigned TV (D-81) + phone pages

`replay-e2e.mp4` (1280×720, H.264, 25 fps, 4:06, 6.4 MB) is a screen recording of an
**automated** Playwright run of the redesigned TV UI (waves 1–4). Every beat asserts what
it shows, so the recording is also a test: **20 / 20 beats passed** (run of 2026-10-20 on
hfbox, commit `ecee2ee` plus the recording harness changes committed with this README). The full-quality 1920×1080 copy stays on the box at
`/workspace/wt/replay-rec2/out/replay-e2e-full.mp4`.

- **Left:** the TV app (`apps/tv`, react-native-web build) in Chrome at 1920×1080, driven
  only by the keyboard as a D-pad (arrows, Enter = Select, Esc = Back).
- **Right:** a phone browser context at 390×844. It shows an idle placeholder until it
  opens a link **read from a QR code the TV shows**: Add game's `/u/<id>#t=…` and On your
  phone's `/p/<id>?job=…#k=…`. Each QR is decoded and checked module for module against
  the URL the API returned; the phone never gets a URL any other way.
- **Back end:** the real `services/api` with `REPLAY_PIPELINE=worker` and
  `REPLAY_PUBLIC_WEB_BASE=http://127.0.0.1:5194` (the phone pages, so the QR links open
  them), served by `scripts/box-demo.sh serve`. No mock API, no fake pipeline.
- **Footage:** SYNTHETIC only: a 20 s half-court clip (`courtcam synth --sport basketball
--variant half --duration 20 --seed 7 --size 1280x720`) uploaded from the phone, and the
  two `make demo` games (60 s synthetic basketball and pickleball doubles).
- The caption band names each beat, its PASS/FAIL, and on line 2 what the beat found.

## Reproduce

```sh
make record-e2e     # sync to the box, run scripts/record-e2e.sh there, copy the MP4 here
```

or on the box: `bash scripts/record-e2e.sh <copy dir>` (`DEMO_DIR=<dir>` reuses demo games
built elsewhere; the build step tops them up from cache). The script builds the demo games,
generates the upload clip, copies the demo games into a fresh `data/recording`, serves API
:8093, TV :5193, phone :5194 in tmux `replay-recording-serve`, runs the `recording`
Playwright project under `.pw.lock` + `.cpu.lock`, stops the servers, copies `api.log`, and
composites with `scripts/record_e2e_compose.py` (writes `beats.md`, the ≤ 25 MB copy).

## Beats

Times are in `replay-e2e.mp4`. Nothing was cut: the upload's pipeline run took 19 s.

| #   | beat                                   | video time    | result | what it found                                                                                                                                      |
| --- | -------------------------------------- | ------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Home + Settings                        | 0:02.9–0:16.1 | PASS   | hero follows focus (2 games); Test connection `Connected · 2 games`                                                                                |
| 2   | Add game: sport, QR                    | 0:16.1–0:23.2 | PASS   | Basketball creates a game; the QR encodes `127.0.0.1:5194/u/<id>#t=…` (the token is only in the QR); "Waiting for your phone"                      |
| 3   | Phone: open QR link + upload           | 0:23.2–0:28.6 | PASS   | 20 s SYNTHETIC clip uploaded; TV "Uploaded. Calibrating on the phone…"                                                                             |
| 4   | Phone: calibrate                       | 0:28.6–0:39.6 | PASS   | proposal "Found 9 points · 0.0 px · needs a check" refused, Accept disabled (D-72); landmarks placed by hand                                       |
| 5   | Process, TV opens the game             | 0:39.6–1:02.9 | PASS   | "Reading the court, under a minute"; ready after 19 s; the TV opens and plays it                                                                   |
| 6   | Player transport + court-line timeline | 1:02.9–1:13.3 | PASS   | 6 moment notches = `GET /moments`                                                                                                                  |
| 7   | Tap-seek snap                          | 1:13.3–1:16.1 | PASS   | snapped to "Rebound" 0:14 (moment thumb in the preview), resumes at its start                                                                      |
| 8   | Hold-to-seek                           | 1:16.1–1:21.2 | PASS   | step grows 10 → 30 s (readout −0:16)                                                                                                               |
| 9   | FF ×8, Prev/Next                       | 1:21.2–1:31.7 | PASS   | 8.0 s of game per 1 s; Next "Steal" 0:34, Prev "Shot" 0:15                                                                                         |
| 10  | Moments row                            | 1:31.7–1:40.1 | PASS   | 6 cards, the playhead follows the walk; chip "Player 1" → 1 card; jump to "Missed shot" 0:07                                                       |
| 11  | Highlights                             | 1:40.1–1:56.7 | PASS   | 1 of 3 → 2 of 3 back to back; Next 3 of 3; Prev 2 of 3                                                                                             |
| 12  | Condensed (pickleball)                 | 1:56.7–2:20.3 | PASS   | "Condensed, rally 1 of 4" → "rally 2 of 4"                                                                                                         |
| 13  | Follow player                          | 2:20.3–2:37.1 | PASS   | 10 chips; "Following Player 2" while playing; Back to wide                                                                                         |
| 14  | Angles                                 | 2:37.1–2:57.0 | PASS   | "Shot · #p1 (miss)": 11 angles, Real video + 2.5D + 3D; Back returns to the game at 0:12                                                           |
| 15  | Stats panel                            | 2:57.0–3:05.5 | PASS   | 6 box-score rows, shot chart, "Review 13 plays"; video keeps playing                                                                               |
| 16  | Commentary                             | 3:05.5–3:21.2 | PASS   | broadcast rendition + caption "Player 10 brings it in."; off again                                                                                 |
| 17  | On your phone: Clip                    | 3:21.2–3:37.6 | PASS   | QR `/p/g_demo_basketball?job=clip&t=…#k=…` verified; moment 0:34.0–0:34.5 trimmed to 0:33.5–0:35.0, "Clip saved." (in `GET /clips`), 9:16 rendered |
| 18  | Phone: Tag + Review                    | 3:37.6–3:46.6 | PASS   | p1 tagged "Riley" (name-only profile); review "Yes", 12 left                                                                                       |
| 19  | Resume from Home                       | 3:46.6–3:55.7 | PASS   | hero "Resume 0:36"; plays on from 36.1 s                                                                                                           |
| 20  | TV picks up phone edits                | 3:55.7–4:04.1 | PASS   | follow chip and box score say "Riley"; "Review 12 plays" (was 13)                                                                                  |

## Caveats

- **Synthetic data**: mannequins on a rendered court; the product loop, not accuracy.
- **Not a Fire TV**: react-native-web in headless Chromium; the APK is not in this run.
- **No audio**: Playwright records video only; the commentary captions are on screen.
- **Calibration path**: the synthetic proposal is not confident enough to accept, so the
  run shows the D-72 refusal and clicks the generator's true landmarks by hand.
- **No Free view beat**: the demo games have no 2.5D scene package (only Tier C
  `scene/pl_*.json`); the API's `scene_url` needs `replays/<play>/scene/layout.json` from
  the opt-in `scene` stage, which `box-demo.sh build` does not run.
- **The run edits the copy it serves** (an upload, a clip and its 9:16 cut, a profile tag,
  a review answer); `make demo`'s games are untouched.
- Dwells are paced for a viewer; timings are not performance numbers.

## Files

- `apps/tv/e2e-recording/replay-e2e.spec.ts`: rewritten for the new UI (20 beats, QR
  decoding, per-beat `detail`, `FAIL_` key frames)
- `scripts/record-e2e.sh`: phone = the QR links' server; copies `api.log`; `REC_REAL` removed
- `scripts/record_e2e_compose.py`: DejaVu fallback font (the box has no FreeSans), captions
  fitted to width, line 2 = what the beat found
- `scripts/box-demo.sh`: serve sets `REPLAY_PUBLIC_WEB_BASE`; build names the `storyboard`
  and `moments` stages (seek previews, moment thumbs, hero art) for both demo games
- `Makefile`: `record-e2e-real` removed (it is in git history)

## Bugs found while recording

- **Product: Home "Play" vs the player's resume disagree near the end.** `resumeAt`
  (resume.ts) returns null when the stored spot is within 5 s of the end, so Home's hero
  shows plain "Play" with no "Start over", but Watch's initial position uses
  `resumeSpot(gameId)` raw. Repro: basketball demo → Highlights → let the reel reach its
  end → Back → hero says "Play" → Select: the player opens at ~56–57.6 s of 60 s, not
  0:00. The spec steps back to "2 of 3" before leaving (commented), so the beat does not
  depend on it.
- Spec bugs fixed during the runs: the snapped preview shows the moment thumb, not the
  storyboard sprite; the chip locator lost focus after Enter; an unhandled
  `waitForResponse` rejection; the follow pick matched the `follow-p` prefix.

# Historical: recorded run of the pre-redesign UI (2026-10-06)

The sections below describe the old TV UI and are kept for the record. `make
record-e2e-real` and `REC_REAL` were removed; they are in git history.

## The synthetic run (old UI)

`replay-e2e.mp4` (then 1280×720, H.264, 25 fps, 3:25, 4.2 MB) was a screen recording of an
**automated** Playwright run of the product. Every beat asserts what it shows, so the
recording is also a test: **15 / 15 beats passed** (run of 2026-10-06 on hfbox, commit
521561f + the files listed below). The full-quality 1920×1080 copy (12.3 MB) stays on the
box at `/workspace/wt/replay-recording/out/replay-e2e-full.mp4`.

- **Left:** the TV app (`apps/tv`, the react-native-web build) in Chrome at 1920×1080,
  driven only by the keyboard as a D-pad (arrows, Enter = Select, Esc = Back).
- **Right:** the phone companion (`apps/web`) in a second browser context at 390×844.
- **Back end:** the real `services/api` with `REPLAY_PIPELINE=worker` (the worker runs the
  courtcam stages), served by `scripts/box-demo.sh serve`. No mock API (`VITE_MOCK_API`
  unset), no fake pipeline.
- **Footage:** SYNTHETIC only. A 20 s half-court clip from
  `courtcam synth --sport basketball --variant half --duration 20 --seed 7 --size 1280x720`,
  uploaded through the phone, and the two `make demo` games (60 s synthetic basketball and
  pickleball doubles, built by `scripts/box-demo.sh build`).
- The caption band under the two screens names each beat and its assertion result. The
  caveat line stays on screen the whole time.

## Reproduce

```sh
make record-e2e     # sync to the box, run scripts/record-e2e.sh there, copy the MP4 here
```

or on the box: `bash scripts/record-e2e.sh <copy dir>`. The script:

1. builds the demo games (`box-demo.sh build`; cold ~10.5 min on 2026-10-06, then cached),
2. generates the upload clip (seeded, so the same bytes every time),
3. copies the demo games into a fresh data dir (`data/recording`, with an empty worker
   cache, so the upload's pipeline run is cold and a re-run starts from the same state),
4. serves API :8093, TV :5193, phone :5194 in tmux `replay-recording-serve`,
5. runs `pnpm exec playwright test --project=recording` in `apps/tv` (opt-in: the project
   exists only when `REPLAY_REC_TV` is set) under the `.pw.lock` and `.cpu.lock`,
6. stops the servers, then `scripts/record_e2e_compose.py` composites the TV video, the
   phone video and the captions with the box's static ffmpeg and writes the ≤ 25 MB copy.

Playwright records each context at its own size (`video: on`, 1920×1080 for the TV; the
phone context's `recordVideo` at 390×844). The compositor places the TV at 1488×837 and the
phone at 1:1; its time offset is in `beats.json` (`phone_offset_s`, 0.02 s here).

## Beats

Times are in `replay-e2e.mp4`. Nothing was cut: the uploaded clip's pipeline run took
19 s (beat 4), so the processing wait is shown in full.

| #   | beat                                  | video time | result | what is asserted                                                                                                                                                                                                                                                                                                                             |
| --- | ------------------------------------- | ---------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | TV settings: test connection          | 0:02–0:09  | PASS   | Library → Up → Settings (D-69); address = the build default; Test connection → `Connected · 2 games`                                                                                                                                                                                                                                         |
| 2   | Phone: create game + upload           | 0:09–0:14  | PASS   | game created, the clip uploaded (`upload-done`)                                                                                                                                                                                                                                                                                              |
| 3   | Phone: calibrate                      | 0:14–0:27  | PASS   | auto-calibration proposed 9 points but scored 0.83 < 0.90: the weak-fit note shows and **Accept is disabled** (D-72). The override box is not ticked; the landmarks are placed by hand in the profile's order (`GET /sports`) at the clip's true pixels (`landmarks.json` from `courtcam synth`); `calib-error` ok; Start processing enabled |
| 4   | Phone: process (real worker pipeline) | 0:27–0:46  | PASS   | a stage `running`, then status `ready`. Worker log: 15 tasks, all cache misses (YOLO detect 7.2 s, pose 6.4 s); the game came out with 10 players, 2 shots, 2 possession changes                                                                                                                                                             |
| 5   | TV: the uploaded game plays           | 0:46–0:53  | PASS   | its card is in the TV library; Enter → plays past 2 s                                                                                                                                                                                                                                                                                        |
| 6   | Library → Watch                       | 0:53–1:02  | PASS   | D-pad to the basketball demo card; hype meter and event markers on the scrubber; plays                                                                                                                                                                                                                                                       |
| 7   | Select → follow → spotlight → inset   | 1:02–1:14  | PASS   | pause → select boxes; Right ×2, Enter → follow-cam; Playback ▸ Spotlight → spotlight overlay; court inset with > 1 player dot; Back → wide                                                                                                                                                                                                   |
| 8   | Broadcast + commentary                | 1:14–1:25  | PASS   | Broadcast → the `broadcast` rendition loads; Commentary → a caption appears while playing                                                                                                                                                                                                                                                    |
| 9   | Pair phone + Clip that                | 1:25–1:47  | PASS   | Pair phone → 4-digit code; the phone connects with it; the TV's now-playing reaches the phone; past the end of a play the phone taps **Clip that** → `Clip saved · 0:13.0–0:17.4` on the phone and the same toast on the TV; Game ▸ Clips has the `tap` clip; D-pad trim −0.5 s / +0.5 s → `Trim saved`                                      |
| 10  | 9:16 share                            | 1:47–2:00  | PASS   | Share 9:16 on that clip → export `done`, the portrait preview video loads (burned-in `#p5 · STEAL` caption)                                                                                                                                                                                                                                  |
| 11  | Replay angles A/B/C                   | 2:00–2:30  | PASS   | Game ▸ Replays → first replay; paused, Right through all 11 angles; the tier badges seen are exactly Real video (A), 2.5D (B), 3D (C)                                                                                                                                                                                                        |
| 12  | Highlights + search                   | 2:30–2:51  | PASS   | Highlights → `All shots` → a reel; Search → `Type a search…` → "steal" typed on the on-screen keyboard with the arrows → results (SigLIP index: "No match · ranked by similarity", steal plays ranked first)                                                                                                                                 |
| 13  | Review + box score                    | 2:51–2:57  | PASS   | `auto-detected` label, shot chart, box-score rows; Enter answers the first review question and the queue moves on (`PATCH /events/e_0000`)                                                                                                                                                                                                   |
| 14  | Player profile + card                 | 2:57–3:10  | PASS   | the phone creates a profile (name only; no face data, so no consent step is involved); on the TV, select mode → Players ▸ Link profile → that profile → toast `Linked to …`; the phone shows "Linked in 1 game"; Library → Players → the profile → Card → Render → the card PNG loads with the profile's name                                |
| 15  | Pickleball rallies + condensed        | 3:10–3:24  | PASS   | pickleball demo → Game ▸ Rallies → rows; Longest → plays with the rally counter; Condensed game → plays with `RALLY n / N`                                                                                                                                                                                                                   |

## Caveats

- **Synthetic data.** Generated mannequins on a rendered court. The demo games use the
  synthetic detector and ground-truth poses (`box-demo.sh`); the uploaded clip has no
  ground truth beside it, so it went through the API's default detector (YOLO) and pose
  model. This shows the product loop working, not accuracy on real footage.
- **Not a Fire TV.** The TV side is the react-native-web build of `apps/tv` in headless
  Chromium. The Fire TV APK has still never run on a device or emulator.
- **No audio.** Playwright records video only, so the Kokoro narration of the broadcast
  rendition is not audible here; the on-screen commentary captions are.
- **Calibration path.** The synthetic clip's proposal is not confident enough to accept,
  so the run shows the D-72 refusal and the manual walk. The pixels it clicks come from the
  generator's true landmarks (a scripted user who taps accurately), not from the proposal.
- **The run edits the copy it serves:** one phone-tap clip, one trim, one review answer,
  one profile and its link, one 9:16 export. `record-e2e.sh` serves a fresh copy of the
  demo games each run, so `make demo`'s games are not changed.
- Beats are paced for a viewer with fixed dwells (2.5 s after each beat, plus a few
  seconds on screens worth reading); the timings are not performance numbers.

## Files

- `apps/tv/e2e-recording/replay-e2e.spec.ts`: the spec (two contexts, per-beat
  assertions, `beats.json`)
- `apps/tv/playwright.config.ts`: the opt-in `recording` project (video on, 1920×1080);
  `apps/tv/tsconfig.json` type-checks the new folder
- `scripts/record-e2e.sh`, `scripts/record_e2e_compose.py`, `make record-e2e`
- `scripts/box-demo.sh`: each served tmux window now sources the box env itself (see the
  bug in the next section)

## Bugs found while recording

- **`box-demo.sh serve` ran on the wrong toolchain whenever the box's tmux server had
  not been started from a shell that had sourced env.sh** (the case on 2026-10-06): the
  API window ran `/opt/venv`'s python instead of the replay venv, and the two vite windows
  hung on corepack's "download pnpm 12.9.1? [Y/n]" prompt, so the TV and phone ports never
  came up (Playwright: `net::ERR_CONNECTION_REFUSED`). Fixed: every window starts with
  `source /workspace/wt/replay-env/env.sh &&`. The tmux global environment stays untouched.
- No product bugs. Two early failures were in this spec, not in the app. (1) The TV app
  keeps its pairing session in memory, so a `page.goto` after pairing drops it, and the
  phone never sees the TV's now-playing; the beat now stays inside the app (Back from Pair,
  then scrub with the D-pad). (2) Re-runs against the shared demo dir inherited the
  previous run's profile link: the TV then refused it with "Not linked: … is linked to
  another profile", which is correct. Each run now serves a fresh copy.

# Historical: E2E on REAL footage, old UI: basketball and volleyball, with Free view (local only)

The same spec, script and compositor, run on **real** corpus clips with `REC_REAL=<sport>`.
Nothing derived from these runs is committed: `samples/real` is local-test footage (D-7),
and the volleyball clip, although CC BY, shows minors (D-76). This section describes the
runs; it contains no frames. The recordings, `beats.json`, `beats.md` and 20–21 key
frames per run are in `docs/evidence/local/E2E-real/{basketball,volleyball}/` (gitignored);
the full-quality 1920×1080 copies are on the box in
`/workspace/wt/replay-recreal/out-real-{basketball,volleyball}/replay-e2e-full.mp4`.

Run of 2026-10-06 on hfbox, commit d352ad3 + the harness changes below: **basketball
16 / 16 beats PASS, volleyball 17 / 17 beats PASS.**

## Reproduce

```sh
make record-e2e-real SPORT=basketball    # or SPORT=volleyball
```

or on the box: `REC_REAL=basketball bash scripts/record-e2e.sh <copy dir>`. Differences
from the synthetic run:

- **Clip:** a 90 s cut of live play, re-encoded to H.264 by the script:
  `basketball_kennesawwide_240s` t 130–220 s (2560×960, 20 fps, panoramic) and
  `volleyball_westwashington_240s` t 0–90 s (1920×1080, 30 fps).
- **No demo games.** The library starts empty; every TV beat uses the uploaded game.
- **Calibration by hand.** The phone first shows what auto-calibration proposed. Both
  proposals were ok=false, so the D-72 refusal is on screen (Accept disabled). The run then
  takes "Place points myself" and clicks the clip's tracked hand-clicked
  `samples/real/*.landmarks.json` at its pixels, including the profile's optional points
  ("More points"). It never ticks the override.
- **Opt-in stages.** The API is served with `REPLAY_WORKER_STAGES=hype,replays,scene`. This
  is a new API setting: the worker's opt-in stages run on every upload after its default
  ones. Before it, an uploaded game could not get replays or a scene package through the
  API at all. The status page reads `ready` only after these stages finish too.
- **Captions on every frame:** "REAL footage — local test only (D-7)" (volleyball: "D-76:
  CC BY, but minors — never published"), "TV = react-native-web build in Chrome, NOT a
  Fire TV", and the beat with its PASS/FAIL.
- **Processing wait:** cut in post. The caption names the real elapsed time.

## Basketball (Kennesaw, 3:04, 5.3 MB)

Processing: 6 min 48 s real elapsed (6 min 33 s cut at 0:46). The worker ran 53 tasks,
all cache misses. The largest stage times were:

| stage             | tasks    | time  |
| ----------------- | -------- | ----- |
| SAM 2.1 `segment` | 3 plays  | 171 s |
| `tierb`           | 9 angles | 110 s |
| `scene`           | 3 plays  | 57 s  |
| `pose`            | –        | 36 s  |
| `plate`           | –        | 32 s  |
| YOLO `detect`     | –        | 20 s  |

The pipeline found 6 possession changes and 4 turnovers, and **no shot**.

| #   | beat                                    | video time    | result | what is asserted                                                                                                                                                                                     |
| --- | --------------------------------------- | ------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | TV settings: test connection            | 0:02.5–0:08.9 | PASS   | `Connected · 0 games` (empty library)                                                                                                                                                                |
| 2   | Phone: create game + upload             | 0:08.9–0:13.8 | PASS   | basketball game, 90 s clip uploaded                                                                                                                                                                  |
| 3   | Phone: calibrate                        | 0:13.8–0:33.8 | PASS   | proposal "Found 9 points · needs a check" (score 0.61 < 0.90) refused, Accept disabled; 14 points placed by hand; fit 3.3 px                                                                         |
| 4   | Phone: process                          | 0:33.8–0:51.6 | PASS   | a stage `running`, then `ready`                                                                                                                                                                      |
| 5   | TV: the uploaded game plays             | 0:51.6–0:58.4 | PASS   | card in the library, plays past 2 s                                                                                                                                                                  |
| 6   | Watch: event markers + hype             | 0:58.4–1:07.0 | PASS   | hype meter, > 0 event markers                                                                                                                                                                        |
| 7   | Select → follow → spotlight → inset     | 1:07.0–1:19.8 | PASS   | select boxes, follow-cam, spotlight, court inset with > 1 dot                                                                                                                                        |
| 8   | Replay angles                           | 1:19.8–1:38.6 | PASS   | 6 angles; tiers seen are Real video (A) and 2.5D (B)                                                                                                                                                 |
| 9   | Free view: enter                        | 1:38.6–1:47.5 | PASS   | Down at 2.23 s: mode `free`, scene frame = the angle's time (±1 frame), preset `real`, the package's honesty label, view-limit line and gauge, no SYNTHETIC tag. Envelope az −7.5…+5°, el 12.1…17.1° |
| 10  | Free view: orbit to both azimuth limits | 1:47.5–1:59.7 | PASS   | `data-az` stops exactly at −7.5 and +5.0; edge bar and gauge shown; one more press does not move it                                                                                                  |
| 11  | Free view: elevation limit              | 1:59.7–2:09.1 | PASS   | stops at 17.1° (top) and 12.1°, edge bars shown                                                                                                                                                      |
| 12  | Free view: dolly in and out             | 2:09.1–2:16.8 | PASS   | Menu → zoom mode; 17.1 m (gauge "closest") ↔ 19.9 m                                                                                                                                                  |
| 13  | Free view: cycle all presets            | 2:16.8–2:39.7 | PASS   | FF: Real camera → Broadcast high → Orbit left → Orbit right → Push-in → wrap; each preset's az/el equal `presetState`; Rew back                                                                      |
| 14  | Free view: play, then Back to the angle | 2:39.7–2:47.5 | PASS   | the atlas frame advances; paused at 7.05 s; Back → angles mode, video at 7.05 s (< 0.05 s), paused                                                                                                   |
| 15  | Highlights                              | 2:47.5–2:55.2 | PASS   | "All shots" → "No clips match that query" (0 shots detected; see notes)                                                                                                                              |
| 16  | Review + box score                      | 2:55.2–3:01.1 | PASS   | auto-detected label, shot chart, box-score rows, the first review answer moves the queue                                                                                                             |

## Volleyball (West Washington, 4:05, 9.1 MB)

Processing: 6 min 28 s real elapsed (6 min 13 s cut at 0:48). The worker ran 54 tasks.
The largest stage times were:

| stage                                      | tasks    | time  |
| ------------------------------------------ | -------- | ----- |
| SAM `segment`                              | 3 plays  | 204 s |
| `tierb`                                    | 9 angles | 79 s  |
| `pose`                                     | –        | 40 s  |
| `scene`                                    | 3 plays  | 33 s  |
| `plate`                                    | –        | 30 s  |
| `detect`                                   | –        | 24 s  |
| `condensed` (rendered on the TV's request) | 1        | 25 s  |

The pipeline found 3 rallies, 3 serves, 3 points and 14 blocks.

| #   | beat                                    | video time    | result | what is asserted                                                                                                                             |
| --- | --------------------------------------- | ------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | TV settings: test connection            | 0:02.5–0:08.9 | PASS   | as above                                                                                                                                     |
| 2   | Phone: create game + upload             | 0:08.9–0:13.8 | PASS   | volleyball game, 90 s clip uploaded                                                                                                          |
| 3   | Phone: calibrate                        | 0:13.8–0:35.7 | PASS   | proposal "Found 8 points · needs a check" (score 0.888 < 0.90) refused, Accept disabled; 10 points by hand (6 + 4 optional); fit 2.0 px      |
| 4   | Phone: process                          | 0:35.7–0:53.5 | PASS   | `running`, then `ready`                                                                                                                      |
| 5   | TV: the uploaded game plays             | 0:53.5–1:00.2 | PASS   |                                                                                                                                              |
| 6   | Watch: event markers + hype             | 1:00.2–1:09.0 | PASS   |                                                                                                                                              |
| 7   | Select → follow → spotlight → inset     | 1:09.0–1:21.7 | PASS   |                                                                                                                                              |
| 8   | Replay angles                           | 1:21.7–1:40.9 | PASS   | 6 angles: Real video + 2.5D                                                                                                                  |
| 9   | Free view: enter                        | 1:40.9–1:49.7 | PASS   | at 2.34 s; envelope az −17…+17°, el 15.6…32.6°                                                                                               |
| 10  | Free view: orbit to both azimuth limits | 1:49.7–2:09.0 | PASS   | −17.0 / +17.0, edge bars, gauge                                                                                                              |
| 11  | Free view: elevation limit              | 2:09.0–2:22.7 | PASS   | 32.6° / 15.6°                                                                                                                                |
| 12  | Free view: dolly in and out             | 2:22.7–2:36.1 | PASS   | 9.9 m ↔ 16.0 m                                                                                                                               |
| 13  | Free view: cycle all presets            | 2:36.1–2:59.4 | PASS   | the five presets, wrap, Rew                                                                                                                  |
| 14  | Free view: play, then Back to the angle | 2:59.4–3:07.5 | PASS   | paused at 7.44 s; the angle at 7.44 s                                                                                                        |
| 15  | Highlights                              | 3:07.5–3:15.3 | PASS   | "Rallies" → a reel of 3 clips                                                                                                                |
| 16  | Review: heatmap                         | 3:15.3–3:20.9 | PASS   | heatmap with cells, no shot chart (the volleyball profile's review panel)                                                                    |
| 17  | Volleyball rallies + condensed          | 3:20.9–3:59.7 | PASS   | rally rows; Longest plays with the rally counter; the condensed game rendered on request and plays with `RALLY n / 3` (60 s of play in 1:30) |

## Beats not in the real runs, and why

- **Broadcast + commentary, Search.** These need the `broadcast` / narration and
  `search_index` stages, which `REPLAY_WORKER_STAGES` does not run on the upload.
- **Pair phone + Clip that, 9:16 share, Player profile + card.** These do not depend on the
  footage, and the synthetic run covers them. Linking a profile to a real person is
  deliberately not done; for the volleyball minors it never is.
- **Tier C (3D) angles.** The `tierc*` stages are not in the opt-in list. The replay
  angles here are Tier A + B only.
- **Volleyball** has no shot chart or box score: its review panel is the heatmap. Its
  highlights chip is "Rallies", not "All shots".

## What the key frames show (read off the frames, honestly)

**Basketball, Free view** (Kennesaw panoramic corner rig):

- **Void.** A large dark void fills the upper right of every view, including the Real
  camera preset. The backdrop plane covers only the left part of the panorama, so the far
  wall and bleachers on the right exist only where the floor plate reaches.
- **Floating hoops.** The modelled hoop primitives do not sit on the real baskets:
  - a white backboard outline with an orange rim floats near the top-left basket, offset
    from it;
  - the far hoop is drawn as a large grey board with an orange ring hanging in the void
    at the top right (D-53's panoramic hoop-height ceiling).
- **Smeared floor.** Ghost streaks of players are baked into the floor plate near the far
  bleachers. The scorer's table at the bottom left is a flat, stretched smear on the floor
  that slides at the azimuth limits.
- **Players.** The cutouts themselves are clean and stand on their feet.
- **Tier B "Broadcast high" angle** (server-rendered) shows the same faults: black voids on
  both sides, the floating modelled backboard, and a cluster of players whose cutouts
  overlap.

**Volleyball, Free view** (fixed elevated camera, in the net plane):

- **The best case for 2.5D.** It has the widest envelope of any package so far (±17°).
- **Voids.** The Real camera preset does not fill the frame: the backdrop and floor plates
  end, leaving black wedges at the left, right and bottom.
- **Double net.** The modelled net (a white top line and a translucent band) does not
  coincide with the real net. The real net is baked flat into the floor plate as a dark
  blue stripe, which visibly diverges from the modelled post at az −17°. This is D-75's
  "static objects baked flat into the floor".
- **Line judge** (red flag) and a spectator at the right edge are partly baked into the
  plates and smear when the camera orbits.
- **Mask errors.** On dolly-in, a near player's legs are doubled (two overlapping players
  in one cutout) with a pink smear at the feet.
- **Dead-ball window.** At 2.3 s into the first highlight both teams are still huddled, so
  the Free view stills show huddles rather than a rally in play. The play window starts
  before the serve.

**Both:**

- Free view runs in headless Chromium, so WebGL is SwiftShader on the CPU. Motion in the
  video is not representative of a device's frame rate, and fps was not measured in these
  runs.
- The auto-calibration status shows "0.0 px" next to "needs a check". The proposals'
  `reprojection_error_px` is about 1e-4 px (they are template fits, exact by construction),
  so that number says nothing about whether the fit is right. The score (0.61 / 0.888 vs
  0.90) is what refused them.
- **No shot in the basketball cut.** The real pipeline found no shot in Kennesaw 130–220 s,
  although the scene agent's full 240 s run found one at 133 s. This cut was calibrated
  from the UI clicks (3.3 px) rather than the landmarks file, and is a 20 fps H.264
  re-encode. So the shot chart is empty and "All shots" has no clips; the TV says so
  correctly.
- **Likely false positives.** 14 volleyball blocks in 90 s is implausible; volleyball
  event precision is known to be low (docs/progress.md).

## Harness changes for the real runs

- `scripts/record-e2e.sh`: `REC_REAL=basketball|volleyball` cuts the clip, copies its
  landmarks, sets `REPLAY_WORKER_STAGES`, serves an empty library, writes
  `out-real-<sport>/` (plus the upload's `worker.jsonl`), and passes the real captions to
  the compositor.
- `apps/tv/e2e-recording/replay-e2e.spec.ts`: `REPLAY_REC_REAL` / `REPLAY_REC_SPORT`; the
  hand walk includes optional landmarks; the shared beats (select/follow, review, rallies)
  are functions; there are six new Free view beats, plus highlights and heatmap beats; key
  frames go to `frames/`.
- `scripts/record_e2e_compose.py`: `--title` and `--caveat`.
- `make record-e2e-real SPORT=…`.
- `services/api`: `REPLAY_WORKER_STAGES` (config, pipeline adapter, a test).
- `scripts/box-demo.sh`: passes `REPLAY_WORKER_STAGES` to the API window.

The synthetic `make record-e2e` path was restructured, not changed in intent. It was not
re-recorded in this run.

## Bugs found while recording the real runs

- **Product gap (fixed):** the API had no way to run the opt-in replay and scene stages on
  an upload (`pipeline_adapter.run` always ran the worker's default DAG). So Free view
  could never appear on a game uploaded from the phone. `REPLAY_WORKER_STAGES` adds them.
- **Spec bugs (fixed):**
  - The spec assumed a non-empty library.
  - It read the play id from the page URL, but the TV navigates in memory, so the URL is
    still `/tv/<game>` on the Replay screen. It now reads the focused replay card's
    `data-play-id`.
  - The recorded basketball beat 15 caption reads "detected no all shots"; the wording was
    fixed in the spec after the run.
- No TV or Free view bug: every Free view assertion passed on both sports at the first run
  where the spec itself was right.
