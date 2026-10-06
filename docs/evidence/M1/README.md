# M1 metrics: detection and tracking (synthetic)

**Synthetic data only.** Re-measured 2026-10-06 on hfbox. The numbers are in `metrics.json`,
which `../M4/eval/split.py` generated. `synthetic_basketball_half_yolo_overlay.*` are older
visuals and were not regenerated.

The runs are the same ones as M4 and M5. The commands, code state and scripts are in
`../M4/README.md` and `../M4/eval/`.

- **Scenes:** the five seed-7 clips from `courtcam synth --duration 90 --seed 7`, 1280x720 at
  30 fps. They are basketball half court, basketball full court, pickleball doubles, badminton
  doubles and volleyball indoor.
- **Tracking scores:** from `courtcam eval --gt <clip>/ground_truth.json --out <run>`
  (`run_metrics.sh mot`), scored on the on-court players.
- **YOLO runs:** `run1.py <clip> <out> yolo yolo` (yolo11m detection).
- **Ground-truth detector runs:** `run1.py <clip> <out> synthetic auto`.

| scene | YOLO MOTA | YOLO IDF1 | YOLO ID switches | GT detector MOTA / IDF1 |
|---|---|---|---|---|
| basketball half | 0.64 | 0.31 | 122 | 1.00 / 1.00 |
| basketball full | 0.43 | 0.25 | 157 | 1.00 / 1.00 |
| pickleball | 0.98 | 0.99 | 0 | 1.00 / 1.00 |
| badminton | 0.99 | 1.00 | 0 | 1.00 / 1.00 |
| volleyball | 0.91 | 0.75 | 37 | 1.00 / 1.00 |

Court-position error for YOLO-matched players (median) runs from 0.26 m (badminton) to 0.47 m
(basketball full). With the ground-truth detector it runs from 0.16 m to 0.30 m.

## Voice ASR on the synthetic mixes

The test runs whisper-small through `pipeline.stage_triggers` (`run_trig.py`) on each clip's
`audio.wav`. Those files contain the synthetic speech mixed with synthetic crowd noise and
contact sounds.

- whisper-small heard 37 of 37 "Replay, clip …" lines across all 9 clips.
- So every line was heard in 9 of 9 clips. The YOLO runs give the same result.

This is not necessarily the same test as the old "8/9 crowd-noise mixes" claim. The script
behind that claim was not found.

## Tracking v2: jersey-swap splitting and global linking (2026-10-06)

**Synthetic data only.** Numbers in `metrics_tracking_v2.json` (`../M4/eval/agg.py` over
`courtcam eval` outputs; keys `<clip>_before` / `<clip>_after`). Scripts in `eval_tracking_v2/`;
`final.sh` lists the exact steps. "Before" is identity at HEAD 005cf87; "after" re-runs only the
identity stage on the same YOLO11m + BoT-SORT detections (`courtcam/botsort.yaml` unchanged), so
detection and tracker output are identical in both columns. The baseline reproduced exactly
(half s7 0.6366 / 0.3104 / 122, full s7 0.4277 / 0.2453 / 157, half s11 0.6644 / 0.3112 / 125).

### Where identities break (half s7 / full s7, `diag.py`, `oracle.py`)

- 28 of 109 / 27 of 117 on-court tracklets already carry two or more people (16 % / 14 % of
  their samples). 27 of 43 / 20 of 37 of those swaps are with an **opponent**.
- `merge_groups` then made more wrong links than right ones: 28 right vs 43 wrong / 39 vs 43.
- Ceilings on the same tracklets: perfect linking gives IDF1 0.73 / 0.56; perfect splitting
  plus linking gives 0.85 / 0.64. The loss is association, not detection.
- No single link cue picks the true successor reliably (`feat.py`, top-1 among same-team
  candidates): end distance 65-66 %, velocity extrapolation 50-69 %, body histogram 52-59 %
  (60-61 % on the last / first 2 s only), relative stature 43-44 %.

### What changed (`courtcam/identity.py`)

1. `jersey_labels` + `split_switches`: every 2nd sample gets the nearer team's torso colour;
   a change that holds ≥ 1 s cuts the tracklet, and each piece takes its own team. Only for
   `team_rule: jersey_color`, and only when ≥ 85 % of sampled torsos agree with their
   tracklet's team (`JERSEY_MIN_AGREE`): synthetic 0.875-0.966, Kennesaw pickup 0.80.
2. `merge_groups` links by one Hungarian assignment (`lap`) over
   `dist / (1 m + 3 m/s × gap) + 0.3 × gap`, links above 2.0 left unmade, instead of
   cheapest-first greedy. Costs tuned on dev seeds 13 and 17 only.

### Results (YOLO11m + BoT-SORT, players)

