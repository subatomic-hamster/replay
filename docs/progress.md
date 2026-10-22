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
- Left / known issues: never run on a device or emulator (no KVM, no Fire TV attached) — playback, key codes and performance on Fire OS unverified; API base hardcoded in apps/tv/app.json and release signed with the debug keystore (both fixed by D-69, "TV first-run" below); Highlights reel plays wide only.

## M4 — Events + plays (2026-10-06)

- Works: pose stage (YOLO11m-pose on upscaled track crops, GPU, per chunk, cached), audio stage (16 kHz WAV + full-quality copy, onsets, loudness, hype), pose-based basketball shots with 2/3 points and make/miss, possession changes with cause, turnovers, net-sport rallies with serve/point/contacts, volleyball blocks (no GT), play grammars → plays.json, score.json with API corrections (`GET/POST /games/{id}/score`, `GET /games/{id}/plays`).
- Verified on hfbox (staged snapshot): courtcam 171, api 123, worker 15, render 20 passed, ruff clean. 9 synthetic clips, re-measured on current code after the accuracy pass (2026-10-06, docs/evidence/M4/metrics.json): synthetic detector + GT poses — shots P 1.00 / R 0.67 (18/27; 2 vs 3 pts 18/18), possession P 0.83 / R 0.80, plays P 0.83 / R 0.79, contacts P 0.91 / R 0.89; YOLO detect + YOLO pose — shots P 1.00 / R 0.78 (21/27), rallies P 0.75 / R 0.69. At the time of M4 (before the accuracy pass) GT-pose shots were logged as P 0.96 / R 0.85 and YOLO rallies as P 0.97 / R 0.88; those cannot be re-measured on current code, and GT-pose shot recall and rally P/R are lower now (not yet investigated). Real (local only, not re-measured): badminton 240 s rallies P 1.00 / R 0.86 (motion-only); Kennesaw shot precision ≈ 0.4–0.6 on a hand check of 10.
- Evidence: docs/evidence/M4/README.md + metrics.json + eval/ (scripts), timeline_synthetic_*.png · docs/evidence/local/M4/ (real timelines + hand-check crops)
- Decisions: D-49, D-50, D-51.
- Left / known issues: YOLO-pose shot recall on small players; possession causes unreliable on real footage (identity fragments); contact hitter/side attribution weak (volleyball attack P 0.30); net-sport auto score needs point `winner_side`.

## M5 — "Replay, clip that" (backend) (2026-10-06)

- Works: gesture (X overhead held ≥ 0.8 s), voice ("Replay, clip that / clip <name>", whisper-small) and tap (`POST /games/{id}/triggers`) triggers resolve to the play that just ended and produce attributed clips; `GET /games/{id}/clips`, `PATCH /games/{id}/clips/{id}` trims (source user).
- Verified on hfbox, re-measured on current code (2026-10-06, docs/evidence/M5/metrics.json), synthetic with GT poses: gesture 22 TP / 0 FP / 0 FN (who 22/22, clip right 16/22) after the D-68 fix, voice 37/37 (named subject 18/18, clip right 30/37), tap clip right 10/14; resolution rule exact on GT plays 73/73. History: at M5 the gesture was logged as 22/22; the accuracy pass's relaxed rule (D-61) regressed it to 16 TP / 26 FP / 6 FN (P 0.38, R 0.73; all 26 false gestures were synthetic jump shots); D-68 restored it (before/after in docs/evidence/M5/README.md). Real footage: 0 false triggers in 480 s with YOLO and ViTPose (re-run with the D-68 rule; local only).
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
- Evidence: docs/evidence/{M4,M5}/metrics.json "accuracy pass" sections (re-measured 2026-10-06: shots 21/27 at P 1.00, ViTPose 19/27, winner_side 27/33, X gesture vit 9/22 at P 1.00, YOLO pose 0/22 — all match; the "before" values are history), docs/evidence/M4/accuracy_timeline_yolo__.png, docs/evidence/M5/accuracy___on_synthetic_x_holds.png · docs/evidence/local/{M1,M4,M5}/accuracy_* (Kennesaw)
- Decisions: D-61.
- Left / known issues: the relaxed X-gesture rule regressed the GT-pose gesture test to P 0.38 / R 0.73 (fixed afterwards by D-68, see "Gesture fix" below); gesture recall 0.41 vs the 0.8 target on far players (misses are players ≤ 56 px tall); ViTPose not default yet (deps + lock); tracking needs tracklet-level association (real ReID or a stronger small-player detector); real shot recall dropped; contact `side_ok` near chance; pickleball doubles second-server rule.

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
- Left / known issues: never run on a Fire TV or emulator (no KVM); TextureView follow-cam transform/clip and its GPU cost unverified on hardware; key-repeat feel, error payloads and rapid angle cuts need a device; Watch/Profile duration pollers do not yet stop on `error()` (fixed by D-67); API base hardcoded in app.json and release signed with the debug keystore (fixed by D-69).

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

## Gesture fix (2026-10-06)

- Works: the X-gesture rule no longer fires on synthetic jump shots (ball overhead, hands together, elbows out, held < 0.9 s) and accepts side-on crossed X holds again: confident crossings skip the elbow-spread gate; uncrossed holds must keep the arms overhead ≥ 0.9 s (= `shot.release_max_s`).
- Verified on hfbox with the committed harness (docs/evidence/M4/eval): GT-pose gesture 22/22 with 0 FP (was 16 TP / 26 FP / 6 FN); `--pose vit` 9/22 at P 1.00 (unchanged); YOLO pose 0/22; real 480 s (Kennesaw + badminton auditorium) 0 false triggers with YOLO and ViTPose; M4 shot/contact/rally and voice/tap numbers unchanged; courtcam pytest 185 passed. The YOLO-step triggers were re-scored on the fixed code from tracks/poses computed before the fix (they do not depend on the gesture rule; stated in metrics.json).
- Evidence: docs/evidence/M5/README.md ("Gesture fix (D-68)": before → after) + metrics.json
- Decisions: D-68.
- Left / known issues: far-player X under ViTPose capped at 9/22 (arm keypoints score ≈ 0.1 on 48–56 px players); a held two-hands-overhead ball call (≥ 0.9 s, elbows wide) would read as an X; the synthetic rig's shot pose has the hands closer than the ball is wide (rig realism, left to keep goldens).

## TV first-run (2026-10-06)

- Works:
  - Settings screen for the API address: D-pad keyboard, connection test, kept on the device, opens on first run, reachable from the library and the error banner.
  - Release signing from env vars or Gradle properties, with a debug-key fallback warning.
  - docs/fire-tv.md: side-load and first-run checklist.
  - The M3/M13 evidence specs pass live on the demo games.
  - Atomic render mux: a 9:16 export used to read as "done" while still being written.
- Verified on hfbox:
  - box-test ALL GREEN: tv Playwright 50 (incl. TV-16 settings), web 100, courtcam 186, api 220 + 1 skipped, worker 24, render 49.
  - Evidence project: 8/8 on the mock; live, M3 1/1 and M13 4/4, twice.
  - `assembleRelease` offline: `/workspace/wt/replay-tvnative/apk/replay-tv-0.1.0-release.apk`, sha256 f657241e…; leanback launcher and banner present (aapt2).
- Evidence: docs/evidence/M13/README.md (re-run section), docs/evidence/M13/tv-demo-rerun/
- Decisions: D-69.
- Left / known issues: everything in docs/fire-tv.md's device checklist needs a real Fire TV; the APK is debug-signed until a real key is supplied.

