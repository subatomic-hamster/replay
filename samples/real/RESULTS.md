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

## End-to-end through the product (Phase 1 §6.3 DoD)

Everything below ran through the real product path, not the CLI: `services/api` with
`REPLAY_PIPELINE` unset (so courtcam + YOLO), the Vite app pointed at it, and Playwright
driving the browser. It is reproducible as the opt-in `real` Playwright project:

```sh
cd apps/web
REPLAY_E2E_REAL=1 REPLAY_E2E_REAL_DATA=/tmp/replay-real pnpm exec playwright test --project=real
```

`apps/web/e2e-real/` holds three specs — `R-01` (upload → calibrate → process → watch →
follow → highlights → review on the 50 s smoke cut), `R-02` (the select/follow DoD table
below on the 240 s clip) and `R-03` (a 1920×1080 `recordVideo` run of the whole loop).
They skip themselves when the clip is missing, because `samples/real/` is gitignored (D-7).

### DoD — "select → follow → back works for every on-court player in a 5-minute stretch"

`basketball_kennesawwide_240s.mp4`, uploaded and processed through the API, driven on the
TV with the keyboard D-pad only. At each timestamp every `select-box-*` was enumerated,
reached by arrow presses alone (cap 20), followed with Enter, and dismissed with Escape.

| t | player | reached (presses) | followed | same frame | back to wide |
|---|---|---|---|---|---|
| 30 s | p1 | yes (9) | yes | yes | yes |
| 30 s | p2 | yes (6) | yes | yes | yes |
| 30 s | p3 | yes (12) | yes | yes | yes |
| 30 s | p4 | yes (6) | yes | yes | yes |
| 30 s | p5 | yes (4) | yes | yes | yes |
| 30 s | p6 | yes (8) | yes | yes | yes |
| 30 s | p7 | yes (2) | yes | yes | yes |
| 30 s | p8 | yes (4) | yes | yes | yes |
| 90 s | p1 | yes (6) | yes | yes | yes |
| 90 s | p2 | yes (6) | yes | yes | yes |
| 90 s | p3 | yes (8) | yes | yes | yes |
| 90 s | p4 | yes (2) | yes | yes | yes |
| 90 s | p5 | yes (6) | yes | yes | yes |
| 90 s | p6 | yes (2) | yes | yes | yes |
| 90 s | p7 | yes (6) | yes | yes | yes |
| 90 s | p8 | yes (6) | yes | yes | yes |
| 90 s | p9 | yes (2) | yes | yes | yes |
| 150 s | p1 | yes (3) | yes | yes | yes |
| 150 s | p9 | yes (2) | yes | yes | yes |
| 150 s | p10 | yes (2) | yes | yes | yes |
| 210 s | p9 | yes (2) | yes | yes | yes |
| 210 s | p10 | yes (2) | yes | yes | yes |

**22/22 reachable, followed and returned.** "same frame" = `currentTime` moved by less
than 1/30 s across the Enter, i.e. following is not a seek (W4).

The honest caveat is not the interaction, it is the **roster**: 8–9 boxes at t = 30/90 s
but only 3 at 150 s and 2 at 210 s. `players.max = 10` caps *merged* players, and on this
clip the ten best-scoring merges are not contemporaneous — p1…p8 all end by ~155 s while
p9/p10 only start at 84 s/124 s. Every player who *is* on court is selectable; the number
on court late in the clip is smaller than the number actually playing. Raising
`players.max` (the cap exists to bound the O(n²) merge, which `tracking.max_candidates`
already does) is the obvious next experiment.

### Per-stage timings, through the API

| stage | 50 s smoke cut | 240 s clip |
|---|---|---|
| ingest | 20.9 s | 107.9 s |
| calibrate | 2.9 s | 4.0 s |
| detect (+ ByteTrack) | 143.9 s | 808.9 s |
| track | 0.2 s | 0.8 s |
| court | 0.4 s | 0.8 s |
| identity | 3.1 s | 16.5 s |
| tracks | — | 1.0 s |
| crops | — | 0.4 s |
| events | 13.3 s | 16.6 s |
| **job total** | **174.6 s** | **957.0 s** |

≈ 3.5× and 4.0× realtime. Detect is still 85 % of it. (Smoke-cut `tracks`/`crops` are
folded into `events` there — they are sub-second.)

### Follow-cam zoom, re-measured

The earlier note that the subject is "a ~60 px figure" was eyeballed and too pessimistic.
Measured over every track of the 240 s run, an on-court box is **p10 96 px, median 124 px,
p90 227 px** tall in the 2560×960 source. `followcam.zoom` now divides the court's pixel
width (2492.7 px here) instead of the frame's, and the window is 16:9 instead of the
source's 8:3:

| zoom | window | median player |
|---|---|---|
| 2.0 | 1246×701 | 1/5.7 of crop height |
| **2.4** | **1039×584** | **1/4.7** |
| 3.0 | 831×467 | 1/3.8 |
| 4.5 | 554×312 | 1/2.5 |

Shipped at **2.4**. Spot-checked against the most mobile player's own box: 1/4.8, 1/4.9
and 1/5.2 of the crop height at t = 30.8 / 77.0 / 123.2 s. The real defect the old
constant caused was the **aspect**, not the width — a 1280×480 window stretched into a
16:9 viewport made every player 1.5× too tall; that is fixed in `PlayerSurface` and in
`render.render_crop` (D-20).

### Calibrating real footage from the uploader

