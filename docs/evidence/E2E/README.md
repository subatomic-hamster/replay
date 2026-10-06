# E2E: recorded end-to-end run (TV web build + phone companion)

`replay-e2e.mp4` (1280×720, H.264, 25 fps, 3:25, 4.2 MB) is a screen recording of an
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

| # | beat | video time | result | what is asserted |
|---|---|---|---|---|
| 1 | TV settings: test connection | 0:02–0:09 | PASS | Library → Up → Settings (D-69); address = the build default; Test connection → `Connected · 2 games` |
| 2 | Phone: create game + upload | 0:09–0:14 | PASS | game created, the clip uploaded (`upload-done`) |
| 3 | Phone: calibrate | 0:14–0:27 | PASS | auto-calibration proposed 9 points but scored 0.83 < 0.90: the weak-fit note shows and **Accept is disabled** (D-72). The override box is not ticked; the landmarks are placed by hand in the profile's order (`GET /sports`) at the clip's true pixels (`landmarks.json` from `courtcam synth`); `calib-error` ok; Start processing enabled |
| 4 | Phone: process (real worker pipeline) | 0:27–0:46 | PASS | a stage `running`, then status `ready`. Worker log: 15 tasks, all cache misses (YOLO detect 7.2 s, pose 6.4 s); the game came out with 10 players, 2 shots, 2 possession changes |
| 5 | TV: the uploaded game plays | 0:46–0:53 | PASS | its card is in the TV library; Enter → plays past 2 s |
| 6 | Library → Watch | 0:53–1:02 | PASS | D-pad to the basketball demo card; hype meter and event markers on the scrubber; plays |
| 7 | Select → follow → spotlight → inset | 1:02–1:14 | PASS | pause → select boxes; Right ×2, Enter → follow-cam; Playback ▸ Spotlight → spotlight overlay; court inset with > 1 player dot; Back → wide |
| 8 | Broadcast + commentary | 1:14–1:25 | PASS | Broadcast → the `broadcast` rendition loads; Commentary → a caption appears while playing |
| 9 | Pair phone + Clip that | 1:25–1:47 | PASS | Pair phone → 4-digit code; the phone connects with it; the TV's now-playing reaches the phone; past the end of a play the phone taps **Clip that** → `Clip saved · 0:13.0–0:17.4` on the phone and the same toast on the TV; Game ▸ Clips has the `tap` clip; D-pad trim −0.5 s / +0.5 s → `Trim saved` |
| 10 | 9:16 share | 1:47–2:00 | PASS | Share 9:16 on that clip → export `done`, the portrait preview video loads (burned-in `#p5 · STEAL` caption) |
| 11 | Replay angles A/B/C | 2:00–2:30 | PASS | Game ▸ Replays → first replay; paused, Right through all 11 angles; the tier badges seen are exactly Real video (A), 2.5D (B), 3D (C) |
| 12 | Highlights + search | 2:30–2:51 | PASS | Highlights → `All shots` → a reel; Search → `Type a search…` → "steal" typed on the on-screen keyboard with the arrows → results (SigLIP index: "No match · ranked by similarity", steal plays ranked first) |
| 13 | Review + box score | 2:51–2:57 | PASS | `auto-detected` label, shot chart, box-score rows; Enter answers the first review question and the queue moves on (`PATCH /events/e_0000`) |
| 14 | Player profile + card | 2:57–3:10 | PASS | the phone creates a profile (name only; no face data, so no consent step is involved); on the TV, select mode → Players ▸ Link profile → that profile → toast `Linked to …`; the phone shows "Linked in 1 game"; Library → Players → the profile → Card → Render → the card PNG loads with the profile's name |
| 15 | Pickleball rallies + condensed | 3:10–3:24 | PASS | pickleball demo → Game ▸ Rallies → rows; Longest → plays with the rally counter; Condensed game → plays with `RALLY n / N` |

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