## Tracking v2 (2026-10-06)

- Works: identity cuts cross-team jersey swaps inside tracklets (gated on kit agreement ≥ 0.85) and links tracklets by one global Hungarian assignment.
- Verified on hfbox, same detections before and after (YOLO11m + BoT-SORT; identity stage re-run):
  - Synthetic basketball IDF1 0.310 → 0.366 (half s7), 0.245 → 0.263 (full s7), 0.311 → 0.326 (half s11); MOTA within 0.01; ID switches unchanged.
  - Pickleball and badminton identical; volleyball 0.750 → 0.785 (s7), 0.746 → 0.737 (s11).
  - Kennesaw 150–210 s (local, hand count ±5): ≈ 51 → ≈ 42 visible changes, referee one stable row.
  - courtcam 187 passed on the agent's copy.
- Root-caused: the CC 240 s pickleball 0-events run used an autocalib landmark file marked `ok: false` (score 0.74, corners ~100–400 px too high). The same detections split teams 15/1 with it and 5/8 with hand-clicked landmarks. Not fixed yet: calibration should refuse or flag `ok: false` landmarks.
- Evidence: docs/evidence/M1/README.md "Tracking v2", metrics_tracking_v2.json, eval_tracking_v2/ (scripts behind every number); local sheets in docs/evidence/local/M1/
- Decisions: D-70.
- Left / known issues: same-team swaps are invisible to jersey colour (perfect split + link ceiling IDF1 0.85 vs ≈ 0.37 now); needs an appearance embedding or a better tracker.

## Events v2 (2026-10-06)

- Root-caused the GT-pose shot drop since M4: the accuracy pass's lower arm line made synthetic releases longer than `release_max_s` (0.9 s); 1.0 restores GT shots to 23/27 at P 1.00 (YOLO and real Kennesaw unchanged). The M4-logged YOLO rally P 0.97 was a run with audio fusion on, not a code regression.
- Works: rally end extension from audio onsets; pickleball side-out second-server rule (USA Pickleball 4.B.6); one-touch contact sides for badminton/pickleball.
- Verified on hfbox, same harness, 9 clips, seeds 7 + 11, before = 005cf87 (YOLO "before" reproduces the committed M4 metrics.json exactly):
  - GT poses: plays P/R 0.83/0.79 → 0.94/0.89; rallies 0.73/0.67 → 0.90/0.83; points 0.79/0.73 → 0.96/0.89; contact side right 148/222 → 209/239.
  - YOLO: plays 0.80/0.78 → 0.90/0.88; rallies 0.75/0.69 → 0.90/0.83; points 0.77/0.71 → 0.96/0.89; contact side right 113/223 → 143/239.
  - Contacts P 0.91 → 0.87 (landing onsets), R 0.89 → 0.96. Real badminton 240 s rallies unchanged (12/14, P 1.00, local).
  - Synthetic pickleball `winner_side` drops (GT 12 → 9 of 13) because synth.py uses rally scoring; expected, not a regression in the rule.
  - courtcam 191 passed on the agent's copy.
- Not yet measured together with Tracking v2 (D-70): both were measured against 005cf87 separately.
- Evidence: docs/evidence/M4/README.md "Events v2", metrics_events_v2.json, events_v2/ (scripts)
- Decisions: D-71.
- Left / known issues: volleyball attack P 0.30 / 0.10 untouched; synth.py should model side-out scoring; side-out assumes the clip starts a game; one_touch and extend_end untested on real pickleball; ViTPose branch not re-measured; commentary still says "Point to X" on a side-out rally.

## Low-confidence calibration guard (2026-10-06)

- Works: an auto-calibration proposal with ok=false is refused, unless explicitly overridden, in all four places: courtcam (`run`, `calibrate`), the worker, `POST /calibration` and the S-04b uploader (Accept is disabled until confirmed, or a dot is dragged). The override is recorded.
- Verified on hfbox:
  - The real CC 240 s pickleball autocalib file (score 0.74) is refused by `courtcam run`, `courtcam calibrate` and `replay_worker run` (exit 2, message names 0.74 / 0.90).
  - Same clip with tierB's hand-clicked landmarks for the same fixed camera: teams 5/8, 54 events (15 rallies, 15 serves, 15 points, 9 contacts), 15 plays. With the autocalib file plus the override: 12/1 and 0 events. The run used the events v2 code before it was committed.
  - Tests: one courtcam CLI test, one API test, Playwright S-04b-10/11 (docs/test-spec.md). box-test ALL GREEN on the agent's copy (courtcam 191, api 221 + 1 skipped, Playwright 102, tv 50).
- Evidence: run log on the box only (`/workspace/wt/replay-calibok/runs/pb240.log`); the footage is CC but no frames were committed.
- Decisions: D-72.
- Left / known issues: the API-path override is not carried into the pipeline's calib.json; the autocalib fit itself still lands in the fence on this clip.

## Tracking v2 + events v2 combined (2026-10-06)

- Measured together for the first time on 9b777bb with the unchanged harness (9 clips, seeds 7 + 11, GT and YOLO; ViTPose not run). No code changes.
- Rows identical to events v2 alone: shots, rallies, points, `winner_side`, contacts.
- Better with identity v2 (YOLO): possession change P/R 0.76/0.73 → 0.79/0.77, cause right 13/22 → 15/23; plays P 0.90 → 0.92; volleyball attack 1 → 2 TP.
- Worse by one shot each, and swapping 005cf87's identity.py back restores them exactly, so the cause is identity v2:
  - points right: GT 23/23 → 22/23; YOLO 14/21 → 13/21
  - YOLO shooter right 8/21 → 7/21
  - YOLO shot team right 19/21 → 18/21
  - YOLO made right 10/12 → 10/13
- Side effect D-70 missed: the jersey cut also fires on perfect GT-detector tracks. Basketball half/full IDF1 goes 1.000 → 0.995 with 3 / 2 ID switches, including one cross-team relink on half s11. Likely torso colour under a guarding opponent (not confirmed).
- Evidence: docs/evidence/M4/metrics_combined_9b777bb.json, docs/evidence/M4/README.md "Combined (9b777bb)"

## Recorded end-to-end run (2026-10-06)

- Works: `make record-e2e` records an automated run of the TV web build (1920×1080) plus the phone companion (390×844) against the real API and worker pipeline on hfbox. docs/evidence/E2E/replay-e2e.mp4, 3:25, 1280×720, 4.2 MB; full 1080p copy on the box at /workspace/wt/replay-recording/out/replay-e2e-full.mp4.
- Steps:
  - TV Settings shows "Connected".
  - The phone uploads a 20 s synthetic clip. Its auto-calibration proposal is refused (D-72) and the points are placed by hand.
  - The real worker pipeline finishes cold in 19 s, and the uploaded game plays on the TV.
  - The demo beats on the TV: watch, follow/spotlight/inset, broadcast + commentary, phone pairing + "Clip that" + trim, 9:16, replay angles A/B/C, highlights + SigLIP search, review, profile card, pickleball rallies/condensed.
- Verified on hfbox: 15/15 beats asserted and passing; box-test ALL GREEN on the committed snapshot (courtcam 191, api 221 + 1 skipped, worker 24, render 49, web Playwright 102, tv 50 + 1 skipped). Key frames checked by eye.
- Fixed: `box-demo.sh serve` ran the API on /opt/venv's python, and vite hung on a corepack prompt, when tmux's global PATH lacked env.sh. Each window now sources env.sh; tmux's global env is untouched.
- Evidence: docs/evidence/E2E/README.md (commands, beat timestamps, caveats)
- Decisions: D-73.

