# replay-render

Replay-side rendering (not part of MIT courtcam; may carry non-MIT optional extras later).
M6: the broadcast **auto-director** (`cuts.json`) and **compositor** (one H.264 "broadcast"
rendition with graphics, slow-motion replays, telestrator and a mixed audio track).

```bash
# on the box: source /workspace/wt/replay-env/env.sh
d=/workspace/wt/replay-<you>; export PYTHONPATH=$d/courtcam:$d/render
python -m replay_render direct data/games/g_x                    # -> data/games/g_x/cuts.json
python -m replay_render render data/games/g_x --out b.mp4 --size 1920x1080 [--t0 150 --t1 240]
       [--narration commentary.wav] [--label SYNTHETIC] [--crf 20] [--abr 128k]
python -m replay_render stills data/games/g_x b.mp4 --out stills/ [--t0 150 --t1 240]
python -m replay_render jitter data/games/g_x --out plots/       # camera-path jitter + plots
python -m replay_render truth-game g_synth <synth out dir> --out g_synth_gt   # synthetic only
(cd render && python -m pytest -q)
```

Through the worker (`services/worker`, stages `director` and `broadcast`, both outside the
default DAG): `python -m replay_worker run <game> --stages broadcast` writes `cuts.json` and
`renditions/broadcast.mp4`; the API lists it at `GET /games/{id}/renditions` and as
`game.renditions.broadcast` + `game.cuts_url`.

## cuts.json (`replay.cuts.v1`)

`{schema, duration_s, provisional, geometry, rules, cuts: [...], graphics: {...}}`.
Each cut: `{t_start, t_end, camera: "wide" | "tight" | "follow:<pid>" | "tight:<pid>",
reason, kind: "live" | "replay", transition: "cut" | "ease" | "sting"}`; replays add
`replay: {src_t_start, src_t_end, speed, event_id, play_id, player_id, shot_arc, passes}`.
Times are **rendition = source seconds**: a replay replaces live footage in the dead time
after the play, so score.json, events and the TV scrubber line up with the rendition.
Cuts are contiguous, ordered and never overlap (`director.validate`). `graphics` carries
everything drawn on screen (team labels/colours, score timeline, lower thirds), so the
render is a pure function of cuts.json + tracks + crops + calibration + source.
`provisional: true` means there was no score.json and the score came from made shots in
events.json.

## Director rules (`director.Rules`)

wide in dead time / tight (players within 8 m of the on-court centroid) in action
(median player speed > 1.1 m/s, hysteresis, 2 s bridges); long lulls alternate 12 s wide /
7 s tight; `follow:<shooter>` from 2.5 s before to 1 s after each shot; instant replay
2 s after makes (score.json), clipped plays, long rallies (≥ 8 s), or — only if no outcome
is known at all — shots with confidence ≥ 0.5: 3 s before to 1 s after the moment at 0.5x,
trimmed to end 0.5 s before the next action, dropped under 4 s, ≥ 15 s apart; no live
shot under 3 s, no A-B-A with B under 5 s; live changes ease (0.9 s smootherstep, width
in log space), replays enter/leave through a 0.7 s sting.

## Cameras (`camera.py`)

Every virtual camera is a raw target smoothed like an operator: dead zone, anticipation
from an EMA velocity, critically damped spring (zoom in log space), clamped to the frame.
`follow:<pid>` reuses courtcam's crop path (crops/<pid>.json), so the broadcast and the TV
follow mode agree. Measured (`jitter`, rms of the window-centre second difference in
1080p screen px/frame²): Kennesaw 150–240 s tight 51.3 → 0.42, wide 14.5 → 0.07;
synthetic tight 25.3 → 0.25. courtcam's follow-cam got the same dead zone + EMA lead
(croppath `DEAD_FRAC`, `VEL_TAU_S`): 2.12 → 0.64 (Kennesaw, 22 players), 1.37 → 0.51
(synthetic, 10 players).

## Graphics package

