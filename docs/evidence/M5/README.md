# M5 metrics: "Replay, clip that" triggers (synthetic)

**Synthetic data only.** Re-measured 2026-10-06 on hfbox. The numbers are in `metrics.json`,
which `../M4/eval/split.py` generated. The `*.mp4` and `*.png` files here are older visuals and
were not regenerated.

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
| gesture (22) | 16 TP, 26 FP, 6 FN (P 0.38, R 0.73); who 16/16; clip right 11/22 |
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
