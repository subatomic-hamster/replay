# M6 evidence: broadcast auto-director + compositor

Everything here is **synthetic** (courtcam synth v2, basketball, 90 s, seed 11, 2560x1440).
Real-footage renders live in `docs/evidence/local/M6/` (gitignored, D-7).

| file | what |
|---|---|
| `broadcast_synthetic_basketball_90s.mp4` | the broadcast rendition, 1280x720 H.264 crf 32 + AAC 96k (kept small for git), labelled on screen "SYNTHETIC · EVENTS FROM GROUND TRUTH" |
| `cuts_synthetic_gt.json` | the cuts.json that drove it: 15 cuts, 4 replays, final 4–6 |
| `cuts_synthetic_pipeline.json` | cuts.json from the pipeline's own events on the same clip: no makes detected yet, so wide/tight/follow only, 0 replays, score 0–0 |
| `stills/` | live wide / tight / follow, lower third, replays with telestrator (ring, trail, shot arc to the 3.05 m rim), sting mid-wipe |
| `jitter/` | camera-path jitter (rms of the window-centre second difference, 1080p screen px/frame²) raw target vs smoothed per camera, and courtcam follow-cam before/after the dead zone + EMA lead |

**Provenance of the "GT" variant.** The worker ran the full pipeline on the clip
(`--detector synthetic`: tracks, identity, crops, calibration are pipeline output). At
render time the plays agent's make detection did not yet report any makes on this clip,
so `replay_render truth-game` replaced events/score/plays with the generator's ground
truth (shots, makes, scorer, 2/3 points by the 6.75 m line), mapped onto pipeline player
ids by box overlap and written with `provenance: synthetic_ground_truth`. Director,
cameras, graphics, telestrator and audio are unchanged pipeline code. This shows the
replay/score/lower-third path end to end; it is not a measure of make detection.

Jitter, rms px/frame² (raw target to smoothed):

| | synthetic (0–90 s) | Kennesaw 150–240 s (local) |
|---|---|---|
| wide | 0.63 to 0.022 | 14.50 to 0.072 |
| tight | 25.28 to 0.25 | 51.32 to 0.42 |
| follow-cam, courtcam croppath before/after | 1.37 to 0.51 (p95 2.54 to 0.71, 10 players) | 2.12 to 0.64 (p95 4.31 to 1.24, 22 players) |

Render speed on hfbox (CPU, one process): 90 s at 720p in 13.4 s; 90 s at 1080p of the
2560x960 Kennesaw source in 27 s; the worker `broadcast` stage at 1080p on this clip in 29 s.

## Commands (hfbox, `source /workspace/wt/replay-env/env.sh`, PYTHONPATH = courtcam, services/*, render)

```bash
s=/workspace/wt/replay-broadcast-scratch
python -m courtcam.cli synth --sport basketball --variant full --duration 90 --seed 11 \
  --size 2560x1440 --out $s/synth90
python -m replay_worker run $s/synth90/clip.mp4 --out data/games/g_synth90 --detector synthetic
python -m replay_worker run $s/synth90/clip.mp4 --out data/games/g_synth90 --detector synthetic \
  --stages broadcast                       # director + broadcast stages (cuts_synthetic_pipeline.json)
python -m replay_render truth-game data/games/g_synth90 $s/synth90 --out data/games/g_synth90_gt
python -m replay_render direct data/games/g_synth90_gt
python -m replay_render render data/games/g_synth90_gt --out broadcast_synthetic_basketball_90s.mp4 \
  --size 1280x720 --crf 32 --abr 96k --label "SYNTHETIC · EVENTS FROM GROUND TRUTH"
python -m replay_render stills data/games/g_synth90_gt broadcast_synthetic_basketball_90s.mp4 --out stills
python -m replay_render jitter data/games/g_synth90 --out jitter
```

Local (not committed): `docs/evidence/local/M6/broadcast_kennesaw_150_240.mp4` (1920x1080,
crf 22, 150–240 s of the Kennesaw clip, from `python -m replay_render render
data/games/g_kennesaw --size 1920x1080 --crf 22 --t0 150 --t1 240`), its cuts.json (30 cuts:
8 wide, 7 tight, 11 follow, 4 replays of shots with unknown outcome; provisional, score
stays 0–0), stills and jitter plots. On that stitched panorama no pinhole camera fits
(player-height ratio 1.31), so shot arcs are off and the ring/trail use the homography.
