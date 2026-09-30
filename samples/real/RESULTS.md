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
| `sports/pickleball-highlights.png` | this profile's chips, `Rallies` resolving to an interpretation (no clips at the time — the rally detector was a stub; see "Rally segmentation") |
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

# Ultra-wide / fisheye — the lens model (D-22 revisited, D-24 proposed)

Two 0.5×-class clips, added to the corpus for exactly this question:

| clip | camera | frame | what it is meant to prove |
|---|---|---|---|
| `badminton_auditorium_240s.mp4` | GoPro superview, elevated, **in the plane of the net**, one court, doubles | 1920 × 1080 | a strong barrel lens end to end |
| `basketball_ceilingcam_240s.mp4` | extreme fisheye, above *and behind* the near backboard | 1280 × 720 | the case the lens model does **not** rescue |

## Calibration — `badminton_auditorium_240s.mp4`

### The camera is not what `MANIFEST.md` says

The manifest entry describes a camera "set well back from one baseline … looking down the
length of the court". It is not. The camera stands beside the court **in the plane of the
net**: the net projects to a single near-vertical line at x ≈ 930, the court's long axis
runs left–right across the frame, and **both back boundary lines fall at or outside the
frame edges**. That is why `corner_nl/nr/fl/fr` — the four landmarks D-19 asks for — are
absent from `badminton_auditorium_240s.landmarks.json` by design. The manifest's "far
baseline ≈ 1050 px, near baseline ≈ 1800 px, court height ≈ 450 px" are real measurements
of the court's **width** direction, not its length.

Reconstructed from first principles and checked before any fitting:

- the four players split cleanly left/right of the net pole, two a side — doubles;
- the centre line is present outside the short service lines and absent between them,
  which fixes which white curve is which;
- a 1-D projective cross-ratio on the four sideline curves at x = 930 (image y
  983 / 902 / 530 / 516 ↔ court 0 / 0.46 / 5.64 / 6.10 m) predicts the fourth from the
  other three to **0.3 px**. The lines are identified correctly.

### The twelve landmarks

Clicked on a 40-frame temporal median (players removed), each one an intersection of two
painted lines found by sub-pixel ridge tracing plus a local degree-2 fit in a ±170 px
window around the crossing — a global fit to a *curved* line is wrong at its ends (it
missed `short_nl` by 26 px).

Four optional landmarks were added to the profile to reach the eight the lens model
needs: `singles_nl/nr/fl/fr`, the short-service-line ends on the **inner (singles)**
sidelines, at (±2.59, 4.72) and (±2.59, 8.68) in `badminton_doubles.json`. They are
`landmarks_optional` only, and only on the doubles template, so nothing the uploader is
asked for changed.

### D-22's revisit criterion is met: the residual grows with radius

Least-squares pinhole homography over all twelve landmarks, residual measured in frame
pixels, against distance from the image centre:

| landmark | r (px) | pinhole resid | with `k1 = −0.653` |
|---|---:|---:|---:|
| `net_post_r` | 37 | 4.69 | 4.76 |
| `short_fr` | 168 | 1.97 | 1.99 |
| `singles_fr` | 176 | 1.33 | 0.91 |
| `short_nr` | 215 | 4.09 | 2.53 |
| `singles_nr` | 224 | 3.25 | 1.86 |
| `centre_sf` | 276 | 4.71 | 2.94 |
| `centre_sn` | 323 | 3.52 | 3.73 |
| `net_post_l` | 444 | **41.76** | 0.18 |
| `singles_fl` | 542 | 8.19 | 2.08 |
| `singles_nl` | 585 | 6.51 | 1.70 |
| `short_fl` | 619 | **18.11** | 1.41 |
| `short_nl` | 663 | **17.17** | 1.97 |
| **rms** | | **14.62** | **2.47** |
| **max** | | **41.76** | **4.76** |

Binned, which is the shape D-22 asked for:

| radius band | n | pinhole rms | `k1` rms |
|---|---:|---:|---:|
| 0–200 px | 3 | 3.04 | 3.03 |
| 200–400 px | 4 | 3.93 | 2.85 |
| 400–600 px | 3 | **24.85** | 1.55 |
| 600–900 px | 2 | **17.65** | 1.71 |

Inside a third of the half-diagonal the two models are the same. Past it the pinhole model
is eight times worse and the lens model is *flat*. That is radial error, not click noise.

### The model

`courtcam/courtcam/distortion.py` — one-parameter division (Fitzgibbon) model about the
image centre, radius normalised by the half-diagonal:

```
r_u = r_d / (1 + k1 · r_d²)          undistort_points
r_d = r_u · 2 / (1 + √(1 − 4·k1·r_u²))   distort_points  (exact inverse, stable at k1 → 0)
```

`estimate_k1` grid-searches 81 values over [−0.80, 0.20] then refines by golden section,
minimising the **distorted-pixel** reprojection rms of a homography refitted on the
undistorted points at each candidate. Measuring the error in distorted pixels is what
stops the search running away: in undistorted space a large |k1| shrinks every distance
and the error falls for free.

Gate, in `estimate_k1` itself, so no caller can skip it: **≥ 8 landmarks and ≥ 30 %
reduction in reprojection rms**, otherwise it returns `k1 = 0.0` and the payload is the
old one byte for byte.

