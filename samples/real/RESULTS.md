# Real-footage tuning run

Box: 16-core CPU, no GPU. Everything below was run as `uv run ...` from the repo root.
Clips are gitignored (`samples/real/MANIFEST.md` has the yt-dlp lines); the
`*.landmarks.json` files and `frames/` are checked in.

## Reproducing the best run

```sh
uv run courtcam run \
    --input samples/real/basketball_kennesawwide_240s.mp4 \
    --calib samples/real/basketball_kennesawwide_240s.landmarks.json \
    --sport basketball --variant full \
    --title "Kennesaw wide" --out out/kennesaw
uv run courtcam overlay --out out/kennesaw
uv run courtcam render  --out out/kennesaw --player p9
```

## Clip triage

| clip | usable? | why |
|---|---|---|
| `basketball_pavilion_240s.mp4` | **no** | 13 hard cuts (multi-camera edit, found with ffmpeg scene detection). A fixed homography is meaningless across cuts. |
| `basketball_parkwide_240s.mp4` | no | outdoor, no painted lines survive a high-pass filter — only tree shadows. Nothing to click. |
| `basketball_powellgym_240s.mp4` | marginal | elevated corner camera, half court readable, but heavy lens distortion. |
| `basketball_northsidewide_240s.mp4` | yes | wide indoor, continuous play. Second choice. |
| `basketball_kennesawwide_240s.mp4` | **yes — primary** | 2560×960, single continuous shot, whole court, real 5v5 in the back half of the clip. |

## Calibrations

| clip | file | variant | landmarks | reprojection error |
|---|---|---|---|---|
| kennesawwide | `basketball_kennesawwide_240s.landmarks.json` | full | 14 (`corner_fr` off-frame) | **0.261 px** |
| northsidewide | `basketball_northsidewide_240s.landmarks.json` | full | 14 (`corner_fr` off-frame) | **0.119 px** |
| powellgym | `basketball_powellgym_240s.landmarks.json` | full | 15 | **1.041 px** |

All three are well under `calibrate.MAX_REPROJ_PX = 5.0`, and all three are
**flattered by that number**: these cameras are ultra-wide/panoramic-stitched, so the
image is barrel-distorted and a single homography cannot be right everywhere. The fit
trades accuracy in the far half for accuracy near the clicked points. Look at
`frames/kennesawwide_overlay_t*.jpg`: the yellow polygon **contains** the play area but
does not sit on the lines — the far sideline rides up into the bleachers.

That is good enough for what the polygon is actually used for (the on-court filter,
`margin_m = 1.0`) and not good enough for court-metre analytics (heatmaps, shot charts,
distance gates) on this corpus. Fixing it needs a distortion model
(`cv2.fisheye` / `calibrateCamera` with `k1,k2`), not more landmark clicking.

Because corners are routinely off-frame or under a bleacher, `basketball.yaml` grew
`court.landmarks_optional` (`key_*`, `ft_*`, `centre_*`). Any of them present in a
`landmarks.json` is folded into the fit; the uploader still only asks for the 4 corners
+ rim, so the API contract is unchanged.

## Full run — `basketball_kennesawwide_240s.mp4`

### Timing (240 s clip, stride 2 = 3600 detected frames)

| stage | wall | note |
|---|---|---|
| ingest | ~6 min | software H.264 encode of 2560×960; VAAPI is the known 3× win |
| calibrate | 0.0 s | |
| detect + track | **709 s** | dominates: 5.96 sampled-frames/s at imgsz 960 |
| court | 0.7 s | |
| identity | **14.5 s** | was 214 s before the sequential-decode fix (below) |
| tracks | 0.6 s | |
| crops | 2.3 s | |
| events | 9.6 s | |
| **run total** | **17 min 23 s** | 678 MB peak RSS |
| overlay | ~3.5 min | separate command |
| render (1 player) | ~8 min | separate command |

≈ 4.3× realtime for `run`. Detection is the only stage worth optimising.

### Players

721 raw tracklets → 396 survive the on-court filter → merged into 10 players
(profile cap `players.max = 10`):

