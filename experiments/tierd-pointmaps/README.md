# Tier D experiment A: per-frame metric point maps (MoGe-2) vs Tier B

**Hypothesis.** A monocular metric point-map model gives real 3D for everything the camera
sees (hoop, posts, net, fences, players as relief surfaces instead of flat cutouts), so
replays rendered from virtual cameras should beat Tier B's 2.5D planes (D-54): no ghost
net/hoop on the floor, players that are not cardboard side-on.

**Verdict: not yet.** On held-out synthetic cameras the raw point clouds are clearly worse
than Tier B (players smear 0.7 m along the view ray and land 0.6 m off). A hybrid
(Tier B's calibrated floor and tracked player positions, MoGe only for depth relief and
standing structure) gets back to Tier B on the floor (within 1 dB) and close on player
silhouettes. It beats Tier B on silhouettes only at the steepest side view (orbit -60°,
IoU 0.38 vs 0.35) and never on player-region PSNR. On the real CC pickleball clip the static
scene (fence, far courts, net, banners) looks much richer than Tier B's backdrop wall,
and that is the part worth keeping. Nothing here fills the floor the camera never saw.

## Method

1. `pointmaps.py` (GPU): MoGe-2 ViT-L (`Ruicheng/moge-2-vitl-normal`) on the court plate
   (`plate/plate.jpg`, the temporal median with players masked, from the M8 worker) and
   on every 2nd frame of one highlight. MoGe gets the calibrated horizontal FoV, so only
   its scale is free. Each depth map is scaled onto the calibrated floor: median ratio of
   the floor-plane depth to the predicted depth over court-floor pixels (court polygon
   + 1 m, minus player masks dilated by 15 px). SAM 2.1 player masks (M8 `segments/`,
   eroded by 2 px, depth outliers more than 0.75 m from the player's median dropped) are
   lifted to court metres.
2. `scene.py` (CPU): z-buffered square splats sized by each point's source footprint,
   then one hole-filling pass. The renderer draws three versions:
   * **Tier D raw**: the plate cloud (2x subsampled; points within 0.15 m of the floor
     snapped onto it) plus the per-frame player clouds.
   * **Tier D hybrid**: plate points with a vertical MoGe normal (|n_z| > 0.9) below
     0.6 m go onto the calibrated floor plane. Each player cloud slides along the real
     camera's rays until its median depth matches the tracked foot point at 0.9 m, so the
     source view stays unchanged and the position comes from the tracker.
   * **Tier B**: the production drawing code (`replay_render.virtual.tierb`) for the
     same `View`s, so every comparison uses identical cameras (production
     `orbit` / `broadcast_high` paths).
3. `eval_synth.py` (CPU, synthetic only) re-scripts the exact synthetic scene
   (`courtcam.synth.build_scene`, same seed) and measures player placement and height
   against the truth. It then has the generator render the same frames from cameras the
   pipeline never saw (real camera as a sanity row, orbit ±30° and ±60° about the play,
   and a high camera 15 m back and 9 m up) and scores every tier against those images.

## Dependencies and licences

| Item | Licence | Notes |
|---|---|---|
| MoGe (`moge` 3.0.0, github.com/microsoft/MoGe, main) | MIT (repo LICENSE also carries an Apache-2.0 section) | installed `--no-deps` in `venvs/tierd` |
| MoGe-2 weights `Ruicheng/moge-2-vitl-normal` | MIT (HF model card) | read-only from the shared `/workspace/.hf/hub` (1.3 GB, already present) |
| utils3d_moge 1.7 (@62f09d5), pipeline 1.0.0 (@1c51139), EasternJournalist | MIT / MIT | MoGe's pinned deps |
| scipy, einops | BSD-3 / MIT | |
| SAM 2.1 masks, plate, calibration, Tier B code | as in M8 (Apache-2.0 SAM 2.1; our code) | reused unchanged |

All of it is permissive. This path is licence-clean enough to ship if it were good enough.

## Commands (hfbox, copy `/workspace/wt/replay-tierd`)

```bash
source /workspace/wt/replay-env/env.sh; d=/workspace/wt/replay-tierd; W=$d/_work
export PYTHONPATH=$d/experiments/tierd-pointmaps:$d/courtcam:$d/services/api:$d/services/worker:$d/render
export HF_HUB_CACHE=/workspace/.hf/hub HF_HUB_OFFLINE=1; PY=/workspace/wt/replay-env/venvs/tierd/bin/python
# inputs: synthetic clip + M8 worker stages (plate, SAM masks) for one highlight
python -m courtcam.cli synth --sport basketball --variant half --duration 40 --seed 7 --size 1920x1080 --out $W/syn_bb
python -m replay_worker run $W/syn_bb/clip.mp4 --out $W/g_syn_bb --detector synthetic --stages plate,segment --set highlights_n=1 --cache $W/cache
#   (CC: a copy of the M8 game dir g_cc_pb90, CC BY 3.0 pickleball, first 90 s)
flock /workspace/airtools/.gpu.lock timeout 900 $PY $d/experiments/tierd-pointmaps/pointmaps.py $W/g_syn_bb pl_0001 --out $W/out/syn_pl_0001_moge.npz --stride 2
flock /workspace/airtools/.gpu.lock timeout 900 $PY $d/experiments/tierd-pointmaps/pointmaps.py $W/g_cc_pb90 pl_0001 --out $W/out/cc_pl_0001_moge.npz --stride 2
$PY $d/experiments/tierd-pointmaps/eval_synth.py $W/out/syn_pl_0001_moge.npz --out $W/out/syn_pl_0001_eval
$PY $d/experiments/tierd-pointmaps/scene.py $W/out/syn_pl_0001_moge.npz --out $W/out/syn_pl_0001 --tag SYNTHETIC
$PY $d/experiments/tierd-pointmaps/scene.py $W/out/cc_pl_0001_moge.npz --out $W/out/cc_pl_0001 --tag "CC BY 3.0 pickleball4you (modified)"
python -m pytest $d/experiments/tierd-pointmaps -q      # 2 passed (geometry round trip, splat z-order / hole fill)
```

## Results

Inputs: SYNTHETIC basketball/half 1920x1080 seed 7, highlight `pl_0001` (8 s, 10 players,
120 processed frames); CC BY 3.0 pickleball clip (`pickleball_surrey2026`, M8 game dir, 8
hand-clicked landmarks), highlight `pl_0001` (6.7 s, 2 tracked players, 101 frames).

### Cost (RX 9070 XT, ROCm 7.2, cudnn off)

| | synthetic | CC pickleball |
|---|---|---|
| model load | 4.3 s | 3.8 s |
| MoGe-2 per 1920x1080 frame (median / max) | 0.141 / 0.171 s | 0.141 / 0.234 s |
| GPU peak | 3.19 GB | 3.19 GB |
| npz (player points, stride 2) | 26 MB (2.0 M points) | 70 MB (5.8 M points) |
| CPU render, 2 paths x 120 / 101 frames x 3 panels at 640x360 | 31 s | 62 s |

That is 4.2 GPU-seconds per second of 30 fps video (2.1 s at stride 2), next to SAM 2.1's
≈ 7.8 s for 10 players (D-55: 26 ms per object per frame).

### Metric scale and floor (MoGe given the true FoV; residuals after one scale per image)

| | synthetic plate | synthetic frames (median) | CC plate | CC frames (median) |
|---|---|---|---|---|
| scale needed (1.0 = MoGe metric was right) | 3.81 | 1.46 (CV 4.9 % over frames) | 0.82 | 0.90 (CV 1.5 %) |
| floor depth error, median | 5.6 % | 2.3 % | 0.9 % | 1.1 % |
| floor height \|z\|, median / p90 | 0.34 / 0.87 m | 0.14 / 0.34 m | 0.018 / 0.040 m | 0.022 / 0.043 m |

The flat-shaded synthetic court is out of distribution: MoGe's metric scale is off by
1.5 to 3.8x and the floor ripples by tens of centimetres. On real footage it is flat to
about 2 cm once scaled, but its own metric scale is still 10 to 18 % off. **The
calibration, not the model, has to set the scale.**

### Player placement vs ground truth (synthetic, 1199 player-frames)

| | Tier B (tracked foot point, billboard) | Tier D raw (median of lifted points) |
|---|---|---|
| ground position error, median / p90 | **0.18 / 0.25 m** | 0.62 / 1.51 m |
| height error, median abs (signed) | **0.13 m (+0.13)** | 0.28 m (-0.28) |
| depth extent of the player, p10 to p90 along the ray | 0 (flat) | 0.71 m median, 0.92 m p90 (a body is about 0.3 m) |

### Held-out cameras (synthetic, generator renders the truth; median of 3 frames)

| camera | metric | Tier B | Tier D raw | Tier D hybrid |
|---|---|---|---|---|
| real (sanity) | player IoU / floor PSNR / player-region PSNR | **0.80** / **28.2** / **17.7** | 0.75 / 24.0 / 15.4 | 0.75 / 24.6 / 15.4 |
| orbit +30° | " | **0.61** / **24.1** / **13.4** | 0.35 / 16.7 / 10.8 | 0.53 / 23.6 / 12.4 |
| orbit -30° | " | **0.50** / **24.7** / **12.9** | 0.35 / 18.1 / 11.4 | **0.50** / 23.9 / 12.6 |
| orbit +60° | " | **0.55** / 21.5 / **12.5** | 0.20 / 15.4 / 10.2 | 0.42 / **21.8** / 11.6 |
| orbit -60° | " | 0.35 / 21.1 / **11.7** | 0.16 / 14.8 / 10.4 | **0.38** / **21.4** / 11.5 |
| high, 15 m back, 9 m up | " | **0.73** / 23.6 / **17.6** | 0.69 / 18.5 / 14.0 | 0.71 / **24.1** / 14.7 |

Floor coverage of court + 1 m was 0.94 to 1.0 for every method: the synthetic camera sees
the whole half court. The void is outside that region, see experiment B. Full numbers:
`docs/evidence/M12/synth_bb_half_eval.json`.

### What the stills show (`docs/evidence/M12/`)

* `synth_bb_half_pl_0001_heldout.jpg`: truth | Tier B | Tier D raw | Tier D hybrid
  per held-out camera. In the raw clouds the floor tears along MoGe depth steps and
  players stretch into streaks. The hybrid fixes the floor, but cracks remain on the
  apron where MoGe's normal was not vertical. Real 3D hoop/backboard/post in both Tier D
  variants, where Tier B draws its own hoop next to a flat ghost of the real one.
* `synth_bb_half_pl_0001_paths.jpg`, `..._orbit.mp4`: three panels along the production
  `orbit` / `broadcast_high` paths. All synthetic frames are labelled SYNTHETIC.
* `cc_pickleball_surrey2026_pl_0001_paths.jpg`, `..._orbit.mp4` (CC BY 3.0,
  attribution in docs/evidence/M12/README.md): fence, far courts, tent, banner and cars
  come out as real 3D, and the net no longer ghosts onto the floor. Thin structures
  (fence, net) become stripes at grazing angles, and the floor beside and behind the
  camera is still void.

### Failure modes

1. Flying pixels and depth smear: monocular depth on a 60 to 200 px player is a relief of
   about 0.7 m, not a body. Side-on it reads as a streak.
2. Per-frame scale flicker (CV 1.5 to 4.9 %) moves the whole cloud. It is hidden here only
   because each frame is re-scaled to the calibrated floor.
3. Floor ripple and tears unless the floor is replaced by the calibrated plane.
4. The real camera never saw the back of anything: players have no back side, and hidden
   floor stays hidden.
5. The splat renderer has no anti-aliasing, so lines alias. The real-camera sanity view is
   4 dB below Tier B's floor because of this renderer, not because of the geometry.

## What it would take

* Ship only the useful part: MoGe for the static plate (licence-clean, about 1 s per
  game). Turn it into a mesh, keep the calibrated floor plane, and add standing structure
  (net, posts, fence, background) to Tier B in place of the backdrop wall. That removes
  the ghosting artefact in D-54. Estimate: one stage and a mesh exporter, about a day.
* Players: keep billboards, or Tier C avatars. Monocular relief does not beat a flat
  cutout until it has multi-view or temporal fusion and a body prior, which is what
  Tier C's joints already provide.
