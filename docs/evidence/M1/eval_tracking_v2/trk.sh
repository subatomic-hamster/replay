#!/bin/bash
# Tracking-only variant of docs/evidence/M4/eval/run_metrics.sh (yolo + mot steps), synthetic only.
# setup: mkdir -p _m && cp docs/evidence/M4/eval/*.py docs/evidence/M1/eval_tracking_v2/* _m/
#        then `bash _m/run_metrics.sh gen` (M1 clips) and `bash _m/dev.sh gen` (dev clips)
# usage (from the copy root): bash _m/trk.sh <step> <outdir> [clips...]
#   det   : YOLO detect + track + court + identity (run_trk.py), GPU lock
#   ident : re-run the identity stage only, on an existing det output in <outdir>
#   mot   : courtcam eval (CLEAR-MOT / IDF1) -> <outdir>/<clip>_yolo.mot.json
#   diag  : diag.py per clip
source /workspace/wt/replay-env/env.sh
exec < /dev/null
d=$(pwd)
export PYTHONPATH=$d/courtcam:$d/services/api
step=$1 O=$2; shift 2
CLIPS=${*:-"basketball_half_s7 basketball_full_s7 pickleball_doubles_s7 badminton_doubles_s7 volleyball_indoor_s7"}
S=_m/synth
mkdir -p $O
for c in $CLIPS; do
  out=$O/${c}_yolo
  case $step in
  det)   rm -rf "${out:?}"; flock /workspace/airtools/.gpu.lock timeout 900 python _m/run_trk.py $S/$c $out yolo > $out.times.json 2> $out.log || { echo "FAIL $c"; tail -3 $out.log; } ;;
  ident) python _m/run_trk.py $S/$c $out yolo identity > $out.times.json 2> $out.log || { echo "FAIL $c"; tail -3 $out.log; } ;;
  mot)   python -m courtcam.cli eval --gt $S/$c/ground_truth.json --out $out --json $out.mot.json > /dev/null || echo "MOTFAIL $c" ;;
  diag)  python _m/diag.py $S/$c $out ;;
  esac
done
