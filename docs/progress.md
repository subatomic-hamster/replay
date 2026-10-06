# Progress

One entry per milestone (newest last). Each entry: what works, the exact commands that
proved it on the box with their results, evidence paths (docs/evidence/README.md rules),
and what is left. Keep it factual; numbers come from runs, not estimates.

Template:

```markdown
## M<n> — <title> (<date>)

- Works: ...
- Verified on hfbox: `<command>` → <result: pass counts / metrics>
- Evidence: docs/evidence/M<n>/... (synthetic/CC) · docs/evidence/local/M<n>/... (not committed)
- Decisions: D-<k> ...
- Left / known issues: ...
```

## M0 — Recon and scaffold (2026-10-06)

- Works: hfbox measured and documented (RX 9070 XT 16 GB, ROCm 7.2, torch 2.14; rsync laptop↔box 1.4–1.9 MB/s; YOLO11n 8.1 ms/frame, YOLO11m 10.7 ms/frame) in docs/compute.md. `services/worker` stage DAG over a content-hash cache wraps courtcam's nine stages with byte-identical output. Ten providers at the time (eleven since `profiles` was added in M10) selectable local/aws with AWS stubs. CDK skeleton synthesizes without credentials; CI workflow; `make sync|test|demo`.
- Verified on hfbox: `scripts/box-test.sh` on HEAD + platform changes → ruff clean, courtcam 99, api 108, worker 10 passed, `cdk synth` ok, web tsc/eslint clean, Playwright chromium+live 62 passed. `make demo` → 9 misses then 9 hits. Kennesaw 240 s through the worker: 76.4 s cold (3.1× realtime), 1.4 s warm.
- Evidence: docs/evidence/M2/worker-cache-synthetic.txt · docs/perf.md
- Decisions: D-34 worker + cache, D-35 provider layout, D-36 courtcam subtree split.
- Left / known issues: no real fan-out stage yet (first ones arrive with per-play / per-angle work); Step Functions machine is a placeholder chain; local tts/llm/embeddings/face/speaker raise NotConfiguredError until models land.

## M2 — API + local worker + uploader (2026-10-06)

The M2 work is recorded in the M0 entry above (platform commit 5d9e44d: worker, providers, CDK skeleton, CI, `make sync|test|demo`); this entry only indexes it.

- Works: `services/worker` (the local stage DAG over a content-hash cache, D-34) is what the API runs with `REPLAY_PIPELINE=worker`; the API's provider layout (D-35) selects local or AWS stub per provider with `REPLAY_PROVIDER_<NAME>`. The uploader is the Phase 1 `/upload` route of the one Vite app (D-2, D-14).
- Verified on hfbox: see the M0 entry (`scripts/box-test.sh`: ruff clean, courtcam 99, api 108, worker 10 passed, `cdk synth` ok, web tsc/eslint clean, Playwright 62 passed; `make demo` → 9 misses then 9 hits; Kennesaw 240 s cold 76.4 s, warm 1.4 s). Cache behaviour on the synthetic sample: docs/evidence/M2/worker-cache-synthetic.txt (run 1: 9 miss, 0 hit; run 2: 0 miss, 9 hit); early timings (synthetic 20 s clip cold 1.3 s / warm 0.0 s) in docs/perf.md section 4.
- Evidence: docs/evidence/M2/worker-cache-synthetic.txt
- Decisions: D-34, D-35 (D-36 is the courtcam subtree split, also in M0).
- Left / known issues: as in M0 (no fan-out stage yet at that time, placeholder Step Functions machine). No separate M2 test run was logged beyond M0's, so no further numbers are claimed here.

## M1 — Synthetic generator v2 + tracking metrics (2026-10-06)

