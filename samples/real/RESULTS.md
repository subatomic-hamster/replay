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

---

# Net sports — pickleball and badminton (§4.9 Tier 1)

Two more clips, picked to put the *lens* under test as much as the sport:

| clip | camera | lens | what it is meant to prove |
|---|---|---|---|
| `pickleball_legacypark_240s.mp4` | fixed, on a fence post behind the near baseline, ~2 m up | 1× normal | a net sport end to end on a well-behaved lens |
| `badminton_russiaclub_240s.mp4` | fixed, indoors, low (~2 m) and far back | 0.5× ultra-wide, visible barrel | the hard lens case |

## Calibration — `pickleball_legacypark_240s.mp4`

Hand-clicked, 10 landmarks (6 required + 4 optional), `variant: doubles`:

| what | value |
|---|---|
| landmarks | `corner_nl/nr/fl/fr`, `net_post_l/r`, `kitchen_nl/nr`, `centre_n`, `centre_kn` |
| `courtcam calibrate` reprojection error | **2.762 px** (gate: `max(5 px, 1 % of clicked span)`) |

The clicks were not eyeballed. The near baseline, both sidelines, both kitchen lines and
the centre service lines were found with `HoughLinesP` on a brightness mask, fitted by
total least squares (SVD), and intersected as homogeneous lines (`np.cross`); the far
baseline and the net line were derived from the vanishing point at (1133, 274) and a
perspective parameter fitted from the baseline/kitchen pair on each sideline.

Drift of the fitted polygon from the painted lines, measured per edge in pixels:

| edge | mean | max |
|---|---|---|
| near baseline | 0.09 | 0.19 |
| left sideline | 0.08 | 0.28 |
| right sideline | 0.29 | 1.39 |
| kitchen | 0.01 | 0.01 |
| centre service | 0.84 | 2.15 |

**Worst case 2.15 px** (`frames/pickleball_legacypark_calib.jpg`). Verified at t = 1 s
and t = 200 s (fixed camera) and on
`pickleball_legacypark_smoke.mp4`, which is the same camera — the same `landmarks.json`
serves both, which is why `R-04` can calibrate the smoke clip by POSTing the 240 s file.

**This clip needs no distortion model.** That is the useful negative result: a 1× phone
lens on a 6.10 × 13.41 m court is a plain homography problem.

### What the geometry costs anyway

A fixed camera *behind* a baseline buys accuracy in the near half and pays for it in the
far half, lens or no lens. Measured from the fitted homography, along the centre line:

| court y | image y | resolution |
|---|---|---|
| 0.00 m (near baseline) | 871 | **201 px/m** |
| 2.00 m | 649 | 83 px/m |
| 4.00 m | 547 | 45 px/m |
| 6.71 m (net) | 474 | 25 px/m |
| 9.00 m | 437 | 17 px/m |
| 11.00 m | 414 | 12 px/m |
| 13.41 m (far baseline) | 394 | **9.6 px/m** |

The far half of a 13.41 m court is 80 px tall. A 2 px error on a landmark at the far
baseline is 0.2 m of court; a 2 px error in a detected foot point is the same. That is
fine for the on-court filter (`margin_m: 2.5`) and fine for a heatmap at 0.4 m bins; it
is not fine for anything that wants a metre.

## Calibration — `badminton_russiaclub_240s.mp4` — **not achieved**

This clip is not calibrated, and `samples/real/badminton_russiaclub_240s.landmarks.json`
does not exist, so `R-05-badminton.spec.ts` skips itself by design. What follows is why,
with numbers, because the *reason* is the finding.

### It is not (mainly) the lens

The barrel distortion is real — the painted lines visibly curve, and a line fitted to the
left third of a sideline and a line fitted to its right third disagree by ~4° — but it is
the second problem. The first is the viewing angle:

| measurement | how | value |
|---|---|---|
| person box height, nearest / farthest | 2068 YOLO boxes on the 50 s smoke clip | 374 px / 100 px |
| implied camera distance to near / far baseline | ratio 3.74 over a 13.40 m court | **4.9 m / 18.3 m** |
| foot-point image span, whole court | `min/max` of box bottom | y 594 → 762 = **168 px** |
| depth resolution at the near baseline | fitted from the above | ≈ **47 px/m** |
| depth resolution at the far baseline | same | ≈ **3.4 px/m** |

