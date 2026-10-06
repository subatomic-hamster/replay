#!/bin/bash
# Tracking v3 measurement, synthetic only (box copy root = `git archive 81e1e99`, samples/real
# symlinked per READY). Writes _m/metrics_tracking_v3.json (= docs/evidence/M1/metrics_tracking_v3.json).
set -e
mkdir -p _m && cp docs/evidence/M4/eval/* docs/evidence/M1/eval_tracking_v2/* docs/evidence/M1/eval_tracking_v3/* _m/
S11="basketball_half_s11 pickleball_doubles_s11 badminton_doubles_s11 volleyball_indoor_s11"
DEV="basketball_half_s13 basketball_full_s13 basketball_half_s17 basketball_full_s17"
mot_s11() {  # run_metrics.sh mot scores the s7 scenes only
  (source /workspace/wt/replay-env/env.sh; export PYTHONPATH=$PWD/courtcam:$PWD/services/api
   for c in $S11; do for t in yolo gt; do
     python -m courtcam.cli eval --gt _m/synth/$c/ground_truth.json --out _m/out/${c}_$t --json _m/out/${c}_$t.mot.json > /dev/null
   done; done)
}
# 1. before: identity.py as at 81e1e99 (save it as _v2/courtcam first: cp -r courtcam _v2/)
for s in gen gt yolo mot; do bash _m/run_metrics.sh $s; done; mot_s11
bash _m/dev.sh gen && bash _m/trk.sh det _m/out $DEV   # dev seeds, YOLO, up to identity
for c in $DEV; do (source /workspace/wt/replay-env/env.sh; PYTHONPATH=$PWD/courtcam:$PWD/services/api \
  flock /workspace/wt/replay-env/.cpu.lock python _m/run_trk.py _m/synth/$c _m/out/${c}_gt synthetic > /dev/null); done
# 2. cut rule variants, identity stage only, on the same detections (v3 identity.py in _v3/courtcam)
for det in gt yolo; do
  for C in "basketball_half_s7 basketball_half_s11 basketball_full_s7" "$DEV"; do
    CLIPS="$C" FIX=_v3 TAG=_d70 VAR=ship bash _m/sweep.sh $det 1.0
    for v in ship weight drop; do CLIPS="$C" FIX=_v3 TAG=_$v VAR=$v bash _m/sweep.sh $det 0.5; done
  done
done
mv _m/out _m/out_before
# 3. after: the copy's courtcam/ = v3 identity.py, same clips, same harness
for s in gt yolo mot; do bash _m/run_metrics.sh $s; done; mot_s11
python _m/make_v3.py _m/out_before _m/out _m/sw > _m/metrics_tracking_v3.json