## Tracking v3: jersey cut skips guarded torsos (2026-10-06)

- Cause of the D-70 side effect: every false cut with the GT detector sat on a torso covered by an opponent's box. The cross-team player on half s11 was one mislabelled piece.
- Fix: a changed run where most torsos are more than half covered by another box is not a cut (D-74). New test: an opponent standing in front does not cut a track (fails on 81e1e99).
- Verified on hfbox, same harness, same 9 clips, seeds 7 + 11; the before run reproduced metrics_combined_9b777bb.json exactly:
  - GT-detector basketball MOTA / IDF1 / switches: half s7 0.989 / 0.995 / 3, half s11 0.951 / 0.925 / 9 (never measured before), full s7 0.990 / 0.995 / 2; all three now 1.000 / 1.000 / 0.
  - GT 2-vs-3 points right 22/23 → 23/23; every other M4 row identical.
  - YOLO identity output byte-identical to D-70 (IDF1 0.366 / 0.326 / 0.263 kept).
  - Dev seeds 13/17: GT 1.000 on all four clips; YOLO within ±0.001.
  - box-test ALL GREEN on the committed snapshot (courtcam 192).
- Evidence: docs/evidence/M1/metrics_tracking_v3.json, docs/evidence/M1/README.md "Tracking v3", docs/evidence/M1/eval_tracking_v3/
- Decisions: D-74.
- Left / known issues:
  - The YOLO rows D-70 costs one shot each remain: points right 14 → 13/21, shooter 8 → 7, team 19 → 18, made 10/12 → 10/13. They come from D-70's real YOLO cuts and links.
  - Kennesaw not re-run (the gate input is unchanged).
  - One "before" clip was briefly run with an intermediate file and redone; noted in the README.

## Scene packages for navigable 2.5D replays (2026-10-06)

- Works:
  - worker `scene` stage producing `replay.scene_package.v1` (plates, an atlas video of SAM cutouts, layout.json with the camera envelope and presets)
  - docs/scene-format.md
  - a CPU reference renderer
  - `GET /games/{id}/scenes[/{play}]`
  - tv-core types
  - a synthetic fixture `services/api/fixtures/scene_synth/` (45 frames, 0.7 MB)
- Verified on hfbox:
  - box-test ALL GREEN on the committed snapshot, with the DAG regenerated: courtcam 192, api 225 + 1 skipped, worker 25, render 54, web Playwright 102, tv 50 + 1 skipped.
  - Real footage, local only:
    - Kennesaw: 3 plays through the full worker pipeline.
    - Powell gym: 2 plays.
    - Per play: SAM 105–150 s on the GPU, scene stage 3–28 s; packages 1.3–4.9 MB.
  - Real-camera reproduction, players: 21.5–28.3 dB PSNR, SSIM 0.78–0.92.
  - Real-camera reproduction, plates: 24.6–29.4 dB.
  - Novel views against synthetic ground truth: silhouette IoU 0.685 at the real camera, ≥ 0.95 of that up to a ~13° billboard turn, 0.80–0.91 at 36–40°.
- Evidence:
  - docs/evidence/scene/ (synthetic: eval_synth.json and reference stills of the fixture)
  - docs/evidence/local/scene/ (real stills, local only, D-7)
- Decisions: D-75.
- Left / known issues:
  - The navigable envelope is small on real rigs: Kennesaw ±7.5–12.5° azimuth, +4–7.5° elevation.
  - Large void beside the single backdrop wall.
  - Scorer's table and bleachers are laid flat on the floor.
  - Hoops misplaced on the panoramic rig.
  - Push-in is blurry, and one SAM mask carries a neighbour's head.
  - The caption text on the reference stills overlaps.
  - Fire TV decoder limits are unchecked for the 1920×768 atlas.
  - Viewers (web, native) not built yet. Built in "Free view" below.

## Real volleyball corpus clip (2026-10-06)

- `volleyball_westwashington`: CC BY school livestream, 1080p30, from a fixed elevated whole-court camera.
- 10 hand-clicked landmarks, 1.26 px reprojection error. The projected court lines sit on the painted lines within about 1 px.
- Smoke run (30 s): 17 track ids (refs and benches inside the court margin), 2 teams, 2 rallies, 3 blocks; 86 s wall time.
- Local only (D-76): the players are minors.

## Free view (2.5D) on the TV, web and Fire TV renderers (2026-10-06)

- Works:
  - Free view mode on the Replay screen. Down enters at the angle's time; Back returns.
  - D-pad orbit and dolly with hard envelope clamps, edge bars, a view-limit gauge, the package's honesty label, and presets on Rew/FF.
  - Web renderer in raw WebGL2.
  - Fire TV renderer as a Kotlin GL Fabric view, sharing `camera.ts`.
- Verified on hfbox:
  - box-test ALL GREEN on the committed snapshot: courtcam 192, api 225 + 1 skipped, worker 25, render 54, web Playwright 102, tv Playwright 53 + 3 skipped (TV-17 included).
  - `scene-check.sh`: all 6 shaders pass glslangValidator; camera maths OK.
  - Web against the reference renderer on the synthetic fixture: 41.9 dB / 0.995 on the scene, 40.4 dB / 0.997 on players.
  - Web speed in desktop Chromium on the box: 60 fps on the GPU, 34–37 fps under headless SwiftShader. Indicative only, not a Fire TV.
  - Real Kennesaw and Powell gym packages ran live through the API and passed TV-17's opt-in live test. Envelopes reached: ±6–12.5° azimuth, with Powell's pl_0010 at −7.5…+22.5°. Evidence is local only.
  - Release APK with the native view: `/workspace/wt/replay-viewnative/scratch/replay-tv-scene-release.apk`, built from in-progress JS. Rebuild it from HEAD.
- Evidence:
  - docs/evidence/scene/web/ (synthetic comparison pairs, fps and compare JSON)
  - docs/evidence/local/scene/web/ (real, local only)
- Decisions: D-77.
- Left / known issues:
  - Never run on a Fire TV (checkboxes in docs/fire-tv.md).
  - The native view draws no ball trail and clears to a flat colour.
  - The real camera often sits on the d-max limit, so "farthest" shows on entry.
  - A stale vite server left by an earlier agent held port 5181 for ~3 h, so TV Playwright runs in that window may have reused another copy's server. The tsc/eslint results stand. This run proved the server matched the snapshot, because the new TV-17 passed. box-test needs a port guard. Added by D-78.

## Real-footage E2E recordings with Free view (2026-10-06)

- Works:
  - `make record-e2e-real SPORT=basketball|volleyball` runs the real API and worker pipeline on a 90 s real cut. (Removed 2026-10-20 with the redesign recording; its beats targeted the old UI.)
  - Calibration: the D-72 refusal, then hand-placed landmarks.
  - Then: watch, follow, replay angles, six Free view beats, highlights, review/heatmap, and volleyball rallies/condensed.
  - `REPLAY_WORKER_STAGES` lets uploads get replays and scene packages (D-79).