| clip | MOTA before → after | IDF1 before → after | ID switches before → after |
|---|---|---|---|
| basketball half s7 | 0.637 → 0.627 | **0.310 → 0.366** | 122 → 119 |
| basketball full s7 | 0.428 → 0.422 | **0.245 → 0.263** | 157 → 158 |
| basketball half s11 | 0.664 → 0.669 | **0.311 → 0.326** | 125 → 125 |
| pickleball s7 / s11 | 0.979 / 0.985, unchanged | 0.990 / 0.993, unchanged | 0 / 0 |
| badminton s7 / s11 | 0.994 / 0.989, unchanged | 0.997 / 0.995, unchanged | 0 / 0 |
| volleyball s7 | 0.909 → 0.906 | 0.750 → 0.785 | 37 → 37 |
| volleyball s11 | 0.923 → 0.915 | 0.746 → 0.737 | 23 → 25 |
| dev: basketball half s13 / s17 | 0.640 → 0.684 / 0.642 → 0.712 | 0.416 → 0.461 / 0.356 → 0.563 | 84 → 74 / 102 → 101 |
| dev: basketball full s13 / s17 | 0.447 → 0.433 / 0.428 → 0.417 | 0.287 → 0.328 / 0.244 → 0.242 | 144 → 137 / 167 → 176 |

Court error medians move by ≤ 0.005 m. Identity stage time on Kennesaw 240 s: 11.6 s wall.

- **Held-out basketball (M1 seeds):** IDF1 +0.015 to +0.056; mean 0.289 → 0.318. MOTA within
  ±0.01. CLEAR-MOT ID switches do not move: they are swaps inside BoT-SORT tracklets, and a
  cut piece is still counted as a switch when it is relinked to someone else.
- **Not shipped (measured, no gain on the dev seeds):** BoT-SORT `fuse_score: false` (raw
  tracklets halve, but more swaps inside them: dev IDF1 0.274 base / 0.345 with this pass),
  thresholds 0.15 / 0.05 / 0.4 (0.293 / 0.371), `match_thresh` 0.9, stride 1 (half s7 0.307),
  appearance cost in the assignment (±0.01), "only unambiguous links", splitting at net
  crossings for net sports (no change on 6 clips).
- **Kennesaw 150-210 s (local, hand count, ±5):** about 51 visible changes in 19 rows before,
  about 42 in 21 rows after; the referee stays one stable row. Without the agreement gate,
  colour cuts broke the referee into four rows. Sheets:
  `docs/evidence/local/M1/tracking_v2_kennesaw_id_rows_150-210s_{before,after}.jpg` (my count of
  the before sheet is higher than the 38 in progress.md; same counter for both).

## Tracking v3: no jersey cut under a guard (2026-10-06)

**Synthetic data only.** Numbers in `metrics_tracking_v3.json`, written by
`eval_tracking_v3/make_v3.py`. "Before" is 81e1e99 (identity v2, D-70). "After" is the same
tree with only `courtcam/identity.py` changed. Both run the same harness on the same 9 clips
(`../M4/eval/run_metrics.sh`, seeds 7 and 11, regenerated today). The "before" reproduced the
committed `../M4/metrics_combined_9b777bb.json` on every events row, GT and YOLO.

### Cause (`eval_tracking_v3/diag_cut.py`, GT detector = perfect tracks)

D-70 found 15 off-team runs on half s7 / half s11 / full s7 (6 / 5 / 4 runs, 30 cut points).
Every one was false: each tracklet's samples all sit on one GT id. Output is in
`eval_tracking_v3/diag/`. Per clip, the samples in the cut runs compare to all
samples like this:

- **Torso box covered by another player's box:** 0.89 / 0.91 / 0.81 of its area in the cut runs,
  against 0.28 / 0.29 / 0.30 over all samples.
  - 93-100 % of cut-run samples are covered by more than 0.3.
  - In 74-95 % of them the covering box is the one in front (its foot point is lower).
- **Colour margin to the two team centroids:** 0.41 / 0.35 / 0.42 in the cut runs, against
  0.59 / 0.61 / 0.49 overall. The ranges overlap, so a colour-separation rule cannot pick the
  false cuts out.
- **Run lengths:** 8-31 samples, i.e. the ≥ 1 s that D-70 asks for.

So the torso shows the guard's jersey: an opponent standing over the player, not a tracker
swap. On half s11, tracks 5, 6, 9 and 10 were cut. The piece of 10 got team 1 and was linked
to a piece of 9; that is the cross-team player.

Under YOLO the same measure is 0.06-0.08 overall. NMS rarely keeps both boxes of an overlap, so
the rule hardly ever applies there. Of the 41 YOLO cut points, 40 change the majority GT id: they
are real swaps.

### What changed (`courtcam/identity.py`)

- `jersey_labels` also marks each sample "clear" when no other tracklet's box covers more than
  `JERSEY_MAX_COVER = 0.5` of its torso rectangle.
