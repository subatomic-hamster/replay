# Tier D: "true 3D" replays (M12 experiments summary)

Tier D was meant to go beyond Tier B (2.5D cutouts, D-54) and Tier C (capsule avatars,
D-40) to real novel-view or 4D reconstruction. Three time-boxed experiments ran on hfbox
(RX 9070 XT 16 GB, ROCm 7.2) on a SYNTHETIC basketball clip, where the generator renders
ground truth from cameras the pipeline never saw, and on the CC BY 3.0 pickleball clip.
Details, commands and every number: `experiments/tierd-*/README.md`. Evidence:
`docs/evidence/M12/`.

| Experiment | Result | Verdict |
|---|---|---|
| A. MoGe-2 per-frame metric point maps + plate cloud, rendered on Tier B's camera paths (`experiments/tierd-pointmaps`) | Runs: 0.14 s per 1080p frame, 3.2 GB. Raw clouds lose to Tier B on every held-out view (player IoU 0.16 to 0.69 vs 0.35 to 0.80; players 0.62 m off vs 0.18 m; 0.7 m depth smear). The hybrid (calibrated floor + tracked positions + MoGe relief) roughly ties Tier B. On real footage the static background (fence, net, far courts) comes out as convincing 3D | **Not yet** for players. **Worth shipping later** for the static plate |
| B. VGGT-1B multi-frame static court (`experiments/tierd-vggt-static`) | Runs: 5.7 s for 32 frames, 8.8 GB. It correctly finds the camera static (≤ 26 mm). It adds ≤ 1.4 % of court cells outside the camera frustum, so the void floor stays void. Weights CC-BY-NC | **Dead end** for a tripod (no parallax); licence-blocked anyway |
| C. Dynamic splats / 4D (gsplat, shape-of-motion, 4DGaussians) (`experiments/tierd-dynamic`) | gsplat fails at first call: `No CUDA toolkit found`. The box has no hipcc or ROCm SDK. shape-of-motion also pins NVIDIA RAPIDS; 4DGaussians uses Inria non-commercial rasterisers | **Dead end here**. Needs the ROCm SDK plus gsplat-amd (Apache-2.0) |

## Tiers compared

| Tier | What it is | Quality (measured where possible) | Cost per 8 s highlight | Robustness | Licence |
|---|---|---|---|---|---|
| A | Virtual cameras (crop / follow / push-in) on the real video | Real pixels, no new viewpoint | 5 to 8 ms per frame, CPU | Works wherever tracking works | Our code |
| B | 2.5D: plate floor + backdrop planes, SAM cutout billboards on tracked feet | Held-out synthetic: player IoU 0.80 (real view) to 0.35 (orbit -60°), floor PSNR 21 to 28 dB; position 0.18 m, height +0.13 m | SAM ≈ 26 ms per object per frame (≈ 1 GPU-min for 10 players) + 32 to 62 ms per frame CPU render | Floor exact from calibration. Ghosts of static objects, void beyond the frustum, thin side-on | Apache-2.0 SAM 2.1 + our code |
| C | Capsule mannequins from 2D keypoints → MotionBERT 3D joints on the calibrated court (M9) | Any angle incl. overhead and POV; joints 125 to 139 mm MPJPE on synthetic, height ≤ 3 cm; stylised, not photographic | 8 to 12 s per play scene + 3.6 to 15 s per angle | Robust to any viewpoint. Looks like avatars, not people | MotionBERT Apache-2.0, but trained on Human3.6M (academic dataset): optional extra only |
| D-A raw | MoGe-2 point clouds per frame | Held-out IoU 0.16 to 0.75, floor 15 to 24 dB; players 0.62 m off, 0.7 m smear | 0.14 s per frame GPU (4.2 s per second of video) + mask cost as B | Fails off-axis (streaks, tears); MoGe metric scale off 10 to 18 % (real) or 1.5 to 3.8x (synthetic) | MIT code + MIT weights |
| D-A hybrid | B's floor and positions, MoGe relief for players and structure | ≈ B: IoU 0.38 to 0.75, floor 21 to 24.6 dB; real 3D hoop/net/fence, no ghosts | as D-A raw | Still void beyond the frustum; players still have no back | MIT |
| D-B | VGGT multi-frame static court | No new coverage from a tripod | 5.7 s per 32 frames, 8.8 GB | n/a | **CC-BY-NC weights** |
| D-C | Dynamic Gaussian / 4D | Not run | n/a | Needs HIP SDK | gsplat Apache-2.0; others NC or NVIDIA-only |

## Recommendation

1. Keep the product on A + B + C. Tier D does not beat B at replaying players from one
   fixed phone camera, and nothing reconstructs what the camera never saw.
2. Worth one more stage later: lift the court plate with MoGe-2 (MIT, about 1 s per
   game) into a mesh of the standing structure (net, posts, hoop support, fence,
   background). Keep Tier B's calibrated floor and billboards or Tier C avatars. This
   fixes the D-54 ghosting artefact and replaces the flat backdrop wall. It must stay
   labelled 2.5D or hybrid.
3. Revisit true multi-view or 4D only if the capture changes (two phones, or a panning
   camera) and the box gets the ROCm HIP SDK. Use permissive weights only
   (VGGT-1B-Commercial is gated; the open VGGT-1B is NC).