Clicking the 14 usable landmarks by hand on the real calibrate screen gives **5.2 px**,
against 0.26 px for the exact values in `basketball_kennesawwide_240s.landmarks.json`.
That gap is click quantisation, and it is brutal here: ±0.5 px of jitter already costs
~3.5 px of reprojection error on this point set, because no single homography fits a
barrel-distorted panorama (D-18). Measured, 25 samples each:

| frame shown at | reprojection error (median) | court polygon vs the exact fit |
|---|---|---|
| 560 px (the old phone column) | 16.5 px | 53 px |
| 1200 px | 10.2 px | 54 px |
| 1920 px | 2.9 px | 25 px |

So the calibrate screen now uses the whole viewport, a required landmark can be skipped
when it is off-frame, `landmarks_optional` are reachable from the uploader, and the gate
scales with the clicked span (D-19). Guessing `corner_fr` on-frame instead of skipping it
is 17–21 px with 5 points and ~2000 px once the optional points are in — worse than
leaving it out, which is why "Not visible" exists.

### Screenshots and demo

Held outside the repo (third-party footage, D-7) under the run's scratch dir:
`real/{01-calibrate,02-select,03-follow,04-highlights,05-status-phone-midrun,06-review}-real.png`
at 1920×1080, plus `real/demo-rough.webm` (1920×1080, the R-03 loop).

### Concurrency cap

The roster caveat above is fixed. `players.max` was a **global** cap on merged players,
so on a 240 s clip the ten best-scoring merges were simply the ten longest-lived ones —
all clustered in the first half. It is now a **concurrency** cap: merged players are taken
best score first and one is accepted only if it never pushes the number of players alive
at the same instant past `players.max`. The roster over the clip can therefore be much
larger than 10; the TV never sees more than 10 boxes at once.

Re-run on the same `_work/dets.json` / `_work/tracklets.json` as the run above (stages
`identity,tracks,crops,events` only — no YOLO, nothing before `identity` changed):

**Players in `game.json`: 10 → 57.** `identity` still 16 s, `tracks` 1.3 s, `crops` 14.5 s,
`events` 15.3 s.

Concurrent selectable players per 10 s chunk, counted from `tracks/{chunk}.json`:

| window | before (min-max, mean) | after (min-max, mean) |
|---|---|---|
| 0-10 s | 7-8, 7.4 | 9-10, 9.9 |
| 10-20 s | 8-8, 8.0 | 10-10, 10.0 |
| 20-30 s | 8-8, 8.0 | 10-10, 10.0 |
| 30-40 s | 8-8, 8.0 | 10-10, 10.0 |
| 40-50 s | 8-8, 8.0 | 10-10, 10.0 |
| 50-60 s | 8-8, 8.0 | 10-10, 10.0 |
| 60-70 s | 8-8, 8.0 | 10-10, 10.0 |
| 70-80 s | 8-8, 8.0 | 10-10, 10.0 |
| 80-90 s | 8-9, 8.6 | 9-10, 9.8 |
| 90-100 s | 8-9, 9.0 | 9-10, 9.8 |
| 100-110 s | 6-8, 7.1 | 7-10, 9.0 |
| 110-120 s | 3-6, 4.0 | 6-10, 9.0 |
| 120-130 s | 3-4, 3.5 | 8-10, 9.1 |
| 130-140 s | 3-3, 3.0 | 7-10, 8.6 |
| 140-150 s | 3-3, 3.0 | 9-10, 9.3 |
| 150-160 s | 2-3, 2.4 | 9-10, 9.8 |
| 160-170 s | 2-2, 2.0 | 10-10, 10.0 |
| 170-180 s | 2-2, 2.0 | 9-10, 9.4 |
| 180-190 s | 2-2, 2.0 | 8-10, 8.6 |
| 190-200 s | 2-2, 2.0 | 8-10, 9.1 |
| 200-210 s | 2-2, 2.0 | 9-10, 9.7 |
| 210-220 s | 2-2, 2.0 | 8-10, 9.1 |
| 220-230 s | 2-2, 2.0 | 9-10, 9.8 |
| 230-240 s | 2-2, 2.0 | 9-10, 10.0 |

The late-clip dead zone is gone: the second half now holds 8-10 boxes where it held 2.
The cap is never breached — 10 is the maximum in every chunk. The remaining dips (6 at
110-120 s, 7 at 130-140 s) are frames where fewer than ten tracklets survive
`oncourt_min_fraction`, not the cap.

**The scorer's-table officials still take slots** — this is unchanged and expected (D-18:
the loose polygon includes the table). In the new run they are `p3` (0-129 s) and `p12`
(0-82 s): single-tracklet, 0.4 m and 0.2 m of total court displacement, 0.05 / 0.02 m·s⁻¹,
visible as the two boxes at the bottom-left of the overlay at t = 30 s. A referee, `p1`
(84-240 s, 0.97 m·s⁻¹), holds a third. Because the cap is now per-instant rather than
global, three static bystanders cost three of ten *concurrent* slots instead of three of
the whole roster — the same nuisance, a much smaller blast radius. Filtering them wants a
motion prior (a seated official never crosses the half-court line), not a smaller cap.

**Identity switches:** unchanged per seam, more of them in absolute terms because more
merges survive. Over all merged players, jumps across a sample-time gap > 0.2 s: 233
before / 596 after, of which > 5 m is 15 (6.4 %) before and 38 (6.4 %) after; mean jump
1.00 m → 1.12 m. One id does span an obvious switch: **`p31` teleports 22.4 m in 0.73 s at
t ≈ 226.2 s** — a genuine mis-merge, which the tag UI is the correction mechanism for.
The overlay at t = 30 / 120 / 210 s shows 10 / 9 / 9 boxes, every one of them on a real
person, and no duplicate id on two people in the same frame.
