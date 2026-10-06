# Overnight build report: Replay (2026-10-05 23:46 to 2026-10-06 ~07:45 EDT)

This is the final deliverable of the unattended overnight build. Every number below comes from
a file in this repo (cited) or from a read-only command on hfbox (section 11). "Not measured"
means that no run produced the number. Where `docs/progress.md` records a correction, the
re-measured value is used and the earlier claim is shown next to it. Git range: `e35533e..e4b79bf`,
39 commits. The first overnight commit is 5d9e44d (00:48 EDT) and the last is e4b79bf (06:22 EDT).

## 1. Summary

- **What Replay is:** you film a court-sports game with one phone on a tripod. On the box, a
  pipeline turns it into a TV experience: wide/select/follow viewing, an auto-directed
  "broadcast" rendition with graphics, slow-motion replays and grounded commentary, "Replay,
  clip that" clips, virtual replay angles (Tiers A/B/C), highlights, search, profiles and
  post-game review. Basketball comes first; pickleball, badminton and volleyball run through
  sport profiles. The computer-vision core is the MIT library `courtcam/`.
- **What works end to end:** `make demo` builds two synthetic games through the worker and
  serves the real API, the TV app's web build and the phone companion. The demo games have the
  broadcast with narration, 11 replay angles per highlight, hype, condensed game and a 9:16 export.
  `scripts/box-test.sh` is all green (docs/progress.md:164). The Fire TV APKs build (box only).
- **Headline caveats:**
  - Validation is mostly synthetic. Real footage was measured only on a few local or CC clips,
    mostly not re-measured.
  - The Fire TV APK has never run on a device or an emulator.
  - Basketball tracking is weak on small, bunched players (synthetic IDF1 0.31 / 0.25).
  - "Clip that" gesture works on clean poses (synthetic GT poses 22/22, 0 false, after the D-68 fix
    of a D-61 regression) but not on far players: ViTPose 9/22, default YOLO pose 0/22.
  - Real shot recall is 3 of 6 on Kennesaw.
  - Nothing ran on AWS.
  - The app carries the AGPL through `courtcam[yolo]`.

## 2. What works, and how to see it

| what | command / location | notes |
|---|---|---|
| Demo (build + serve) | `make demo` (laptop; syncs to `BOX_DIR`, default `/workspace/wt/replay-dev`) | Builds `g_demo_basketball` + `g_demo_pickleball` (synthetic, 60 s, seed 11). Cold 551 s, warm 222 s on a shared box; about 7.5 min cold and about 10 s warm on an idle box (docs/perf.md §1). The build log is `<copy>/data/demo-build.log`. |
| View the demo | `make demo-tunnel` (second terminal), then TV `http://localhost:5190/`, phone `http://localhost:5191/companion` | Keys: arrows = D-pad, Enter = select, Esc = back. Pair the phone with the 4-digit code the TV shows (Makefile:43-47). |
| Stop | `make demo-stop` | Kills the box tmux session `replay-demo` (scripts/box-demo.sh:142). |
| Tests | `make test` (runs `scripts/box-test.sh <copy>` on the box) | Steps: ruff, then courtcam, api, worker and render pytest, then dag-drift, infra `cdk synth`, web tsc/eslint and Playwright chromium+live. **apps/tv is not in box-test.sh or CI.** Run it separately: `cd apps/tv && pnpm exec tsc --noEmit && pnpm exec eslint . && pnpm exec playwright test --project=tv`. |
| Last green run | docs/progress.md:164 | Staged snapshot, ALL GREEN: courtcam 184, api 220 + 1 skipped, worker 24, render 49, web Playwright 100. apps/tv: tsc/eslint clean, Playwright tv 48 + 1 skipped. |
| Worker CLI (box) | `python -m replay_worker run <clip> --out <game> [--detector synthetic] [--sport pickleball --variant doubles] --stages <list> [--set key=value]` | Also `status`, `perf` and `dag` (README.md:155). Examples are in docs/evidence/M6/README.md:36-49, M9/README.md:90-97 and docs/perf.md §2. Run on the box under `flock /workspace/wt/replay-env/.cpu.lock` with `PYTHONPATH=<copy>/courtcam:<copy>/services/api:<copy>/services/worker:<copy>/render`. |
| courtcam CLI | `python -m courtcam.cli synth --sport basketball --variant full --duration 90 --seed 11 --out <dir>`; `courtcam eval --gt <clip>/ground_truth.json --out <run>` | Synthetic generator and MOT eval (docs/evidence/M1/README.md). |
| Re-run the M1/M4/M5 metrics | `docs/evidence/M4/eval/run_metrics.sh gen\|gt\|yolo\|vit\|mot`, then `agg.py`, then `split.py` | docs/evidence/M4/README.md:27-37 |
| APKs | **Box only:** `/workspace/wt/replay-tv-scratch/apk/` holds `replay-tv-0.1.0-release.apk` (30.6 MB), `replay-tv-0.1.0-release-texture.apk` (30.6 MB, with the TextureView patch) and `replay-tv-0.1.0-debug.apk` (61.2 MB). | Universal arm64-v8a + armeabi-v7a, minSdk 24, targetSdk 36, leanback launcher. The release APK is signed with the debug keystore (docs/progress.md:140-143). |
| TV web build (dev) | `cd apps/tv && pnpm install && VITE_MOCK_API=1 pnpm web` (mock API) or `VITE_REPLAY_API_BASE=<api>` | README.md:64-71 |
| Phone companion (dev) | `apps/web`: `/companion` (pair, tap-to-clip, search, voice query), `/upload` (upload + calibrate), phone profiles | Served on :5191 by `make demo` |

## 3. Feature status (brief items 1-28)

The condensed brief numbers items 1-10 and 21-28. Items 11-20 are numbered here in the brief's
order: the 3D tiers, ball arcs, angle switching, then the "clip that" triggers. Status comes from
docs/progress.md.