- Works: `courtcam synth` renders 5 scenes (basketball half/full, pickleball, badminton, volleyball) with articulated mannequins, ballistic ball, scripted plays, X-gesture/voice/tap triggers, Kokoro voice lines and crowd/contact audio; exports labelled-synthetic GT per the contracts. `courtcam eval` scores CLEAR-MOT/IDF1 + court error. Research pass: every repo on the list checked for URL/license/activity/ROCm (docs/research-log.md, docs/licenses.md); models installed and benchmarked on hfbox (docs/models.md); 5 CC BY clips (basketball, pickleball, badminton) on the box (docs/test-data.md).
- Verified on hfbox: courtcam pytest 157 passed (goldens match), api 110, worker 11, ruff clean (staged snapshot). YOLO pipeline on synthetic, players MOTA / IDF1 — re-measured on current code (2026-10-06, docs/evidence/M1/metrics.json; the originally logged values were higher for basketball): basketball half 0.64 / 0.31 (122 ID switches), full 0.43 / 0.25 (157), pickleball 0.98 / 0.99, badminton 0.99 / 1.00, volleyball 0.91 / 0.75; GT detector 1.0 on 5/5 scenes. Whisper-small: 37/37 synthetic voice lines heard, in 9/9 clips (the originally logged "8/9 crowd-noise mixes" test could not be found and is superseded).
- Evidence: docs/evidence/M1/README.md + metrics.json, synthetic_basketball_half_yolo_overlay.{mp4,png} (older render) · docs/evidence/local/M1/pickleball_legacypark_240s_overlay_M1.mp4
- Decisions: D-38, D-39, D-40, D-41.
- Left / known issues: basketball YOLO tracking weak on small bunched players (re-measured IDF1 0.31 half / 0.25 full); foot-point bias ~0.2 m; no CC volleyball footage; ASR untested on real game audio; ultralytics (AGPL) must become an optional extra before the courtcam split.

## M3 — Fire TV client (2026-10-06)

- Works: `apps/tv` (react-native-tvos 0.87 + react-native-video) at parity with the browser TV route: Library; Watch with seek-bar event markers, select mode with D-pad cone focus and overlap cycling, transform-based follow, spotlight, court inset, tag/rename, bookmarks; Highlights reel; Review; Pair. Shared logic in `packages/tv-core`, used by apps/web and apps/tv.
- Verified on hfbox: apps/tv `tsc` + `eslint` clean, `playwright test --project=tv` 11 passed; apps/web `tsc` + `eslint` clean, Playwright chromium+live 62 passed. Gradle `assembleDebug` + `assembleRelease` → arm64/armv7 APKs (leanback launcher, targetSdk 36), box-only at /workspace/wt/replay-tv-scratch/apk/.
- Evidence: docs/evidence/M3/tv-synthetic/01..09.png (synthetic game) · docs/evidence/local/M3/tv-real-kennesaw/ (real footage, not committed)
- Decisions: D-37.
- Left / known issues: never run on a device or emulator (no KVM, no Fire TV attached) — playback, key codes and performance on Fire OS unverified; API base hardcoded in apps/tv/app.json; release signed with the debug keystore; Highlights reel plays wide only.

## M4 — Events + plays (2026-10-06)

- Works: pose stage (YOLO11m-pose on upscaled track crops, GPU, per chunk, cached), audio stage (16 kHz WAV + full-quality copy, onsets, loudness, hype), pose-based basketball shots with 2/3 points and make/miss, possession changes with cause, turnovers, net-sport rallies with serve/point/contacts, volleyball blocks (no GT), play grammars → plays.json, score.json with API corrections (`GET/POST /games/{id}/score`, `GET /games/{id}/plays`).
- Verified on hfbox (staged snapshot): courtcam 171, api 123, worker 15, render 20 passed, ruff clean. 9 synthetic clips, re-measured on current code after the accuracy pass (2026-10-06, docs/evidence/M4/metrics.json): synthetic detector + GT poses — shots P 1.00 / R 0.67 (18/27; 2 vs 3 pts 18/18), possession P 0.83 / R 0.80, plays P 0.83 / R 0.79, contacts P 0.91 / R 0.89; YOLO detect + YOLO pose — shots P 1.00 / R 0.78 (21/27), rallies P 0.75 / R 0.69. At the time of M4 (before the accuracy pass) GT-pose shots were logged as P 0.96 / R 0.85 and YOLO rallies as P 0.97 / R 0.88; those cannot be re-measured on current code, and GT-pose shot recall and rally P/R are lower now (not yet investigated). Real (local only, not re-measured): badminton 240 s rallies P 1.00 / R 0.86 (motion-only); Kennesaw shot precision ≈ 0.4–0.6 on a hand check of 10.
- Evidence: docs/evidence/M4/README.md + metrics.json + eval/ (scripts), timeline_synthetic_*.png · docs/evidence/local/M4/ (real timelines + hand-check crops)
- Decisions: D-49, D-50, D-51.
- Left / known issues: YOLO-pose shot recall on small players; possession causes unreliable on real footage (identity fragments); contact hitter/side attribution weak (volleyball attack P 0.30); net-sport auto score needs point `winner_side`.

