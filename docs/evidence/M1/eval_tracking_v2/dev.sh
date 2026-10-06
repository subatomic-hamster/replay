#!/bin/bash
# Tuning set (not the M1 seeds): basketball half/full, seeds 13 and 17, synthetic.
# usage (from the copy root): bash _m/dev.sh gen | det <tracker yaml names in _m/trk/...>
source /workspace/wt/replay-env/env.sh
exec < /dev/null
d=$(pwd)
export PYTHONPATH=$d/courtcam:$d/services/api
DEV="basketball_half_s13 basketball_full_s13 basketball_half_s17 basketball_full_s17"
step=$1; shift
case $step in
gen)
  for c in $DEV; do
    IFS=_ read -r sport variant seed <<< "$c"
    [ -f _m/synth/$c/clip.mp4 ] && continue
    flock /workspace/wt/replay-env/.cpu.lock python -m courtcam.cli synth --out _m/synth/$c --sport $sport \
      --variant $variant --duration 90 --seed ${seed#s} --voice-dir samples/synthetic/voice 2>&1 | tail -1
  done ;;
det)
  for v in "$@"; do TRACKER=$d/_m/trk/$v.yaml bash _m/trk.sh det _m/v_$v $DEV; done ;;
esac
