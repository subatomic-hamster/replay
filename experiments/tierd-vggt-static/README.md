# Tier D experiment B: multi-frame static court reconstruction (VGGT-1B)

**Hypothesis.** Fusing many frames of the clip with a feed-forward multi-view
reconstructor (VGGT) should fill Tier B's void floor and remove its plate ghosts (D-54).

**Verdict: dead end for a tripod camera, and also licence-blocked.** VGGT works on ROCm and
correctly finds that the camera never moved (≤ 26 mm, ≤ 0.08°). With no parallax it
reconstructs nothing outside the single camera's frustum: 0.07 % (synthetic) and ≤ 1.4 %
(CC, stray points) of court + 3 m cells outside it. The void is a visibility problem, not
a reconstruction problem. Inside the frustum, fusing frames adds floor that players had
hidden, which the temporal-median plate already does. Its floor is also less exact than
the calibrated plane, and the `facebook/VGGT-1B` weights are CC-BY-NC-4.0.

## Method

`vggt_static.py`: N frames sampled evenly over the whole clip (8, 16, 32), resized to
518x294 (VGGT's input), one forward pass in bf16 (cudnn off, D-39). Measured:

* camera motion: VGGT's camera centres and rotations relative to frame 0, in metres after
  scaling (truth: a tripod, so 0);
* focal: VGGT's fx vs the calibration;
* floor flatness: each depth map scaled onto the calibrated floor, same metric as
  experiment A;
* top-down coverage of court ± 3 m in 0.25 m cells with a floor point (|z| < 0.3 m):
  frame 0 alone vs all N fused, and the share of cells outside the real camera's frustum.
  Two variants: VGGT's own cameras, and VGGT depth with the calibrated K, R, t (the best
  case). The frustum share is the geometric ceiling: the fraction of cells the camera
  sees at all.

## Dependencies and licences

| Item | Licence | Notes |
|---|---|---|
| VGGT code (`vggt` 0.0.1, github.com/facebookresearch/vggt, main) | "VGGT License" v1 (Meta custom research-materials licence with an acceptable-use policy) | `--no-deps` in `venvs/tierd` |
| `facebook/VGGT-1B` weights | **CC-BY-NC-4.0 (non-commercial)** | read-only from the shared `/workspace/.hf/hub` (already present). Experiment only, never shipped |
| `facebook/VGGT-1B-Commercial` | gated, "vggt-aup-license" | not downloaded. It is the route if VGGT were ever wanted |
| einops | MIT | |

## Commands (hfbox; env as in experiment A)

```bash
flock /workspace/airtools/.gpu.lock timeout 900 $PY $d/experiments/tierd-vggt-static/vggt_static.py $W/g_syn_bb  --frames 8,16,32 --out $W/out/syn_vggt
flock /workspace/airtools/.gpu.lock timeout 900 $PY $d/experiments/tierd-vggt-static/vggt_static.py $W/g_cc_pb90 --frames 8,16,32 --out $W/out/cc_vggt
```

## Results

| | synthetic basketball (SYNTHETIC) | CC pickleball |
|---|---|---|
| model load | 7.8 to 11.8 s | 7.7 to 10.5 s |
| forward 8 / 16 / 32 frames | 2.2 / 2.5 / 5.7 s (0.18 s per frame at 32) | 2.2 / 2.5 / 5.7 s |
| GPU peak 8 / 16 / 32 frames | 8.05 / 8.31 / 8.77 GB | same |
| camera motion found, median / max (32 frames) | 3 mm / 8 mm (max over runs 26 mm) | 5 mm / 9 mm (max over runs 12 mm) |
| camera rotation found, max | 0.08° | 0.08° |
| focal error vs calibration | **111 to 119 %** (114° HFOV synthetic camera) | 15 % |
| depth scale needed, CV over frames | 9.1 to 9.2, 0.2 % | 9.3 to 9.7, 0.2 % |
| floor height \|z\| median / p90 (32 frames) | 0.20 / 0.64 m | 0.017 / 0.37 m |
| frustum ceiling (court ± 3 m cells seen at all) | 0.992 | 0.857 |
| coverage, calibrated K: frame 0 → 32 fused | 0.28 → 0.31 | 0.47 → 0.56 |
| coverage, VGGT cameras: frame 0 → 32 fused | 0.12 → 0.15 | 0.54 → 0.72 |
| fused cells **outside** the frustum | 0.0007 | 0.014 (stray points, not floor) |

The coverage figures inside the frustum are limited by 518 px input (a far pixel is wider
than a 0.25 m cell) and by the |z| < 0.3 m floor test, not only by visibility. The
outside-frustum number is the one that answers the question.
`docs/evidence/M12/*_vggt_coverage.png`: top-down maps, far side up. Yellow = fused floor
points, grey = inside the frustum but not reconstructed, black = never seen.
Full JSON: `docs/evidence/M12/{synth_bb_half,cc_pickleball_surrey2026}_vggt.json`.

Compared with experiment A, VGGT's per-frame depth is temporally steadier (scale CV
0.2 % vs MoGe's 1.5 to 4.9 %), because it sees all frames at once. Its floor is less
flat at range (CC p90 0.37 m vs MoGe 0.04 m), and on the wide synthetic camera its
intrinsics are unusable.

## What it would take

* The void floor needs content the camera never recorded. Options are a second camera
  (true multi-view), a template-and-texture fill (the court template is known; mirror the
  seen half of a symmetric court, or paint a synthetic floor clearly labelled as such), or
  a generative inpainting model (honesty labelling, licence check). Multi-frame
  reconstruction from one tripod cannot do it.
* A panning or handheld camera would give VGGT parallax. Re-test then, with
  `VGGT-1B-Commercial` (gated) or a permissive alternative.