## M5 — "Replay, clip that" (backend) (2026-10-06)

- Works: gesture (X overhead held ≥ 0.8 s), voice ("Replay, clip that / clip <name>", whisper-small) and tap (`POST /games/{id}/triggers`) triggers resolve to the play that just ended and produce attributed clips; `GET /games/{id}/clips`, `PATCH /games/{id}/clips/{id}` trims (source user).
- Verified on hfbox, re-measured on current code (2026-10-06, docs/evidence/M5/metrics.json), synthetic with GT poses: gesture 16 TP / 26 FP / 6 FN (P 0.38, R 0.73; who 16/16, clip right 11/22), voice 37/37 (named subject 18/18, clip right 30/37), tap clip right 10/14; resolution rule exact on GT plays 73/73. The gesture regression is real: at M5 it was logged as 22/22 with no false triggers, and the accuracy pass's relaxed "hands together overhead" rule (D-61), tuned for far YOLO/ViTPose players, fires on GT poses 26 times. Real footage (local only, not re-measured): 0 false triggers in 480 s.
- Evidence: docs/evidence/M5/README.md + metrics.json, trigger_{gesture,voice,tap}_synthetic_basketball_half_s7.mp4 (older renders), timeline_synthetic_badminton_doubles_s7.png
- Left / known issues: no staged real gesture/voice footage (synthetic only); gesture via YOLO-pose 0/22 on far synthetic players (re-measured; docs/evidence/M5/README.md); TV trim UI pending the integration wave.

## M6 — Broadcast mode (2026-10-06)

- Works: auto-director (cuts.json) + compositor render one H.264 broadcast rendition: score bug, LIVE/REPLAY bugs, lower thirds, sting, 0.5× replays with telestrator (ring, trail, shot arc to the 3.05 m rim), game audio under graphics with procedural stings and a narration ducking hook. Worker stages director → broadcast cached; `GET /games/{id}/renditions`.
- Verified on hfbox: render 12 + worker cache tests (2nd run 0 miss). Jitter (rms px/frame², raw → smoothed) on Kennesaw: wide 14.5 → 0.072, tight 51.3 → 0.42, courtcam follow-cam 2.12 → 0.64. ~100 fps render at 1080p on CPU.
- Evidence: docs/evidence/M6/broadcast_synthetic_basketball_90s.mp4 (events from synthetic ground truth, labelled on screen), stills, jitter plots · docs/evidence/local/M6/ (Kennesaw)
- Decisions: D-42, D-43, D-44.
- Left / known issues: real-footage makes not detected reliably yet, so real scores stay provisional; no shot arcs on panoramic footage (no pinhole fit); slow motion repeats frames.

## M11 — Discovery (backend) (2026-10-06)

- Works: hype meter (`replay.hype.v1`), condensed game + rally browser, longest rallies, vertical 9:16 exports with deterministic captions, shot chart, auto-detected box score, distance covered, review queue; API routes + worker stages. Semantic search is part of M7.
- Verified on hfbox: render 20, api discovery 6 + worker discovery 2 passed. Hype vs synthetic GT: basketball P 0.86 / R 1.0, pickleball 1.0 / 1.0, badminton 1.0 / 0.89. Distance covered median error 0.7–4.9 %. Condensed real badminton 240 s → 87.5 s in 10.6 s; vertical exports ~300 fps.
- Evidence: docs/evidence/M11/ (synthetic) · docs/evidence/local/M11/ (Kennesaw, badminton)
- Decisions: D-45..D-48.
- Left / known issues: backend only — hype scrubber, rally browser, review screen and export button await the TV/web integration wave; hype untested on real crowd noise.

