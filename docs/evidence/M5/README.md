# M5 metrics: "Replay, clip that" triggers (synthetic)

**Synthetic data only.** Re-measured 2026-10-06 on hfbox after the D-68 gesture fix. The
numbers are in `metrics.json`, which `../M4/eval/split.py` generated (the M1/M4 numbers of the
same run did not change). The `*.mp4` and `*.png` files here are older visuals and were not
regenerated. The yolo step ran before the fix landed, so its `run_trig.py` + `eval_synth.py`
lines were re-run on the fixed code; its tracks and poses do not depend on the gesture rule.

The runs are the same ones as M4. The commands, code state and scripts are in
`../M4/README.md` and `../M4/eval/`.

The data is nine 90 s synthetic clips, seeds 7 and 11.

## How the triggers were scored

- **Gesture:** `eval_synth.py` matches a gesture to the truth within ±1 s of the hold start.
  "Who" means the gesture-maker maps to the right ground-truth player.
- **Voice:** matched within ±1 s. The named subject is resolved through a simulated roster
  (`run_trig.py`).
- **Clip right:** `triggers.resolve` returns the pipeline play that matches the ground-truth
  play.
- **Resolution rule:** ground-truth trigger times are resolved against the ground-truth plays.
  This checks the rule only, not detection.

## Results

### Synthetic detector + GT poses

| item | result |
|---|---|
| gesture (22) | 22 TP, 0 FP, 0 FN (P 1.00, R 1.00); who 22/22; clip right 16/22 |
| voice, whisper-small (37) | 37/37; named subject 18/18; clip right 30/37 |
| tap (14) | clip right 10/14 |
| resolution rule on GT plays | 73/73 |

### YOLO detect + YOLO pose

| item | result |
|---|---|
| gesture (22) | 0/22 |
| voice (37) | 37/37; named subject 16/18; clip right 31/37 |
| tap (14) | clip right 9/14 |

## Accuracy pass (current code only, "after" values)

| item | YOLO pose (default) | `--pose vit` (vitpose-base-simple) |
|---|---|---|
| X gesture (22) | 0/22 | 9 TP, 0 FP (P 1.00, R 0.41); who 9/9; clip right 8 |

The accuracy pass's "before" value (gesture 0/22) was measured on older code and is history.

## Gesture fix (D-68): before this fix → after

"Before this fix" is the D-61 rule as committed at e4b79bf, measured by the same harness
earlier on 2026-10-06.

| item | before this fix | after |
|---|---|---|
| GT poses, gesture (22) | 16 TP, 26 FP, 6 FN (P 0.38, R 0.73); clip right 11 | **22 TP, 0 FP, 0 FN** (P 1.00, R 1.00); clip right 16 |
| `--pose vit`, gesture (22) | 9 TP, 0 FP (P 1.00, R 0.41) | 9 TP, 0 FP (P 1.00, R 0.41) |
| YOLO pose, gesture (22) | 0/22 | 0/22 |
| real 480 s (Kennesaw + badminton), YOLO and ViTPose | 0 false triggers | 0 false triggers |

What was wrong (GT poses, every case inspected):

- **All false gestures were synthetic jump shots** (basketball only; badminton, pickleball and
  volleyball had none). The rig's shot pose holds the ball overhead with the hands 0.2 torso
  apart and the elbows 0.8–0.95 torso apart, uncrossed, for 0.5–0.8 s. That is exactly the
  relaxed "hands together overhead, elbows apart" form, and the 0.6 vote over 0.8 s accepted
  it. Each false hold ends at a ground-truth shot release by the same player (for example
  half_s7 8.7–9.4 s p5, shot at 9.19 s).
- **All misses were real, crossed X holds** (strict crossing in 10 of 10 samples) by players
  turned side-on. Their elbows overlap in the image (median spread 0.26–0.51 torso), and the
  elbow gate was also applied to the strict crossing.

The fix, in `courtcam/courtcam/triggers.py` (parameters in `TriggerCfg`):

- A crossing whose arm keypoints all score ≥ `gesture_cross_kp` (0.35) needs no elbow spread.
  A low-score crossing still needs the elbows apart: ViTPose flips the side labels of an
  arms-up contest on Kennesaw (arm scores 0.2–0.5, elbows 0–0.4 torso apart).
- An uncrossed hands-together hold must keep both arms overhead for `gesture_together_min_s`
  (0.9 s = `shot.release_max_s`). Unscored samples do not end that span. Anything shorter is
  what the shot detector calls a release.
