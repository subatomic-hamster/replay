# 2.5D scene package — `replay.scene_package.v1`

One highlight as data that a GPU client renders live from any camera inside an envelope
around the real one: the court plate as two textured planes, every player as a flat
cut-out billboard standing on its tracked foot point, a few primitives (hoop, net, a
modelled ball). One H.264 video carries every player cut-out for the whole highlight, so a
Fire TV needs exactly one hardware decoder (MediaCodec → SurfaceTexture → external GL
texture) and the web one `<video>` (three.js `VideoTexture`). No per-angle server render.

Producer: worker stage `scene` (one task per highlight, cached, opt-in like every virtual
stage — D-56), code in `render/replay_render/virtual/scene.py`. It reuses Tier B's plate
(`courtcam.plate`), SAM 2.1 masks (`segment`), calibration (D-53) and geometry (D-54).
The CPU reference renderer in the same module (`scene.render`) is the ground truth the web
and native viewers are compared against.

The schema string differs from Tier C's `scene/{play_id}.json` (`replay.scene.v1`, 3D
joints, D-59): that file and this package are unrelated.

## Files

`<game>/replays/{play_id}/scene/`

| file | what |
|---|---|
| `layout.json` | everything below (compact JSON, ~0.2–0.4 MB for an 8 s play with 10 players) |
| `atlas.mp4` | player cut-outs, one video frame per play frame |
| `floor.png` | RGBA floor texture, alpha = seen by the real camera |
| `backdrop.png` | RGBA vertical wall texture, alpha = seen |

API (GET only):

- `GET /games/{id}/scenes` → `{game_id, scenes: [{play_id, label, schema, t_start, t_end,
  n_frames, synthetic, layout_url}]}` in time order.
- `GET /games/{id}/scenes/{play_id}` → `layout.json` plus `game_id`, and an absolute `url`
  next to every `file` (plates and atlas). The files are served by
  `/media/games/{id}/replays/{play_id}/scene/<file>` with HTTP Range (206), like every
  other media file.
- `GET /games/{id}/replays/{play_id}` (the M8 manifest) carries `scene_url` (the layout
  route) when the package exists, else `null`.

TypeScript: `SceneLayout`, `SceneSummary` and friends in `packages/tv-core/src/types.ts`.
Committed synthetic fixture (labelled SYNTHETIC, a few frames): `services/api/fixtures/scene_synth/`.

## Time

`fps` and `n_frames` are the source's; atlas frame `f` is media time `f / fps`, and media
time 0 is `t_start` of the play in the source video — the same clock as every M8/Tier B
angle of the play (D-56), so a TV can cut from a video angle to the live scene at the same
`currentTime`. `frames[f]` describes atlas frame `f`. Seek the atlas like any video;
keyframes are at most 1 s apart (`gop_frames` = floor(fps)).

## Coordinate frame

The **scene frame** is the court frame of the sport template (metres; the floor is z = 0;
+z up; basketball: x across the court, centre line x = 0, y along it from 0 to 28): when
the calibration is mirrored (D-53, det R = −1) every x in the package is negated
(`frame.mirror_x: true`), so the real camera is always a proper rotation and no client
flips anything. Right-handed, metres, degrees in the JSON, seconds.

`camera` is the real camera, OpenCV convention: `x_cam = R·X + t`, `pixel = K·x_cam / z`
(x right, y down, z forward), `image_size` the source size, principal point at its centre
(D-53), `position_m = −Rᵀt`. Pixels are pinhole pixels: the lens (k1) is already removed
from every texture. A GL view matrix is `diag(1, −1, −1, 1) · [R | t]`. K uses OpenCV pixel
centres (pixel (0,0)'s centre is at 0,0); GL's are at half-integers, so a GL client shifts its
projection by half a pixel (`camera.viewProjection` in apps/tv/src/scene/camera.ts does).
Without it players land 0.5 px off, which cost ~15 dB PSNR against the reference renderer.

## Plates

`plates` = `[backdrop, floor]` (draw in that order). Each: `file`, `size_px`, and
`corners_m` = the world positions of the texture's **edges** at uv (0,0), (1,0), (1,1),
(0,1), uv origin at the image's top-left, v down (flip v if your upload puts row 0 at the
bottom). Planes are flat quads: draw two triangles, double-sided (a mirrored scene flips
the winding). Texture alpha is 0 (with a 1-texel bilinear edge) where the real camera never
saw that texel: do **not** paint anything there except the background colour — the void
is intended, it is what the camera did not see.