## M7 — Grounded commentary, advice, query, search (2026-10-06)

- Works: `commentary` worker stage writes a grounded script, per-play WAVs and a game-clock `narration.wav` that the broadcast mixer ducks under; per-player advice; free-text query (rules, then a validated LLM filter); `embeddings` (fan-out per play) + `search_index` stages; API routes for commentary, advice and search. Local tts/llm/embeddings/speaker/query providers run behind a subprocess model runner; AWS stubs unchanged.
- Verified on hfbox (staged snapshot): ruff clean, courtcam 171, api 193 + 1 skipped, worker 18, render 20 passed; model-runner box test 7 passed against the real venvs. Grounding over 28 synthetic plays: template 28/28, LLM paraphrase accepted 26/28 (both rejections fell back to the template), LLM median 0.27 s/play. Kokoro median 0.19 s/line on GPU (RTF 0.085), 0.35 s on CPU. Advice templates grounded 18/18. Query LLM median 0.58 s; "the crowd going wild" correctly yields no filter. Search: "a steal" and "rebound" rank their two matching plays first.
- Evidence: docs/evidence/M7/ (synthetic, incl. synthetic_bb90_narrated.mp4) · docs/evidence/local/M7/ (Kennesaw: template 32/32, LLM 30/32)
- Decisions: D-52.
- Left / known issues: runner reloads the model per call (index build 107 s for 10 plays); TTS on CPU while llama-server is up; no TV/web UI yet for commentary, advice or search (integration wave); SigLIP retrieval weak on synthetic frames.

## M8 — Tier B virtual replay angles + TV angle switching (2026-10-06)

- Works: full `calibration.json` (K, R, t, k1, height landmarks, mirrored rigs); court plate; SAM 2.1 masks; Tier A (wide, follow, tight) and Tier B 2.5D (broadcast_high, orbit, push_in) renders per highlight, time-aligned; worker fan-out per play × angle, cached; `GET /games/{id}/replays[/{play_id}]`; Replay screen in apps/tv and apps/web /tv cutting between six angles with Left/Right at the same media time.
- Verified on hfbox (staged snapshot, `scripts/box-test.sh`): ruff clean, courtcam 178, api 196 + 1 skipped, worker 19, render 29 passed, dag drift none, infra synth ok, web tsc/eslint clean, Playwright chromium+live 66 passed; apps/tv tsc/eslint clean, Playwright tv 15 passed + 1 skipped; TV-09/S-38 40/40 on repeat (agent run). Calibration on synthetic truth (20 seeds, 1 px noise): focal 0.25–0.64 %, rotation 0.11–0.28°, camera position 4–8 cm median; lens k1 −0.2 up to 1.9 % / 0.56 m. Real clips: floor reprojection 0.03–2.64 px; held-out hoop 53–92 px. Tier B ≈ 32–62 ms/frame; SAM ≈ 26 ms per object per frame. Angle cut keeps media time to within 8 ms through the real API.
- Evidence: docs/evidence/M8/ (9 highlights × 6 angles: synthetic basketball, synthetic volleyball, CC BY pickleball; angle sheets, orbit mp4/GIF, TV screenshots through the real API, calibration tables) · docs/evidence/local/M8/ (real-clip calibration)
- Decisions: D-53, D-54, D-55, D-56, D-57.
- Left / known issues: hoop 50–90 px off on wide real basketball rigs (heights approximate); plate ghosts and void floor on far orbits; thin billboards side-on; no ball model outside basketball; SAM GPU cost and lock contention; native TV path untested on a device. Fixed on the way: `apps/web/src/data/tracksCache.ts` had never been committed (the unanchored `data/` ignore hid it), so fresh clones did not build.

## M10 — Profiles, player cards, cross-game linking, opt-in faces (backend) (2026-10-06)

