# M12 evidence: Tier D experiments

Produced on hfbox by the scripts in `experiments/tierd-pointmaps/` and
`experiments/tierd-vggt-static/` (commands in their READMEs; summary in `docs/tier-d.md`).
Only synthetic and CC BY footage appears here. Every synthetic frame is captioned
SYNTHETIC and every synthetic file is named `synth_*`. Tier D renders are research
experiments and are never shipped in the product path.

| File | What |
|---|---|
| `synth_bb_half_pl_0001_heldout.jpg` | Held-out cameras (rows: real view, orbit ±30°, ±60°, high). Columns: generator ground truth, Tier B, Tier D raw (MoGe-2), Tier D hybrid |
| `synth_bb_half_eval.json` | All synthetic metrics (calibration vs truth, MoGe scale / floor residuals, player placement, held-out IoU / PSNR / coverage, timings) |
| `synth_bb_half_pl_0001_paths.jpg`, `synth_bb_half_pl_0001_orbit.mp4` | Tier B, Tier D raw and Tier D hybrid side by side on the production `orbit` / `broadcast_high` paths (15 fps, every 2nd frame) |
| `synth_bb_half_moge.json`, `cc_pickleball_surrey2026_moge.json` | MoGe-2 run logs: load time, s per frame, GPU peak, plate / per-frame scale and floor residuals |
| `cc_pickleball_surrey2026_pl_0001_paths.jpg`, `cc_pickleball_surrey2026_pl_0001_orbit.mp4` | The same three tiers on the CC clip |
| `*_vggt.json`, `*_vggt_coverage.png` | VGGT-1B static reconstruction: camera motion, focal, floor flatness, timings / memory for 8, 16 and 32 frames. Coverage maps are top-down, court ± 3 m, far side up: yellow = fused floor points, grey = inside the camera frustum but not reconstructed, black = never seen by the camera |

## CC footage attribution

`cc_pickleball_surrey2026_*`: frames and renders derived from "2026.09.04 MD4.0 (age 50+)
John Lee + Ernest Tosch vs Brendan Fong + Anthony Chang (Gold Medal)" by pickleball4you,
https://www.youtube.com/watch?v=4M58YJoZ4O4, licensed CC BY 3.0
(https://creativecommons.org/licenses/by/3.0/). Cut to source 100-190 s (highlight
`pl_0001` = 0-6.7 s of that cut) and modified: re-rendered as point clouds and planes
from virtual cameras, scaled, captioned.

No real YouTube-licensed footage was used for M12, so `docs/evidence/local/M12/` is empty.