Barlow Condensed SemiBold/Bold (SIL OFL 1.1, `replay_render/assets/OFL.txt`), dark panel
`#0E1116`, replay amber `#FFB800`, LIVE red `#E5484D`, team colours from identity lifted
into a legible lightness band (`graphics.broadcast_color`). Score bug (team chips, score
with a team-colour flash on change, elapsed clock), LIVE / REPLAY 0.5× bugs, lower third
on each score (roster name if tagged, else `#<player id>` — the tracker's id, not a
jersey number; `+points · total PTS`), diagonal three-band sting with a REPLAY wordmark.

Telestrator (replays): spotlight ring (0.75 m circle on the floor, pulsing rim), 2.5 s
movement trail, pass arcs (when events carry `pass` with `receiver_id`), and the shot arc:
a parabola from the shooter's spot at 2.3 m to the nearest rim at 3.05 m, landing at the
shot's key time. Arcs need a pinhole projection — the calibration's K/R/t, or a camera
recovered from the ground homography (Zhang's constraints, principal point at the centre)
that predicts tracked box heights within 25 % — otherwise (stitched/barrelled footage) no
arc is drawn; ring and trail only need the homography.

## Audio

Game audio on the source clock continues under everything, ducked 9 dB under replays;
procedural two-chord sting (no samples, no noise whoosh) at each replay edge; optional
narration WAV (source clock) with sidechain ducking (−12 dB) of the game under it — the
hook for the commentary track (M7).

## Discovery (M11): hype meter, condensed game, vertical export, shot chart

```bash
python -m replay_render hype data/games/g_x                      # -> hype.json
python -m replay_render condensed data/games/g_x [--size 1280x720 --label SYNTHETIC]
                                       # -> renditions/condensed.mp4 + condensed.json
python -m replay_render vertical data/games/g_x --out v.mp4 (--clip c_1 | --play pl_1 |
                                       --event e_1 | --t0 10 --t1 18 [--player p3])
```

* **hype.py** (`replay.hype.v1`): 0-1 at 2 Hz = noisy-or of audio loudness over its 20 s
  rolling median (courtcam `audio.json`, else measured from the video; courtcam `hype`
  events lift it), players with both wrists above their shoulders (`poses/`), and speed
  bursts over a 30 s baseline (weights 0.85 / 0.6 / 0.35). Candidates: peaks >= 0.4, >= 8 s
  apart, each mapped to the play that ended up to 8 s before the peak.
* **condensed.py**: rallies only (+1.5 s pre-roll, +1 s after the point, windows < 0.5 s
  apart merged), wide camera, rally counter (RALLY n / N, shots, length) in the package's
  look, score bug when score.json has points; `condensed.json` is the rally browser
  (`replay.rallies.v1`: rallies with length, shots — audio contact count, else contact
  events — server, last hitter, `condensed_t`; longest / most-shots lists).
* **vertical.py**: 9:16 window following the clip's key player (subject, else the play's
  shooter / attacker / ... / server, else the gesture owner) through `camera.smooth`
  with `aspect=9/16`; captions burned in from the events (no LLM); H.264 + AAC.
  `spec_id` (content hash) names `exports/vertical/<id>.mp4`.
* **review.py**: shot-chart PNG from the API's stats response.
* `compositor.render_segments` is the shared cut-and-concat renderer (video + audio with
  15 ms join fades) both renders use.

Worker stages `hype`, `condensed`, `vertical` (services/worker `stages/discovery.py`, all
opt-in); API routes in services/api `discovery_routes.py`.

## Tier C 3D replays (M9)

`replay_render/avatars/`: 3D skeletons per player (MotionBERT lift or the analytic
fallback), `scene/{play_id}.json` (`replay.scene.v1`), capsule-avatar renders from 4 angles
+ the shooter's POV. Contract, pipeline, quality numbers and limits:
[`replay_render/avatars/README.md`](replay_render/avatars/README.md). Worker stages
`tierc_scene`, `tierc`, `tierc_manifest` (opt-in) add the angles to
`replays/{play_id}/manifest.json` as `tier: "C"`.

## Limits

Single CPU render, ~100 fps at 1080p from a 2560×960 source on the box. Frame
interpolation for slow motion is not done (frames repeat). Ball-side framing uses players
only (no ball tracker yet). On the panoramic Kennesaw clip the spotlight ring sits within
about a player-width of the player (tracking on a stitched frame, D-18).