- Works: profile CRUD (SQLite, DynamoDB stub), link/unlink with roster naming and rename propagation, same-name link suggestions, per-sport career stats with flagged user edits, career reel manifest, collectible card JSON + 810×1080 PNG with a grounded title (template; LLM paraphrase optional), opt-in face enrollment with consent and purge, `face_match` worker stage (opt-in, skips without enrolled profiles) and API job.
- Verified on hfbox (staged snapshot, `scripts/box-test.sh` ALL GREEN): ruff clean, courtcam 178, api 211 + 1 skipped, worker 21, render 29, web Playwright 66 passed. Synthetic cards (4 synthetic games, 3 profiles, one spanning basketball + badminton): titles grounded 3/3, card JSON byte-identical on rebuild 3/3, 0.5–1.1 s per profile; LLM titles 3/3 accepted. Faces on CC footage: usable faces in 2.8–14.8 % of person samples (synthetic mannequins 0 %). Hand-labelled CC fisheye badminton clip (tuning set, not held out) at threshold 0.45: genuine face match 64–72 %, unenrolled 3 %; genuine windows suggested 39/45, unenrolled 0/47.
- Evidence: docs/evidence/M10/ (synthetic cards, profiles, reels; face yield and match metrics as JSON, no face images committed)
- Decisions: D-58.
- Left / known issues: TV/web profile screens not built; no voice-enrollment route (field always false); no held-out labelled face clip; `match_game` uses seek-based frame reads (~11 s for 48 players); career reel not rendered.

## M9 — Tier C reconstruction replays (2026-10-06)

- Works: MotionBERT 2D→3D lift (analytic fallback) placed on the calibrated court, motion clean-up (smoothing, rigid bones, foot pinning, collision push), `replay.scene.v1`, capsule-mannequin renders from broadcast_high, baseline, overhead, reverse and shooter POV, basketball ball arc; opt-in worker stages that merge Tier C angles into the replays manifest, so the M8 Replay screen shows them.
- Verified on hfbox (staged snapshot, `scripts/box-test.sh` ALL GREEN): courtcam 178, api 211 + 1 skipped, worker 22, render 49 passed. Synthetic full-court basketball, 12 body joints, all players: MotionBERT MPJPE 125–139 mm (74–75 mm pelvis-aligned), analytic 172–187 mm; jitter 10–13 → 4–5 m/s² (GT itself 4.5–5.6), foot slide 25–29 → ≤ 0.9 cm/s, bone-length CV 0.04 → 0, height error ≤ 3 cm; torso overlap ≤ 0.28 % → ≤ 0.06 %. CC BY pickleball with YOLO keypoints: jitter 39–56 → 9–15 m/s², foot slide 59–69 → 0.2–1.4 cm/s. `tierc_scene` 8–12 s per play; 3.6–15 s per angle at 1280×720.
- Evidence: docs/evidence/M9/ (synthetic basketball make/miss angle sheets, overhead GIF, POV and baseline MP4s; CC BY pickleball sheet + MP4s; metrics and timings). The make/miss outcome on the synthetic sheets was set from synthetic GT in a copy's highlights.json, standing in for a user-confirmed answer (stated in the README).
- Decisions: D-59.
- Left / known issues: shot outcome never automatic (ball stops at the rim unless confirmed); untracked players are absent; grounding flattens jumps; depth along the ray is the weak axis (absolute ≈ 2× pelvis-aligned error); Kennesaw (panoramic) not attempted. Worker re-runs restore cached `events.json` and drop user event edits (bug, all corrections).

## M13 (part) — TV/web integration of M5, M6, M7, M11 (2026-10-06)

