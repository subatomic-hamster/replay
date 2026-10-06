#!/usr/bin/env bash
# Runs ON the box (make demo): the synthetic sample through the worker. A second run with
# nothing changed is all cache hits. Usage: box-demo.sh <copy dir> <game id>
set -euo pipefail
d=${1:?copy dir}
game=${2:-g_synth_basketball_half}
source /workspace/wt/replay-env/env.sh
export PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker
cd "$d"
sample=samples/synthetic/basketball_half

avail=$(free -g | awk '/^Mem:/ {print $7}')
if [ "$avail" -lt 8 ]; then echo "only ${avail} GB RAM available (< 8): try later" >&2; exit 1; fi

# Heavy CPU job: take the shared CPU lock. The worker takes the GPU lock itself, per GPU task.
flock /workspace/wt/replay-env/.cpu.lock \
  python -m replay_worker run "$sample/clip.mp4" \
    --out "data/games/$game" --game-id "$game" \
    --title "Synthetic half court (generated)" --detector synthetic
python -m replay_worker status "data/games/$game"