- floor: the Tier B top-down texture, court + 3 m, 40 px/m.
- backdrop: a vertical wall at the far edge of the floor bounds facing the real camera,
  8 m tall, 20 px/m.

Both come from the temporal median of the whole clip with players masked out; static real
objects (hoop stanchions, tables, benches, bleachers) are baked in flat (ghosts). Only one
wall exists: when the real camera looks diagonally (Kennesaw), the side of the hall
outside that wall is void.

## Atlas

`atlas`: `size_px` (W, H) with W, H multiples of 16, W ≤ 2048, H ≤ 1024; H.264 High,
yuv420p, BT.709 tagged limited range, faststart, constant `gop_frames`.

- Left half (`u < 0.5`): colour. Right half: the mask as grey (luma; chroma neutral).
  The mask texel of a colour uv is at `u + mask_offset_u` (0.5), same v.
- A fixed grid of `grid = [cols, rows]` cells of `cell_px = [w, h]` (multiples of 16, so
  cells never share a macroblock), the same in both halves. A player keeps its cell while
  visible; a cell freed by one player can be reused by another later.
- Each frame lists its players in `frames[f]`: `{pid, cell, foot: [x, y], rect: [s0, z0,
  s1, z1], uv: [u0, v0, u1, v1], depth}`. `uv` is the content rect (texel edges, full-video
  normalised, v down) of the colour half; `inset_px` texels of gutter around it contain an
  outward extension of the colour and the mask's falloff, so bilinear taps at the rect
  edge are safe. Unused cells are black with mask 0.
- **Alpha**: sample the mask half (any channel; G has the most precision), get `m` in 0..1
  after the decoder's YUV→RGB conversion, then `alpha = clamp((m − lo) / (hi − lo), 0, 1)`
  with `[lo, hi] = mask_ramp` (0.1, 0.9). The ramp absorbs codec ringing at silhouettes and a
  decoder that ignores the limited-range flag (16..235 still maps to 0..1).
- Colour outside the mask is a normalised blur of the colour inside, so chroma subsampling
  and filtering do not pull the court into the silhouette; premultiply is not needed.
- `depth` is the real camera's depth (m) of the player's chest point (foot + 0.9 m) — a
  stable tie-break; the per-view draw order is computed by the client.

Cell content is **rectified**: it is the source image resampled onto the player's
billboard plane, metric and axis-aligned, so a client draws an ordinary rectangle with
affine uv — no projective texturing.

## Billboards