- Works in apps/tv and the web /tv route: broadcast mode with commentary captions; clips list with attribution, D-pad trim, 9:16 share (export, poll, portrait preview); phone tap-to-clip and phone search → "Play on TV" in the web companion; hype meter above the scrubber with jump-to-peak; rally browser (in order / longest) and condensed game with a synced rally counter; API-driven review queue with identity naming/merging and the extended auto-detected box score; search with a labelled keyword fallback; per-player advice.
- Verified on hfbox (staged snapshot): web tsc/eslint clean, Playwright chromium+live 86 passed; apps/tv tsc/eslint clean, Playwright tv 33 passed + 1 skipped; agent runs: `--repeat-each=3` tv 99 passed, web chromium 237 passed; evidence spec against the real API on worker-processed synthetic games 4/4.
- Evidence: docs/evidence/M13-ui/ (tv-synthetic-live/ via the real API, tv-mock/; synthetic only)
- Decisions: D-60.
- Left / known issues: `GET /games` 500s when `recorded_at` is null (worker-made synthetic games); a deleted export with a "done" job returns `url: null`; clips have no `edited` flag; Watch menu (16 items) wraps to two rows over the video; worker-made games have no search index by default; commentary TTS needs `REPLAY_MODEL_VENVS`; profile screens not built.

## Accuracy pass (M1 / M4 / M5 follow-up) (2026-10-06)

- Works: shots on the default YOLO pose path, net-sport point winners, X gesture with the opt-in ViTPose backend; zero false gesture triggers on real footage kept.
- Verified on hfbox (staged snapshot, `scripts/box-test.sh` ALL GREEN): courtcam 182, api 211 + 1 skipped, worker 22, render 49, web Playwright 86 passed. Synthetic (9 clips): shots 5/27 → 21/27 at P 1.00 (YOLO pose; ViTPose 19/27); `winner_side` right on 27/33 points with known winner; X gesture 0/22 → 9/22 with `--pose vit` (P 1.00, R 0.41), still 0/22 with YOLO pose. Real 480 s: 0 false gesture triggers. Kennesaw shots: precision 0.5 → 1.0 (3 found, all real), but recall 3 of 6 known shots (was 5 of 6). Pose time with ViTPose fp16: Kennesaw 38 s vs YOLO 88 s.
- Tracking unchanged: synthetic basketball players IDF1 0.31 / 0.31 / 0.25 with 122–157 ID switches; Kennesaw 150–210 s ≈ 38 visible ID changes across 19 ids. ReID on, tighter BoT-SORT, 1280 px detection and gated merging all failed to help (details in samples/real/RESULTS.md).
- Evidence: docs/evidence/{M4,M5}/metrics.json "accuracy pass" sections (re-measured 2026-10-06: shots 21/27 at P 1.00, ViTPose 19/27, winner_side 27/33, X gesture vit 9/22 at P 1.00, YOLO pose 0/22 — all match; the "before" values are history), docs/evidence/M4/accuracy_timeline_yolo_*.png, docs/evidence/M5/accuracy_*_on_synthetic_x_holds.png · docs/evidence/local/{M1,M4,M5}/accuracy_* (Kennesaw)
- Decisions: D-61.
- Left / known issues: the relaxed X-gesture rule regressed the GT-pose gesture test from 22/22 with no false triggers to P 0.38 / R 0.73 (26 false gestures; see M5) — needs a stricter rule for clean, near poses; gesture recall 0.41 vs the 0.8 target on far players (misses are players ≤ 56 px tall); ViTPose not default yet (deps + lock); tracking needs tracklet-level association (real ReID or a stronger small-player detector); real shot recall dropped; contact `side_ok` near chance; pickleball doubles second-server rule.

## M12 — Tier D experiments (2026-10-06)