- In `split_switches` / `_runs`, a changed run where most samples are not clear counts as
  short. It joins its neighbours, so no cut is made there.
- The cut position and the ≥ 1 s rule are unchanged. The `JERSEY_MIN_AGREE` gate still reads
  all samples, so Kennesaw (0.80) is still never cut.
- `merge_groups` is unchanged. It already links only equal team labels. The cross-team player
  existed only because a false piece carried the wrong label.

### Results, M1 (players, MOTA / IDF1 / ID switches)

| clip | GT detector before → after | YOLO before → after |
|---|---|---|
| basketball half s7 | 0.989 / 0.995 / 3 → **1.000 / 1.000 / 0** | 0.627 / 0.366 / 119, unchanged |
| basketball half s11 | 0.951 / 0.925 / 9 → **1.000 / 1.000 / 0** | 0.669 / 0.326 / 125, unchanged |
| basketball full s7 | 0.990 / 0.995 / 2 → **1.000 / 1.000 / 0** | 0.422 / 0.263 / 158, unchanged |
| pickleball s7 / s11 | 1.000 / 1.000 / 0, unchanged | 0.979 / 0.990 / 0 and 0.985 / 0.993 / 0, unchanged |
| badminton s7 / s11 | 1.000 / 1.000 / 0, unchanged | 0.994 / 0.997 / 0 and 0.989 / 0.995 / 0, unchanged |
| volleyball s7 / s11 | 1.000 / 1.000 / 0, unchanged | 0.906 / 0.785 / 37 and 0.915 / 0.737 / 25, unchanged |

YOLO `players.json` is byte-identical before and after on all three basketball clips. All of
D-70's YOLO IDF1 gain (0.366 / 0.263 / 0.326) is kept.

### Results, M4 rows (9 clips, `eval_synth.py`)

- **GT:** 2 vs 3 points right goes 22/23 → **23/23**. Every other row is identical.
- **YOLO:** every row is identical, including the four rows D-70 cost one shot each: points
  13/21, shooter 7/21, team 18/21, made 10/13.
  - Those losses come from D-70's YOLO identity (its real cuts and links). v3 leaves that
    identity untouched.
  - Getting those rows back means giving back the IDF1 gain. That is the 005cf87 bisect.

### Rule variants (identity stage only, same detections, `sweep.sh`; `variants_identity_only`)

| YOLO IDF1 | D-70 | **v3 (shipped)** | B: run length counts clear samples only | A: drop covered samples |
|---|---|---|---|---|
| half s7 | 0.366 | **0.366** | 0.365 | 0.324 |
| half s11 | 0.326 | **0.326** | 0.326 | 0.326 |
| full s7 | 0.263 | **0.263** | 0.235 | 0.235 |
| dev half s13 | 0.461 | **0.461** | 0.461 | 0.461 |
| dev full s13 | 0.328 | **0.329** | 0.292 | 0.292 |
| dev half s17 | 0.563 | **0.563** | 0.564 | 0.552 |
| dev full s17 | 0.242 | **0.242** | 0.235 | 0.238 |

- **GT detector, all 7 clips:** D-70 scores 0.925-0.998 with 0-9 switches. All three variants
  score 1.000 with 0 switches.
- **Why A and B lose:** they drop true YOLO swaps whose new run is only just ≥ 1 s and has a
  few covered samples (2 on full s7).
- **Order tried:** A then B on the M1 seeds, then v3. Dev seeds 13 / 17 confirm the choice.
- **Cover threshold:** 0.3 / 0.5 / 0.7 were tried for A and B (console only, not kept). At 0.7,
  GT full s7 stays at 0.998.

Run notes:

- The first "before" run of `basketball_half_s7_yolo` used an intermediate identity.py: I
  synced it into the copy while the run was going. It was redone with 81e1e99's file
  (`_m/redo_before.sh`, `_v2/`).
- The volleyball s11 GT "before" run may also have picked that file up. Net sports never reach
  the jersey code, and its numbers match 9b777bb.

Commands (box copy of `git archive 81e1e99`; `eval_tracking_v3/run.sh` lists every step):

```bash
mkdir -p _m && cp docs/evidence/M4/eval/* docs/evidence/M1/eval_tracking_v2/* docs/evidence/M1/eval_tracking_v3/* _m/
for s in gen gt yolo mot; do bash _m/run_metrics.sh $s; done      # before (81e1e99 identity.py)
bash _m/sweep.sh ...                                               # variants, see run.sh
mv _m/out _m/out_before                                            # then install the v3 identity.py
for s in gt yolo mot; do bash _m/run_metrics.sh $s; done          # after (+ s11 mot, see run.sh)
python _m/make_v3.py _m/out_before _m/out _m/sw > docs/evidence/M1/metrics_tracking_v3.json
bash _m/diag_all.sh   # diag_cut.py -> eval_tracking_v3/diag/<clip>_{gt,yolo}.cuts.jsonl
```
