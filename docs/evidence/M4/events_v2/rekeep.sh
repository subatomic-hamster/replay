#!/bin/bash
# Re-run events -> triggers -> plays (../eval/rerun.py keep) with <code_root>'s courtcam on a
# finished run, optionally with profile overrides, then the copy's own ../eval/eval_synth.py.
# usage: bash _m/rekeep.sh <code_root> <src_out_dir> <src_tag> <clips_dir> <tag> [k.f=v ...] -- clips...
#   e.g. bash _m/rekeep.sh _old/v3 _m/bis v2_gt _m/synth v3_gt_no1t rally.one_touch=false -- badminton_doubles_s7
source /workspace/wt/replay-env/env.sh
exec < /dev/null
d=$(pwd)
code=$1; src=$2; stag=$3; S=$4; tag=$5; shift 5
ovr=()
while [ $# -gt 0 ] && [ "$1" != "--" ]; do ovr+=("$1"); shift; done
shift
O=_m/bis; mkdir -p $O
for c in "$@"; do
  out=$O/${c}_$tag
  PYTHONPATH=$code/courtcam:$code/services/api flock /workspace/wt/replay-env/.cpu.lock python _m/rerun.py $src/${c}_$stag $out keep "${ovr[@]}" > $out.times.json 2> $out.log || { echo "FAIL $c"; tail -3 $out.log; continue; }
  PYTHONPATH=$d/courtcam:$d/services/api python _m/eval_synth.py $S/$c $out > $out.eval.json 2>> $out.log || echo "EVALFAIL $c"
  echo "done $tag $c"
done