| | value |
|---|---|
| landmarks | 12 |
| `k1` | **−0.6530** |
| reprojection rms, before → after | **14.621 → 2.466 px** (−83 %) |
| worst single landmark | **4.77 px** (`net_post_r`, r = 37, the least distorted point in the set) |
| `court_polygon_px` | 148-point polyline, 0.25 m per sample, re-distorted |

`calib.json` gains three additive fields — `k1`, `image_size`, `lens_rms_px` — and
`court_polygon_px` becomes a dense polyline instead of four corners. Everything else keeps
its name and meaning, so `croppath.court_px_width` (D-20) and `render.render_overlay` got
the curved court for free: both already read `court_polygon_px`.

### What it is worth in metres

The number that matters is not pixels, it is how wrong the court coordinates are. Each
clicked landmark pushed through each run's own `H` and compared with the template:

| | `k1 = −0.653` | `k1 = 0` |
|---|---:|---:|
| metre error, rms | **0.048 m** | 0.181 m |
| metre error, max | **0.087 m** | 0.469 m |
| error at r = 168 px | 0.084 m | 0.025 m |
| error at r = 619 px | **0.012 m** | **0.469 m** |

Half a metre of error at the frame edge on a 6.10 m-wide court is a tenth of the court.

### The RANSAC trap — a real bug, in a file this task did not own

`calibrate.homography()` fits with `cv2.findHomography(..., cv2.RANSAC)`. On a barrelled
frame the pinhole model genuinely cannot fit all twelve points, so RANSAC does what it is
built to do: it finds a **five-point consensus**, reports that consensus's error, and
discards the rest. On this clip the lens-free calibration therefore reports

```
reproj_error_px 1.515      # the five inliers
residuals_px    short_fl 167.0   singles_fl 103.1   short_nl 21.4   ...
```

— a 1.5 px calibration whose worst landmark is **167 px** out. It is also
non-deterministic: run to run, `cv2.theRNG()` picks a different consensus (measured:
52/90 px one run, 45/33/26 px the next, all reporting 1.3–2.5 px).

Working around it inside code this task owns, `pipeline._refit_least_squares` replaces the
homography with a plain least-squares fit over *all* landmarks when `k1 != 0`, and only
when that is strictly better. Measured at `k1 = −0.6601`, 8 landmarks:

| fit | worst landmark | polygon x-extent |
|---|---:|---|
| RANSAC | 47.5 px | −10 … 2014 |
| least squares | **4.34 px** | −59 … 1918 |

and it is now deterministic: four repeat runs give `k1 = −0.6530`, worst residual 4.77 px,
polygon x ∈ [−61, 1922], y ∈ [515, 983].

**The real fix belongs in `courtcam/courtcam/calibrate.py`** (not owned here): keep the
RANSAC result only when `mask.sum() >= len(names) - 2`, otherwise fall back to the
least-squares fit over every landmark. A calibration that silently drops half its evidence
and reports the half it kept is worse than one that reports 15 px honestly.

### Overlay

`frames/badminton_auditorium_calib.jpg` — the twelve landmarks and the fitted polygon on
the temporal median, labelled with `k1` and the worst residual.

| frame | what it shows |
|---|---|
| `frames/badminton_auditorium_overlay_t100.jpg` | four players, two a side, blue/orange by net side; the yellow polygon **curves along the painted sidelines** for the whole 1920 px |
| `frames/badminton_auditorium_overlay_t232.jpg` | same at the end of the clip — the camera is fixed, the fit holds |
| `frames/badminton_auditorium_overlay_nok1_t2.jpg` | the same court with `k1 = 0`: a straight-edged quadrilateral, ~100 px below the paint at the bottom centre and above it at both edges |

## Full run — `badminton_auditorium_240s.mp4`, with and without `k1`

One YOLO pass (`_work/dets.json` shared); the post-detect stages run twice.

### Timing (240 s clip, stride 2 = 3602 detected frames)

| stage | s |
|---|---:|
| ingest | 138.7 |
| calibrate | 0.1 |
| detect (yolo11n, imgsz 960, CPU, contended) | 1212.9 |
| track | 0.3 |
| court | 0.2 |
| identity | 0.2 |
| tracks | 0.5 |
| crops | 1.4 |
| events | 0.1 |

The lens model costs nothing measurable: `estimate_k1` is 81 + ~30 homography fits on 12
points, and `to_court` adds one vectorised division per foot point.

### Players

Four players on court for the whole clip; the hall is otherwise empty.

| | `k1 = −0.653` | `k1 = 0` |
|---|---:|---:|
| tracklets | 39 | 39 |
| survive the on-court filter | 29 | 30 |
| merged players | 9 | 9 |
| median concurrent | **4.0** | 4.0 |
| seconds with ≥ 4 selectable | 232 / 240 | 237 / 240 |
| team by `net_side` wrong | **0 of 14 026 samples** | 0 of 14 043 |
| bystanders admitted | 0 | 0 |

Per-10 s selectable count, `k1` run: `4 4 4 5 4 4 5 4 4 4 4 4 4 4 4 4 5 4 4 4 4 4 4 4`.

**The roster is the same with and without the lens model, and that is the honest headline.**
On a clip whose only occupants are the four players, the on-court filter has nothing to
decide, so a court polygon 100 px off the paint still contains exactly the same people.
What `k1` changes is the *metres*:

