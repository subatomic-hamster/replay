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
