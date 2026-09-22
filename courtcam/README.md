# courtcam

A video pipeline that turns one fixed wide shot of a court into **per-player tracks,
follow-cam crop paths, and events** — so a TV app can let you pick a player out of
the frame and watch the game follow them.

Point a phone at a rec game from the bleachers, click four court corners, and
`courtcam` gives you: every player's position in **metres on the court**, a smooth
follow-cam rectangle per player per frame, and a list of shots. Everything
sport-specific lives in a **sport profile** (a YAML file plus a court template);
core code never branches on the sport.

Part of the [Replay](../README.md) project. MIT licensed.

## Why it is shaped this way

- **A homography, not a 3D reconstruction.** One camera, one flat court. Four clicks
  give you pixels → metres, which is all the on-court filter, the court inset and the
  shot heuristic need.
- **The on-court filter is the whole trick.** A person detector finds the bench, the
  spectators and the guy walking his dog. Projecting each box's foot point onto the
  court and keeping only tracklets that live inside the lines is what makes
  "tap a player" usable.
- **Crop paths, not rendered video.** A crop rectangle per frame is a few KB; the
  client applies it with a CSS transform. Rendering per-player MP4s is the fallback
  (`courtcam render`), done lazily.
- **Stages are pure file → file functions.** Each one skips itself if its output is
  already on disk, so a crashed detect run resumes instead of restarting.

## Install

Python 3.12. From the Replay workspace root:

```sh
uv sync --all-packages --all-extras     # shared .venv with courtcam + services/api
uv run courtcam --help
```

Standalone:

```sh
uv pip install -e "courtcam[dev]"
```

Needs `ffmpeg` and `ffprobe` on `PATH`. The H.264 encoder is picked at run time
(`libx264`, else `libopenh264`, else `h264_qsv`) — not every distro ships libx264.

## CLI

```sh
# 1. make a synthetic court clip + ground truth + landmark clicks (no model needed)
uv run courtcam synth --out samples/synthetic/basketball_half

# 2. run the whole pipeline
uv run courtcam run \
    --input samples/synthetic/basketball_half/clip.mp4 \
    --calib samples/synthetic/basketball_half/landmarks.json \
    --sport basketball --variant half \
    --out out/

# ... with ground-truth boxes instead of YOLO (CI, no weights required)
uv run courtcam run --detector synthetic --input ... --out out/

# only re-run some stages (this also forces them to recompute)
uv run courtcam run --input ... --out out/ --stages detect,track,court

# 3. check it with your eyes: court polygon + boxes + ids burned into an MP4
uv run courtcam overlay --out out/

# other commands
uv run courtcam calibrate --landmarks landmarks.json --out out/calib.json
uv run courtcam render --out out/ --player p1      # rendition-mode follow-cam MP4
uv run courtcam sports                              # installed profiles
```

Useful flags on `run`: `--stride` (detect every Nth frame; the profile's default is 2
= 15 Hz), `--max-frames`, `--title`, `--ground-truth`, `--landmarks` (inline JSON as
well as a path).

`courtcam render` writes `media/<player_id>.mp4` and points
`renditions.players[<player_id>]` at it, setting `stages.render` to `partial` — that
is the lazy render the API triggers on first request (D-6).

`--landmarks` / `--calib` accept any of: a `landmarks.json`
(`{"variant": "half", "landmarks_px": {...}}`), a bare `{"corner_nl": [x, y], ...}`
object, or an already-computed `calib.json`.

## Output layout

```
out/
  game.json              replay.game.v1   — the index; `stages` fills in as they finish
  calib.json             homography, its inverse, court polygon in px and metres
  media/wide.mp4         30 fps H.264 faststart mezzanine at source resolution
  media/thumb.jpg  media/calib.jpg
  tracks/00000.json …    replay.tracks.v1 — 10 s chunks at 10 Hz
  crops/p1.json …        replay.crops.v1  — one rect per video frame at 30 Hz, t0 = 0
  events.json            replay.events.v1
  _work/                 intermediates (dets, tracklets, court tracks, players)
```

`_work/` is what makes stages resumable. Delete a file in it to force that stage to
recompute; delete the directory to start over from the mezzanine.

## Stages

| Stage | Reads | Writes |
|---|---|---|
| `ingest` | source video | `media/wide.mp4`, stills |
| `calibrate` | landmark clicks + court template | `calib.json` |
| `detect` | `wide.mp4` | `_work/dets.json` (boxes + track ids) |
| `track` | `_work/dets.json` | `_work/tracklets.json` |
| `court` | tracklets + `calib.json` | `_work/court.json` (on-court only) |
| `identity` | court tracks + `wide.mp4` | `_work/players.json` (`p1..pN`, teams) |
| `tracks` | players | `tracks/*.json` |
| `crops` | players | `crops/*.json` |
| `events` | players + `wide.mp4` | `events.json` |

Detection and ByteTrack association happen in the same Ultralytics pass, so `detect`
emits track ids and `track` only has to group them into tracklets.

## Using it from Python