| | `k1 = −0.653` | `k1 = 0` | truth |
|---|---:|---:|---:|
| y reached, p99 | **13.34 m** | 11.71 m | court is 13.40 m long |
| \|x\| reached, p95 | **2.21 m** | 1.92 m | half-width is 3.05 m |

Without the lens model the homography is anchored on whichever five landmarks RANSAC
liked and systematically **shrinks the court**: it reports that nobody in four minutes of
doubles ever came within 1.7 m of a back boundary line, which is not badminton. Every
metre-denominated product surface — the court inset dots, the review heatmap, any future
distance or speed — is wrong by that much.

### Identity

Nine player ids for four people, in both runs: **five switches in 240 s**. `p1` holds one
far-side player unbroken for the whole clip; the near-side pair breaks into six ids. The
lens model does not help here and should not be expected to — the breaks are occlusions at
the net and two players in near-identical dark kit, not geometry.

Note that `players: {max: 4}` is **not** enforced on the merged roster: `identity.identify`
returns nine. It is not wrong at any instant (median concurrent is 4, peak 5 during a
handover), but "9 players" is what `game.json` says. See *Changes needed elsewhere*.

### Follow-cam — measured, and the two UNMEASURED comments are gone

This camera stands in the plane of the net, so the scale across the court is nearly
uniform: person boxes run **117–483 px** tall (p50 256, p95 324, p99 369) instead of
pickleball's 7× run from baseline to baseline. The court fills the frame
(`court_px_width` = 1920), so:

