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