- Verified on hfbox:
  - Kennesaw basketball: 16/16 beats PASS, 3:04 recording.
    - 6 min 48 s processing.
    - Auto-calibration score 0.61 refused; 14 points placed by hand, 3.3 px fit.
    - Free view envelope: azimuth −7.5…+5°, elevation 12.1…17.1°.
  - West Washington volleyball: 17/17 beats PASS, 4:05 recording.
    - 6 min 28 s processing.
    - Auto-calibration score 0.888 refused; 10 points placed by hand, 2.0 px fit.
    - Free view envelope: azimuth ±17°, elevation 15.6…32.6°.
  - box-test ALL GREEN on the committed snapshot: courtcam 192, api 226 + 1 skipped, worker 25, render 54, web Playwright 102, tv 53 + 3 skipped, scene-check OK.
  - Key frames read by the agent and by the orchestrator.
- Evidence:
  - docs/evidence/local/E2E-real/{basketball,volleyball}/: MP4, beats, frames, worker.jsonl. Local only.
  - Full-quality copies on the box under /workspace/wt/replay-recreal/out-real-*/.
  - docs/evidence/E2E/README.md: text only.
- Decisions: D-79.
- Left / known issues:
  - Basketball Free view:
    - a large backdrop void at the upper right, even at the real preset
    - hoop primitives floating off the real hoops (D-53)
    - ghost streaks and a smeared scorer's table baked into the floor
  - Volleyball Free view:
    - a double net: the model net next to the real one baked flat into the floor
    - a line judge and a spectator smeared into the plates
    - one cutout holding two overlapping players (seen on dolly-in)
  - Kennesaw 130–220 s cut found 0 shots, although the full 240 s run found one at 133 s.
  - 14 volleyball "blocks" in 90 s, likely false.
  - The calibration status shows a meaningless "0.0 px" for template-fit proposals.
  - Recorded WebGL is SwiftShader, so motion is not representative.
  - Broadcast, Search and Tier C are not in the real runs.
  - The restructured synthetic `make record-e2e` was not re-recorded.
- Left / known issues:
  - No audio in the recording, so the Kokoro narration is not heard.
  - The demo games use the synthetic detector.
  - Not a Fire TV.
  - Auto-calibration scored 0.83 (< 0.90) even on the clean synthetic half-court clip.
  - On the replay-angle screen, the "TIER C 3D" stage label overlaps the "REPLAY Shot" header (top left).

## AWS migration: QR upload, cloud API, ReplayCloud stack (2026-10-19)

- Works (D-80, design in docs/aws-migration.md, runbook in docs/aws-deploy.md):
  - TV "Add game": pick a sport, then a QR code of the phone upload page (grid of Views, native and web). The screen shows `host/u/<id>` without the token, then live status until ready.
  - Phone page `/u/{id}#t=<token>`: multipart upload straight to S3 (3 parts in flight, per-part retry), calibration, process, status. No phone app.
  - API cloud mode (`REPLAY_STORAGE=s3`, `REPLAY_JOBS=s3`): S3-mirrored storage, S3 job queue with conditional-write claims, per-game HMAC upload tokens (24 h), `/media` as presigned 302, Lambda via Mangum. Secrets from SSM.
  - hfbox remote runner (`python -m replay_api.remote_runner`) pulls jobs over HTTPS with the worker key, so hfbox holds no AWS credentials.
  - TV Settings has an API key (masked; Gradle `REPLAY_API_KEY` build default from env).
  - `ReplayCloud` CDK stack: Lambda Function URL (python3.12 arm64), private media bucket, CloudFront + OAC for apps/web at `/` and apps/tv web at `/tvapp/`, runtime `config.json`. CDK assertion tests. Estimated about $0.50–1/month.
  - Security review: no critical/high. Fixed: uploads must be ISO-BMFF before OpenCV/FFmpeg decodes them, with a protocol whitelist; `/media` refuses `source.mp4` in cloud mode; the single-request upload returns 409 in cloud mode.
- AWS account (profile `replay`): free plan, $160 credit after the Budgets, Lambda and EC2 activities (placeholders torn down). Budget `replay-monthly-10usd`. SSM SecureStrings `/replay/{api-key,worker-key,upload-token-secret}` created.
- Verified on hfbox: box-test ALL GREEN per commit; api 240 + 1 skipped, worker 25, render 54, web Playwright 105, tv 55 + 3 skipped, infra synth + 5 CDK tests. Lambda zip 169 MiB unzipped. Web builds contain only the committed synthetic mock media.
- Left / known issues:
  - Not deployed yet: `cdk bootstrap`/`deploy` was blocked by the permission classifier and needs the user.
  - Bedrock-playground and RDS credit activities not done (console-only / blocked).
  - Cloud mode: `/sessions` 501, profile photos not in S3, only `process`/`autocalib` jobs, a dead runner leaves its job `running`, last write wins on edits.
  - The TV on-screen keyboard types lowercase only (fine for hex keys).

## Deployed, and the TV redesign waves 1–3 (2026-10-20)