For a player with foot `F = (x, y, 0)` and rect `[s0, z0, s1, z1]` the billboard is the
vertical rectangle `F + s·a + z·ẑ`, `s ∈ [s0, s1]`, `z ∈ [z0, z1]` (z0 may be slightly below
0: the mask's feet), textured with uv `[u0, v0, u1, v1]`: `(s0, z1) ↔ (u0, v0)`, `(s1, z1) ↔
(u1, v0)`, `(s1, z0) ↔ (u1, v1)`, `(s0, z0) ↔ (u0, v1)`.

`a` is the horizontal unit axis facing a camera position `C`:
`d = F − C; a = normalize(d.y, −d.x, 0)` (the camera's right). `billboard.facing` says which
`C` to use; v1 packages say **`real`**: `C = camera.position_m`, a fixed orientation per
player and frame. With `real` facing the package reproduces the real camera exactly and
every other view is the true planar parallax of a flat cut-out; the alternative (`viewer`,
`C` = the virtual eye, Tier B's rule) keeps cut-outs full width but swims as the camera
moves and moves the silhouette away from its true position. Measured below.

## Static geometry and ball

- `static.hoops[]`: `rim_m` (centre, 3.05 m), `rim_radius_m` 0.225 — draw an orange ring
  (Tier B: 3 px, #FF5A00-ish); `backboard_m` quad (white, ~35 % opacity, opaque outline).
  Heights on wide/panoramic real rigs are approximate (D-53: the hoop is 50–90 px off on
  Kennesaw): the drawn hoop does not sit on the plate's hoop.
- `static.net`: `top_l_m`, `top_r_m`, `depth_m` (net sports): posts from the floor to the
  tops, a translucent band `depth_m` deep below the top line. Draw it between the players
  behind it and the players in front of it (by view depth of its centre).
- `ball`: `null` or `{source: "model", xyz: [[x, y, z] | null per frame], radius_m}` — the
  Tier B parabola for a basketball shot (release → rim), **not** a tracked ball. Say so if
  you label it.

## Camera envelope and presets

A camera state is `{azimuth_deg, elevation_deg, distance_m, roll_deg, fov_y_deg}`:

```
az  = radians(envelope.azimuth0_deg + azimuth_deg)
el  = radians(elevation_deg)
eye = target_m + distance_m · (cos el · cos az, cos el · sin az, sin el)
R0  = look-at(eye → target_m, world up +z)    rows: right = normalize(fwd × ẑ), down = fwd × right, fwd
R   = Rz(roll) · R0,  Rz(r) = [[cos r, −sin r, 0], [sin r, cos r, 0], [0, 0, 1]]
f   = (viewport height / 2) / tan(fov_y / 2),  principal point at the viewport centre
```

`target_m` is the point of the real optical axis nearest the players' mean chest point (it
can lie below the floor when the real camera looks down at the near court: it is only a
pivot). `azimuth0_deg` makes azimuth 0 the real camera's own azimuth, so the preset `real`
(azimuth 0, the real elevation/distance/roll/fov) is exactly the real camera on any aspect
ratio (vertical fov kept).

`envelope`: `azimuth_deg [min, max]` (offsets), `elevation_deg [min, max]` (absolute),
`distance_m [min, max]`, `fov_y_deg` (the real one; v1 has no zoom other than distance),
`limits` and `edge_metrics` (measured at each edge, see below). Clients clamp the state to
the box; roll is not user-controlled (it only moves with the `real` preset).

`presets` (ids are stable across packages; the values are per package):
`real`, `broadcast_high` (az 0, 85 % up the elevation range), `orbit_left` / `orbit_right`
(90 % of the azimuth range towards the real camera's left / right, a little higher),
`push_in` (az 0, closer, halfway down the elevation range). Interpolate between presets
in state space (each field linearly, eased).

Remote mapping as shipped (D-77; shared JS in apps/tv/src/scene/camera.ts, so web and native
match): Left/Right = azimuth ∓ 2.5° per step, Up/Down = elevation ± 2.5° (or dolly by 5 % of
the real camera's distance in zoom mode), Menu = toggle zoom mode, Rewind/Fast-forward =
previous/next preset, Select or Play/Pause = play/pause, Back = leave the scene for the same
angle at the scene's time. Held keys repeat at most 12 steps/s. The `camera` a renderer is given
is a target: it eases toward it (`easeCamera`, `EASE_MS` = 140), and reports `onTime` once
more when unmounted.

### How the limits are derived (per package, from the real camera and the floor it saw)

For a candidate camera the producer computes (`scene.view_metrics`):

- `seen` — fraction of a 192×108 view covered by plate texels the real camera saw (the
  rest is void);
- `az_dev` — over every tracked chest point of the play that lands in the view, the largest
  angle between the real and the virtual horizontal lines of sight: how far a flat cut-out
  is turned away from the side the camera saw (90° = edge-on, > 90° = its back);
- `el_dev` — the same for elevation;
- `mag` — largest cut-out magnification relative to the real camera on the same screen.

Azimuth, elevation and distance grow outwards from the real camera's values in 2.5° / 5 %
steps while `seen ≥ 0.85 × seen(real)`, `az_dev ≤ 30°`, `el_dev ≤ 20°` and `mag ≤ 2`; the
four azimuth × elevation corners are then checked and the box shrunk until they pass. The
envelope is therefore the box in which no visible player is ever turned more than 30°
from the side the camera saw, no cut-out is enlarged beyond 2× and at most ~15 % more void
appears than in the real view. Values per package are in `envelope.edge_metrics`.

### Measurements behind the limits and the billboard rule

Synthetic ground truth (`scripts/eval_scene.py`, `docs/evidence/scene/eval_synth.json`):
`courtcam synth` basketball/full, seed 7, 30 s, 1280×720 sideline camera (fov_y 117°, so
players are only ~30 px tall), 10 players + 3 referees/decoys, highlight pl_0001 (240
frames) through the worker with SAM 2.1 masks. The same seed re-rendered from each orbit
camera is the truth; 8 frames per camera; IoU = on-court silhouettes (truth: pixels that
differ from the empty plate inside the truth boxes, shadows removed; package: billboard
alpha > 0.5); PSNR over the union of both silhouettes. "real / viewer" = billboard facing.

| az | Δel | az_dev° | el_dev° | mag | IoU real / viewer | player PSNR real / viewer |
|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 1.00 | 0.685 / 0.685 | 18.3 / 18.3 |
| +10 | 0 | 12.6 | 2.5 | 0.98 | 0.684 / 0.686 | 15.4 / 15.4 |
| −10 | 0 | 13.0 | 3.4 | 1.24 | 0.635 / 0.634 | 15.3 / 15.2 |
| +20 | 0 | 24.6 | 4.5 | 0.96 | 0.652 / 0.658 | 14.1 / 14.1 |
| −20 | 0 | 26.4 | 8.0 | 1.56 | 0.589 / 0.586 | 13.8 / 13.7 |
| +30 | 0 | 36.1 | 6.0 | 0.95 | 0.621 / 0.634 | 13.3 / 13.3 |
| −30 | 0 | 40.0 | 14.4 | 2.02 | 0.553 / 0.546 | 12.8 / 12.6 |
| +45 | 0 | 52.2 | 7.7 | 0.97 | 0.580 / 0.610 | 12.4 / 12.6 |
| −45 | 0 | 60.9 | 29.8 | 2.94 | 0.474 / 0.468 | 11.8 / 11.6 |
| 0 | +10 | 6.1 | 13.2 | 1.06 | 0.645 / 0.646 | 15.1 / 15.0 |
| 0 | +20 | 14.6 | 26.2 | 1.14 | 0.608 / 0.608 | 13.7 / 13.5 |
| 0 | −5 | 2.3 | 6.6 | 1.01 | 0.689 / 0.690 | 16.6 / 16.5 |
| +20 | +15 | 28.4 | 16.9 | 1.06 | 0.617 / 0.622 | 13.4 / 13.3 |
| −20 | +15 | 26.0 | 24.9 | 1.40 | 0.593 / 0.590 | 13.5 / 13.4 |

Reading it:

- The IoU at the real camera (0.685) is the floor set by SAM masks on ~30 px players and
  the double resampling; it is the reference for the rest.
- Silhouette agreement degrades smoothly with the billboard turn: ≥ 0.95 of the real-view
  IoU up to az_dev ≈ 13°, ≈ 0.86–0.95 at 25°, 0.80–0.91 at 36–40°, 0.69–0.85 beyond 50°.
  The side where players come closer to the camera (−az here: mag 1.6–2.9) degrades
  faster: a 2× enlarged flat card is where the eye sees it is a card. Hence `az_dev ≤ 30°`
  (≈ 0.85 of the real-view IoU at the worst player) and `mag ≤ 2`. Elevation behaves the
  same per degree (el_dev 13° → 0.94, 26° → 0.89), so `el_dev ≤ 20°`.
- Player PSNR drops ~3 dB as soon as the camera moves at all (a flat card is not the
  3D body), then slowly; it does not separate the limits better than IoU.
- **Facing real vs viewer** differ by ≤ 0.03 IoU and ≤ 0.2 dB everywhere inside ±30°;
  `viewer` is only ahead beyond 30° (outside the envelope). v1 uses `real`: it is exact at
  the real camera, needs no per-view axis and does not swim when the camera moves.

Real footage (local only, YouTube-licensed; values from each package's `edge_metrics`):

| clip / play | frames | azimuth | elevation (real) | distance (real) | binding limit |
|---|---|---|---|---|---|
| Kennesaw pl_0001 | 240 | ±7.5° | 11.9–16.9° (11.9) | 15.8–18.4 m (17.5) | az_dev 24.8/26.3° at the az edges after the corner shrink |
| Kennesaw pl_0005 | 150 | ±8.5° | 11.9–16.1° | 15.5–19.2 m (18.3) | az_dev, corners |
| Kennesaw pl_0007 | 240 | ±12.5° | 11.9–19.4° | 11.1–14.6 m (13.9) | az_dev 27.4/29.3° |
| Powell gym pl_0010 | 80 | −7.5…+22.5° | 13.3–28.3° | 12.4–19.1 m | seen (left), az_dev 27° (right) |
| Powell gym pl_0012 | 240 | ±6.1° | 11.8–17.9° | 10.3–12.2 m | corners (az_dev at high elevation) |

Kennesaw's camera stands at the court-end corner 2.55 m high, so players a few metres
from it turn fast with any orbit; going 2.5° below the real elevation drops `seen` from
0.76 to 0.58 (void beyond the single backdrop wall), so the real camera is the lowest
allowed view. Distances shrink to −10…−20 % before `mag` reaches 1.5–1.9 and grow only
+5 % before `seen` falls. Small envelopes, and the honest ones for these rigs: a camera at
head height near the court sees little of anyone's side.

Real-camera reproduction (`--check`, every frame of the play, the `real` camera at the
source size; "seen" = plate texels the camera saw plus players; void excluded there):

| play | players PSNR / SSIM | static PSNR / SSIM | seen PSNR / SSIM | whole frame PSNR / SSIM | seen fraction |
|---|---|---|---|---|---|
| synthetic pl_0001 (1280×720) | 21.9 / 0.866 | 37.8 / 0.973 | 33.5 / 0.967 | 18.0 / 0.693 | 0.26 (no hall in the synthetic world) |
| Kennesaw pl_0001 (2560×960) | 27.9 / 0.905 | 24.6 / 0.880 | 24.6 / 0.880 | 13.2 / 0.741 | 0.79 |
| Kennesaw pl_0005 | 28.3 / 0.903 | 26.6 / 0.887 | 26.6 / 0.887 | 13.2 / 0.746 | 0.79 |
| Kennesaw pl_0007 | 27.9 / 0.920 | 25.0 / 0.881 | 25.0 / 0.881 | 13.2 / 0.743 | 0.79 |
| Powell gym pl_0010 (1920×1080) | 21.5 / 0.780 | 29.4 / 0.949 | 28.7 / 0.946 | 11.0 / 0.683 | 0.61 |
| Powell gym pl_0012 | 24.8 / 0.894 | 26.3 / 0.939 | 25.8 / 0.933 | 10.9 / 0.674 | 0.61 |

Players lose ~1–2 px of silhouette (soft-alpha erosion, two resamplings, CRF 18) and the
synthetic players are only ~30 px tall; the static plate is the clip-wide median (moving
reflections, lighting, people who stood still are not in it); "whole frame" is dominated by
the void (ceiling and side walls the plates do not model).

## How to render (GL client)

Per frame (media time `t` → `f = floor(t · fps)`, clamp to `n_frames − 1`; the decoded atlas
frame is the texture):

1. Clear to the background (Tier B: vertical gradient #16 1A 22 → #09 0A 0C, or any dark
   colour). Depth test off for the whole scene (painter's order is enough and avoids
   alpha-sorting problems with the depth buffer).
2. Backdrop then floor: textured quads, fragment `colour = tex.rgb, alpha = tex.a`, blend
   `SRC_ALPHA, ONE_MINUS_SRC_ALPHA`. Linear filtering, mipmaps on (the floor is minified a
   lot at grazing angles).
3. Contact shadows: for each player a soft dark disc of radius `billboard.shadow_radius_m`
   on the floor at the foot (Tier B: Gaussian falloff, 45 % darkening at the centre).
4. Hoops (backboard, then rim).
5. Players back to front by view depth of `foot + 0.9 m·ẑ`; draw the net when the sort
   passes its depth. Each player: one quad (four world corners from the rect above, uv
   from `uv`); vertex shader passes `uv`; fragment shader, with the atlas as an external
   OES texture (Android) or `VideoTexture` (three.js):

   ```glsl
   vec3 c = texture2D(atlas, vUv).rgb;
   float m = texture2D(atlas, vUv + vec2(maskOffsetU, 0.0)).g;
   float a = clamp((m - rampLo) / (rampHi - rampLo), 0.0, 1.0);
   gl_FragColor = vec4(c, a);              // blend SRC_ALPHA, ONE_MINUS_SRC_ALPHA
   ```
   On Android remember the SurfaceTexture transform matrix (`getTransformMatrix`) for
   `vUv`; apply it to both the colour and the mask coordinate.
6. Ball (if any): a small sphere/disc at `ball.xyz[f]`, optionally a short fading trail.
7. Overlay `honesty_label` permanently (plus SYNTHETIC when `synthetic`).

Billboards: either use `facing: real` exactly (recommended, it is what the producer and
the reference renderer validate) or `viewer`; never rotate them about any axis but z.

## Versioning

`schema` = `replay.scene_package.v1`. Additive fields keep v1 (clients ignore unknown
keys). A change of meaning — frame, uv convention, the alpha ramp, billboard construction,
atlas packing — is `v2`, and the API keeps serving the old directory until it is rebuilt.
The worker stage's code version covers `scene.py`, `tierb.py`, `segment.py`, `replays.py`
and the courtcam calibration and plate modules, so any of those changes rebuilds packages
while SAM masks stay cached.

## Reference renderer

```
python -m replay_render.virtual.scene <game_dir> <play_id> [--no-build] [--max-frames N]
    [--stills DIR] [--check]
```

builds the package (or uses the existing one), writes preset stills at 30 % and 75 % of
the play, and `--check` renders every frame from the exact real camera and reports PSNR /
SSIM against the (undistorted) source frames over the whole frame, the seen region, the
players (the SAM masks) and the static plate (seen, away from players).
`scripts/eval_scene.py` measures novel views against synthetic ground truth.
