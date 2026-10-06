#!/bin/bash
# Identity-only reruns of finished runs with another jersey-cut rule, scored with courtcam eval.
# usage (copy root): FIX=<code tree> TAG=_<variant> VAR=<ship|weight|drop> [SRC=_m/out] [CLIPS=...] \
#                    bash _m/sweep.sh <det: gt|yolo> <cover...>
#   -> _m/sw/<clip>_<det>_<variant>_c<cover>.mot.json   (ident_cover.py; synthetic only)
source /workspace/wt/replay-env/env.sh
exec < /dev/null
d=$(pwd); det=$1; shift
export PYTHONPATH=$d/${FIX:-.}/courtcam:$d/services/api
CL=${CLIPS:-"basketball_half_s7 basketball_half_s11 basketball_full_s7"}
SRC=${SRC:-_m/out}
mkdir -p _m/sw
for c in $CL; do for cv in "$@"; do
  o=_m/sw/${c}_${det}${TAG}_c$cv
  python _m/ident_cover.py $SRC/${c}_$det $o $cv $VAR \
    && python -m courtcam.cli eval --gt _m/synth/$c/ground_truth.json --out $o --json $o.mot.json > /dev/null \
    || echo "FAIL $c $cv"
  rm -rf "${o:?}"
done; done