```
members per player   [8, 1, 6, 12, 11, 9, 10, 8, 4, 13]
lifetime (s)         [153.9, 128.9, 114.8, 114.3, 110.2, 105.7, 99.6, 99.0, 155.5, 116.0]
inside_fraction      [0.99, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
coverage             mean 4.77 players/s, median 4, min 1, 0 dead seconds
team split           4 / 6
```

Good:
- Bench players on the right-hand bleachers and spectators behind the baseline are
  dropped by the on-court filter — visible in every overlay frame.
- 0 dead seconds: there is always someone selectable, which is what select mode needs.
- Fragmentation is real (up to 13 tracklets per player) and the merge handles it.

Bad:
- **The scorer's table is on the court.** The two seated officials bottom-left
  (`frames/kennesawwide_shot_t16.4.jpg`) are inside the over-large polygon for the whole
  clip, so they merge into long, stable, high-scoring "players" and eat 2 of the 10
  slots. They are the *best* tracklets by the current score (lifetime × inside
  fraction), because they never move. Root cause is the loose homography, not the
  filter.
- **Team split is meaningless here.** `team_rule: jersey_color` returned
  `#585861` and `#38373E` — two near-identical greys. The teams in this clip wear white
  and light blue, but at 2560×960 across a whole gym a player is ~60 px tall and the
  dominant torso colour is floor-reflection grey. 4/6 is arbitrary.
- Identity switches are frequent around the paint (the merge window is 5 s / 7 m, which
  is deliberately loose — see below). The tag UI is the correction mechanism.
- The first ~90 s of this clip is warm-up, not 5v5. "~10 on court" only holds after
  roughly t = 100 s.

### Follow-cam (`courtcam render --player p9`)

`frames/kennesawwide_p9_t{100,150}.jpg`. Motion is smooth — no jitter, no snapping;
the spring is doing its job. Two problems:

- **`zoom: 2.0` is far too wide for a whole-court source.** The crop is 1920×720 out of
  2560×960; the subject is a ~60 px figure in a frame mostly full of empty floor. At
  t=100 s the subject is right-of-centre, not centred, because the lead term aims ahead
  of a player who then changed direction. On a 2560-wide whole-court clip this wants
  zoom ≈ 4–5. Left at 2.0 because the synthetic golden and the TV app's framing were
  both tuned against it — `# ponytail:` candidate, not a blind change.
- p9 at t=150 s is centred on the **referee**. Same root cause as the scorer's table.

> `media/p9.mp4` in the scratch run is truncated past ~155 s because the background job
> that ran the render was killed on a timeout, not because of a courtcam bug.

### Shot events

8 events at t_key = 16.4, 114.4, 153.2, 201.2, 207.3, 227.8, 233.6, 237.0 s.
Checked three against the overlay (`frames/kennesawwide_shot_t*.jpg`):

| t_key | actually a shot? |
|---|---|
| 16.4 s | **no** — a single player dribbling up the left side during warm-up |
| 153.2 s | **maybe** — a contested drive / rebound scramble in the left key; a shot may be in it |
| 207.3 s | **no** — players walking the left wing, ball not even in the ROI |

Precision is roughly 1/3. The knob the profile exposes (`burst_sigma`) is **not** the
problem: 8 events in 240 s is not a spam rate, the events are landing in the right
*place* and at the wrong *moment*. The gate that would help is
`shot.rim_radius_m = 7.0`, which on a half court is "anywhere inside the arc" — but
tightening a metre threshold is pointless while the homography is the loose fit
described above, since the metric distance is what is wrong. Left alone deliberately:
per §6.3 the review queue is the correction mechanism, and the real fix is the
`Labeler` seam (VLM on the candidate clip), not a better pixel heuristic.

## Detection speed and recall

100 frames sampled across the pavilion clip, counting person boxes. Each backend
measured alone (concurrent runs contaminate the numbers by ~2.5×).

