#!/bin/bash
# diag_cut.py on GT-detector and YOLO runs (up to identity) of the three M1 basketball clips.
# usage (copy root, after `run_metrics.sh gen`): bash _m/diag_all.sh   -> _m/diag/<clip>_<det>.cuts.jsonl
source /workspace/wt/replay-env/env.sh
exec < /dev/null
d=$(pwd); export PYTHONPATH=$d/courtcam:$d/services/api
mkdir -p _m/diag
for c in basketball_half_s7 basketball_half_s11 basketball_full_s7; do
  flock /workspace/wt/replay-env/.cpu.lock python _m/run_trk.py _m/synth/$c _m/diag/${c}_gt synthetic > /dev/null 2>&1 || echo FAIL $c gt
  flock /workspace/airtools/.gpu.lock timeout 900 python _m/run_trk.py _m/synth/$c _m/diag/${c}_yolo yolo > /dev/null 2>&1 || echo FAIL $c yolo
  for t in gt yolo; do python _m/diag_cut.py _m/synth/$c _m/diag/${c}_$t > _m/diag/${c}_$t.cuts.jsonl; done
done
echo DIAGDONE
