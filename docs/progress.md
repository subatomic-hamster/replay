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
