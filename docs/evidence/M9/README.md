# M9 evidence: Tier C 3D reconstruction replays

Everything here was produced on hfbox. Sources:
- the worker (`python -m replay_worker run ... --stages tierc_manifest`), and
- the Tier C CLI (`python -m replay_render.avatars scene|render|eval`).

Synthetic inputs carry SYNTHETIC in every frame and `synth_` in every file name. Every
Tier C frame is labelled "3D reconstruction - stylized (MotionBERT lift)". Pipeline,
`replay.scene.v1` contract and limits: `render/replay_render/avatars/README.md`.

## Inputs

| tag | input | plays |
|---|---|---|
| `synth_bb` | SYNTHETIC basketball/full, 90 s (`courtcam synth`, the `g_syn_bb90` worker game), keypoints from the rig (`--kp gt`), 10 players | 3 shots |
| `synth_bb_full` | SYNTHETIC basketball/full with per-person true 3D joints (`ground_truth.json` `kp3`) | 2 highlights, used for accuracy |
| `cc_pickleball_surrey2026` | CC BY 3.0 real clip (attribution below), the first 90 s. The camera is tierB's hand-clicked calibration. Keypoints are YOLO11m-pose, run through the worker | 3 rallies |

### Shot outcome

The pipeline's shot events carry `made: null` until a user answers "Made / Missed",
which is a PATCH on the event. For the `synth_bb` sheets, the outcome in a copy of the
game's `highlights.json` was set from the synthetic ground truth (events e3 / e8 / e17),
the way a confirmed answer would set it. This shows the three ball paths:

| file tag | outcome | ball path |
|---|---|---|
| `_make` | made | the ball drops through the rim and net |
| `_miss` | missed | the ball bounces off the front of the rim |
| (outcome unknown) | not set | the ball stops at the rim; no outcome is drawn |

## Files

- **`synth_bb_pl_0002_make_angles.jpg`, `synth_bb_pl_0004_make_angles.jpg`,
  `synth_bb_pl_0001_miss_angles.jpg`** — the source frame plus all five Tier C angles at
  the moment the ball reaches the rim. The angles are broadcast high, baseline, overhead,
  reverse and shooter's POV.
- **`synth_bb_pl_0002_make_overhead.gif`** — the overhead angle, descending.
- **`synth_bb_pl_000x_*_pov.mp4`, `synth_bb_pl_0002_make_baseline.mp4`** — the shooter's
  POV and the baseline angle, at 640 px wide.
- **`cc_pickleball_surrey2026_pl_0003_angles.jpg`, `_baseline.mp4`, `_pov.mp4`** — real
  footage. The net sports get a 3D net, the baseline camera behind the focus player's
  baseline, and a POV looking across the net.
- **`synth_bb_full_metrics_pl_000x.json`, `synth_bb_full_quality_pl_000x.png`** — accuracy
  and clean-up metrics for both methods. The plots show ankle speed before, after and
  true, with detected stances shaded, plus mean joint acceleration.
- **`timings.json`** — the worker's per-task log for both games (wall time and GPU-lock
  wait), plus each scene's quality block.

## Accuracy and quality (synthetic, all players, 12 body joints)

| play | method | MPJPE mm before→after | pelvis-aligned | jitter m/s² | foot slide cm/s | bone CV | height err |
|---|---|---|---|---|---|---|---|
| pl_0001 | MotionBERT | 128→125 | 75→74 | 10.0→4.0 | 25.2→0.3 | 0.040→0 | 2 cm |
| pl_0001 | analytic | 171→172 | 174→174 | 15.3→5.4 | 31.0→0.4 | 0→0 | 2 cm |
| pl_0002 | MotionBERT | 141→139 | 74→75 | 12.8→5.1 | 28.5→0.9 | 0.040→0 | 3 cm |
| pl_0002 | analytic | 185→187 | 174→175 | 16.7→6.2 | 28.8→1.1 | 0→0 | 3 cm |
| (truth) | | | | 4.5-5.6 | 24 (the rig skates) | 0.005 | |

What the table shows:
- The clean-up roughly halves jitter, to about the level of the true motion. Foot
  sliding while planted is gone.
- Bones are rigid after the clean-up, and accuracy changes by no more than ±2 mm.
- MotionBERT is about 45 mm better than the licence-clean analytic fallback in absolute
  terms. Pelvis-aligned, MotionBERT is 74-75 mm against the analytic method's 174-175 mm.
- The scale from the calibrated height is within 2-3 cm of the true stature.

Real footage (CC pickleball, YOLO keypoints, no ground truth):
- jitter 39-56 → 9-15 m/s²
- foot slide 59-69 → 0.2-1.4 cm/s

## Timings

Measured on hfbox (RX 9070 XT + 7800X3D), from the worker log, with GPU-lock queueing
excluded.

| task | synthetic basketball (10 players) | CC pickleball (2-3 tracked) |
|---|---|---|
| `tierc_scene` (2D, MotionBERT lift, clean-up, ball) | 9-12 s per play | 8-9 s per play (incl. YOLO-pose) |
| `tierc` per angle, 1280x720 (process + render + x264) | 3.6-15 s per 150-240 frames (POV fastest) | 3.4-7.6 s per 201-240 frames |
| painter, ms/frame (CLI, shared CPU) | 14-47 | 6-28 |
| `tierc_manifest` | 0.05 s | 0.04 s |

The renderer is OpenCV painter's-algorithm. A headless GL path (moderngl on Mesa EGL)
measured 3.6 ms/frame for an equivalent load. It is the upgrade path but is not needed;
see the avatars README.

## Commands

```bash
python -m replay_worker run syn_bb90/clip.mp4 --out g_syn_bb90 --detector synthetic \
    --set highlights_n=3 --stages tierc_manifest
python -m replay_worker run cc/pb90/clip.mp4 --out g_cc_pb90 --sport pickleball \
    --variant doubles --stages tierc_manifest
flock <gpu lock> python -m replay_render.avatars eval g_syn_bb_full pl_0001 \
    --ground-truth syn_bb_full/ground_truth.json --out ev/
```

## CC footage attribution

`cc_pickleball_surrey2026_*`: frames and renders are derived from "2026.09.04 MD4.0 (age
50+) John Lee + Ernest Tosch vs Brendan Fong + Anthony Chang (Gold Medal)" by
pickleball4you, https://www.youtube.com/watch?v=4M58YJoZ4O4, licensed CC BY 3.0
(https://creativecommons.org/licenses/by/3.0/). The clip was cut to source 100-190 s
and modified: 3D reconstruction, re-rendered from virtual cameras, scaled and captioned.

## Known gaps

- **Missing players.** Only the on-court tracks that tierB's game holds are rebuilt. The
  CC rally has 2-3 of its 4 players, because the far-right player is not tracked
  upstream.
- **No jumps.** Jumps are flattened, because the lower ankle is pinned to the floor.
- **Monocular depth.** Absolute error is about 2x the pelvis-aligned error.
- **Panoramic footage.** The Kennesaw clip (panoramic 2560x960, local-only) was not
  attempted. Its pinhole fit is 51-92 px off at hoop height (M8), so heights and lifts
  would be wrong.
