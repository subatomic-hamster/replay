#!/bin/bash
# Full pipeline (../eval/run1.py) with ANOTHER code tree's courtcam, then the copy's own
# ../eval/eval_synth.py (fixed harness). Synthetic clips only.
# setup (box, copy root): mkdir -p _m && cp docs/evidence/M4/eval/* docs/evidence/M4/events_v2/* _m/
#   bash _m/run_metrics.sh gen                       # the 9 clips -> _m/synth
#   git archive <commit> courtcam services/api | tar -x -C _old/<name>   (code trees, read-only git)
# usage: bash _m/bisect.sh <code_root> <clips_dir> <tag> <detector> <pose> [clips...]
#   -> _m/bis/<clip>_<tag>{,.eval.json,.log,.times.json}
source /workspace/wt/replay-env/env.sh
exec < /dev/null
d=$(pwd)
code=$1; S=$2; tag=$3; det=$4; pose=$5; shift 5
export HF_HOME=/workspace/wt/replay-env/hf HF_HUB_OFFLINE=1
export COURTCAM_POSE_MODEL=/workspace/wt/replay-env/models/yolo/yolo11m-pose.pt
O=_m/bis; mkdir -p $O
CLIPS=${*:-"basketball_half_s7 basketball_half_s11 basketball_full_s7 badminton_doubles_s7 badminton_doubles_s11 pickleball_doubles_s7 pickleball_doubles_s11 volleyball_indoor_s7 volleyball_indoor_s11"}
lock=/workspace/wt/replay-env/.cpu.lock
[ "$det" = yolo ] && lock=/workspace/airtools/.gpu.lock
for c in $CLIPS; do
  out=$O/${c}_$tag; rm -rf "${out:?}"
  PYTHONPATH=$code/courtcam:$code/services/api flock $lock timeout 900 python _m/run1.py $S/$c $out $det $pose > $out.times.json 2> $out.log || { echo "FAIL $c"; tail -3 $out.log; continue; }
  PYTHONPATH=$d/courtcam:$d/services/api python _m/eval_synth.py $S/$c $out > $out.eval.json 2>> $out.log || echo "EVALFAIL $c"
  echo "done $tag $c"
done