```python
from pathlib import Path
from courtcam import pipeline

def on_progress(stage: str, fraction: float) -> None:
    print(f"{stage} {fraction:.0%}")

game_json = pipeline.run(
    Path("game.mp4"), Path("out/"),
    sport="basketball", variant="half",
    landmarks_px={"corner_nl": (120, 810), ...},   # or calib=Path("landmarks.json")
    detector="yolo",                                # or "synthetic" + ground_truth=
    progress=on_progress,
    show_progress=False,                            # no tqdm bars in a worker
)
```

`pipeline.run` returns the path to `out/game.json`. Every stage is also importable on
its own (`pipeline.stage_detect`, `stage_crops`, …) if you want to drive them yourself.

## Profile format

A profile is `courtcam/sports/<id>.yaml` plus one court template JSON per variant.
Core code reads only these fields (plan §4.9):

```yaml
id: basketball
display_name: Basketball
tier: 2
court:
  templates: {half: basketball_half.json, full: basketball_full.json}
  variants: [half, full]
  landmarks: [corner_nl, corner_nr, corner_fl, corner_fr, rim]
  margin_m: 1.0                 # how far off the lines a player may stray
players: {min: 2, max: 10}      # max also caps the on-court filter
team_rule: jersey_color         # or net_side
detection: {classes: [person], stride: 2, model: yolo11n.pt, imgsz: 960, conf: 0.25}
tracking:
  oncourt_min_fraction: 0.6     # of its lifetime a tracklet must spend on court
  min_lifetime_s: 1.0
  merge_max_gap_s: 1.5          # tracklet merge window
  merge_max_dist_m: 2.0
  smooth_window: 5
events: [shot]                  # which detectors run
shot: {rim_radius_m: 7.0, roi_px: 96, min_gap_s: 2.0, burst_sigma: 2.5, pre_s: 3.0, post_s: 2.0}
followcam: {zoom: 2.0, lead_s: 0.3, stiffness: 7.0}
query_vocab: {...}              # read by the API's query engine
sport_ui: {...}                 # read by the TV app; courtcam only carries it
```

A **court template** is metres in the profile's origin convention — baseline centre
under the basket for half-court, centre of one baseline for full-court, `+x` toward
the right sideline, `+y` into the court:

```json
{"name": "basketball_half", "standard": "fiba", "units": "m",
 "size": [15.0, 14.0],
 "court": [[-7.5, 0], [7.5, 0], [7.5, 14], [-7.5, 14]],
 "rim": [0.0, 1.575], "rims": [[0.0, 1.575]],
 "landmarks": {"corner_nl": [-7.5, 0], "...": []},
 "features": {"paint": [...], "three_point": [...], "centre_line": [...]}}
```

`court` is the polygon the on-court filter tests against. `features` are polylines
for drawing only — the three-point arc is approximated as a 53-point polyline.

## Adding a sport

1. Write `courtcam/sports/<sport>.json` — the court polygon and line polylines in
   metres, plus `landmarks` for the points a user will click.
2. Write `courtcam/sports/<sport>.yaml` with the fields above.
3. Check it: `uv run courtcam synth --out /tmp/<sport> --sport <sport>` renders the
   template through a camera, then run the pipeline on it with `--detector synthetic`.
4. If the sport needs a new event type, add a detector function to
   `events.DETECTORS`. Do not add a branch on the sport id anywhere else.

`team_rule: net_side` raises `NotImplementedError` — the net-side split needs the net
line from the template and per-rally re-evaluation, and no net sport ships yet.

## Tests

```sh
uv run pytest courtcam/tests -q     # ~15 s; no model weights needed
uv run ruff check courtcam/
```

The suite regenerates the synthetic clip if `samples/synthetic/basketball_half/` is
missing, runs the whole pipeline over it with `--detector synthetic`, validates every
output against the schemas, and compares against
`samples/synthetic/basketball_half/golden.json` with tolerances (court positions
±0.25 m, event count ±3).

## Schema notes (deviations from REPLAY_PLAN.md §4.5)

- **`Event.made` is nullable.** The plan shows `"made": true`. The default
  `HeuristicLabeler` cannot see the ball, so it emits `made: null` = unknown. A VLM
  labeler plugged into the `Labeler` protocol fills it in. Clients must treat
  `null` as "not judged yet", distinct from `false`.
- **`court.templates` in a profile.** The plan shows a single `template:`; basketball
  needs a different template per variant, so the loader also accepts
  `templates: {variant: file}`. `template:` still works for single-variant sports.
- No other field names differ. `schema` strings are unchanged.

## Known ceilings

Marked in the source with `# ponytail:` comments.

- **Shot detection is a frame-difference heuristic.** Mean absolute difference in the
  rim ROI fires on any motion there, so a defender under the basket scores like a
  shot. `shot.burst_sigma` is the knob; the real fix is the `Labeler` seam (send the
  candidate clip to a VLM) rather than a better pixel heuristic.
- **The rally detector is a stub** returning `[]`. Basketball does not emit rallies.
- **Ingest always encodes in software.** VAAPI is roughly a 3× win on long files.
- **Appearance sampling seeks once per sampled frame** (≤ 8 per tracklet).