- Works (experiments only, no product code): A) MoGe-2 point maps scaled onto the calibrated floor, SAM-masked players lifted to court metres, point-splat renders along the production Tier B camera paths, with a hybrid variant; B) VGGT multi-frame static court; C) dynamic splats feasibility. Write-up in docs/tier-d.md and `experiments/tierd-*/README.md`.
- Verified on hfbox: experiment helper tests 2 passed. A: 0.141 s/frame, 3.19 GB; floor after scaling |z| median 0.02 m (CC) / 0.14 m (synthetic); synthetic players 0.62 / 1.51 m median / p90 position error vs Tier B 0.18 / 0.25 m; held-out cameras player IoU Tier B 0.35–0.80, Tier D raw 0.16–0.75, hybrid 0.38–0.75; floor PSNR Tier B 21–28 dB, hybrid 21–24.6 dB. B: 2.2–5.7 s for 8–32 frames, 8.8 GB; static camera found (≤ 26 mm); off-frustum coverage ≤ 1.4 %. C: gsplat fails without a CUDA/HIP toolkit (exact error in experiments/tierd-dynamic/README.md).
- Evidence: docs/evidence/M12/ (synthetic + CC BY pickleball)
- Decisions: D-62.
- Left / known issues: synthetic court is out of distribution for MoGe (pessimistic numbers); CC clip judged qualitatively only (no ground truth); splat renderer has no anti-aliasing (≈ 4 dB floor PSNR lost); one highlight per clip; experiment tests are not part of the CI suites.

## Backend fix wave (2026-10-06)

- Works: user corrections survive worker re-runs and reach downstream stages (D-63, `edits.json` overlay); `GET /games` tolerates `recorded_at: null`; deleted renders read `missing` and re-render on POST; clips carry `edited`; confirmed events count as verified in stats; model providers name `REPLAY_MODEL_VENVS` when unset and worker commentary falls back to captions; embeddings batched into one model load.
- Verified on hfbox (staged snapshot, `scripts/box-test.sh` ALL GREEN): courtcam 182, api 218 + 1 skipped, worker 24, render 49, web Playwright 86 passed. Real CLI repro on synthetic basketball_half (patch made/confirmed, rename, merge, user score via a live API, then `replay_worker run` again): events cache hit with every edit intact, plays and pose re-keyed, stats show the renamed player's corrected makes. Embeddings for 10 plays: 82.1 → 10.5 s (GPU), 60.8 → 11.0 s (CPU).
- Decisions: D-63.
- Left / known issues: dismissed events still form plays (courtcam `build_plays`); merges re-run pose for the affected chunks; player/clip patches anchored by id only; pre-D-63 corrections can't be recovered; UI to adopt `edited`/`missing` (profiles-UI wave).

## M3 addendum — Fire TV native re-verify and playback hardening (2026-10-06)

- Works: after the M8–M13 screens, the Metro release bundle, `assembleRelease` and `assembleDebug` all build (release 1m17s, debug 43 s of Gradle time); universal APK with arm64-v8a + armeabi-v7a, minSdk 24, targetSdk 36, leanback launcher; release bundle contains the Replay, Clips, Rallies, Search, Advice and Review screens. Native playback: seeks/play queued until load, restart after end, looping replays no longer pause on each wrap, video errors shown, held D-pad arrows repeat (D-64).
- Verified on hfbox: aapt2 badging (leanback-launchable-activity present); after the hardening, apps/tv tsc + eslint clean, Playwright tv 33 passed + 1 skipped on the committed tree, release Metro bundle builds (1.07 MB). APKs at /workspace/wt/replay-tv-scratch/apk/ (release 30.6 MB, debug 61.2 MB; box only).
- TextureView: a pnpm patch for react-native-video 6.19.3 makes `viewType=TEXTURE` produce a real TextureView (Media3 1.8.0 PlayerView inflated with `surface_type="texture_view"`); frozen offline install applies it, tsc clean, Playwright tv 45 passed + 1 skipped on the committed tree, `assembleRelease` OK with dex and layout confirmed in the APK (box only: /workspace/wt/replay-tv-scratch/apk/replay-tv-0.1.0-release-texture.apk, 30.6 MB).
- Left / known issues: never run on a Fire TV or emulator (no KVM); TextureView follow-cam transform/clip and its GPU cost unverified on hardware; key-repeat feel, error payloads and rapid angle cuts need a device; Watch/Profile duration pollers do not yet stop on `error()`; API base hardcoded in app.json; release signed with the debug keystore.

## M10 UI — Profiles on TV and phone, one-row Watch menu (2026-10-06)

