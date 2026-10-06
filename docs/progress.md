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

- Works: hfbox measured and documented (RX 9070 XT 16 GB, ROCm 7.2, torch 2.14; rsync laptop↔box 1.4–1.9 MB/s; YOLO11n 8.1 ms/frame, YOLO11m 10.7 ms/frame) in docs/compute.md. `services/worker` stage DAG over a content-hash cache wraps courtcam's nine stages with byte-identical output. Ten providers selectable local/aws with AWS stubs. CDK skeleton synthesizes without credentials; CI workflow; `make sync|test|demo`.
- Verified on hfbox: `scripts/box-test.sh` on HEAD + platform changes → ruff clean, courtcam 99, api 108, worker 10 passed, `cdk synth` ok, web tsc/eslint clean, Playwright chromium+live 62 passed. `make demo` → 9 misses then 9 hits. Kennesaw 240 s through the worker: 76.4 s cold (3.1× realtime), 1.4 s warm.
- Evidence: docs/evidence/M2/worker-cache-synthetic.txt · docs/perf.md
- Decisions: D-34 worker + cache, D-35 provider layout, D-36 courtcam subtree split.
- Left / known issues: no real fan-out stage yet (first ones arrive with per-play / per-angle work); Step Functions machine is a placeholder chain; local tts/llm/embeddings/face/speaker raise NotConfiguredError until models land.

## M1 — Synthetic generator v2 + tracking metrics (2026-10-06)

- Works: `courtcam synth` renders 5 scenes (basketball half/full, pickleball, badminton, volleyball) with articulated mannequins, ballistic ball, scripted plays, X-gesture/voice/tap triggers, Kokoro voice lines and crowd/contact audio; exports labelled-synthetic GT per the contracts. `courtcam eval` scores CLEAR-MOT/IDF1 + court error. Research pass: every repo on the list checked for URL/license/activity/ROCm (docs/research-log.md, docs/licenses.md); models installed and benchmarked on hfbox (docs/models.md); 5 CC BY clips (basketball, pickleball, badminton) on the box (docs/test-data.md).
- Verified on hfbox: courtcam pytest 157 passed (goldens match), api 110, worker 11, ruff clean (staged snapshot). YOLO pipeline on synthetic, players MOTA / IDF1: basketball half 0.66 / 0.44, full 0.47 / 0.49, pickleball 0.98 / 0.99, badminton 0.99 / 0.99, volleyball 0.86 / 0.86; GT detector 1.0 everywhere. Whisper-small heard the voice trigger in 8/9 crowd-noise mixes.
- Evidence: docs/evidence/M1/synthetic_basketball_half_yolo_overlay.{mp4,png} · docs/evidence/local/M1/pickleball_legacypark_240s_overlay_M1.mp4
- Decisions: D-38, D-39, D-40, D-41.
- Left / known issues: basketball YOLO tracking weak on small bunched players (IDF1 0.40–0.49); foot-point bias ~0.2 m; no CC volleyball footage; ASR untested on real game audio; ultralytics (AGPL) must become an optional extra before the courtcam split.

## M3 — Fire TV client (2026-10-06)

- Works: `apps/tv` (react-native-tvos 0.87 + react-native-video) at parity with the browser TV route: Library; Watch with seek-bar event markers, select mode with D-pad cone focus and overlap cycling, transform-based follow, spotlight, court inset, tag/rename, bookmarks; Highlights reel; Review; Pair. Shared logic in `packages/tv-core`, used by apps/web and apps/tv.
- Verified on hfbox: apps/tv `tsc` + `eslint` clean, `playwright test --project=tv` 11 passed; apps/web `tsc` + `eslint` clean, Playwright chromium+live 62 passed. Gradle `assembleDebug` + `assembleRelease` → arm64/armv7 APKs (leanback launcher, targetSdk 36), box-only at /workspace/wt/replay-tv-scratch/apk/.
- Evidence: docs/evidence/M3/tv-synthetic/01..09.png (synthetic game) · docs/evidence/local/M3/tv-real-kennesaw/ (real footage, not committed)
- Decisions: D-37.
- Left / known issues: never run on a device or emulator (no KVM, no Fire TV attached) — playback, key codes and performance on Fire OS unverified; API base hardcoded in apps/tv/app.json; release signed with the debug keystore; Highlights reel plays wide only.

## M4 — Events + plays (2026-10-06)

- Works: pose stage (YOLO11m-pose on upscaled track crops, GPU, per chunk, cached), audio stage (16 kHz WAV + full-quality copy, onsets, loudness, hype), pose-based basketball shots with 2/3 points and make/miss, possession changes with cause, turnovers, net-sport rallies with serve/point/contacts, volleyball blocks (no GT), play grammars → plays.json, score.json with API corrections (`GET/POST /games/{id}/score`, `GET /games/{id}/plays`).
- Verified on hfbox (staged snapshot): courtcam 171, api 123, worker 15, render 20 passed, ruff clean. 9 synthetic clips (synthetic detector + GT poses): shots P 0.96 / R 0.85 (2 vs 3 pts 23/23), possession P 0.83 / R 0.80, plays P 0.83 / R 0.79, contacts P 0.91 / R 0.89. With YOLO detect + YOLO pose on synthetic video: shots R 0.19, rallies P 0.97 / R 0.88. Real: badminton 240 s rallies P 1.00 / R 0.86 (motion-only); Kennesaw shot precision ≈ 0.4–0.6 on a hand check of 10.
- Evidence: docs/evidence/M4/timeline_synthetic_*.png · docs/evidence/local/M4/ (real timelines + hand-check crops)
- Decisions: D-49, D-50, D-51.
- Left / known issues: YOLO-pose shot recall on small players; possession causes unreliable on real footage (identity fragments); contact hitter/side attribution weak (volleyball attack P 0.30); net-sport auto score needs point `winner_side`.

## M5 — "Replay, clip that" (backend) (2026-10-06)

- Works: gesture (X overhead held ≥ 0.8 s), voice ("Replay, clip that / clip <name>", whisper-small) and tap (`POST /games/{id}/triggers`) triggers resolve to the play that just ended and produce attributed clips; `GET /games/{id}/clips`, `PATCH /games/{id}/clips/{id}` trims (source user).
- Verified on hfbox: synthetic with GT poses — gesture 22/22 (who 22/22, clip right 16/22), voice 37/37 (named subject 18/18, clip right 31/37), tap clip right 10/14; resolution rule exact on GT plays 73/73. Real footage: 0 false triggers in 480 s.
- Evidence: docs/evidence/M5/trigger_{gesture,voice,tap}_synthetic_basketball_half_s7.mp4, timeline_synthetic_badminton_doubles_s7.png
- Left / known issues: no staged real gesture/voice footage (synthetic only); gesture via YOLO-pose 0/14 on far synthetic players; TV trim UI pending the integration wave.

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
