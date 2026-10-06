# M1 metrics: detection and tracking (synthetic)

**Synthetic data only.** Re-measured 2026-10-06 on hfbox. The numbers are in `metrics.json`,
which `../M4/eval/split.py` generated. `synthetic_basketball_half_yolo_overlay.*` are older
visuals and were not regenerated.

The runs are the same ones as M4 and M5. The commands, code state and scripts are in
`../M4/README.md` and `../M4/eval/`.

- **Scenes:** the five seed-7 clips from `courtcam synth --duration 90 --seed 7`, 1280x720 at
  30 fps. They are basketball half court, basketball full court, pickleball doubles, badminton
  doubles and volleyball indoor.
- **Tracking scores:** from `courtcam eval --gt <clip>/ground_truth.json --out <run>`
  (`run_metrics.sh mot`), scored on the on-court players.
- **YOLO runs:** `run1.py <clip> <out> yolo yolo` (yolo11m detection).
- **Ground-truth detector runs:** `run1.py <clip> <out> synthetic auto`.

| scene | YOLO MOTA | YOLO IDF1 | YOLO ID switches | GT detector MOTA / IDF1 |
|---|---|---|---|---|
| basketball half | 0.64 | 0.31 | 122 | 1.00 / 1.00 |
| basketball full | 0.43 | 0.25 | 157 | 1.00 / 1.00 |
| pickleball | 0.98 | 0.99 | 0 | 1.00 / 1.00 |
| badminton | 0.99 | 1.00 | 0 | 1.00 / 1.00 |
| volleyball | 0.91 | 0.75 | 37 | 1.00 / 1.00 |

Court-position error for YOLO-matched players (median) runs from 0.26 m (badminton) to 0.47 m
(basketball full). With the ground-truth detector it runs from 0.16 m to 0.30 m.

## Voice ASR on the synthetic mixes

The test runs whisper-small through `pipeline.stage_triggers` (`run_trig.py`) on each clip's
`audio.wav`. Those files contain the synthetic speech mixed with synthetic crowd noise and
contact sounds.

- whisper-small heard 37 of 37 "Replay, clip …" lines across all 9 clips.
- So every line was heard in 9 of 9 clips. The YOLO runs give the same result.

This is not necessarily the same test as the old "8/9 crowd-noise mixes" claim. The script
behind that claim was not found.
