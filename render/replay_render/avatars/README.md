# Tier C: 3D reconstruction replays (M9)

A highlight is rebuilt as a 3D scene: one 17-joint skeleton per player in court
metres, plus the ball's arc. It is then rendered from virtual cameras that the real
camera never had: baseline, overhead, reverse, broadcast high, and the shooter's POV.
Every frame carries the label **"3D reconstruction - stylized"**, and synthetic input
is also marked SYNTHETIC. The players are capsule mannequins in jersey colours (D-40),
not photoreal people.

```
python -m replay_render.avatars scene  <game> <play> [--method auto|motionbert|analytic] [--kp auto|gt|yolo|poses]
python -m replay_render.avatars render <game> <play> <angle>        # replays/<play>/tierc_<angle>.mp4
python -m replay_render.avatars eval   <game> <play> --ground-truth gt.json --out dir
```

In the worker these steps are the stages `tierc_scene`, `tierc` (one task per play
and angle) and `tierc_manifest`, in `services/worker/replay_worker/stages/tierc.py`.
All three are off by default, so you have to name them in `--stages`.

## Pipeline (`scene.build`)

1. **2D keypoints** (COCO-17) for every on-court track at every frame of the
   highlight. The source is picked like this:
   - `gt`: the synthetic rig's own keypoints, used for development and CI.
   - `yolo`: YOLO11m-pose run on the frames, matched to the track boxes.
   - `poses`: the `poses/` stage output, interpolated.

   Gaps under 0.2 confidence are interpolated.
2. **Height** comes from the calibration. The eye ray above the foot point gives eye
   height, which is divided by 0.936 and clamped to 1.6-2.1 m. This number sets the
   body-to-court scale.
3. **Lift**, by one of two methods:
   - `motionbert` (`lift.py`): perspective-correct crops, rotated to a per-frame
     virtual camera that looks at the pelvis ray. These are resampled to 50 fps and
     cut into 243-frame windows (stride 121, blended). The lift runs with flip
     test-time augmentation in a subprocess under `venvs/lift`, and the result is
     rotated back to the court frame. The spine is levelled (max 25°) and the
     skeleton scaled to the height from step 2. The ankles are then translated onto
     their floor-ray hits, staying within 0.75 m of the track point.
   - `analytic` (`place.py`): no learned weights; this is the licence-clean fallback.
     The pelvis goes on its ray above the mid-foot floor point. Each bone's child
     goes where its ray meets a sphere of that bone's length (anthropometric) around
     the parent. Of the two roots, a 2-state Viterbi picks the one that is closer to
     a standing-pose prior and has the smaller frame-to-frame change. A foot whose
     floor point is within reach is then IK'd onto it.

   `auto` uses MotionBERT when `venvs/lift` and its checkpoint exist, and analytic
   otherwise.
4. **Clean-up** (`motion.py`), measured in the table below:
   - `ground`: the lower ankle sits at 8 cm. The shift is smoothed over 0.2 s, so
     the body does not bob.
   - `smooth_joints`: zero-phase Savitzky-Golay. The window is 0.27 s for the
     root-relative pose and 0.5 s for the root path. The edges use the polynomial
     fit, so there is no lag and no edge bias.
   - `fix_bones`: every bone is set to its median length, with left and right
     equal.
   - `separate`: torso capsules (radius 0.25 m) of different players are pushed apart
     on the floor. The push is held at its peak for ±0.25 s and then Gaussian-smoothed
     (σ 0.25 s). An earlier Savitzky-Golay smoothing kept the push's step edges, which
     made the whole body jerk at about 32 m/s².
   - `contacts` + `pin_feet`: an ankle counts as planted when it moves slower than
     0.4 m/s and is within 12 cm of flat-foot height, for at least 3 frames. It is
     held at the stance's median floor point, with two-bone IK on the knee. Pinning
     eases in and out over 6 frames with smootherstep, because a linear blend left
     acceleration spikes at release.
5. **Ball** (basketball): a parabola from the release, at the shooter's higher wrist,
   to the nearest rim at 3.05 m, timed by the shot event.
   - A make continues through the rim and drops through the net.
   - A miss bounces off the front of the rim.
   - When the outcome is unknown, the ball stops at the rim and no outcome is drawn.

## `scene/{play_id}.json` (`replay.scene.v1`)

```jsonc
{
  "schema": "replay.scene.v1", "play_id": "pl_0001", "label": "...", "sport": "basketball",
  "variant": "half", "synthetic": true, "fps": 30.0, "t_start": 12.3, "t_end": 20.1,
  "frames": 234,                       // frame f is at t_start + f / fps (source clock)
  "units": "m", "axes": "court template frame: x, y on the floor, z up",
  "method": "motionbert" | "analytic", "keypoints": "gt" | "yolo" | "poses",
  "skeleton": {"format": "h36m17", "joints": ["pelvis", "r_hip", ...], "parents": [-1, 0, ...]},
  "camera": {"K", "R", "t", "dist", "image_size"},     // the real camera (calibration.json)
  "court": {"rims": [[x, y, 3.05], ...], "rim_height_m": 3.05},
  "primary": "p3", "shooter": "p3",
  "players": [{"id": "p3", "team": 0 | 1 | null, "color": "#C0392B", "label": "Avery", "height_m": 1.87,
               "joints": [[[x, y, z] x 17] | null per frame],   // null = not on court
               "planted": [[r, l] 0/1 per frame]}],
  "ball": null | {"model": "parabola", "event_id", "shooter", "t_release", "t_rim",
                  "made": true | false | null, "release": [x, y, z], "target": [x, y, z],
                  "radius_m": 0.12, "positions": [[x, y, z] | null per frame]},
  "quality": {"players", "jitter_ms2", "foot_slide_cms", "bone_cv", "penetration"
              /* each {"before", "after"} the clean-up */, "planted_frac", "build_s"}
}
```