- Deployed: `ReplayCloud` is live (user ran CDK). The hfbox runner forces IPv4 (hfbox IPv6 is blackholed) and runs the worker pipeline; `scripts/cloud-smoke.py` passed end to end on a synthetic `courtcam synth` clip.
- Redesign (D-81), spec and mockups in docs/ux:
  - Wave 1: tokens and Barlow type, focus primitives (`ui.tsx`), immersive Home replacing the library grid, restyled Add game, Settings, Players and Profile.
  - Data: `storyboard` and `moments` worker stages, readiness and ETA fields, hero art, `/moments`, `/storyboard`, resumable phone uploads, early media push from the runner.
  - Wave 2: the player. Court-line timeline with moment notches, tap and hold-to-seek tiers with sprite previews and moment snap, Rew/FF scrub, Moments row with filters, Highlights and Condensed as ways to watch (the Highlights and Rallies screens are gone), layered Back, 5 s auto-hide, a placeholder Do more row, 10 s polling while processing.
  - Phone handoff that works on AWS: `POST /games/{id}/phone-link` mints a 24 h per-game phone token (a separate HMAC kind from the upload token; neither opens the other's routes) and the phone URL `{web_base}/p/{id}?job=..&t=..#k=<token>`. The token opens one allowlist (`auth.PHONE_ROUTES`): reading the game, clips and the 9:16 export, tagging players to name-only profiles, review answers and search; never uploads, processing, other games or biometrics. The phone page `/p/{id}` has Clip, Tag, Review and Search tabs, no WebSocket. The TV QR encodes the API's URL and never shows the token. `GET /config` exposes the public web base.
  - Fire TV resume positions persist in SharedPreferences (generic string get/set on the ReplaySettings module), written at most every 5 s and on pause or leave, 50 games kept.
  - The hfbox runner no longer logs presigned S3 URLs (httpx at WARNING, paths only, redacted error messages).
  - Re-recorded E2E video for the redesign (`make record-e2e`): docs/evidence/E2E/replay-e2e.mp4, 4:06, 6.4 MB, 20/20 beats passed against the real API and worker on synthetic footage. The phone context opens only links decoded from the TV's QR codes. Covers Add game by QR, upload, calibration, processing (19 s), the player (seek tiers, previews, FF, Moments, Highlights, Condensed), Do more (follow, 11 angles, stats, commentary), the phone Clip/Tag/Review pages with the edits showing on the TV, and Resume. The demo games now build with the `storyboard` and `moments` stages. No Free view beat: `box-demo.sh build` doesn't run the opt-in scene stage.
  - Fixed: opening a game watched to within 5 s of the end resumed there instead of starting over (the player now uses Home's resume rule).
  - Wave 3: the Do more layer inside the player. Tiles scroll within the safe zone (Follow player, Angles, Free view, Watch, Stats, Commentary, On your phone, Bookmark); follow chips with a "Following" chip; angles and Free view play in the player and return at the same time; a Stats side panel over playing video (box score, shot chart, review, tips); a phone QR panel for Clip, Tag, Review and Search; resume position saved every second, and Home offers "Resume m:ss" and "Start over". The Replay screen is gone (`/replays` links open the player).
- Verified on hfbox: box-test ALL GREEN per commit; api 246 + 1 skipped, worker 28, render 54, web Playwright 107, tv 79 + 3 skipped (new TV-19 to TV-29). TV specs also ran 3–4 times over with no failures after fixing several player startup races (a key pressed before the opening seek or a source swap landed was undone).
- Left / known issues:
  - Lambda redeploy with the new API fields and web builds is built (`infra/build`, `infra/cdk.out`) and waits on the user.
  - The courtcam-direct fallback makes no storyboard or moments; older games need a re-run for thumbs and hero art.
  - Every angle thumbnail shows the same storyboard frame (no per-angle poster from the API).
  - Phone page: 16:9 "clips" are the wide video with a time range, not a rendered file (only 9:16 renders); Tag lists profiles already linked; `GET /profiles` is open to phone tokens, so a phone link shows profile names (no photos or biometrics).
  - The `/companion` pairing page still needs the `/sessions` socket (501 in cloud mode); the TV no longer points at it.
  - Mock media is SMPTE colour bars; not yet tried on a real Fire TV.
- Real game in the live library (2026-10-21): game `g_c8b6186280ac`, "Nottingham vs Barking Abbey (CC BY, Super League Basketball)". It is the CC BY 3.0 Q1 cut of `basketball_nottingham_widecam` (attribution in docs/test-data.md §3.1; footage stays on the box), driven through the live API from hfbox like the phone does it. The title uses a no-break space in "CC BY" so the hero breaks into 2 lines (Barlow SemiBold 72 px in 1100 px) instead of 3.
  - Timings: create + 5-part multipart upload of 67 MB in 6 s; autocalib 41 s; processing 261 s from `process` to `ready` (runner on the shared GPU).
  - Calibration: the auto proposal was ok=false (0.75 < 0.9, the court template on the far wall) and was not used (D-72). Hand landmarks were placed on a median frame and refined with dark-line crossings along rows and columns. There are 13 points, including the near rim, with no ground truth. Lens k1 -0.415, lens RMS 3.66 px, API reprojection error 9.56 px (gate 16.7). The projected template follows the black main-court paint: the sidelines, the centre circle, both 3-point arcs, both keys and the far no-charge arc. A 26 or 27 m court fits worse, so the court is FIBA 28 × 15.
  - Outputs: watchable, hero art, a 2-sheet storyboard, renditions wide and broadcast (`players` empty), 45 events (17 shots, 17 possession changes, 11 turnovers) and 33 moments with thumbs.
  - Quality, honestly: the hero and the storyboard are good live-play frames. At 142–145 s a detected shot does show a shot or rebound scrum at the left key. The 13 s "missed three" lands on a stoppage. No shot is marked made, so there is no score. Identity fragments into 59 players for about 13 people on court. Both team colours come out dark red/brown (#57282A, #402B28), although one team wears red and the other dark, so the team split and the per-team stats are unreliable. The far-side players are 30–60 px tall on this low action cam.
- Backend pass (2026-10-22): media caching, the opt-in stages on AWS, the user's clips as moments, and a highlight reel. Lambda redeploy and a runner restart (docs/aws-deploy.md §5) are still to do.
  - Media caching: `/media/{game}/{rel}` signs S3 URLs at the start of a `REPLAY_MEDIA_SIGN_WINDOW_S` window (default 3600 s, valid for 2 windows), so the same object gets the same URL for an hour. The 302 carries `Cache-Control: public, max-age=<seconds left>`. Image URLs carry `?v=<etag>`, and S3 serves them `immutable`. Before (live, from hfbox): every fetch got a new signature and no Cache-Control; 302 83–130 ms, total 250–500 ms per thumb, hero or storyboard sheet. The after numbers need the redeploy (moto test checks a back-dated signature is served).
  - Opt-in stages: the worker pipeline runs the default stages, then each `REPLAY_WORKER_STAGES` stage plus `moments` as its own run, so a failed extra leaves the game ready. Condensed now works for basketball (shot/turnover/block plays). `/rallies` and `/hype` read the stored outputs when Lambda has no render code. `COURTCAM_ASR_MODEL` passes through, so voice triggers work on the runner.
  - The user's clips as moments: triggers and clips become `bookmark` moments "Your clip (voice)" / "Your clip (X sign)", with additive `trigger` and `clip_id` fields.
  - Highlight reel: `POST /games/{id}/exports/reel {aspect}` (16:9 or 9:16) plans the user's clips first, then top plays (≤ 90 s), and renders captions, "TOP PLAY i/N" tags and dips to black. The 9:16 cut follows the key player. Job kind `reel:<id>`; runner stage `reel`; phone link job `reel`.
  - Verified on hfbox, local mode, synthetic clip (`courtcam synth` basketball 30 s, TTS "Replay, clip that"): all features ready in 582 s (SAM replays about 100 s a play). The voice trigger at 24.6 s became a "Your clip (voice)" moment. The X sign was missed with YOLO-pose on the synthetic mannequins (known), and found with ground-truth poses. Reels 18 s in 6 s each, h264/aac 1280x720 and 720x1280; frames checked (tags, captions, 9:16 framing on the shooter). api+worker 288 passed, 1 skipped.
  - Real game (local copy of `g_c8b6186280ac`, runner env): default stages 51 s, hype 9 s (6 candidates), condensed 81 s (28 plays; 241 s cut to 175 s, so not much shorter, because plays cover most of this game). Reels of 28 s, 4 top plays (2 steals, a 3-pt shot and a 2-pt shot), in 8 s each. The 9:16 cut keeps the ball handler in frame. No triggers on this footage, so no user clips. The long game title overflowed the caption; `caption_sprite` now cuts it with an ellipsis (this also fixes the 9:16 export).
  - Left: in the voice segment the caption names the overlapping play ("#P10 · 2-PT SHOT"), not the clip. Tier C stays out. Without `botocore.auth.get_current_datetime` (old botocore), URLs fall back to a fresh signature each time.

## Alexa backend and skill package (2026-10-22)

- `POST /alexa` is the Replay Court custom skill endpoint (dev stage, no account linking). Requests are verified with `cryptography`'s web-PKI verifier plus an RSA-SHA256 check of the raw body, the timestamp within 150 s and the skill id from SSM `/replay/alexa-skill-id`.
- Intents:
  - Pair (4-digit code from `POST /tv/pair`, 5 tries) links the Alexa userId to the TV.
  - ExportReel writes `export_reel` and queues the reel job.
  - ClipThat writes `clip_that` at the TV's heartbeat time, extrapolated while playing.
  - Launch, Help, Stop and Fallback give short answers that say the real state.
- The TV side is `/tv/state` heartbeats, a 1 s `/tv/commands` poll and acks. State is small JSON docs under `alexa/` in S3 (local: `data/alexa/`).
- The skill package is in `alexa/skill-package` (en-US, invocation "replay court", endpoint = the Function URL with the wildcard-cert option). Runbook and TV contract: docs/alexa.md.
- Verified on hfbox:
  - api 286 passed, 1 skipped, including 26 Alexa tests: a self-made CA, valid/bad signature, stale timestamp, wrong or unset skill id, 9 bad cert URLs, wrong SAN, expired cert, missing intermediate, and the pair/command/ack flow in local and moto S3 mode with the SSM skill-id lookup.
  - Amazon's real echo-api-cert-9..12 chains pass the verifier at their validity dates and are rejected now (expired).
  - ruff clean.
- Left:
  - The user does the console setup and the `put-parameter` (docs/alexa.md §2–3), then a Lambda rebuild and redeploy.
  - The TV side of the contract (pair panel, heartbeat, poll, `reel` phone job, long-press fallback) goes to the TV agent.
  - Untested on hardware: the Function URL accepted as a wildcard-cert endpoint, and Fire TV Stick voice reaching a dev skill.

## Angles and POV for every upload (2026-10-22, D-84)

- Root causes: the hfbox runner had no `REPLAY_WORKER_STAGES` (no upload got replays), the TV hid Angles/Free view when the nearest play had none, Tier B and Tier C shared the `broadcast_high` id, and a POV could show another player's eyes.
- Fixed: stages default on (`hype,condensed,replays,scene,tierc_manifest`), a virtual POV per 3D player (`pov:<pid>`), `3d:` ids, Angles tile always in Do more, Player POV tile and chips, POVs share one cut slot (Up = next player), Moments "▼ Angles". Web Replay screen uses the same cut order.
- Measured on hfbox, full extras forced: CC BY basketball (241 s) 693 s wall; local-only volleyball (240 s) about 13 min of stage time (21.6 min wall under box contention). 17–21 angles per play, scenes for Free view.
- Evidence: TV web build against a local API on both real games (angles row, POV chips, next player, Free view orbit, Moments link). Volleyball screenshots stay local (D-76).
- Left: user redeploys the Lambda (CDK), restarts the runner with the stages unset or set, and re-POSTs `/games/g_c8b6186280ac/process` to backfill the live game. Tier C team colours on real footage are approximate.

## Follow player: client camera, pick on the video (2026-10-22, D-82)

- Root causes: 59 short-lived track ids for about 10 players, so chips offered players who were not on court. The server crop path parked the camera on empty floor after an id ended. The camera only started after a ~2 s fetch. The ring ran at track rate, not frame rate. The clock jumped forward by the length of a pause after Play.
- Fixed:
  - tv-core `createFollowCam`: a spring camera with lead, eased zoom, a hold and widen through gaps, and conservative hand-offs.
  - PlayerSurface: one animation-frame loop moves the camera and the ring, sending only changed values. The ring has grace, fade and a hand-off ease.
  - Follow player: markers on the video, arrows move spatially, Select follows, Back cancels. Labels are the name or "Player N", in team colours. When the player is lost the chip says "Lost sight of X", and Select picks again.
  - Clock: no time jump after a pause.
  - Watch exposes `followedId` (and `data-followed`) for the player card.
- Tests:
  - tv-core unit tests in core.spec (camera motion and lead, hand-off cases, gaps, clock).
  - TV-25-follow-pick replaces TV-25-follow-chips: it measures ring and camera response under 200 ms and checks the ring stays steady with no flicker through a gap.
  - TV-01 and TV-03 updated.
- Real games:
  - Fire TV, CC BY basketball: ring and "Following" are on the first frame captured after Select, and the camera is zoomed in by the next capture. Jank is 0.5–0.8% in wide playback and 8–15% while following a moving player.
  - Offline over 60 picks × 30 s on basketball and the local-only volleyball clip: the box is always inside the camera window. The ring is on 68% / 74% of the time; the rest is real track loss.
- Left:
  - Server-side re-identification (merging tracklets) is needed for continuity over minutes.
  - The `crops` stage output is unused by the TV.
  - The mock's motion is too small for an e2e pan check (the unit tests cover panning), and its 1 s gap is under the 1.5 s "lost" threshold, so the "Pick again" flow is checked on device and in the unit tests only.

## TV text centring and UI polish (2026-10-22, D-85)

- Root cause: Barlow plus Android font padding put text low in every rounded rect, by 1.5–2.5 px on the Fire TV. Fixed in `T` (ui.tsx), so every label in the app is corrected.
- Polish found on the real games:
  - Moments filter chips slide to keep focus on screen.
  - Moment thumbnails have rounded corners, and labels have a shadow.
  - Review box score is capped at 10 rows plus "and N more", with "Player N" names and wider columns.
  - Five screens now sit in the safe zone.
  - Radii are consistent, and badge fills are on Views.
- Tests: new TV-33 (pixel-measured centring and the chip slide). TV suite 109 passed, 3 skipped. Before and after captures were taken on the Fire TV.
- Left (other owners): the Do more follow-chip row clips its last chip, the ghosted transport title under top layers, Profile badges, and Players/Profile on `ui.screen`.

## Player card on Menu (2026-10-22, D-83)

- Menu (≡, web `m`) while following opens a player card on the right; it pauses the game, and Back resumes it. Elsewhere Menu still opens Do more. Do more → Follow player → Player details opens the card for the focused player.
- The card shows the avatar (profile photo, initials, or the track number), the name or "Player N", the team swatch, and a "This game" stat line (tv-core `statLine`). Actions: Edit name, Follow / Stop following, Their moments (N), and View profile.
- The stat line is counted from the game's events.json, by event type. A stat no event credits is listed as "Not detected", never shown as 0.
- Names save through the existing `PATCH /games/{id}/players/{pid}`. The API now trims names and caps them at 60 characters (needs a Lambda redeploy; the card works on the live API without it).
- Also fixed:
  - Review showed "Review queue (0) / Nothing left to review" while its request was in flight. It now says Loading, then shows 32, matching the Stats panel.
  - Why the request was slow: on a fresh Lambda instance, `/review/queue` pulled the whole game from S3 (`game_dir`, one GET per object), about 17 s against about 2–4 s for `/stats`. It now pulls only events.json and tracks/, like `/stats`. Needs a redeploy. The test_cloud regression test fails on the old route.
  - Back from View profile (opened from the card) is one press: it returns to the card on the same player, paused at the same time, still following. The card's Back then plays on.
  - Stats that are not detected collapse into one line, "Not detected yet: …", under the cells. On real volleyball most cells are missing, so the card reads as one count plus that line, not as a broken grid.
  - The Stats shot chart takes the free height.
  - Unfocused Stats exits are visible.
  - Profile badges are on Views.
  - Players and Profile are in the safe zone.
- Tests:
  - TV-32: 7 tests on synthetic fixtures, including a failed name save (the mock answers the PATCH with a 503: the card says "Couldn't save the name (503: Service Unavailable)" and keeps the old name) and the one-press profile Back.
  - e2e-evidence/PCARD-real: run against a local API on real games, a local-only volleyball clip and the CC BY basketball. It passed twice on each.
  - Gate: TV 113 passed, web 115, API 288 passed with 1 skipped.
- Fire TV, live CC BY game:
  - The card shows Shots 2 / Reb 0 / Stl 1, and D-pad focus moves through the actions.
  - Back resumes the game.
  - The new Stats and Review screens were checked on the device.
- Left:
  - No jersey numbers in the data.
  - On real volleyball the pipeline credits blocks only, not contacts or serves.
  - The name-save error path is untested on the device: making the PATCH fail would take a wrong API key or a cut network.

## Cloud API pulls only what each route reads (2026-10-22, D-86)

- Every API route that read a game on S3 through `game_dir()` mirrored the whole game on a fresh Lambda instance. Each route now names its files (`game_dir_with`): hype, rallies, condensed, vertical exports, score, commentary, search, review queue, profile careers, face match, and the player, event, bookmark, tap, trim and score writes. Commentary's per-play audio checks share one LIST. Whole-game pulls stay only in the hfbox runner and local mode's in-process tasks.
- Live API before the redeploy:
  - Warm, a Watch open is 9 requests at 0.3–0.6 s each. `/hype` and `/rallies` answer 503 for this game: no stored hype.json or condensed.json, and Lambda has no `replay_render`.
  - On fresh instances: `/hype` 10.7 s, `/commentary` 8.4 s, `/review/queue` ~17 s; `/moments` once 1.0 s.
  - Five Watch opens at once (45 requests) got 429s. The function has no reserved concurrency, so the account's concurrency quota is the limit.
- Tests: test_cloud adds 19 moto cases (Watch, Stats and Review reads; exports; five writes; folder coverage); 12 of them fail on the old code. API suite 308 passed, 1 skipped; ruff clean.
- Needs a Lambda redeploy.

## TV/phone clients: throttle retry and fewer requests on open (2026-10-22, D-87)

- TV and phone clients retry a throttled request (429, or a 503 that says throttle) up to 4 times within ~4 s with jittered backoff, honouring Retry-After, only for safe-to-repeat requests. Our own 503 "not available" is not retried, and for `/hype` and `/rallies` it is not asked again that session.
- At most 4 API requests in flight per app. Watch sends replays, commentary, hype and rallies after the first frame (or 3 s). Clips' export poll is 3 s, not 1 s.
- Watch open, web build: before 11 requests, peak 7 in flight; after 11 requests, peak 4, with the extras after the first frame (539 ms vs 310 ms).
- Tests: TV-35 (8 cases) pass. Box gate: ruff clean, API 308 passed / 1 skipped, web Playwright 115, TV Playwright 124, tsc and eslint clean.
- Fire TV: new APK installed; the live CC BY game opens and plays, Do more shows (Angles: "No replay angles for this game"), no JS errors in logcat.
- Not done: network errors are not retried; Retry-After is unreadable cross-origin without an expose header. Needs a new APK and web deploy, no Lambda change.

## Follow accuracy (2026-10-22, D-89)

- Back takes the follow ring off at once. The ring and camera run on the native driver (Fire TV jank while following: 6.6-14 % vs 30-34 % JS-driven). The chip no longer says "Lost sight of" right after Select on a paused picture. Do more chips run to the screen edge.
- courtcam cuts tracklets where the person changes (body look) and gates merges by look. Kit check, 120 follows × 30 s:
  - Nottingham: ring on the wrong kit 22 % -> 16 %.
  - Volleyball (local only): 20 % -> 14 %.
- Games with up to 6 people on court are solved as that many people. On the new CC BY 2v2 park proxy with a hand-checked GT (4 people, 120 s): 21 ids -> 4, and the ring on the right person 47 % -> 83 % of a 30 s follow. The tracks' boxes sit about 3 px from the person: no lag in the data.
- Tests: courtcam 23 identity tests (synthetic swaps, roster), full suite green. TV Playwright subset 52 passed, tsc and eslint clean.
- Needs: reprocessing the live game (new courtcam version), a new APK. Not done: same-kit teammates in a full game (needs numbers or a licence-clean re-ID model), and display lag measured on the device.
- Round 3: small games are labelled box by box, and a box that is no one's has no id. On the 2v2 proxy (1000 follows × 30 s, scored while the person is on screen): ring on the right person 89.9 % -> 93.7 %, on someone else or no one 17.5 % -> 6.4 %. `game.json` `tracks.people` turns off the TV's hand-off to another id. With it on, the hand-off doubled the wrong time. DINOv2 crops and the detector's raw boxes were measured and not kept. The 95 % / near-0 target is not met: about 4 points are boxes on no one (merged or part boxes).

## Score and highlights from the ball (2026-10-22, D-90)

- Hand annotations as evaluation truth: `samples/truth/nottingham_q1.json` and `nottingham_q3.json` (CC BY; Q3 is the hold-out), plus `cc3x3_usti.json` (CC BY 3x3 proxy, 3 shots). Each is checked against the in-arena scoreboard. Score a game with `courtcam eval-events -o GAME --truth FILE`.
- Shots and makes now come from the ball at the rim (`courtcam/ball.py`: classical CV, no model). Also new: team by basket on a full court, free throws from a still scene, points by `profile.scoring` (pickup `to: N` restarts the score).
  - Q1: shots P/R 0.24/0.40 -> 0.90/0.90; make/miss 0/1 -> 8/9; score error 7 -> 2.
  - Q3 hold-out: shots P/R 0.14/0.38 -> 0.80/1.0; make/miss 0/1 -> 7/8; FTs 1/4 -> 4/4; score error 1 -> 2. The baseline's 1 was luck.
- Highlights: the hype meter adds the detected makes, blocks and steals. Q1 top-5 precision 0.2 -> 0.4, made field goals in the top 5 1/3 -> 2/3. Q3 has a single made field goal, which was missed, so 0 -> 0.
- Play logs (docs/playlog.md): CSV or JSON. `courtcam notes -o GAME --from FILE` stores the uploader's notes; the moments API shows them as "Your note: …" (source user), never mixed into events or score.
- The 2v2 park proxy was not scored: the ball is not found at its far rim (sky behind, heads across it). Filming guidance is in D-90.
- Events stage 43-47 s per 240 s 1080p30 on hfbox CPU. No new model or dependency.
- Needs: reprocessing the live game (new courtcam version) for the score and highlights to change on the TV. Not done:
  - a miss and its put-back within 1 s merge into one shot;
  - a camera re-aim reads as a shot;
  - a notes upload route in the API (CLI only);
  - a per-game scoring override.

## Demo readiness walk (2026-10-22, D-91)

- Every demo beat was walked on real games:
  - the CC BY Nottingham game;
  - the volleyball game (local only);
  - a fresh 45 s upload, Add game → phone upload → calibrate → 13 stages in about 40 s → Home.
  - Status per beat, evidence and the morning list are in docs/demo-readiness.md.
- The Fire TV was checked on the live API and the round-4 APK: open, follow, card, Stats, Review and Advice work. Free view, POV, Watch ways and Commentary wait for the Lambda redeploy and a re-process.
- Fixed:
  - Back from Review/Tips reopens Stats.
  - Back from Highlights/Condensed goes to the full game.
  - The Highlights count matches the reel.
  - The phone clip default is the play (7 s, not 0.5 s).
  - The phone has a Reel tab for the highlight reel, plus a TV phone-panel chip.
  - Unnamed players read "Player N" on the phone.
  - Home puts games waiting for an upload last.
  - Calibration dots are numbered.
  - The phone tab bar stays on one row.
- Tests:
  - Web Playwright 108 passed, 1 skipped.
  - TV Playwright 124 passed, 3 skipped.
  - tsc and eslint clean.
  - Updated or added: TV-22, TV-27, TV-28, TV-29, S-60 Reel and momentClip.
- Routed to other agents:
  - follow: few boxes in Select, fragments, framing;
  - events: no makes, review noise, 0.5 s windows, skewed distance advice;
  - angles: near-empty Free view/Tier B, POV clipping, identical thumbnails.
- Not done:
  - Alexa commands on the TV;
  - TV name presets;
  - reel rendering end to end (runs on the runner);
  - docs/demo-script.md still describes the synthetic build.

## Score round 2 and demo-walk events items (2026-10-22, D-92)

- Make or miss at the rim's edge is now "can't tell", not a miss; the Review queue asks it first. This covers the Q3 156 s make called a miss.
- No more false shots from a camera re-aim (Q1 236 s) or a body under the rim (3x3 11.0 s).
- The put-back at Q1 36 s was not a merge: the first miss is never seen at the rim.
- Results (full table in D-92):
  - Q1: shots P 1.0, R .90; labelled make/miss 1.0.
  - Q3: P .80, R 1.0; make/miss 1.0; highlights P@5 0 → .2.
  - 3x3: P 1.0, R 1.0; makes P 1.0, R 1.0; score error 4 → 2.
- New hold-out, 2v2 park (`samples/truth/basketball_2v2park.json`, 10 attempts, 3 makes), ball only:
  - The played rim is at top right; the round-1 brief named the far rim.
  - Shots P 1.0, R .80; make/miss .714; makes P .60, R 1.0.
  - Two wrong makes come from the camera standing beside the post.
- Highlights rank detected plays first. A pickup 1-point make counts as an inside make; a shot of unknown outcome counts half.
- `POST /games/{id}/notes` loads a play log as notes (docs/playlog.md). Notes are never merged into events.
- Demo walk:
  - Review asks at most 12 event questions, only ones that change score or stats: no inbound or 0:00 items, steals and rebounds named.
  - Steal and rebound moments span 4 s before to 2 s after.
  - Advice compares distance only among well-covered players.
- No new model. Ball scan 15 s per 120 s 1080p clip with one hoop.
- Not done: automatic rim finding, a learned ball detector, arc tracking, make or miss from the net. The live game needs a re-process for these to show on the TV.

## Score round 3: tap the hoop, settle "can't tell" in Review (2026-10-22, D-95)

- Phone calibration has a one-tap "Tap the hoop" after the fit (`rim_top`). The ball is watched at the tapped hoop.
- Review asks "Make or miss?" first. On the TV, "Watch it" opens the play 4 s early and Back returns to Review; the score refreshes after each answer.
- A pickup 1-point make is labelled "Basket", not "Free throw".
- Tried and rejected (numbers in D-95):
  - make or miss from net motion (a rim hit shakes the net as much as a make);
  - a put-back visit split;
  - a static-blob filter.
- New park development set, `samples/truth/basketball_2v2park_dev.json` (11 attempts, 5 makes). Ball only: shots P 1.0, R .82; make/miss .667.
- Highlights P@5 is unchanged (Q1 .4, Q3 .2). The ceilings are .6 and .4, and the gap is unknown outcomes plus no block detector, not ranking.
- Needs: web deploy for the hoop tap, APK for "Watch it", and a re-process for the label fix.

## Demo walk round 6: reel, Play on the TV, every stage on a fresh upload (2026-10-22, D-93)

- Demo script rewritten for the real demo (docs/demo-script.md):
  - 3–4 people on a half court in distinct colours, a phone on a tripod, uploaded live;
  - beats with remote keys, what the audience sees and a fallback for each;
  - filming rules from D-89/D-90; calibration dots dragged by hand.
- Reel end to end on Nottingham: 9:16, 28 s, 5 segments, rendered in about 10 s.
- "Play on the TV" from phone search now works on Fire TV and live (HTTP command queue). Rule search finds steals and rebounds, and hit labels read "Player 12 steal".
- A fresh 45 s CC BY upload on a stack like the runner's (`REPLAY_PIPELINE=worker`, default opt-in stages):
  - ready in about 4 min;
  - thumbnails, 9 Do more tiles, 9 angle cuts, Free view, Player POV, Highlights and Condensed.
- Phone Tag list hides short tracks and the card hides a mixed kit's team, once courtcam adds `seen_s` and `team_mixed`.
- Tests:
  - API 66 in the touched files, full suite run separately;
  - web Playwright 109 passed (1 skipped);
  - TV Playwright 125 passed (3 skipped);
  - tsc, eslint and ruff clean.
- Routed: the reel captions say "#P18", not "Player 18" (render/replay_render/gamedata.py).
- Needs: Lambda redeploy, APK, web deploy, runner restart.
- Court fit fail-safe (D-94): a fit the people disagree with (position or height) is `court.trusted: false` and filters nobody. Autocalib is still wrong on half-court phone frames. Players carry `seen_s` and `team_mixed`; follow-cam zooms in a little at the frame edge; Fire TV ring lag measured at 0–90 ms (no retune); ghost-box check measured, not built (D-89 round 4).
- Second 2v2 check (D-89 round 5): there is now a hand-checked GT for the JaiArtHub clip. Before the fix the follow-cam was on the right person 48 % of the time; now it is 64 % (park: 94 %). People across the park no longer count toward a small game's size. The rest of the gap is outfits (three black tops), so the filming guidance now says: different tops, and calibrate by hand. The follow-cam edge zoom now applies to the sides only, with a little slack; the TV suite passes (127, 3 skipped).

## Virtual views from the real players' pixels (2026-10-22, D-88)

- Tier C is image-based now (`avatars/imageview.py`). Each tracked person is their own SAM cutout, stood at their tracked foot point on the reconstructed court. It fades to a kit-colour silhouette past 35–75° from the real camera, and out within 3 m of the virtual camera. Courts and walls the camera never saw are flat median colours.
- Angles are wing, courtside and baseline (only within 60° of the real camera), plus POVs for the key player and the 5 nearest them. A POV hides its owner and never looks up more than 20°.
- Every frame is labelled "VIRTUAL VIEW". TV badge "Virtual view"; the POV line reads "the real players placed on a reconstructed court, not a camera".
- Free view and Tier B now show every tracked player. Before, SAM lost players mid-chunk and players who walked in were not prompted. Masked player-frames:
  - Nottingham play: 73 % -> 99.8 %.
  - Re-processed plays: 2310/2315 and 2412/2412.
  - Volleyball: 2649/2650 and 2780/2782.
  - 3x3: 524/525.
- Each angle has its own poster jpg (middle frame); the Angles row shows it instead of one shared frame. The row stays on the play it opened on while the video plays under Do more (the volleyball row had swapped plays and POV names mid-browse).
- Unnamed players read "Player 18" in reel captions and broadcast overlays (was "#p18").
- Times on hfbox, per game of four highlights:
  - Nottingham: SAM 116 s, Tier B 45 s, Tier C scene 215 s, 32 renders 202 s.
  - Volleyball: 119 / 56 / 160 / 263 s.
  - 3x3 proxy, two highlights: 23 / 14 / 30 / 58 s.
  - A 240-frame POV: 20.2 s -> 4.3 s after the blur, blend and mask-cache fixes.
- Proxy for the demo scenario: the fixed shot of a CC BY 3.0 3x3 game (Honza Nový), lens-corrected, with hand landmarks (docs/test-data.md 3.1b).
- Evidence: web-build Playwright `ANGLES-real` on the 3x3 proxy and Nottingham (angles row, Tier B cut, virtual wing, POV and Up, Free view, moment link) passes.
- Not done:
  - no articulated proxy, so wide angles become silhouettes;
  - a POV under the basket looks at stand-in walls;
  - an outdoor clip gets plain stand-in walls;
  - the stylized avatar renderer is kept for camera paths only;
  - Tier C files from older runs stay on disk (not in the manifest).
- Needs: runner update and re-process for the new angles, posters and masks; APK and web deploy for the TV changes; Lambda redeploy for poster signing.