- Works in apps/tv and the web /tv route: Players screen (from Library or the Watch menu); profile detail with per-sport career stats (D-pad corrections shown "EDITED · auto N", "Use auto" restores), player card PNG + fields, cross-game career reel, links tab (unlink; accept/decline suggestions, labelled as needing confirmation; face suggestions only for enrolled profiles); link a game player to a profile from Watch and from a Review identity question. Phone companion: create/edit profile, photo upload, consent-gated face enrollment (1–10 photos) and "Delete my face data". Watch menu is one row with groups (was 16 items wrapping over the video). Clips use the API's `edited` flag; `missing` renders are offered for re-render.
- Verified on hfbox (staged snapshot, `scripts/box-test.sh` ALL GREEN): courtcam 182, api 218 + 1 skipped, worker 24, render 49, web Playwright chromium+live 99 passed; apps/tv tsc/eslint clean, Playwright tv 45 passed + 1 skipped. Agent runs: new specs (TV-14, TV-15, S-50..S-52, live S-53) `--repeat-each=3` all green. Found and fixed on the way: focus went to −1 on an empty profile list in both apps.
- Evidence: docs/evidence/M10-ui/ (tv-synthetic-live via the real API in fake-pipeline mode on synthetic games, tv-mock, phone-mock; synthetic only)
- Decisions: D-65.
- Left / known issues: declined suggestions return on reopen (no decline endpoint); face enrollment never exercised end to end through the UI against real face models (fake pipeline answers 503/422; delete verified directly on the API); no face suggestion in live evidence (mannequins have no faces; mock shows it).

## M13 — Packaging, `make demo`, perf, demo script, README (2026-10-06)

- Works: courtcam extras (`yolo` AGPL, `vitpose`, `asr`, `vlm`, `dev`) with fail-fast errors naming the extra; `uv.lock` regenerated (real uv 0.12.18); `make demo` / `demo-tunnel` / `demo-stop` build two synthetic 60 s games (basketball + pickleball) through the worker — plays, broadcast with narration, Tier A/B/C replays, hype, condensed, vertical — and serve API :8090, TV :5190, phone :5191; docs/perf.md with measured demo and CC BY tables and Fire TV rendition specs; docs/demo-script.md (4-minute walk-through); README overhauled; friction-log FL-13..FL-18.
- Verified on hfbox: no-ultralytics venv (`uv sync --locked --package courtcam --extra dev`, 23 packages, no ultralytics/torch/transformers) imports every courtcam module and passes courtcam pytest 183; full workspace `uv sync --locked` OK; `uv lock --check` OK. `make demo` cold 551 s (332 s worker compute + ≈ 210 s waiting on the shared CPU lock, + 117 s synth; SAM 2.1 segment 30–68 s per play dominates), warm 222 s (0.5 s worker compute, rest lock wait); synth deterministic (same sha256 on regeneration); HTTP Range 206. CC BY 90 s pickleball through the worker: cold 92.8 s, warm 1.4 s (26/26 cache hits).
- Evidence: docs/evidence/M13/ (demo broadcast-replay GIF, replay angles sheet, TV demo screenshots; synthetic) · docs/perf.md
- Decisions: D-66.
- Left / known issues: services/api and services/worker rely on the root package for `courtcam[yolo]`; ViTPose could now become the default via the locked `vitpose` extra (D-61); device playback not measured; the 240 s CC pickleball landmarks run produced 0 events (teams split 15 vs 1, not root-caused; the 90 s cut works); courtcam source edits invalidate courtcam stage caches once.

## Small fixes after M10 (2026-10-06)

- Works: play grammars skip user-dismissed events; the TV Watch `?t=` restore and the profile reel stop polling once a video has failed (web build now shows the "Video unavailable" overlay too); declining a profile link suggestion is persisted by the API and stays gone after reopening, in both TV clients.
- Verified on hfbox: each fix had a failing test first (courtcam test_plays 1, api test_profiles 2, tv Playwright 3), then passed. Staged snapshot, `scripts/box-test.sh` ALL GREEN: courtcam 184, api 220 + 1 skipped, worker 24, render 49, web Playwright 100 passed; apps/tv tsc/eslint clean, Playwright tv 48 passed + 1 skipped.
- Decisions: D-67.