Readers must ignore unknown keys.

## Renderer (`render.py`)

The renderer is a painter's-algorithm rasteriser on OpenCV:
- The textured floor is drawn with Tier B's `draw_plane`.
- Capsule limbs are layered anti-aliased thick lines, shaded by depth and by part.
- Head, joints and ball are spheres.
- Backboard, rim, net and stanchion are drawn too.
- Soft shadows are included.
- All primitives are depth-sorted per frame.

The cameras use Tier B's `look_at` / `View` with eased moves (`camera.ease`, smoothed
paths).

| angle | camera |
|---|---|
| `broadcast_high` | orbit, 15 m out, 9 m up, 12° sweep around the action |
| `baseline` | behind the target basket, 2.4 m up, 64° FOV, slow lateral drift. In net sports it sits behind the baseline on the focus player's side |
| `overhead` | top-down, descends from 19 m to 15 m |
| `reverse` | the far side (camera azimuth + 180°), 6.5 m up |
| `pov_<pid>` | the shooter's head; 90° HFOV; looks along the direction of travel, then eases onto the rim 2 s before release. In net sports it looks across the net throughout. The shooter's own body is not drawn |

Net sports (pickleball, badminton, volleyball) get a 3D net: posts, a see-through mesh,
and white tape at the template's `net_height_m`. It is drawn between the post tops from
`courtcam.calibrate.height_landmarks`.

**Why no GL (measured).** No GL library is installed in the box's env: pyrender,
moderngl, open3d, vtk and PyOpenGL are all missing. In a scratch venv, headless moderngl
on Mesa EGL (radeonsi, the CPU's integrated GPU) rendered an equivalent load in
**3.6 ms/frame**. That load was 1130 instanced spheres plus a textured floor, at
1280x720 with 4x MSAA and readback. The painter takes **15-37 ms/frame** on one CPU core.

The painter is kept anyway, for three reasons:
- An 8 s highlight costs it 4-9 s per angle, and the angles render as parallel CPU
  tasks. That is already far inside the replay budget.
- It needs no new dependency and no GL context in the worker.
- It needs no GPU lock on a shared box.

GL is the upgrade path if render time ever matters: it is about 5-8x faster.

## Quality: what the clean-up buys

These numbers come from synthetic basketball (`samples/synthetic` rig, `--kp gt`), on
two highlights × all players. MPJPE is measured over the 12 joints that both skeletons
define the same way.

| play | method | MPJPE mm (abs) | pelvis-aligned | jitter m/s² before→after | foot slide cm/s before→after | bone CV before→after | height err |
|---|---|---|---|---|---|---|---|
| pl_0001 | MotionBERT | 128→125 | 75→74 | 10.0→4.0 | 25.2→0.3 | 0.040→0 | 2 cm |
| pl_0001 | analytic | 171→172 | 174→174 | 15.3→5.4 | 31.0→0.4 | 0→0 | 2 cm |
| pl_0002 | MotionBERT | 141→139 | 74→75 | 12.8→5.1 | 28.5→0.9 | 0.040→0 | 3 cm |
| pl_0002 | analytic | 185→187 | 174→175 | 16.7→6.2 | 28.8→1.1 | 0→0 | 3 cm |

For comparison, the ground truth itself has jitter of 4.5-5.6 m/s². Its foot slide is
about 24 cm/s because the synthetic rig skates. The clean-up brings jitter down to
about the level real motion has, and it removes skating without changing accuracy
(MPJPE within ±2 mm).

Torso overlap (the fraction of pair-frames overlapping by more than 2 cm) is rare on
these clips. It goes 0.05%→0.04% here, and on the denser 10-player worker scenes it goes from at
most 0.28% to at most 0.06%. Plots are in `docs/evidence/M9/synth_bb_full_quality_*.png`.

On real footage (the CC BY pickleball clip, YOLO11m-pose keypoints, MotionBERT; no
ground truth) the raw lift is much noisier, and the clean-up does more:
- jitter 39-56 m/s² → 9-15 m/s²
- foot slide 59-69 cm/s → 0.2-1.4 cm/s

## Limits

- **Jumps are not recovered.** `ground` keeps the lower ankle at floor height, so a
  jump shot is played flat-footed.
- **Monocular depth.** Absolute error is about 2x the pelvis-aligned error: depth
  along the camera ray is the weak axis.
- **Analytic left/right ambiguity.** A bone almost parallel to its ray has two
  equally good roots. The prior and continuity choose between them, and limbs
  sometimes take the wrong one.
- **Ball.** The ball is modelled for basketball shots only. When the outcome is
  unknown, nothing is drawn after the rim.
- **Pinhole only.** A panoramic or stitched camera (e.g. Kennesaw) cannot be placed.
  Real footage needs a calibrated `calibration.json`, possibly with radial `dist`.