| `followcam.zoom` | window | p95 player fills | read at t = 40 s / 150 s |
|---|---|---:|---|
| 1.5 (copied from pickleball's pre-tuning value) | 1280 × 720 | 45 % | subject small, half the window empty court |
| **2.0 (shipped)** | **960 × 540** | **60 %** (tallest 89 %) | whole body, racket, partner and the service lines in shot |

`frames/badminton_auditorium_p1_t40.jpg` (mid-court) and
`frames/badminton_auditorium_p1_t150.jpg` (at the back boundary).

`court.margin_m` could **not** be measured on this clip and the comment in
`badminton.yaml` now says so: sweeping it 0.5 → 3.0 m leaves 29 on-court tracklets at
every value, worst `inside_fraction` 0.74 even at 0.5 m, because there is nobody off court
to reject. It is set to **1.0** for two reasons that are measurable: the players' own
excursion past the paint is p99 0.79 m / max 3.15 m, and 1.0 m is the value pickleball
*measured*, for a failure (the adjacent court) that a badminton hall has too.

### Through the product (`e2e-real/R-05-badminton.spec.ts`)

Repointed from `badminton_russiaclub_*` (still uncalibratable, section above) to
`badminton_auditorium_smoke.mp4` + `badminton_auditorium_240s.landmarks.json` — same fixed
camera, so one landmarks file serves both cuts, exactly as R-04 does for pickleball.

`REPLAY_E2E_REAL=1 pnpm exec playwright test --project=real R-05` — **1 passed (4.9 m)**
on the 50 s smoke cut. Full Tier 1 walk: upload → calibration POST → process → select →
follow → highlights → review. Roster 5 players, **4 selectable** at the screenshot
instant, split 3/2 across the net.

| Screenshot (1920 × 1080) | What it shows |
|---|---|
| `sports/badminton-select.png` | four labelled boxes, blue left of the net and orange right of it, badminton court inset bottom-right with four live dots in the right halves |
| `sports/badminton-follow.png` | `FOLLOW • p2`, amber follow frame, cropped transform, spotlight dim, inset dot amber |
| `sports/badminton-highlights.png` | this profile's chips, `Rallies` resolving to an interpretation (no clips at the time — the rally detector was a stub; see "Rally segmentation") |
| `sports/badminton-review.png` | heatmap on `viewBox="-3.05 0 6.1 13.4"`, occupied cells > 0 |

One wart, and it is in code this task did not own: the `reprojection_error_px` the API
returns to the calibrate screen (and which `net-sport.ts` asserts on) comes from
`pipeline_adapter.calibration_error`, which calls bare `calibrate()` with no lens model.
On this clip it answers **1.5 px** for a fit whose worst landmark is 167 px out, while the
pipeline that actually runs re-estimates `k1` and gets 4.77 px. The assertion passes for
the wrong reason. See *Changes needed elsewhere*.

`e2e-real/R-06-basketball-fisheye.spec.ts` — **1 skipped**, reason
`samples/real/basketball_ceilingcam_240s.landmarks.json is missing; calibrate the clip
first`. That is the intended outcome; the next section is why.

## Calibration — `basketball_ceilingcam_240s.mp4` — **not achieved**, and `k1` is why not

This is the negative control the corpus was missing: a lens *more* distorted than the
badminton clip, on which the lens model correctly refuses to fire.

The camera is bolted above and slightly behind the near backboard. Consequences, measured
on a 40-frame temporal median:

- the **near baseline and both near corners are occluded** — glass safety barrier across
  the bottom of the frame, backboard rigging over the middle of it. Four of the five
  landmarks `basketball` requires (`corner_nl`, `corner_nr`, and a trustworthy `rim`
  ground point) cannot be clicked at all;
- the far half runs at **4–8 px/m** in depth, among four or five overlapping multi-sport
  line systems on the same floor;
- the centre circle images as an ellipse with semi-axes (74, 14.5) px for a 1.8 m radius —
  **41 px/m across, 8 px/m in depth**. That 5:1 anisotropy is the whole problem in one
  number.

Eight landmarks *are* identifiable: `ft_nl/nr`, `key_nl/nr`, `centre_l/r`, `corner_fl/fr`.
They give a pixel-space reprojection rms of **18.27 px** with `k1 = 0` — and `k1` does not
improve it:

| `k1` | reprojection rms (px) |
|---:|---:|
| −0.60 | 22.12 |
| −0.40 | 20.63 |
| −0.20 | 19.36 |
| −0.10 | 18.79 |
| **0.00** | **18.27** |
| +0.10 | 17.79 |

There is no minimum at a barrel value. `estimate_k1` returns `0.0` and the 30 % gate never
opens. **Why**, quantitatively: the half-diagonal is 734 px and every one of the eight
landmarks sits at r = 126…395 px, i.e. **0.17–0.54 of the half-diagonal**, all of them in
the inner half of the frame where a division model barely bends anything. The distortion
term varies across the set by less than the 18 px of click uncertainty, so `k1` is simply
not identifiable from these points — it is not that the lens is undistorted, it is that
the observations cannot see the lens.

Letting the clicks drift inside a ±18 px uncertainty ball while alternately refitting
`(H, k1)` drops the rms to 3.73 px and still chooses `k1 = 0.0000` — the drift absorbs the
distortion into the clicks. (Reassuringly, `centre_l` snaps to (374.9, 157.9), which is
where the centre-circle ellipse independently puts it; less reassuringly `corner_fl` snaps
to y = 79, above the wood floor.) `frames/basketball_ceilingcam_bestfit.jpg` is that best
fit drawn on the median: the modelled three-point arc diverges from the painted one by
55–135 px at the frame edges, which is the visible signature of distortion the landmark
set cannot measure.

So **no `samples/real/basketball_ceilingcam_240s.landmarks.json` is shipped**, and
`e2e-real/R-06-basketball-fisheye.spec.ts` skips on the missing file with that reason —
the same honest mechanism R-05 used while `badminton_russiaclub` was unsolved. The spec is
kept rather than deleted: drop a landmarks file next to the clip and the whole Tier 1 walk
runs. No full pipeline run, no follow-cam and no player counts are reported for this clip,
because every one of them would be conditioned on a homography that is 18 px — two to four
metres — wrong.

**Does `k1` rescue the on-court filter here? No, and it could not.** The blocker is
occlusion and 8 px/m depth resolution, not lens shape. Re-source: a fisheye that sees the
whole floor from the *side* at half-court height, not one looking down the court from
behind a backboard. Same lesson as `badminton_russiaclub` — the clip has to be able to
answer the question.

## D-24 (proposed) — ship the one-parameter lens model, off unless it earns itself

> **D-24. A one-parameter radial lens model is fitted at calibration time and applied
> wherever pixels and metres meet, but only when the landmarks prove it is needed.**
>
> D-18 deferred any lens model on the grounds that no clip in the corpus needed one, and
> D-22 set the revisit criterion: *reprojection residuals that grow with distance from the
> image centre*. `badminton_auditorium_240s.mp4` meets it unambiguously — pinhole residual
> rms 3.0 px inside r = 200 px and 24.9 px beyond r = 400 px, on a 1920 × 1080 frame. So:
>
> 1. `courtcam.distortion` implements the division model `r_u = r_d / (1 + k1·r_d²)` about
>    the image centre, radius normalised by the half-diagonal, with an exact closed-form
>    inverse. One parameter, no `k2`, no principal-point search, no `cv2.calibrateCamera`:
>    a court calibration has 12 points, not 12 views of a chessboard.
> 2. `k1` is estimated at the calibrate stage from the clicked landmarks alone — no extra
>    input from the uploader, no extra API field, nothing new to get wrong.
> 3. **The gate lives inside `estimate_k1`**, not in its callers: at least **8** landmarks
>    and at least a **30 %** cut in reprojection rms, or it returns `k1 = 0.0`. Eight is
>    where a homography (8 dof) stops absorbing `k1` into the fit; 30 % is far above the
>    ~10 % a spurious parameter buys on noise, and the clip that needs the model cut 83 %.
> 4. `k1 = 0` must be **bit-identical** to the pre-D-24 payload — same `H`, same
>    `landmarks_px`, same `reproj_error_px`. `test_distortion.py` asserts exactly that on
>    the synthetic basketball fixture, and the golden test is unchanged.
> 5. `calib.json` gains `k1`, `image_size` and `lens_rms_px` as additive fields, and
>    `court_polygon_px` becomes a polyline sampled every 0.25 m and re-distorted, so the
>    overlay and the D-20 crop-path extent both follow the curved paint with no further
>    change.
> 6. Consequence, to be fixed separately: `calibrate.homography()` must stop reporting a
>    RANSAC consensus's error as the calibration's error. On a barrelled frame it happily
>    returns 1.5 px for a fit whose worst landmark is 167 px out, which is how a lens
>    problem hides from its own quality gate.
>
> **Not adopted:** `k2`, a fitted principal point, per-frame refinement, or undistorting
> the *pixels* (as opposed to the points). Undistorting whole frames would resample every
> frame of every rendition for an error the model already removes analytically at the
> three places that matter — foot points, court polygon, crop-path extent.
>
> **Known ceiling:** one parameter about the frame centre. A lens whose barrel is not
> centred, or a strong fisheye needing `r⁵`, will not fit; the 30 % gate will notice and
> leave `k1 = 0` rather than fitting something wrong. `basketball_ceilingcam_240s.mp4` is
> the standing example of a clip the gate correctly refuses.

## Changes needed elsewhere (files this task did not own)

1. **`courtcam/courtcam/calibrate.py`, `homography()`** — the RANSAC fallback. Keep the
   RANSAC result only when `mask.sum() >= len(names) - 2`; otherwise refit by least
   squares over every landmark and report *that* error. Today a barrelled frame gets a
   five-point consensus reported as a 1.5 px calibration with a 167 px worst landmark, and
   the consensus changes run to run with `cv2.theRNG()`. `pipeline._refit_least_squares`
   works around it for `k1 != 0` only; the bug is there for `k1 == 0` too.
2. **`services/api/replay_api/pipeline_adapter.py:182`** — `calibration_error()` calls
   `calibrate(dict(landmarks_px), load_profile(sport), variant)` directly, so the number
   the calibrate screen shows never reflects the lens model, while the pipeline started a
   moment later does estimate `k1`. Replace that one call with
   `pipeline.calibrate_lens(dict(landmarks_px), load_profile(sport), variant, image_size)`
   and return its `reproj_error_px`/`residuals_px`; `image_size` is already on the game's
   `video` record. It would also let the UI tell the uploader *why* a fisheye clip now
   calibrates, and D-19's span-scaled gate would finally be applied to the fit that runs.
3. **`courtcam/courtcam/identity.py`** — `players.max` is documented (in `court.on_court`)
   as belonging on the merged roster, but `identify()` does not apply it: 240 s of doubles
   comes back as nine players for four people. Concurrency is fine (median 4, peak 5), so
   this is a labelling problem rather than a filtering one, but `game.json` claiming nine
   players for a doubles match is wrong on its face. **Done 2026-09-30:** four ids — see
   "Detection on the GPU, identity stitching, bystanders" at the end of this file.
4. **`samples/real/MANIFEST.md`, entry #7** — the badminton auditorium camera is described
   as being behind a baseline looking down the court. It is beside the court in the plane
   of the net; the quoted baseline pixel spans are measurements of the court's width.


# Auto-calibration on the fisheye clip — lens search (fix wave, 2026-09-30)

The uploader's "Found 21 points · needs a check" on `badminton_auditorium` was a wrong
court: dots stacked along the bottom-right edge of the frame, `corner_*` points invented
off-frame. Causes, each measured:

- **The lens prestep shrank the court.** It re-drew a straightened mask per `k1` and
  rescaled it by `1 + k1` to keep it on the canvas; at `k1 = -0.65` the court shrank to
  a third and the true fit scored 0.000. Now lines and quads are built in undistorted
  pixels and every mask read goes back to the source frame, so one distance map serves
  every `k1` and scores at different `k1` compare.
- **Letterbox bar edges were the two longest lines** in the frame. `content_box` finds
  the picture; the mask is cut to it and "in frame" means inside it.
- **Wrong fits were cameras that cannot exist.** A homography has 8 dof, a pinhole
  camera over a plane has 7 (principal point at the lens centre). The spare one is a
  shear, and every wrong badminton fit used it. For `K = diag(f, f, 1)` the court's two
  axes in camera space must be orthogonal and equal: that **skew** is 0.002-0.023 on all
  five hand-clicked clips and 0.1-1.1 on nearly every wrong fit. `templatefit.physical`
  snaps a fit to the nearest real camera; the lens search only ever scores those.
- **Explained paint length rewards stacking.** With a strong `k1` several court lines
  bend onto one bright curve and each is paid for the same pixels: a court folded onto
  the arc at the bottom of the auditorium frame out-scored the true court by 20 %.
  `templatefit.covered` counts each painted pixel once (4 px cells) and is the lens rank.

Search now: the straight D-24 fit first (unchanged; pickleball stops here). If it is not
`ok`, fit at `k1` in (-0.2, -0.4, -0.6) with physical cameras, refine corners and `k1`
on explained length with bigger first steps, and rank the lens winners *and* the
straight fit by covered paint. Candidates are first scored against 600 template
samples and only the best 128 of each order in full (identical winners, ~30 % faster).
Off-frame required landmarks are reported in `Proposal.not_visible` (and the note), not
invented. `ok` additionally needs camera skew <= 0.05.

### Before / after

`courtcam autocalib-eval --samples <frames> --clips kennesawwide,northsidewide,powellgym,legacypark,auditorium,badminton_auditorium_smoke`
on hfbox, 6 threads, same frames and the same (extended) eval for both columns; "before"
is the pre-wave `templatefit`/`autocalib`. Errors are over the landmarks the fit and the
clicks share, under the best of four relabellings (the template is symmetric and the
auditorium clicks are mirrored against the fitter's winding); the smoke frame is scored
against the 240 s clicks (same fixed camera: the truth homography lands within 2 px).

| clip | before: ok, median / worst px, s | after: ok, median / worst px, s |
|---|---|---|
| `badminton_auditorium_240s` | false, 800 / 1274, 2.4 | false, **24.8 / 84.9**, 10.9 |
| `badminton_auditorium_smoke` | false, 478 / 1472, 9.9 | false, **37.7 / 51.0**, 10.9 |
| `pickleball_legacypark_240s` | **true**, 2.4 / 12.2, 1.0 | **true**, 2.4 / 12.2, 1.1 |
| `basketball_powellgym_240s` | false, 55.6 / 394, 6.9 | false, 55.6 / 394, 9.5 |
| `basketball_kennesawwide_240s` | false, 629 / 2318, 9.5 | false, 550 / 1562, 10.6 |
| `basketball_northsidewide_240s` | false, 587 / 1870, 2.4 | false, 801 / 1169, 10.9 |
| synthetic `basketball_half` (unit test) | true, < 3 px | true, < 3 px |

No ground truth, `ok` only: `basketball_parkwide` (no court paint at all) was **`ok =
true` before** (a wedge of court over the sky, score 0.968) and is false now (skew 0.59 on
the straight fit; the lens fit then fails the reprojection check, 153 px).
`badminton_russiaclub`, `basketball_pavilion`, `basketball_ceilingcam`: false before and
after.

**Target missed:** the brief wanted < 10 px median on the auditorium clip; it is 25 px
(240 s) and 38 px (smoke): the right court, one line off in places, and never `ok`
(score 0.49-0.51 < 0.90). The ceiling is D-25's model, not the search: with one `k1`
about the frame centre the *hand-clicked* court only scores 0.60-0.63, and with a free
distortion centre (+58, -87 px) 0.81. Any fit within ~30 px ties with it on every paint
measure tried (fraction, explained, covered, precision), so which of them wins is noise
(8-25 px across small changes to the search). A principal-point offset in `distortion`
is the next step, and it is a D-25 change. Runtime on clips that fail the straight fit
went from 2-10 s to 10-11 s (three lens passes); a straight `ok` clip is unchanged.

# Rally segmentation (net sports) — `events.detect_rallies`

Before this, `detect_rallies` returned `[]`, so the TV's default `Rallies` chip was empty
on every badminton and pickleball game. It is now a motion segmenter over the identified
players' court tracks, with no sport-specific code: thresholds are the profile's `rally:`
block (`profiles.RallyCfg` defaults).

**How.** Per 0.1 s tick: each player's court speed (m/s), speeds > 6 m/s dropped as
tracker/homography jumps, **median** over the players on court, 2.5 s moving average.
A rally is a run above 0.5 m/s that peaks at ≥ 0.9 m/s; it ends 0.5 s after its last
tick ≥ 0.9 m/s (the walk back after a point stays above 0.5), starts 1.0 s before the run
(the serve comes from stillness — every labelled serve below is preceded by ≥ 1 s at
0.1–0.3 m/s), gaps < 1.5 s are bridged and results < 2 s dropped. Median, not mean: one
player walking to pick up the shuttle is not a rally. `contacts` stays null (no audio).

**Ground truth.** Hand-labelled from 2 fps contact sheets with a > 2.5 kHz audio
transient strip underneath (shuttle hits are clean spikes in the auditorium; a
badminton rally never goes > ~2 s without one, so gaps in the strip mark dead time).
Labels live in `samples/real/<clip>.rallies.json` (gitignored with the footage) and are
copied here:

- `badminton_auditorium_240s`: 14 rallies — 3.3–17.0, 28.4–31.0 (uncertain), 37.9–45.5,
  56.7–62.5, 85.0–93.0, 100.2–105.0, 112.0–116.8, 123.9–129.9, 136.6–146.5,
  156.4–164.8, 171.4–178.0, 184.5–198.3, 206.0–215.0, 222.7–237.0. (76.3–77.8, a
  serve and one return, is under the 2 s floor and excluded.)
- `badminton_auditorium_smoke` = the first 50 s of that clip (MANIFEST §7): the first three.
- `pickleball_legacypark_smoke`: 12.7–23.8, 30.3–35.0 (clip end). Lower confidence:
  the far pair is ~40 px tall and the audio is useless — every neighbouring court pops.
- `pickleball_legacypark_240s`: **not labelled.** From stills the near pair (a metre
  from the lens, often out of frame) cannot be told apart between dinking and waiting to
  serve, and the audio cannot help. The segmenter emits 12 rallies there (unscored).

**Scores** (one-to-one matching, IoU ≥ 0.5). Two sets of tracks per clip, because
detect/track/identity were being changed by another agent during this work: "A" is the
first run, "B" a fresh full run on the later tree (same labels, same segmenter).

| clip | stub | first cut (mean speed, no end trim) | final, tracks A | final, tracks B |
|---|---|---|---|---|
| `badminton_auditorium_240s` (14) | 0 events, R 0 | P 0.77 R 0.71 | **P 1.00 R 0.93** (13/13) | P 0.92 R 0.86 (12/13) |
| `badminton_auditorium_smoke` (3) | 0 events, R 0 | P 0.67 R 0.67 | **P 1.00 R 1.00** | P 1.00 R 0.67 |
| `pickleball_legacypark_smoke` (2) | 0 events, R 0 | P 0.67 R 1.00 | **P 1.00 R 1.00** | P 1.00 R 1.00 |

Honest caveats: the thresholds were chosen by a sweep over these same labels (~20
rallies; the plateau is wide — dozens of settings within 0.05 F1 — but it is in-sample),
and the labels are one person's. Misses are the calm rallies: 156–165 s on the badminton
clip runs at a median 0.6–0.9 m/s, and track set B cuts it at 160 s. Starts land ~1 s
early and the long rallies end a few seconds early (a dip in the median mid-rally), which
IoU ≥ 0.5 tolerates but a tighter criterion would not.

End to end: a fresh `courtcam run` on `badminton_auditorium_smoke.mp4`
(`--calib badminton_auditorium_240s.landmarks.json`, `--variant singles` to exercise the
alias) finishes `ready` with 4 players and `events.json` holding two `rally` events,
1.2–12.6 s and 28.0–33.1 s.

---

# Detection on the GPU, identity stitching, bystanders (fix wave, 2026-09-30)

Box: shared AMD RX 9070 XT (ROCm torch 2.14, reports as `cuda`), 16 cores, other agents'
jobs running alongside, so throughput is a floor, not a benchmark. Clips ingested once;
every variant below reuses the same `media/wide.mp4` + `calib.json` and re-runs
`detect,track,court,identity`. Metrics come from a scratch script over `_work/`:
**on-court boxes/frame** (detected feet inside the court + 1 m — the recall proxy),
**raw / on-court tracklets** (fragmentation at the source), **roster** (player ids in
`game.json`), **concurrency** (players alive per instant), **> 5 m jumps** (consecutive
samples of one player more than 5 m apart — an identity-switch proxy) and
**bystanders** (a player with p90 radius < 1 m over >= 20 s, or inside the painted lines
< 40 % of the time).

## Model x stride (ByteTrack, identity code unchanged)

240 s clips. `x RT` = clip seconds per wall second of `detect` (higher is faster; the
CPU reference is Kennesaw yolo11n = 709 s, **0.34x**).

| clip | model | stride | detect s | x RT | boxes/frame on court | raw tracklets | on-court tracklets |
|---|---|---|---:|---:|---:|---:|---:|
| kennesawwide | n | 2 | 37 | 6.4 | 11.0 | 737 | 400 (capped) |
| kennesawwide | s | 2 | 41 | 5.8 | 13.6 | 690 | 333 |
| kennesawwide | **m** | **2** | **52** | **4.6** | **13.2** | **585** | **301** |
| kennesawwide | l | 2 | 59 | 4.1 | 12.8 | 506 | 273 |
| kennesawwide | m | 1 | 95 | 2.5 | 13.5 | 949 | 352 |
| powellgym | n | 2 | 36 | 6.6 | 8.5 | 489 | 326 |
| powellgym | s | 2 | 35 | 7.0 | 9.0 | 412 | 281 |
| powellgym | **m** | **2** | **55** | **4.4** | **9.5** | **397** | **271** |
| powellgym | l | 2 | 68 | 3.6 | 9.4 | 388 | 258 |
| legacypark (pickleball) | n | 2 | 36 | 6.7 | 2.60 | 679 | 47 |
| legacypark | **m** | **2** | **56** | **4.3** | **2.98** | **601** | **35** |
| legacypark | l | 2 | 68 | 3.5 | 2.95 | 584 | 34 |
| auditorium (badminton) | n | 2 | 48 | 5.0 | 3.88 | 39 | 28 |
| auditorium | **m** | **2** | **58** | **4.1** | **3.90** | **29** | **22** |
| auditorium | m | 1 | 106 | 2.3 | 3.91 | 40 | 25 |

- **yolo11m finds 12-20 % more on-court people than yolo11n** on the three clips with
  small far players and cuts raw tracklets by 11-26 %; `l` adds nothing over `m`; `s` is
  as fast as `n` (decode and the tracker, not the GPU, bound `n`/`s`) but fragments more
  than `m`. Badminton is saturated at 4 people for every model.
- **Stride 1 is worse, not better**: twice the wall time and *more* tracklets (the tracker
  buffer is counted in sampled frames, so it covers half the time).
- **Shipped:** on a GPU, `detection.gpu_model: yolo11m.pt` replaces `model`, stride stays 2.
  Without a GPU nothing changes (`yolo11n`, CPU).

## Tracker (yolo11m, stride 2, final identity code)

| tracker | Kennesaw roster | Kennesaw > 5 m jumps | Powell roster / jumps | badminton ids | badminton left pair |
|---|---:|---:|---:|---:|---|
| `bytetrack.yaml` (stock) | 47 | 29 | 45 / 22 | 4 | red / blue shirts **swap** at ~180 s |
| bytetrack, buffer 90 | 40 | 31 | — | 4 | swap |
| botsort, buffer 30, no GMC | 49 | 23 | 46 / 27 | 4 | no swap |
| **botsort, buffer 90, no GMC** (`courtcam/botsort.yaml`) | **43** | **18** | 43 / 28 | **4** | **no swap** |
| botsort + ReID (detector features) | 50 | 16 | — | 4 | no swap |

The badminton swap was checked by mean torso colour of every member tracklet of each
player: with ByteTrack the red-shirt lane picks up the blue-shirt player at 179 s (a swap
*inside* a ByteTrack tracklet, which no merge can undo); with BoT-SORT the red lane is
red for all 240 s. ReID costs the same wall time and gains nothing measurable here, so it
is off. GMC is off because the camera does not move. Same speed as ByteTrack.

## Identity: what was wrong, and the fix

1. **A one-frame handover killed whole players.** ByteTrack starts a person's new id a
   frame before it drops the old one. `merge_groups` refused any overlap, and
   `_cap_concurrent` counted that single frame as a fifth person and rejected the whole
   group: on the badminton clip a 57 s far-side tracklet (103-160 s) was dropped
   outright — the 3/4 concurrency dip in the old run. Both now tolerate
   `tracking.merge_overlap_s: 1.0`.
2. **Earliest-first merging.** A fragment went to whichever old track *started* first
   among those in reach, not the one that ended where it appeared. Links are now taken
   closest-first, one predecessor and one successor per tracklet.
3. **Every remaining badminton break was a 3-9 m foot jump at an occlusion** (the net, the
   partner, the frame edge the back court runs off), just past `merge_max_dist_m: 3.0`,
   while the other three players were tracked throughout. New `identity._stitch`, after
   the concurrency cap: walk players in start order with "lanes" per team; a player who
   appears while their team is below its share of `players.max` continues the nearest
   lane that ended within `stitch_max_gap_s` (5 s) and within
   `merge_max_dist_m + max_speed_mps (8) x max(gap, 1 s)`, and only if the interpolated
   gap does not push the frame past `players.max` boxes. The roster is what says it is
   the same person; nothing is inferred from shirts.

## Bystanders: what was wrong, and the fix

The on-court test (>= 60 % of samples inside court + 1 m) is right for fragments and
wrong for people who never move: on Kennesaw the scorer's table is *inside* the calibrated
polygon and the bench sits on the baseline inside the 1 m margin, and because they never
move they had the best scores in the concurrency cap — 2-3 of the 10 selectable slots for
the whole clip (frames `ken_base` vs `ken_final` in the scratch run: the two seated
officials and the bench were boxed; after, the far-left players and the referee they
displaced are). Two rules, in `court.py`:

- `stationary`: alive >= `stationary_min_s` (20 s) with p90 radius < `stationary_max_m`
  (0.5 m). Applied to tracklets in `on_court` (before they can merge into a player) and
  to merged players. 1.0 m was tried first and dropped a real badminton player who stood
  25 s within 0.86 m; seated officials measure 0.04-0.22 m.
- `bystander` (merged players): inside the painted lines, no margin, less than
  `inside_min_fraction` (0.4) of the time. Real players measured >= 0.53 (the pickleball
  near pair, who serve from behind the line; basketball >= 0.85); the Kennesaw bench and
  the neighbouring pickleball court's baseline measure 0.0-0.31.

## Before / after, per clip

"Before" = yolo11n + ByteTrack + the old identity (= the previous default, on the GPU).
"Code only" = the same dets with the new identity/court code. "Final" = the new default
path end to end (`courtcam run --stages detect,track,court,identity,tracks,crops` on the
GPU box: yolo11m + `botsort.yaml` + new code).

| clip | | ids (roster) | median / p10 concurrent | mean selectable (of which bystanders) | > 5 m jumps | detect s |
|---|---|---:|---|---|---:|---:|
| badminton auditorium (4 players) | before | 9 | 4 / 3 | 3.70 (0) | 0 | 48 |
| | code only | **4** | 4 / 4 | 4.00 (0) | 0 | |
| | final | **4** | 4 / 4 | 4.00 (0), min 4 | 3 | 54 |
| kennesawwide | before | 55 | 10 / 8 | 9.39 (**2.32**) | 40 | 37 |
| | code only | 50 | 10 / 8 | — (1 official left) | 36 | |
| | final | 43 | 9 / 8 | 9.36 (**0**), min 7 real | **18** | 50 |
| powellgym | before | 57 | 9 / 8 | 9.23 (0.29) | 50 | 36 |
| | code only | 51 | 10 / 8 | — | 25 | |
| | final | 43 | 10 / 9 | 9.46 (0) | 28 | 56 |
| pickleball legacypark | before | 36 | 2 / 1 | 2.38 (0.29) | 0 | 36 |
| | code only | 15 | 2 / 1 | — | 2 | |
| | final | 9 | 2 / 2 | 2.36 (0) | 1 | 57 |

Kennesaw holds 8.4-10 selectable per 10 s chunk (mean 9.36), now all of them on court;
the officials no longer hold slots, so the concurrency number reads 9 instead of
10 while the number of *real* players selectable went from ~7.1 to ~9.4. Pickleball's
concurrent 2 is the real near pair — the far half of this court is empty and the old
third "player" was the next court's baseline (RESULTS above).

courtcam tests on the box: **94 passed**, 2 failed — both in `test_autocalib.py`, from
another agent's in-flight `autocalib` edits in the same tree (`_straighten`/`_bend_back`
missing); every identity/court/pipeline/net-sport test passes. `services/api`: 80 passed.
`ruff check` clean on every file this work touched.

## Still wrong

- **Identity within a same-looking pair is unverified.** Badminton's right-hand pair wear
  near-identical dark kit; torso colour cannot say whether their two lanes swapped. The
  left pair (red / blue) is clean for 240 s with BoT-SORT.
- **Merged officials with a box that flips between two seated people** (Kennesaw, CPU
  `yolo11n` only: one player, p90 radius 0.83 m) and a seated spectator on the Powell far
  sideline whose 28 s tracklet briefly jumped onto a passing player (p90 6.8 m) survive the
  stationary rule. Both are one slot for part of the clip, down from 2-3 slots always.
- **Referees are players** to every rule here (they move and stay inside the lines).
- A stitched or merged gap is **interpolated** (`court.resample`), so for up to 5 s a box
  slides between where a player vanished and where they reappeared.