| # | feature | status | where (code) | evidence | key metric (source) | caveat |
|---|---|---|---|---|---|---|
| 1 | Wide playback + event markers | done (web build) | apps/tv/src/screens/Watch.tsx, components/SeekBar.tsx | M3/tv-synthetic/02-watch-wide.png | Playwright tv 48 + 1 skipped (progress.md:164) | Not run on a device |
| 2 | Select mode (D-pad, overlap cycling) | done (web build) | packages/tv-core/src/spatial.ts, apps/tv/src/components/SelectOverlay.tsx | M3/tv-synthetic/03-select.png | same | same |
| 3 | Follow mode (spring smoothing, lead, clamp) | done (web); native unverified | courtcam/courtcam/croppath.py, packages/tv-core/src/follow.ts, apps/tv/src/components/FollowFrame.tsx, apps/tv/patches/react-native-video@6.19.3.patch | M3/tv-synthetic/04-follow.png, M13/tv-demo/04-follow.png | Follow-cam jitter 2.12 → 0.64 px/frame² on Kennesaw, 1.37 → 0.51 on synthetic (M6/README.md:25-29) | The TextureView transform and its GPU cost are unverified on hardware (D-64) |
| 4 | Spotlight + court inset | done (web build) | apps/tv/src/components/CourtInset.tsx, Watch.tsx | M3/tv-synthetic/05-follow-spotlight.png | not measured | Not run on a device |
| 5 | Tagging + identity correction | done | apps/tv TextEntryDialog + Review identity questions; services/api/replay_api/edits.py (D-63) | M3/tv-synthetic/07-tag-dialog.png, M13-ui/tv-synthetic-live/08 | Corrections survive worker re-runs (progress.md:134) | Player and clip patches are anchored by id only. The tag-dialog evidence spec failed against the menu restructure (M13/README.md:18-22) |
| 6 | Auto-director cut list | done | render/replay_render/director.py, services/worker/replay_worker/stages/broadcast.py | M6/cuts_synthetic_gt.json, cuts_synthetic_pipeline.json | Jitter on Kennesaw: wide 14.5 → 0.072, tight 51.3 → 0.42 px/frame² (progress.md:61) | — |
| 7 | Broadcast graphics + score from detected makes | partial | render/replay_render/graphics.py, compositor.py; courtcam events (2/3 pts); `GET/POST /games/{id}/score` | M6/broadcast_synthetic_basketball_90s.mp4 (events from synthetic GT, labelled), M13/demo_broadcast_replay.gif | 2 vs 3 points right 18/18 (GT poses) and 14/21 (YOLO) (M4/README.md:52) | The M6 evidence used GT events because the pipeline detected no makes on that clip (M6/README.md:14-21). Real scores stay provisional (progress.md:64) |
| 8 | Slow-mo replays + telestrator | done | render/replay_render/compositor.py | M6/stills/ | Broadcast stage 15.3 s for 60 s of video (perf.md:73-74) | Slow motion repeats frames. No shot arcs without a pinhole fit, e.g. on panoramic footage (progress.md:64) |
| 9 | Grounded commentary + TTS | done | services/api/replay_api/narrate/{commentary,grounding}.py, worker stages/narrate.py, providers/{tts,llm,_runner}.py | M7/synthetic_bb90_narrated.mp4, grounding_*.json | Template 28/28 grounded, LLM 26/28 accepted; Kokoro 0.19 s/line on GPU (progress.md:77) | The runner reloads the model per call. The demo uses the template text only. TTS needs `REPLAY_MODEL_VENVS` |
| 10 | Advice | done | narrate/advice.py, apps/tv/src/screens/Advice.tsx | M7/advice_*.json, M13-ui/…/07 | Templates grounded 18/18; LLM accepted 7/10 and 8/8 (M7/README.md:72-77) | Built from its own stats only, with no biomechanics |
| 11 | Tier A virtual cameras | done | render/replay_render/virtual/tiera.py | M8/*_angles.jpg | 5-8 ms/frame on CPU (M8/README.md:92) | — |
| 12 | Tier B 2.5D cutouts | done (labelled approximation) | virtual/tierb.py, virtual/segment.py, courtcam/courtcam/plate.py | M8/ (9 highlights × 6 angles) | Held-out player IoU 0.35-0.80; 32-62 ms/frame; SAM about 26 ms per object per frame (tier-d.md:21, progress.md:85) | Plate ghosts, void floor, thin side-on billboards |
| 13 | Tier C stylized 3D avatars | done (opt-in stages) | render/replay_render/avatars/ | M9/ (make/miss sheets, overhead GIF, POV) | MotionBERT MPJPE 125-139 mm (progress.md:101) | The outcome is never automatic. Jumps are flattened. Kennesaw was not attempted. MotionBERT weights are research-grade |
| 14 | Tier D research | experiments only | experiments/tierd-{pointmaps,vggt-static,dynamic}/ | M12/, docs/tier-d.md | See §6 | Not shipped (D-62) |
| 15 | Ball arcs | partial | Tier B/C geometry and the telestrator arc | M9/synth_bb_pl_0002_make_overhead.gif | Arcs are modelled (shooter to the 3.05 m rim), not tracked | No ball model outside basketball (progress.md:88) |
| 16 | TV angle switching | done (web); native untested | apps/tv/src/screens/Replay.tsx, packages/tv-core/src/replays.ts | M8/tv/ | Media time held within 8 ms through the real API (progress.md:85) | The native loop/src-swap path is untested on a device (D-57) |
| 17 | Gesture trigger (X overhead) | partial | courtcam/courtcam/triggers.py, pose.py | M5/README.md, M5/accuracy_*_on_synthetic_x_holds.png | GT poses 22/22, 0 FP after D-68 (was 16 TP / 26 FP / 6 FN after D-61); YOLO pose 0/22; ViTPose 9/22 at P 1.00 (M5/metrics.json) | Far players (≤ 56 px) mostly missed; synthetic only; real footage 0 false triggers in 480 s |
| 18 | Voice trigger | partial | courtcam triggers (whisper-small, `courtcam[asr]`) | M5/trigger_voice_*.mp4 (older render) | 37/37; named subject 18/18; clip right 30/37 (M5/metrics.json) | Untested on real game audio. No voice-enrollment route (field always false). No wake word shipped |
| 19 | Tap trigger (phone) | done | `POST /games/{id}/triggers`, apps/web/src/screens/Companion.tsx | M13-ui/tv-synthetic-live/03 | Clip right 10/14 (GT poses), 9/14 (YOLO) (M5/metrics.json) | Misses are missed plays (D-50) |
| 20 | Play grammars, trigger resolution, trim UI | done (basketball + net sports) | courtcam/courtcam/plays.py, sports/*.yaml `plays:`; apps/tv/src/screens/Clips.tsx | M4/timeline_*.png, M13-ui/…/04 | Resolution 73/73 on GT plays; plays P 0.83 / R 0.79 (M4/metrics.json) | Volleyball attack P 0.30 / R 0.50. Pickleball doubles second-server rule wrong (D-61) |
| 21 | Profiles, cards, cross-game links, opt-in faces | done (voice enrollment not done) | services/api/replay_api/profiles/, providers/{profiles,face}.py, apps/tv/src/screens/{Players,Profile}.tsx, apps/web/src/screens/PhoneProfiles.tsx | M10/, M10-ui/ | Titles grounded 3/3; card JSON deterministic 3/3; face metrics in §5 | Face enrollment was never exercised end to end through the UI with real models (progress.md:151) |
| 22 | Highlights + LLM structured-filter query | done | apps/tv/src/screens/Highlights.tsx, providers/query.py, narrate/routes.py | M7/queries_half_gt.json | Query LLM median 0.58 s; "crowd going wild" correctly gives no filter (progress.md:77) | The Highlights reel plays wide only (progress.md:41) |
| 23 | Semantic search | partial | narrate/search.py, providers/embeddings.py, worker `embeddings` + `search_index` | M7/search_bb90.json | Only qualitative ranking checks on 3 queries; precision/recall not measured | SigLIP is weak on synthetic frames. Worker-made games have no index by default (progress.md:112) |
| 24 | Net-sport extras (condensed, rally browser, longest) | done | render/replay_render/condensed.py, apps/tv/src/screens/Rallies.tsx | M11/*_condensed.mp4, *_rallies.json | Badminton 90 → 59.8 s; real badminton 240 → 87.5 s (M11/README.md) | Rally P/R is lower on current code (§5) |
| 25 | Hype detection + meter | done | render/replay_render/hype.py | M11/*_hype.png, M13-ui/…/02 | Synthetic P/R in §5 | Untested on real crowd noise; weights are heuristic (D-45) |
| 26 | Post-game review | done | render/replay_render/review.py, services/api/replay_api/stats.py, apps/tv/src/screens/Review.tsx | M11/basketball_shot_chart.png, *_box_score.json | Distance median error 0.7-4.9 % (M11/README.md:28-29) | Box score labelled "auto-detected" |
| 27 | 9:16 export with captions | done | render/replay_render/vertical.py | M11/*_vertical.*, M13-ui/…/05 | About 300 fps at 540x960 (M11/metrics.json) | Captions are deterministic (no LLM) |
| 28 | Phone web companion | partial | apps/web/src/screens/{Upload,Companion,PhoneProfiles,Clips}.tsx | M10-ui/phone-mock/ | not measured | Height-landmark clicking in the phone UI was not verified for this report. The voice query uses the browser Web Speech API (Chrome/Edge only). Downloads are a link on the Clips screen |

## 4. Milestones

| milestone | commits | evidence | one line |
|---|---|---|---|
| M0 recon + scaffold | 5d9e44d, 8a452ba | docs/evidence/M2/worker-cache-synthetic.txt, docs/compute.md | Worker DAG + content-hash cache, provider registry with AWS stubs, CDK skeleton, CI, `make sync\|test\|demo` |
| M1 synthetic generator + tracking metrics | 7734518, d9936f9, 96bae63 | M1/ | 5 synthetic scenes with full GT, own CLEAR-MOT/IDF1, research and licence pass |
| M2 API + local worker + uploader | no separate progress entry; folded into M0 (5d9e44d) and Phase 1 | M2/ | The API and uploader predate the overnight build; the worker landed in M0 |
| M3 Fire TV client | 93524eb, 928ba63; addendum 168c2e7, 5b5bd2b, 2f8ad20, f340746 | M3/tv-synthetic/ | react-native-tvos app at parity with the web TV, APK builds, native playback hardening, TextureView patch |
| M4 events + plays | 4c6c02a, e45e0fa | M4/ | Pose and audio stages, shots/possession/rallies/contacts, grammars, score |
| M5 "Replay, clip that" | 4c6c02a, e45e0fa (TV trim UI in 26bc0ef) | M5/ | Gesture/voice/tap triggers resolve to the play that just ended |
| M6 broadcast mode | 6dd1e47, ecde80f (worker stages in 4c6c02a) | M6/ | Auto-director, graphics, 0.5× replays + telestrator, audio mix |
| M7 commentary, advice, query, search | e929293, 3157e38 | M7/ | Grounded templates + checked LLM paraphrase, Kokoro TTS, SigLIP search |
| M8 Tier B + angle switching | c5e898f, 3cc249f (+ fix 4ad6a0c) | M8/ | Full calibration, plate, SAM 2.1, Tier A/B renders, Replay screen |
| M9 Tier C | 62d651a, 60f140e | M9/ | MotionBERT-lifted capsule avatars, 5 angles incl. overhead + POV |
| M10 profiles + faces | 48ad9a5, f3333d6; UI 9a7ef5b, f340746 | M10/, M10-ui/ | Profiles, career stats with edits, cards, reels, opt-in faces; TV/phone screens |
| M11 discovery | 0c60be2, 529f4ec (API/worker in 4c6c02a) | M11/ | Hype, condensed, rally browser, 9:16, shot chart, box score, review queue |
| Accuracy pass | 35e7909, 011f452 | M4/, M5/ "accuracy pass" sections | Shot confirm, relaxed X rule (D-61), ViTPose opt-in, point winners |
| M12 Tier D | ea7f1df, 3864bbf | M12/, docs/tier-d.md | MoGe-2, VGGT, dynamic-splat feasibility |
| M13 polish | 26bc0ef + 60f140e (TV integration), 5c152b2 + 28a9b4b (backend fixes, D-63), fc22eed + 1b7f300 (extras, `make demo`, perf, README), f001b43 + 752bd6c (D-67), e4b79bf (re-measured metrics), 2a5d085 + 50c0cdf (report, doc fixes), 9aa0e00 (gesture fix, D-68) | M13/, M13-ui/, docs/perf.md | TV/web for M5-M11, edits overlay, packaging, demo, perf, demo script, this report |

## 5. Metrics

All of these are synthetic unless the row says otherwise. The M1/M4/M5 numbers were re-measured
on 2026-10-06 on "HEAD 5b5bd2b plus uncommitted WIP" (M4/metrics.json `code_state`), not on
HEAD e4b79bf. After that, f001b43 changed `build_plays`, which now skips dismissed events. The
numbers were not re-run on HEAD.

### 5.1 Tracking (players, YOLO11m + BoT-SORT; M1/metrics.json, M1/README.md)

| scene (seed 7) | MOTA | IDF1 | ID switches | court err median (m) | GT detector MOTA / IDF1 |
|---|---|---|---|---|---|
| basketball half | 0.64 | 0.31 | 122 | 0.39 | 1.00 / 1.00 |
| basketball full | 0.43 | 0.25 | 157 | 0.47 | 1.00 / 1.00 |
| pickleball doubles | 0.98 | 0.99 | 0 | 0.27 | 1.00 / 1.00 |
| badminton doubles | 0.99 | 1.00 | 0 | 0.26 | 1.00 / 1.00 |
| volleyball indoor | 0.91 | 0.75 | 37 | 0.32 | 1.00 / 1.00 |

- **Claimed earlier vs re-measured:** the basketball values were originally logged higher
  ("IDF1 0.40–0.49"); progress.md now carries the re-measured 0.31 and 0.25 (fixed in 50c0cdf).
- **Real footage (local):** Kennesaw 150-210 s has about 38 visible ID changes across 19 ids
  (progress.md:118). ReID, tighter BoT-SORT, 1280 px detection and gated merging all failed to
  help.

### 5.2 Events and plays (9 clips, seeds 7 + 11; M4/metrics.json)

| item | synthetic detector + GT poses | YOLO detect + YOLO pose | ViTPose (`--pose vit`) |
|---|---|---|---|
| shots (27) | P 1.00 / R 0.67 (18 TP) | P 1.00 / R 0.78 (21 TP) | P 1.00 / R 0.70 (19 TP) |
| 2 vs 3 points right | 18/18 | 14/21 | 16/19 |
| possession change | P 0.83 / R 0.80 | P 0.76 / R 0.73 | P 0.76 / R 0.73 |
| plays | P 0.83 / R 0.79 | P 0.80 / R 0.78 | not measured |
| contacts | P 0.91 / R 0.89 | P 0.91 / R 0.90 | not measured |
| rallies | P 0.73 / R 0.67 | P 0.75 / R 0.69 | not measured |
| points | P 0.79 / R 0.73 | P 0.77 / R 0.71 | P 0.77 / R 0.71 |
| point `winner_side` right / known | 33/34 | 27/33 | 24/33 |
| volleyball attack | P 0.30 / R 0.50 | P 0.10 / R 0.17 | not measured |

- **Claimed earlier vs re-measured (progress.md:46):**
  - GT-pose shots: P 0.96 / R 0.85 at M4, now P 1.00 / R 0.67.
  - YOLO rallies: P 0.97 / R 0.88 at M4, now P 0.75 / R 0.69.
  - The cause was not investigated.
  - The accuracy pass's "before" values (shots 5/27) are history and cannot be reproduced.
- **Real footage (local, not re-measured):**
  - Badminton 240 s rallies: P 1.00 / R 0.86 (motion-only).
  - Kennesaw shots: precision 0.5 → 1.0 after the accuracy pass, but recall fell from 5/6 to 3/6
    (progress.md:117).

### 5.3 "Replay, clip that" triggers (M5/metrics.json)

| trigger | GT poses | YOLO pose | ViTPose |
|---|---|---|---|
| gesture (22 truth) | 22 TP / 0 FP / 0 FN, P 1.00 / R 1.00; who 22/22; clip right 16/22 | 0/22 | 9 TP / 0 FP, P 1.00 / R 0.41; who 9/9; clip right 8 |
| voice (37, whisper-small) | 37/37; subject 18/18; clip right 30/37 | 37/37; subject 16/18; clip right 31/37 | — |
| tap (14) | clip right 10/14 | clip right 9/14 | — |
| resolution rule on GT plays | 73/73 | — | — |

- **Claimed earlier vs re-measured:**
  - Gesture with GT poses was 22/22 with 0 FP at M5. The D-61 relaxed rule regressed it to
    16 TP / 26 FP / 6 FN (P 0.38 / R 0.73; all 26 false triggers were synthetic jump shots). D-68
    restored 22/22 with 0 FP without changing ViTPose (9/22) or real footage (0 false in 480 s);
    the before/after is in M5/README.md.
  - Whisper: the earlier "8/9 crowd-noise mixes" claim is superseded by 37/37 lines heard in 9/9
    clips. The script behind the old claim was not found (M1/README.md:38-39).
- **Real footage:** 0 false gesture triggers in 480 s (progress.md:117). Real gesture and voice
  recall: not measured.

### 5.4 Calibration (M8/README.md, 20 noise seeds, 1 px click noise, medians)

| scene | focal err % | rotation err ° | camera position err m (p90) |
|---|---|---|---|
| basketball half / full | 0.62-0.64 / 0.49-0.50 | 0.27-0.28 / 0.21 | 0.08 (0.18) / 0.07-0.08 (0.11-0.12) |
| pickleball / badminton / volleyball | 0.31-0.32 / 0.21-0.25 / 0.28-0.35 | 0.09-0.14 | 0.03-0.06 |
| with k1 −0.2: basketball half / volleyball | 1.93-1.95 / 0.63-0.73 | 0.27-0.29 / 0.18 | 0.56 (0.70) / 0.19-0.20 |

On real clips the floor reprojection is 0.03-2.64 px. The held-out hoop is 53-92 px off on the
wide or panoramic basketball rigs (M8/README.md:39-55).

### 5.5 Tier C (M9/README.md, synthetic, 12 joints, all players)

| play | method | MPJPE mm | pelvis-aligned mm | jitter m/s² (before → after) | foot slide cm/s | height err |
|---|---|---|---|---|---|---|
| pl_0001 | MotionBERT | 128 → 125 | 75 → 74 | 10.0 → 4.0 | 25.2 → 0.3 | 2 cm |
| pl_0001 | analytic | 171 → 172 | 174 → 174 | 15.3 → 5.4 | 31.0 → 0.4 | 2 cm |
| pl_0002 | MotionBERT | 141 → 139 | 74 → 75 | 12.8 → 5.1 | 28.5 → 0.9 | 3 cm |
| pl_0002 | analytic | 185 → 187 | 174 → 175 | 16.7 → 6.2 | 28.8 → 1.1 | 3 cm |

For comparison, the GT motion's own jitter is 4.5-5.6 m/s². On the CC pickleball clip (YOLO
keypoints, no GT), jitter went from 39-56 to 9-15 m/s² and foot slide from 59-69 to 0.2-1.4 cm/s.

### 5.6 Commentary, advice, query, cards (M7/README.md, M10/README.md)

| item | result |
|---|---|
| Commentary grounding, 28 synthetic plays | template 28/28; LLM paraphrase accepted 26/28 (both rejections fell back to the template); LLM median 0.267 s/play |
| Kennesaw (local) | template 32/32; LLM 30/32 |
| Commentary stage on g_bb90 | 10/10 grounded, 10/10 LLM accepted, 16.2 s |
| Kokoro TTS | GPU median 0.185 s/line (RTF 0.085); CPU median 0.346 s/line |
| Advice | templates 10/10 and 8/8 grounded; LLM accepted 7/10 and 8/8 |
| Query LLM | median 0.581 s; 5 example queries resolved as listed (M7/README.md:65-70) |
| Card titles | grounded 3/3 (template), LLM 3/3; JSON byte-identical on rebuild 3/3; 0.5-1.1 s per profile |

### 5.7 Search (M7/README.md:79-89)

Search was checked only qualitatively: "a steal" and "rebound" rank their two plays first, and
"Player 4 scores" puts that player's basket first. Precision/recall, MRR and other quantitative
metrics were not measured. Index build took 107 s for 10 plays. With batched embeddings
(D-63) it is 82.1 → 10.5 s on GPU and 60.8 → 11.0 s on CPU for 10 plays (progress.md:134).

### 5.8 Faces (M10/README.md, CC BY footage, opt-in path)

| item | result |
|---|---|
| Usable faces (≥ 24 px) per person box | 2.8 % (badminton US nationals) to 14.8 % (fisheye net-post); synthetic mannequins 0 % |
| Hand-labelled fisheye clip at 0.45 (tuning set, not held out) | genuine faces matched 63.5 % / 72.4 %; unenrolled 3.5 % / 2.9 %; genuine windows suggested 39/45; unenrolled windows 0/47 |
| Same clip at OpenCV's 0.363 | unenrolled windows suggested 2/47 |
| End to end `match_game` | 48 players checked in 11.3 s; suggested only the enrolled player's two tracks |
| Pseudo-labelled clips | genuine 4/36 (pickleball), 5/9 (badminton); these are lower bounds |

### 5.9 Hype, condensed, vertical, distance (M11/metrics.json, M11/README.md)

| item | result |
|---|---|
| Hype vs GT | basketball P 0.857 / R 1.0 (7 candidates, 6 makes); badminton P 1.0 / R 0.889; pickleball P 1.0 / R 1.0 |
| Distance covered, median error | basketball 0.7 % (max 1.6 %), badminton 4.9 %, pickleball 1.8 % |
| Condensed | badminton 90 → 59.8 s at 530 fps; pickleball 90 → 65.6 s at 533 fps; real badminton (local) 240 → 87.5 s in 10.6 s |
| Vertical 9:16 | 6.4-13.9 s clips in 0.6-1.4 s (about 300 fps); jitter rms 0.09-0.24 px/frame² |

### 5.10 Perf (docs/perf.md, docs/compute.md)

| run | cold | warm |
|---|---|---|
| `make demo` total (shared box) | 551 s (+117 s synth); worker compute 332 s; about 210 s CPU-lock wait | 222 s (worker 0.5 s; the rest is lock wait) |
| `make demo` on an idle box (derived in perf.md:52-54) | about 7.5 min | about 10 s |
| Basketball pass 1, 64 misses | 304.3 s; SAM 2.1 segment 30 / 62 / 68 s per play (160 s in total); Tier C about 66 s per play | 0.3 s (64 hits) |
| CC BY pickleball 90 s, real models | 92.8 s (analysis to `plays` about 40 s, 2.2× real time) | 1.4 s (26/26 hits) |
| Kennesaw 240 s, courtcam stages (local) | 76.4 s (3.1× real time; detect 50.9 s) | 1.4 s |
| YOLO11n / YOLO11m model only (2560×960) | 8.1 / 10.7 ms/frame | — |
| Tier B per frame / Tier A per frame | 32-62 ms / 5-8 ms | — |
| `tierc_scene` per play / `tierc` per angle | 8-12 s / 3.6-15 s | — |

The following were not measured (perf.md:20-25):

- anything on a Fire TV device or emulator;
- a 10-40 min game, or any 4K input;
- real-footage Tier A/B/C replays and commentary end to end;
- concurrent uploads.

The brief's "10-min 4K game well under real time" target is therefore unmeasured.

### 5.11 Jitter (M6/README.md:23-29)

| camera | synthetic | Kennesaw 150-240 s (local) |
|---|---|---|
| wide | 0.63 → 0.022 | 14.50 → 0.072 |
| tight | 25.28 → 0.25 | 51.32 → 0.42 |
| follow-cam (courtcam croppath) | 1.37 → 0.51 | 2.12 → 0.64 |

## 6. 3D tiers (docs/tier-d.md, M8, M9, M12)

| tier | what | quality | cost per 8 s highlight | licence | verdict |
|---|---|---|---|---|---|
| A | Virtual cameras (wide, follow, tight) on the real video | Real pixels, no new viewpoint | 5-8 ms/frame on CPU | own code | Ships |
| B | 2.5D: plate floor + backdrop planes, SAM 2.1 billboards on tracked feet (D-54) | Held-out synthetic: player IoU 0.80 (real view) to 0.35 (orbit −60°); floor PSNR 21-28 dB; position 0.18 m | SAM about 26 ms per object per frame (about 1 GPU-min for 10 players) + 32-62 ms/frame CPU | SAM 2.1 Apache-2.0 | Ships, labelled "TIER B 2.5D / flat player cutouts" |
| C | Capsule mannequins from MotionBERT 3D joints on the calibrated court (D-59) | MPJPE 125-139 mm; height ≤ 3 cm; stylised | 8-12 s per scene + 3.6-15 s per angle | MotionBERT Apache-2.0 code and weights, trained on Human3.6M (academic): optional; analytic fallback is licence-clean | Ships as opt-in stages, labelled "3D reconstruction - stylized" |
| D-A raw | MoGe-2 per-frame point clouds | Held-out IoU 0.16-0.75; players 0.62 m off; 0.7 m depth smear | 0.14 s/frame GPU, 3.2 GB | MIT | Not for players |
| D-A hybrid | Tier B floor and positions + MoGe relief | About equal to B: IoU 0.38-0.75, floor 21-24.6 dB; real 3D hoop/net/fence | as raw | MIT | Worth one later stage, for the static plate only (D-62) |
| D-B | VGGT-1B multi-frame static court | ≤ 1.4 % off-frustum coverage (no parallax from a tripod) | 5.7 s per 32 frames, 8.8 GB | CC-BY-NC weights | Dead end; licence-blocked |
| D-C | Dynamic splats / 4D | Not run: `gsplat: No CUDA toolkit found` | n/a | gsplat Apache-2.0; others NC or NVIDIA-only | Dead end on this box (no HIP SDK) |

## 7. Research summary

**Chosen** (docs/licenses.md, D-39, D-40, D-58, D-61):

| use | choice | licence |
|---|---|---|
| Detection, pose, tracking | YOLO11m / YOLO11m-pose + BoT-SORT (ultralytics) | AGPL-3.0; optional `courtcam[yolo]` extra (D-66) |
| Opt-in pose | ViTPose-B `usyd-community/vitpose-base-simple` | Apache-2.0 (D-61; no licenses.md row) |
| Segmentation | SAM 2.1 hiera-small through `transformers.Sam2VideoModel`, bf16 | Apache-2.0 |
| ASR | Whisper-small through transformers | MIT |
| TTS | Kokoro-82M | Apache-2.0 (its espeak-ng G2P fallback is GPL-3.0, licenses.md:52) |
| LLM | llama.cpp HIP + Qwen3-4B-Instruct-2507 Q4_K_M, json_schema output + deterministic validator | MIT / Apache-2.0 |
| Embeddings | SigLIP ViT-B-16 through open_clip | Apache-2.0 / MIT |
| Speaker | ECAPA (speechbrain) | Apache-2.0; VoxCeleb data flag |
| 3D lift | MotionBERT | research-grade weights, replay-side only |
| Faces | YuNet + SFace through OpenCV | MIT / Apache-2.0; SFace training data undocumented |
| Font | Barlow Condensed | OFL 1.1 |

**Rejected, with reasons:**

| rejected | reason |
|---|---|
| SMPL / SMPL-X, HMR2.0/4D-Humans, WHAM, GVHMR | Registration or non-commercial licences |
| insightface | Non-commercial weights |
| co-tracker, monst3r/dust3r, Inria gaussian-splatting, 4DGaussians | Non-commercial |
| VGGT-1B | CC-BY-NC; the commercial variant is gated |
| Depth-Anything-V2 Base/Large | CC-BY-NC (Small is OK) |
| openWakeWord models | CC-BY-NC-SA, not shipped |
| piper | Archived; its successor is GPL-3.0 |
| Qwen2.5-3B | "Qwen Research" licence |
| SoccerNet sn-calibration | No LICENSE file |
| boxmot | AGPL, not needed |
| mmpose / RTMW3D | mmcv is hard on ROCm |
| faster-whisper | No ROCm wheel; CPU fallback only |

**ROCm findings (D-39, FL-9..FL-11, research-log.md:55-68):**

- MIOpen on gfx1201 breaks Kokoro's LSTM and hung the first Whisper call for 20+ min while it held
  the GPU lock. Fix: `torch.backends.cudnn.enabled=False` for every non-ultralytics model, plus
  `flock … timeout N`.
- SAM 2.1 in fp32 is 10× slower than in bf16 (428 vs 39.6 ms/frame).
- The llama.cpp ROCm tarball silently runs on CPU (11 tok/s) unless the ROCm 7 libs are on
  `LD_LIBRARY_PATH`. With them it runs at 93-131 tok/s.
- gsplat cannot JIT without a HIP SDK.
- The static ffmpeg build segfaults on https inputs (FL-12).

## 8. AWS integration map (docs/aws-integrations.md)

**Nothing ran on AWS.** No credentials were used, and the CDK app synthesizes but was never
deployed. Provider selection: `REPLAY_PROVIDER_<NAME>=local|aws`. Every AWS stub mirrors its
Protocol and raises `NotImplementedError`.

| provider | local implementation | AWS target (stub) |
|---|---|---|
| storage | `LocalStorage`, disk + `/media` with Range | S3 (`aws.S3Storage`) |
| index | `LocalIndex` (glob of game.json) | DynamoDB `Games` (`aws.DynamoIndex`) |
| jobs | `LocalJobs` thread + `services/worker` DAG | Step Functions + SageMaker Processing (`aws.StepFunctionsJobs`; `infra/lib/pipeline-stack.ts` built from `infra/dag.json`) |
| labeler | `HeuristicLabeler` | Bedrock Nova (`aws.NovaLabeler`) |
| query | `RuleQueryEngine` + validated LLM filter | Bedrock Converse (`aws.ConverseQueryEngine`) |
| tts | Kokoro through the model runner (M7) | Polly (`aws.PollyTTS`) |
| llm | llama.cpp llama-server (M7) | Bedrock Converse / Nova (`aws.BedrockLLM`) |
| embeddings | SigLIP through the model runner (M7) | Bedrock multimodal embeddings (`aws.BedrockEmbeddings`) |
| face | OpenCV YuNet + SFace, opt-in | Rekognition collections (`aws.RekognitionFace`) |
| profiles | SQLite | DynamoDB `Profiles` + `Links` (`aws.DynamoProfiles`) |
| speaker | ECAPA through the model runner | SageMaker endpoint (`aws.SageMakerSpeaker`) |

The IAM roles and policies are written but unattached. The deploy checklist is
docs/aws-integrations.md:60-67. The HLS/MediaConvert ladder is not built (perf.md:186-188).

## 9. Bugs, risks, open issues

### P0: blocks the Fire TV track or a credible demo

1. **The Fire TV app has never run on a device or emulator** (no KVM, no device attached).
   - Unverified (D-64, progress.md:41, 143): playback, TextureView follow-cam transforms and their
     GPU cost, key codes and the 120 ms JS key-repeat, rapid angle cuts, seek latency, decode,
     memory.
   - Every replay-angle cut is a new source load of a 720p file with no audio track (perf.md:182-184).
2. **The X gesture misses far players**: recall 0.41 with ViTPose and 0/22 with the default YOLO
   pose (synthetic). The GT-pose regression from D-61 is fixed (D-68: 22/22, 0 false). A held
   two-hands-overhead call for the ball (≥ 0.9 s, elbows wide) would still read as an X.
3. **Validation is mostly synthetic.**
   - There is no staged real gesture or voice footage, and ASR is untested on real game audio.
   - There is no CC volleyball footage.
   - The real-footage numbers (Kennesaw shots 3/6, badminton rallies) are local, small and not
     re-measured.

### P1: correctness and licence

- **Tracking on small, bunched players:**
  - Synthetic basketball IDF1 is 0.31 / 0.25, with 122-157 ID switches.
  - 15 % of raw tracklet frames are on the wrong person (D-61).
  - This drives possession-cause errors, gesture attribution and the players missing from
    Tier B/C (M9/README.md:109-111).
- **Events:**
  - GT-pose shot recall (0.67) and rally P/R are lower than at M4. The cause was not
    investigated (progress.md:46).
  - Real shot recall fell to 3/6.
  - Volleyball attack is P 0.30.
  - Contact `side_ok` is near chance.
  - The pickleball doubles second-server rule is wrong.
- **Score from makes:** the pipeline found no makes on the M6 synthetic clip at render time, and
  real scores are provisional. The basketball shot outcome stays "unknown" in Tier C until a user
  confirms it.
- **The 240 s CC pickleball run gave 0 events** (teams split 15 vs 1). This was not root-caused;
  the 90 s cut works (progress.md:159).
- **AGPL:** the Replay workspace root depends on `courtcam[yolo]` (ultralytics, AGPL-3.0), so a
  distributed build of the app carries the AGPL unless the detector is swapped (D-66). A
  permissive default detector is still open (licenses.md:80-81).
- **Research-grade or flagged weights:**
  - MotionBERT (Human3.6M) and SFace (training data undocumented) are opt-in and replay-side
    only.
  - The speechbrain ECAPA weights carry a VoxCeleb data flag.
  - Kokoro's espeak-ng G2P is GPL-3.0, loaded as a shared library (licenses.md:52).
- apps/tv tsc, eslint and Playwright now run in `scripts/box-test.sh` and
  `.github/workflows/ci.yml` (50c0cdf).
- **Native TV config:** the API base is hardcoded in apps/tv/app.json, and the release APK is
  signed with the debug keystore. The react-native-video patch must be dropped when upgrading
  (D-64).
- **Evidence specs:** `apps/tv/e2e-evidence` M3-walkthrough and M13-ui did not fully pass
  against the menu restructure. The tag dialog did not open on `t` (M13/README.md:18-22).
  Re-running them now was not attempted.

### P2: quality, performance, docs

- Tier B: plate ghosts, void floor on far orbits, thin side-on billboards. Hoop height is
  50-90 px off on wide real rigs (D-53).
- Tier C: jumps are flattened, depth along the view ray is the weak axis, and Kennesaw was not
  attempted.
- No ball model outside basketball. Slow motion repeats frames.
- The model runner reloads the model per call (about 6 s). With llama-server up, TTS runs on CPU.
- Worker-made games have no search index by default. SigLIP is weak on synthetic frames.
- Face enrollment was never exercised end to end through the UI with real models. The face
  threshold was tuned on one clip with two people, and there is no held-out labelled face clip.
- There is no voice-enrollment route.
- `match_game` uses seek-based frame reads (about 11 s for 48 players). Merges re-run pose for
  the affected chunks. Corrections made before D-63 cannot be recovered.
- The Highlights reel plays wide only.
- Courtcam source edits invalidate courtcam stage caches once.
- The stale docs found while writing this report (`samples/cc` not ignored, unmeasured metric
  claims, missing M2 entry, licence rows, AWS map) were fixed in 50c0cdf.

### Privacy posture

- Face and voice ID are opt-in and off by default.
- Face enrollment needs `consent=true` and 1-10 own photos. The photos are deleted after
  embedding; one mean embedding is kept, and deleting the enrollment purges it.
- Only enrolled embeddings are compared, and nothing about unmatched players is stored. Matches
  are suggestions that a person confirms (D-58).
- No face images from the face runs were committed (M10/README.md:118-119).
- The phone voice query uses the browser's Web Speech API (`webkitSpeechRecognition`,
  apps/web/src/screens/Companion.tsx:28-30). Where its audio is processed depends on the browser,
  and the repo does not document it. Flag this before any public demo.
- Committed CC BY frames show identifiable tournament players without model releases. They are
  attributed and kept small (test-data.md:19).

### Process issues seen this night

- Metrics were logged higher than they re-measured (M1 basketball tracking, M4 shots and rallies,
  M5 gesture). This was corrected in e4b79bf.
- The "8/9 crowd-noise mixes" claim had no findable script.
- FL-17: the first tmux session on the shared box leaked the demo's `PYTHONPATH`,
  `REPLAY_DATA_DIR` and `REPLAY_CACHE_DIR` into tmux's global environment. Every later session
  inherited them, and two api tests failed as a result. **Fixed:** box-demo.sh now strips the
  variables and passes them per session (`-e`).
- FL-18: an ssh drop killed a foreground cold demo build. **Fixed:** the build is nohup'd, and a
  per-demo-dir flock makes a re-run wait.
- FL-13: the `uv` on the box PATH is a shim, so `/workspace/bin/uv` had to be called by full path.
- `apps/web/src/data/tracksCache.ts` had never been committed (hidden by an unanchored `data/`
  ignore), so fresh clones did not build. **Fixed** in 4ad6a0c.
- No progress or friction entry records an agent running git or running compute on the laptop.
  This report did not audit agent transcripts beyond those logs.

## 10. Next 3 tasks

1. **Run the release-texture APK on a real Fire TV**
   (`/workspace/wt/replay-tv-scratch/apk/replay-tv-0.1.0-release-texture.apk`).
   - Check playback, the follow-cam TextureView transform, D-pad/long-press mapping, angle cuts
     and seek latency.
   - Make the API base configurable and sign with a real key.
   - Why: the primary track is Fire TV, and every native path (D-57, D-64) is untested. This is
     the largest single unknown.
2. **Record and hand-label a small real, consented evaluation set:** one phone on a tripod, one
   basketball and one net-sport session, staged X gestures and "Replay, clip that" lines.
   - Use it to re-measure tracking, shots, rallies, gesture, voice and hype held out.
   - Why: almost every number in §5 is synthetic. The real ones are tiny, local and partly stale.
     This also gives the gesture rule (D-68) a real target.
3. **Tracklet-level association for small players**, e.g. a real ReID embedding or a stronger
   small-player detector, measured on the M1 eval and the new real set.
   - Why: tracking errors propagate into possession causes, gesture/clip attribution, profile
     links and the players missing from Tier B/C. The cheaper fixes (BoT-SORT tuning, 1280 px,
     gated merging) already failed (progress.md:118).
   - Runner-up: a permissive default detector to remove the app-level AGPL (D-66).

## 11. hfbox usage

**What ran there:** all tests and Playwright runs, every pipeline, eval and render, model installs
and benchmarks, llama-server, SAM 2.1, MotionBERT, the Tier D experiments and the Gradle APK
builds. The laptop only edited files and synced (docs/compute.md).

**Locks:**

- `/workspace/airtools/.gpu.lock` (one GPU job box-wide; the worker takes it per GPU task).
- `/workspace/wt/replay-env/.cpu.lock` for heavy CPU jobs.
- `/workspace/wt/replay-env/.pw.lock` for Playwright.
- Logged waits include about 210 s of CPU-lock wait in the cold `make demo` and most of the 267 s
  TTS benchmark (GPU lock).

**State at the time of writing** (read-only ssh, 2026-10-06 10:24 UTC):

- `df -h /workspace`: 147 G size, 129 G used, **11 G available (93 %)**. docs/compute.md:16 says
  23-32 GB free; that figure is out of date.
- No tmux server is running and no replay lock is held. `free -g` shows 21 GiB available.

| path | size | keep? |
|---|---|---|
| /workspace/wt/replay-env (total) | 21 G | keep (shared env) |
| ├ android (jdk17 318 M, sdk 2.5 G, gradle-home 4.2 G) | 7.0 G | keep JDK/SDK; see the transforms cache below |
| ├ models (gguf 2.4 G, llama.cpp 1.2 G, vitpose 328 M, yolo 303 M, motionbert 224 M, src 118 M, face 38 M) | 4.5 G | keep |
| ├ hf (Kokoro, whisper-small, ECAPA) | 2.7 G | keep |
| ├ uv-cache | 1.5 G | **cleanable**: FL-13 said to delete it after `uv sync` |
| ├ venvs (asr 351 M, tts 336 M, speaker 318 M, tierd 162 M, emb 41 M, lift/sam2/ytdlp 16 M each) | 1.3 G | keep; `tierd` is experiments only and could go |
| ├ samples-real 1007 M, samples-cc 421 M | 1.4 G | keep (test corpora; never committed) |
| ├ venv 636 M, ms-playwright 641 M, pnpm-home 331 M, node 203 M, bin 153 M, corepack 63 M | about 2.0 G | keep |
| └ cache (shared worker cache) | 469 M | safe to delete per stage (compute.md:104-105); costs recomputes |
| /workspace/wt/replay-env/android/gradle-home/caches/9.4.1/transforms | 2.9 G | **cleanable with the owner's OK.** It was removed once (INSTALLS.md, 04:50 UTC), regenerated by the M3-addendum rebuilds, and rebuilds offline from `modules-2` |
| /workspace/wt/replay-tv-scratch (includes `apk/`, 3 APKs about 122 MB) | 128 M | keep the APKs |
| /workspace/wt/replay-plays (its `_eval/out` is the input of M10/make_evidence.py and M4/eval) | 678 M | keep until the eval inputs are archived |
| 16 other agent copies `replay-*` (accuracy, autocal, base, broadcast-scratch, commentary, events, m13, orch, synth, tierb-scratch, tierb-tv, tierc, tierc-scratch, tv, verify, web) | about 2.0 G combined (17 M-344 M each) | cleanable with the owner's OK, once nothing references them |

The orchestrator expected the demo game dirs to be left on the box. **They are not there.**
`/workspace/wt/replay-m13/data/` (the `make demo BOX_DIR` measured in perf.md:38) is empty (mtime
09:44 UTC), and no `g_demo_basketball` directory exists under /workspace/wt. The next `make demo`
will be a cold build (551 s measured on a shared box). The APKs, venvs, models and both footage
pools are present.

## 12. Footage and licensing compliance

- **Synthetic:** every committed render and screenshot of a generated game is labelled SYNTHETIC,
  in the file name (`synth_*`, `*_synthetic_*`) and/or burned into the frame (docs/evidence/*/README.md).
- **CC BY 3.0:** these clips appear in committed evidence with paste-ready attribution:
  - pickleball_surrey2026 in M8, M9 and M12;
  - the five face-yield clips in M10.

  Their sources are recorded in docs/test-data.md §3 and each clip's box-side `SOURCE.txt`. The
  video files themselves live only on the box (`/workspace/wt/replay-env/samples-cc/`).
- **YouTube standard-licence footage (`samples/real`, D-7):**
  - It is never committed. `git ls-files samples/real` shows only MANIFEST.md, RESULTS.md,
    .gitkeep and five `*.landmarks.json` files (pixel coordinates, no media).
  - Renders derived from it live only in the gitignored `docs/evidence/local/` (.gitignore:18-19).
  - A filename check of the committed evidence finds no corpus clip names.
- **No secrets:** config is via env vars. A filename check of the 731 tracked files found no
  `.env`, key or credential files. No AWS credentials or paid services were used.
- **No music or logos:** stings are procedural, and the font is OFL.