Thirteen metres of court live in 168 rows of pixels. At the far baseline **one pixel is
0.3 m**, so a 2 px landmark error — which is *better* than a careful human click on a
blurred, curved, 1080p line — is 0.6 m of court. The far service court is about 6 px
tall. No homography, and no `k1`, fixes that: the information is not in the image.

### And the hall is hostile

Three overlapping line systems (blue badminton, red, white), at least two badminton
courts side by side, and the played court is **not** the one whose lines fill the bottom
of the frame — the near court's markings dominate the foreground while the rally happens
farther away. Every automatic attempt locked onto the wrong court:

- brightness/`HoughLinesP` → the wall/floor junction (the two longest "lines" in the frame)
- blue-channel mask → the neighbouring court's sidelines
- temporal median (removes the players) → same
- temporal-std motion map → the play area, but only as a band, no corners
- foot-traffic footprint from a real `detect,track` run → a band 168 px tall, confirming
  the geometry above, still no corners
- `courtcam autocalib --sport badminton --backend claude-cli` → timed out at 300 s under
  load and returned 0 landmarks above confidence 0.5

Evidence: `frames/badminton_russiaclub_calib.jpg` (the frame) and
`frames/badminton_russiaclub_foottraffic.jpg` (every detected foot point over the smoke
clip, on the temporal median). The second one is the argument in a picture: all the play
is in one thin band, and the court lines under it belong to three different sports.

### What the clip *does* prove

Detection and tracking are fine: 18 tracklets on the smoke clip, of which 4 are long-lived
(525 / 520 / 486 / … samples) and are exactly the four players. Everything downstream of
`court` is blocked on the homography, not on the detector.

### Recommendation

Re-shoot or re-source: a badminton camera wants to be **above and behind** the baseline
(3 m up is enough) so the far half is not compressed into 6 px, on a single court. This
is a corpus problem, not a courtcam problem — and it is the same lesson as
`basketball_parkwide` (no lines) and `basketball_pavilion` (hard cuts) in the triage table
above: the clip has to be able to answer the question before the pipeline can.

## Full run — `pickleball_legacypark_240s.mp4`

