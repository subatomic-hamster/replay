# M8 evidence: full camera calibration, court plate, SAM 2.1 masks, Tier A + Tier B replay angles

Everything here was produced on hfbox by the worker (`python -m replay_worker run ... --stages
replays`) and the scripts named below. Synthetic inputs are labelled SYNTHETIC in every frame
(burned in by the renderer) and in every file name (`synth_*`). Real YouTube-licensed footage
(D-7) is never in this directory: its renders live in `docs/evidence/local/M8/` (gitignored).

## 1. Full calibration (`calibration.json`)

`courtcam.calibrate.camera_calibration`: focal from the floor homography (Zhang's constraints,
square pixels, principal point at the centre), pose from `K^-1 H`, then `solvePnP` refinement
over floor + height landmarks (rim top at 3.05 m, net-post tops at the sport's net height)
inside a golden-section search on the focal; k1 is the D-25 division model from the lens fit.
If the clicked l/r labels are mirror images of the template the camera lands below the floor:
the fit is redone in the x-mirrored world and the mirror folded into R (det R = -1,
`mirrored: true`).

### Synthetic truth (20 noise seeds per row, `scripts/eval_calibration.py --seeds 20`)

Medians; noise = Gaussian sigma on every click; "height lm" = number of height landmarks
added to the floor clicks. Full table: `calibration_synthetic.md`.

| scene | k1 | noise px | height lm | focal err % | rot err deg | pos err m (p90) |
|---|---|---|---|---|---|---|
| basketball/half | 0 | 1 | 0 / 1 | 0.64 / 0.62 | 0.27 / 0.28 | 0.08 (0.18) / 0.08 (0.18) |
| basketball/full | 0 | 1 | 0 / 1 | 0.49 / 0.50 | 0.21 / 0.21 | 0.07 (0.11) / 0.08 (0.12) |
| pickleball/doubles | 0 | 1 | 0 / 2 | 0.31 / 0.32 | 0.11 / 0.11 | 0.04 (0.07) / 0.04 (0.06) |
| badminton/doubles | 0 | 1 | 0 / 2 | 0.25 / 0.21 | 0.13 / 0.09 | 0.04 (0.06) / 0.03 (0.07) |
| volleyball/indoor | 0 | 1 | 0 / 2 | 0.35 / 0.28 | 0.14 / 0.12 | 0.06 (0.09) / 0.05 (0.08) |
| basketball/half | -0.2 | 1 | 0 / 1 | 1.93 / 1.95 | 0.27 / 0.29 | 0.56 (0.70) / 0.56 (0.70) |
| volleyball/indoor | -0.2 | 1 | 0 / 2 | 0.73 / 0.63 | 0.18 / 0.18 | 0.20 (0.71) / 0.19 (0.68) |

Exact clicks recover the true camera to 0 in every scene, with or without lens. With a
-0.2 lens and 2 px noise the lens fit (not this step) rejects 1-8 of 20 seeds on the net
sports. Height landmarks help a little on the net sports and not at all on basketball.

### Real clips (floor clicks from `samples/real/*.landmarks.json`, no ground truth)

| clip | size | k1 | reproj px | focal px | hfov deg | camera xyz m | mirrored |
|---|---|---|---|---|---|---|---|
| badminton_auditorium | 1920x1080 | -0.653 | 2.47 | 813 | 99.5 | (-4.97, 6.73, 2.12) | yes |
| basketball_kennesawwide | 2560x960 | 0 | 0.03 | 1409 | 84.5 | (7.76, 29.48, 2.55) | no |
| basketball_northsidewide | 2560x960 | 0 | 0.03 | 1228 | 92.4 | (6.80, 28.59, 2.74) | no |
| basketball_powellgym | 1920x1080 | 0 | 0.03 | 656 | 111.3 | (10.91, 26.69, 2.90) | no |
| pickleball_legacypark | 1920x1080 | 0 | 0.44 | 796 | 100.7 | (2.10, -2.25, 1.93) | no |
| pickleball_surrey2026 (CC BY, 8 hand clicks) | 1920x1080 | 0 | 2.64 | 1736 | 57.8 | (0.17, -6.17, 2.05) | no |

Held-out height check (hoop centres hand-clicked, `docs/evidence/local/M8/height_clicks.json`):
the floor-only camera puts the hoop 92 px (kennesaw), 78 px (northside) and 58 / 53 px
(powellgym, both hoops) from where it is. Refitting with the hoop leaves it 51-82 px off and
raises the overall reprojection to 17-22 px: a pinhole with a centred principal point and one
radial term cannot explain these wide / stitched rigs (the 2560x960 clips are panoramic).
The floor fits are near-exact because those landmark sets were snapped to a homography.
Consequence: on these clips Tier B floors and billboard feet are right, heights above the
floor (hoop, ball arc) are only approximate.

## 2-4. Plate, masks, Tier A + Tier B renders

Three games, three highlights each, every highlight rendered in six time-aligned angles
(1280x720 Tier B, 1280-wide Tier A):

| tag | input | highlights |
|---|---|---|
| `synth_bb_half` | SYNTHETIC basketball/half, 40 s, seed 7, 1920x1080 (`courtcam synth`) | 3 shots from plays.json (two makes, one unresolved) |
| `synth_vb_indoor` | SYNTHETIC volleyball/indoor, same settings | 2 rallies + 1 attack |
| `cc_pickleball_surrey2026` | CC BY 3.0 real clip (attribution below), first 90 s, YOLO + tracks, 8 hand-clicked landmarks | 3 rallies |

Per highlight: `<tag>_<play>_angles.jpg` (all six angles at 30% and 75% of the play, each
tile captioned with angle, tier and source) and `<tag>_<play>_orbit.mp4` (640 wide); one
`<tag>_pl_0001_orbit.gif` per game. `<tag>_timings.json` is the per-task log.

**Plate**: per-pixel temporal median of 41 frames over the whole clip with every tracked box
masked out, remapped to a top-down metric floor texture (40 px/m, court + 3 m) and a vertical
backdrop wall (20 px/m) behind the play. **Masks**: SAM 2.1 hiera-small bf16 (transformers
`Sam2VideoModel`), re-prompted with the track boxes every 48 frames, each mask clipped to its
grown track box. **Tier B**: plate floor + backdrop as textured planes, players as
mask-cut billboards standing on their tracked foot points (contact shadows, painter's order),
FIBA hoop/backboard geometry and a parabolic ball from release to rim (basketball), net posts
and a translucent net between far- and near-side players (net sports); cameras `orbit`
(+/-30 deg sweep around the play), `push_in` (starts exactly on the real camera, moves halfway
in) and `broadcast_high` (elevated, trucks with the play), all eased. Every Tier B frame
carries a burned-in "TIER B 2.5D | <angle> / flat player cutouts on a reconstructed court"
label (plus SYNTHETIC on synthetic input).

### Timings (hfbox, RX 9070 XT + 7800X3D, worker log, GPU-lock queueing excluded)

| stage | synth basketball (10 players) | synth volleyball (12) | CC pickleball (2-3 tracked) |
|---|---|---|---|
| camera (calibration.json) | 0.02 s | 0.01 s | 0.7 s |
| plate (41 frames, 1080p) | 12.2 s | 12.0 s | 20.5 s |
| segment, SAM 2.1 per play | 62-67 s / 240 fr (266 ms/fr) | 37-78 s (311 ms/fr) | 17-20 s / 240 fr (82 ms/fr) |
| tiera wide / follow / tight | 8 / 5 / 5 ms/fr | 7 / 5 / 5 ms/fr | 8 / 8 / 7 ms/fr |
| tierb broadcast_high | 40 ms/fr | 45 ms/fr | 57 ms/fr |
| tierb orbit | 42 ms/fr | 49 ms/fr | 56 ms/fr |
| tierb push_in | 32 ms/fr | 46 ms/fr | 62 ms/fr |

SAM costs about 26 ms per object per frame, so masks dominate (an 8 s play with 10 players
is about a minute of GPU); every other stage is CPU and faster than real time. A full
re-render after a renderer change re-uses masks and plate (per-stage code versions).

### CC footage attribution

`cc_pickleball_surrey2026_*` and `tv/cc_pickleball_real-api_*`: frames and renders derived
from "2026.09.04 MD4.0 (age 50+) John Lee + Ernest Tosch vs Brendan Fong + Anthony Chang
(Gold Medal)" by pickleball4you, https://www.youtube.com/watch?v=4M58YJoZ4O4, licensed
CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/). Cut to source 100-190 s and
modified (re-rendered from virtual cameras, cropped, scaled, captioned).

### Known artefacts (visible in the sheets)

- Static real objects (hoop, net posts, net) are baked into the plate, so they also
  appear as flat ghosts on the floor / backdrop next to the drawn hoop or net geometry.
- Floor the real camera never saw (beside and behind it) is void; `orbit` and `push_in`
  show it when the play drifts to the near corner (CC pl_0002 at 75%: the players walk
  off court between points). The aim is clamped to the court + 0.5 m.
- Billboards are flat: side-on views of a player at 60 deg from the real camera look thin.
- No ball model outside basketball shots.

## 5. Manifest

`replays/{play_id}/manifest.json` (`replay.replay_manifest.v1`): Tier A `wide`,
`follow:<pid>`, `tight:<pid>` and Tier B `broadcast_high`, `orbit`, `push_in`, every angle
covering the same window (t=0 = play `t_start`, same duration and frame rate) so a TV cut
keeps its place. Served by `GET /games/{id}/replays` and `GET /games/{id}/replays/{play_id}`
(media URLs resolved), videos through the existing `/media` route.

## 6. TV

`tv/` (see `tv/README.txt`): the multi-angle Replay screen (Left/Right cuts, time and play
state kept, Tier badge) on the mock fixture, and on the real worker output served by
services/api for the synthetic basketball play and the CC pickleball play. On every cut the
media time stayed the same (2.508 s and 2.516 s) through all six angles.

## Scripts

- `scripts/eval_calibration.py --seeds 20 --real samples/real --heights <clicks.json>` (section 1)
- `python -m replay_worker run <clip> --out <game> [--detector synthetic] --stages replays`
- evidence sheets / timings: a scratch script on the box (frame grabs + ffmpeg), not committed.