| model | imgsz | backend | wall | sampled fps | boxes/frame |
|---|---|---|---|---|---|
| yolo11n | 640 | pt | 9.1 s | **10.73** | 9.14 |
| yolo11n | 960 | pt | 16.4 s | 5.96 | **13.54** |
| yolo11s | 640 | pt | 19.2 s | 5.10 | 12.73 |
| yolo11n | 640/960 | openvino | — | slower than pt | same |
| yolo11n | 640/960 | onnx | — | slower than pt | same |

**Defaults unchanged: `yolo11n`, `imgsz: 960`, backend `pt`.**

- 640 loses 32 % of the boxes (13.54 → 9.14/frame). On a whole-court wide shot the
  players are small and 640 drops exactly the far-half ones select mode needs. 1.8×
  speed is not worth a third of the roster.
- `yolo11s` at 640 is *slower than yolo11n at 960* and still finds fewer boxes. No
  reason to go bigger.
- OpenVINO and ONNX both lose to plain PyTorch on this CPU. They are wired up behind
  `--backend {pt,openvino,onnx}` with a cached export under `~/.cache/courtcam/`
  (cache key includes imgsz, because the export bakes the input size in) and a warn +
  fall back to `.pt` if the export fails — measure before switching on a different box.

## Changes made to courtcam

| change | why |
|---|---|
| `players.max` moved from `court.on_court()` to `identity.identify()` | **The bug that mattered.** Capping raw tracklets before the merge kept whoever had the longest unbroken track and threw the rest of the roster away: every player came out with `members: 1` and ~3 were selectable at a time. Capping *merged* players took the run to 10 players / 0 dead seconds. |
| `tracking.max_candidates: 400` (new) | The O(n²) merge still needs a guard; that is all the old cap was really doing. |
| `identity.sample_appearance` does one sequential decode pass | Seeking per sampled frame cost ~214 s and grew with the candidate count. Now 14.5 s, independent of tracklet count. |
| `merge_max_gap_s` 1.5 → **5.0**, `merge_max_dist_m` 2.0 → **7.0** | 1.5 s / 2 m assumes a clean overhead shot. In a real gym a player disappears behind a screen for seconds. Swept the pair; 5 s / 7 m is where coverage stops improving (mean 4.77 players/s, 0 dead seconds) without merging two different people every possession. Costs identity switches, which the tag UI fixes. |
| `court.landmarks_optional` + `key_*`/`ft_*`/`centre_*` in both templates | Real footage puts corners off-frame. Optional, so the API/uploader contract (4 corners + rim) is untouched. |
| `--backend` flag, cached exports | see above |
| per-stage timing in the CLI progress line | produced the timing table above |

`uv run pytest courtcam/tests -q` → **29 passed**. `uv run ruff check courtcam/` clean.
The two identity tests that pin merge behaviour now use a module-local `MERGE` profile
with the old 1.5 s / 2 m so they test the *rule*, not the tuning. The golden tolerances
were **not** touched.

## Recommended defaults

Shipped as-is in `courtcam/sports/basketball.yaml`:

```yaml
detection: {model: yolo11n.pt, imgsz: 960, stride: 2, conf: 0.25}
tracking:  {oncourt_min_fraction: 0.6, min_lifetime_s: 1.0,
            merge_max_gap_s: 5.0, merge_max_dist_m: 7.0, max_candidates: 400}
followcam: {zoom: 2.0, lead_s: 0.3, stiffness: 7.0}
shot:      {rim_radius_m: 7.0, burst_sigma: 2.5, min_gap_s: 2.0}
```

Not changed, and why:

- **`margin_m: 1.0`** — already correct. Raising it lets more bleacher in; lowering it
  clips players who step out. The scorer's-table problem is the homography, not this.
- **`followcam.zoom`** — wants ~4 on a 2560-wide whole-court source and ~2 on a
  tighter one. It should scale with `source_width / court_width_px`, which is a real
  change, not a retune.
- **`shot.burst_sigma` / `rim_radius_m`** — see the shot section.

## Next thing worth doing

Lens distortion. It is the single root cause behind the loose polygon, the
scorer's-table false players, and the unusable metric gates. (The meaningless team
colours are a separate problem — that one is resolution.) `cv2.calibrateCamera` with `k1,k2` estimated
from the straight court lines, applied before the homography, would fix all of it.