One CLI run, all stages, on the calibration above. CPU-only box under load (loadavg ~27
from the other agents' YOLO jobs), so the detect number is a ceiling, not a benchmark.

| Stage | Wall clock |
| --- | --- |
| ingest (1920×1080 rendition) | ~3 min |
| calibrate | < 1 s |
| **detect** (yolo11n, `imgsz: 960`, stride 2 → 3600 inferences) | **~68 min** |
| track + court + identity + tracks + crops + events | ~5 min |
| `courtcam overlay` (7200 frames) | ~3 min @ 37 fps |
| `courtcam render --player p1` (7200 frames) | 3 min 19 s @ 36 fps |

`status: ready`. 660 raw tracklets in, 47 survive the on-court filter, 31 in the roster.

### Players kept vs expected — and the court next door

This is a public venue with courts laid **end to end**: the next court's baseline is about
1.5 m past this one's far baseline, and at 9.6 px/m up there a body on it is ~15 px wide.
`margin_m: 2.5` — chosen on paper, because a pickleball player stands a body-length behind
the baseline to return a deep serve — put the on-court test at y = 15.91 m and admitted the
**entire neighbouring game** as players.

The court-y histogram of every kept sample is cleanly bimodal, with a near-empty gap at
y ≈ 5–7 m (nobody was playing the far half of *this* court):

```
 y (m): -1    0    1    2    3    4    5   6   7   8    9   10  11  12  13   14    15   16
count: 1685  778  829  943 1704  378   86  39  43 421  448 150  66  80 684 2471  925  107
```

Everything from y = 13 upward is the other court. Dropping to `margin_m: 1.0` (the same
value basketball uses) cuts the cut-line to y = 14.41 m:

| | `margin_m: 2.5` | `margin_m: 1.0` |
| --- | --- | --- |
| on-court tracklets kept | 86 | **47** |
| roster size | 40 | **31** |
| distinct ids per 10 s bucket, median | 5 | **3** |
| buckets showing > 4 ids | 5 of 24 | **0 of 24** |
| concurrency histogram (½ s instants) | {1: 9, 2: 88, 3: 185, 4: 199} | {1: 69, 2: 205, 3: 151, 4: 55, 5: 1} |
| instants with **no** selectable player | 0 | **0** |

The remaining 31 is still not 4, and that is honest: over 240 s people walk on, walk off,
and stand at the fence. What matters for Tier 1 is the concurrency, and the `players.max: 4`
cap is never breached by more than one instant of overlap at a merge boundary.

It does not fully separate them — a real far-court player and a neighbour standing 1 m past
the baseline are 10 px apart, so no margin can. What `margin_m: 1.0` buys is that the
*persistent* neighbours (nine ids at 14.4 ≤ y ≤ 15.4, several with 200–450 samples) stop
being roster players.

### Identity

- **p1 is one id for the whole clip**: 3578 of a possible 3600 sampled frames, t = 0.0 s to
  239.9 s, **zero gaps longer than 1 s** (longest 0.93 s). No identity switch on the
  subject a viewer would actually follow.
- Tracklet merging did real work: of the 31 roster players, 8 are merges (6 × two members,
  2 × three). Nothing merged more than three tracklets, which is the shape you want — the
  5-member merge that `margin_m: 2.5` produced was two different people on the far court.
- **`team_rule: net_side` is 100 % correct**: every team-0 player's median court-y is below
  the net line (6.705 m) and every team-1 player's is above it, in both runs, with no
  manual seeding. Jersey k-means would have had nothing to work with — this is rec play,
  four different shirts, at night under sodium lamps.

### Follow-cam — the zoom was wrong, and the frames say why

`followcam.zoom` divides the court's visible pixel width (D-20). Here the court polygon
spans 1421 px, so `zoom: 1.6` gave a **888 × 500** window. The camera sits at the near
baseline of a 13.4 m court, and a player at that end is 600–750 px tall in the source:

```
p1 bounding-box height, px:  min 107   p50 293   p90 612   p95 656   max 745
```

A 500 px-tall window cannot contain a 612 px player. `frames/pickleball_legacypark_p1_t150.jpg`
at zoom 1.6 was the top of a torso with the head cut off.

`zoom: 1.2` → **1184 × 666**, which clears the p90 height with room and still frames a
mid-court player at ~44 % of the window. Re-rendered and re-read:

| Frame | At `zoom: 1.6` | At `zoom: 1.2` (shipped) |
| --- | --- | --- |
| `frames/pickleball_legacypark_p1_t40.jpg` (mid-court) | subject ~1/8 of the width | same framing, subject whole, partner and both nets in shot |
| `frames/pickleball_legacypark_p1_t150.jpg` (near baseline) | head clipped, subject fills the frame | whole body, kitchen line and partner visible |

The residual is inherent, not a tuning miss: a fixed-size pixel crop on a camera whose
scale runs 201 px/m to 9.6 px/m along the court cannot frame both ends the same way. At the
near baseline the subject is already 61 % of the *wide* frame height, so there is nothing
left to zoom into; the follow-cam earns its keep up-court. A per-frame crop size driven by
the subject's court-y would fix it — deliberately not built (see D-22 below).

### Profile values this run settled

| Key | Value | Why |
| --- | --- | --- |
| `court.margin_m` | `1.0` | 2.5 admitted the adjacent court; table above |
| `followcam.zoom` | `1.2` | 1.6 clipped the subject's head at the near baseline |
| `tracking.oncourt_min_fraction` | `0.6` | unchanged; drops the fence-standers without dropping a player who steps out to retrieve |
| `tracking.merge_max_dist_m` | `3.0` | unchanged; 7 m (basketball's) reaches across a 6.7 m half |
| `players.max` | `4` | doubles; never breached |
| `detection.imgsz` | `960` | the far-side players are ~60 px tall; 640 loses them |

### Through the product (`e2e-real/R-04-pickleball.spec.ts`)

`REPLAY_E2E_REAL=1 pnpm exec playwright test --project=real R-04` — **1 passed (5.0 m)**,
on the 35 s smoke clip (same camera, same landmarks file). Full Tier 1 walk: upload →
calibration POST (reprojection 2.76 px) → process → select → follow → highlights → review.
The roster it produces is 5 players, 3 selectable at the screenshot instant.

| Screenshot (1920×1080) | What it shows |
| --- | --- |
| `sports/pickleball-select.png` | four labelled boxes, team colours by net side (blue near, orange far), pickleball court inset bottom-right with live dots |
| `sports/pickleball-follow.png` | `FOLLOW • p2`, amber follow frame, cropped transform, inset dot amber |
| `sports/pickleball-highlights.png` | this profile's chips, `Rallies` resolving to an interpretation (no clips — the rally detector is a stub) |
| `sports/pickleball-review.png` | heatmap drawn on the pickleball `viewBox`, occupied cells > 0 |

The same spec at `margin_m: 2.5` labelled two people on the *next* court as p3 and p5;
after the change they are gone from `pickleball-select.png`.

Overlay evidence for the same thing at 240 s: `frames/pickleball_legacypark_overlay_t140.jpg`
— yellow court polygon exactly on the paint, blue boxes only on the three people on this
court, and the adjacent game left as grey unpromoted tracklets (#2472, #2521, #2568).

## Auto-calibration, second attempt — the `template` backend

D-23's first attempt asked a vision model where the corners were and got 0 of 3
basketball clips within 20 px. This attempt asks nothing: `courtcam/courtcam/templatefit.py`
finds the painted lines, builds every quadrilateral two pairs of them can make, matches
each one against a rectangle the sport template knows (the court outline, the key, the
kitchen box) and keeps the homography under which the *whole* template — every sideline,
arc and service line, sampled every 10 cm — lands on painted pixels. Run it with
`courtcam autocalib --backend template` (or just `auto`, which is now the same thing) and
score it with `courtcam autocalib-eval --backend template`.

### The numbers

`uv run courtcam autocalib-eval --backend template`, 16-core CPU, no GPU, no model call.
Ground-truth landmarks that fall outside the frame are **skipped, not counted as misses**
(`northsidewide.corner_fl` is at x = 2709 on a 2560 px frame, and neither 2560 px clip has
a `corner_fr` at all) — the eval command was changed to do that and says so per clip.

| clip | frame | runtime | line score | `ok` | landmarks < 20 px | mean px |
|---|---|---|---|---|---|---|
| `pickleball_legacypark` | 1920×1080 | **4 s** | **0.922** | **true** | **10 / 10** | **3.9** |
| `basketball_powellgym` | 1920×1080 | 12 s | 0.690 | false | 3 / 14 | 108.5 |
| `basketball_kennesawwide` | 2560×960 | 8 s | 0.739 | false | 0 / 13 | 759.2 |
| `basketball_northsidewide` | 2560×960 | 12 s | 0.919 | false | 0 / 11 | 664.9 |
| `badminton_russiaclub` (no truth) | 1920×1080 | 12 s | 0.610 | false | — | — |
| `basketball_pavilion` (no truth) | 1920×1080 | 6 s | 0.815 | false | — | — |

Per-landmark, `pickleball_legacypark`: `corner_fl` 2.9, `corner_fr` 2.4, `corner_nl` 9.0,
`corner_nr` 12.2, `net_post_l` 2.4, `net_post_r` 2.0, `kitchen_nl` 2.6, `kitchen_nr` 2.0,
`centre_n` 1.5, `centre_kn` 1.7 px. `basketball_powellgym`: `rim` 14.2, `key_nl` 12.7,
`centre_l` 14.6, `ft_nl` 22.1, `corner_nl` 25.0, `key_nr` 20.6, `corner_nr` 55.6 and then
it falls apart down the court — `key_fl` 174, `ft_fr` 261, `corner_fl` 394, `centre_r` 159.

On the SYNTHETIC CI fixture (`samples/synthetic/basketball_half`) the fit lands every
landmark within **1.8 px** in 1.9 s, which is the unit test
(`test_template_backend_lands_on_the_synthetic_court`).

`reproj` is **0.0 px on every clip and means nothing here**: all the landmarks come out of
one homography, so feeding them back to `calibrate.calibrate` can only confirm arithmetic.
The line score is the quality signal, and `ok` rides on it (`MIN_TEMPLATE_SCORE = 0.90`).

**Target missed.** The brief wanted on-frame required landmarks within 20 px on ≥ 3 of the
4 clips with ground truth. It is 1 of 4, and the failure is not a tuning problem.

### Why the basketball clips cannot work, measured

For each true court edge, the closest straight line the detector can produce, as
(perpendicular offset at the edge midpoint, angle):

| clip | near baseline | far sideline | far baseline | near sideline |
|---|---|---|---|---|
| `pickleball_legacypark` | 2 px, 0.3° | 0 px, 0.2° | 6 px, 1.2° | 0 px, 0.0° |
| `basketball_kennesawwide` | 27 px, 4.2° | 24 px, **57.3°** | 42 px, 3.9° | 24 px, 1.2° |
| `basketball_powellgym` | 13 px, 4.0° | **191 px, 6.6°** | 19 px, **51.2°** | 2 px, 0.2° |
| `basketball_northsidewide` | 28 px, 3.1° | **442 px, 16.6°** | **428 px, 13.5°** | 100 px, 5.2° |

On the pickleball clip all four court edges *are* detected lines, to a pixel. On the three
basketball clips at least two edges have no straight line within hundreds of pixels and
tens of degrees, at 30, 45 or 60 candidate lines. These cameras are ultra-wide or
panoramic-stitched (D-18): a court edge is a **curve** in the image, so it fragments into
short chords pointing in different directions and no `HoughLinesP` line represents it. A
quad search over straight lines cannot reach the right answer, so scoring, refinement and
priors are all downstream of a candidate set that does not contain the truth.

Second measurement, same conclusion from the other side: the *ground-truth* homography
scores **0.267 / 0.230 / 0.266** on kennesaw / northside / powellgym and **0.884** on
pickleball. The hand-made basketball landmark sets do not sit on the paint either — they
are exact-fit homographies (all 15 residuals are 0.0 px), i.e. one plane fitted through a
barrel-distorted image, which D-18 already described as "contains the play area but does
not sit on the lines". See `frames/autocalib_template_basketball_powellgym_240s.jpg`: the
proposal and the blue ground-truth rings agree to 13-25 px at the near basket and diverge
to 400 px at the far one, which is what lens distortion looks like.

`basketball_pavilion` fails differently and is worth naming: the fitter latches onto the
**roof beams**, which are longer, straighter and more contrasty than the court paint.
`badminton_russiaclub` latches onto the **window frames** on the hall wall. Both are
"the mask has no idea where the floor is" — the cheap fix is a horizon/playing-surface
prior, not a better scorer.

### Overlays

Every fit is drawn with the full projected template in green (ground truth, where it
exists, as blue rings):

- `frames/autocalib_template_pickleball_legacypark_240s.jpg` — sits exactly on the paint.
- `frames/autocalib_template_basketball_powellgym_240s.jpg` — right at the near basket,
  swings off the court by the far one.
- `frames/autocalib_template_basketball_kennesawwide_240s.jpg`,
  `..._northsidewide_240s.jpg` — a squashed court crammed into the right quarter of the
  panorama.
- `frames/autocalib_template_basketball_pavilion_240s.jpg` — the roof.
- `frames/autocalib_template_badminton_russiaclub_240s.jpg` — the windows.

### What `auto` does now

`autocalib._resolve_backend("auto")` returns `"template"`. It used to return `vlm` /
`claude-cli` / `lines` depending on what was installed. The model backends stay available
by name and their answer can be handed to the template fit as `prior=` (CLI: `--prior
some.landmarks.json`), which leashes the quad search to within 15 % of the frame width of
the prior's court and adds the prior itself as a candidate for the corner refinement to
start from; if the leash leaves nothing the search runs unrestricted. Nothing else in the
proposal contract moved: `Proposal.as_dict()` is unchanged and the API/UI still read
`landmarks_px`, `confidence`, `ok`, `reprojection_error_px`.

Why `template` is the right default even at 1 of 4:

- the model backends were **0 of 4**, cost $0.26 and 3-14 minutes a clip, and timed out
  outright on two of the four;
- `template` costs nothing, runs in 4-12 s, needs no key and no network;
- it is exact (2-12 px, 10/10 landmarks) on the one clip in the corpus shot the way the
  product tells users to shoot — a 1× phone lens on a tripod (D-22) — and within 1.8 px on
  the synthetic fixture;
- it now refuses to claim `ok` on 5 of the 6 clips it gets wrong, so the uploader shows
  draggable dots rather than an Accept button on a wrong court. It does *not* catch all of
  them, and the one it misses (`pavilion`, score 0.89) is a fit on the roof.

The next real step for the panoramic corpus is D-18's upgrade path — estimate `k1`/`k2`
from the curvature of the detected court lines, undistort, then run this fitter — not more
scoring heuristics.
