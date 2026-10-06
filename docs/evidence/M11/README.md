# M11 evidence: hype meter, condensed game, vertical export, post-game review

All files here are **synthetic** (courtcam's generator v2, D-38) and labelled so in the
renders. Games: `courtcam synth --sport basketball --variant full --duration 180 --seed 7`,
`badminton doubles 90 s seed 7`, `pickleball doubles 90 s seed 11`, each run through
`courtcam.pipeline` with the synthetic detector and synthetic poses (no ASR). Regenerate
with `make_evidence.py` (usage in its docstring); numbers below are from `metrics.json`.

| file | what |
|---|---|
| `basketball_shot_chart.png` | shot chart from `GET /stats` (`review.shot_chart_png`): filled = make, cross = miss, ring = outcome unknown |
| `basketball_box_score.json` | the `/stats` response minus heatmaps: points, makes / misses / unknown, rebounds, steals, distance (labelled `auto-detected`, mean confidence) |
| `*_review_queue.json` | `GET /review/queue`: each question's options are the existing PATCH routes |
| `*_hype.json`, `*_hype.png` | `GET /hype` series (2 Hz) + candidates; red dashes = ground-truth makes / points |
| `badminton_condensed.mp4`, `pickleball_condensed.mp4` | condensed games (854x480, rally counter graphic) |
| `badminton_rallies.json`, `pickleball_rallies.json` | rally browser (`replay.rallies.v1`) with offsets into the condensed video |
| `basketball_vertical.mp4` / `.png`, `badminton_vertical.mp4` / `.png`, `pickleball_vertical.png` | 9:16 share exports (540x960) of a play, captions burned in |

Measured on hfbox (CPU, single process):

* Hype vs ground truth (a candidate counts if it peaks within -1 / +6 s of a GT make or
  point): basketball 7 candidates, P 0.857, R 1.0 (6 makes); badminton P 1.0, R 0.889
  (9 points; the pipeline found 7 of 9 rallies); pickleball P 1.0, R 1.0. The synthetic
  crowd cheers follow makes / points by construction, so this checks the fusion and the
  play mapping, not real-crowd behaviour. Before raw loudness was down-weighted when
  courtcam's audio analysis exists, the generator's spoken "Replay, clip that" lines were
  3 of 4 false candidates (basketball: 10 candidates, P 0.6).
* Distance covered (API stats, jump-filtered) vs ground-truth path length: median
  relative error 0.7 % basketball (max 1.6 %), 4.9 % badminton, 1.8 % pickleball.
* Condensed: badminton 90 s game -> 59.8 s (7 rallies, 42.3 s of rally), rendered at
  530 fps (3.4 s wall); pickleball 90 s -> 65.6 s (7 rallies), 533 fps (3.7 s).
* Vertical: 6.4-13.9 s clips at 540x960 in 0.6-1.4 s (~300 fps); camera jitter rms
  0.09-0.24 px/frame² at the output width.

Real-footage versions (YouTube-licensed, D-7) are local only: `docs/evidence/local/M11/`
(Kennesaw basketball: shot chart, box score, hype, 7 s vertical of the one detected make
at 222 fps; badminton auditorium: condensed 240 s -> 87.5 s with 14 rallies at 248 fps /
10.6 s wall, rally browser, hype, vertical). Those games were processed by the current pipeline (YOLO11m
detect + pose on the GPU) in the plays agent's run and copied, not re-run.
