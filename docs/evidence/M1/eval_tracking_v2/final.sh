#!/bin/bash
# Before vs after on the same detections, synthetic only.
#   before: bash _m/trk.sh det _m/base <M1 clips> with identity at HEAD 005cf87 (dev clips:
#           bash _m/dev.sh det base -> _m/v_base, _m/trk/base.yaml = courtcam/botsort.yaml)
#   after : identity re-run on copies of those outputs with this tree
# Scored with courtcam eval and summed by agg.py into _m/metrics_tracking_v2.json
# (= docs/evidence/M1/metrics_tracking_v2.json).
source /workspace/wt/replay-env/env.sh
M1="basketball_half_s7 basketball_full_s7 pickleball_doubles_s7 badminton_doubles_s7 volleyball_indoor_s7 basketball_half_s11 pickleball_doubles_s11 badminton_doubles_s11 volleyball_indoor_s11"
DEV="basketball_half_s13 basketball_full_s13 basketball_half_s17 basketball_full_s17"
mkdir -p _m/after
for c in $M1; do
  rm -rf "_m/after/${c}_yolo"
  cp -r _m/base/${c}_yolo _m/after/
done
for c in $DEV; do
  [ -d _m/base/${c}_yolo ] || cp -r _m/v_base/${c}_yolo _m/base/
  rm -rf "_m/after/${c}_yolo"
  cp -r _m/v_base/${c}_yolo _m/after/
done
flock /workspace/wt/replay-env/.cpu.lock bash _m/trk.sh ident _m/after $M1 $DEV
bash _m/trk.sh mot _m/after $M1 $DEV
bash _m/trk.sh mot _m/base $M1 $DEV
rm -rf "_m/v2"
mkdir -p _m/v2
for c in $M1 $DEV; do
  cp _m/base/${c}_yolo.mot.json _m/v2/${c}_before.mot.json
  cp _m/after/${c}_yolo.mot.json _m/v2/${c}_after.mot.json
done
python _m/agg.py _m/v2 > _m/metrics_tracking_v2.json
