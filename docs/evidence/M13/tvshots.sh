#!/usr/bin/env bash
# M13 evidence: the TV app's evidence specs against a hard-linked COPY of the make-demo games
# (the specs post a phone tap and an export; the demo data itself stays untouched).
# usage on hfbox: tvshots.sh <copy dir>   (after `make demo` built <copy>/data/demo)
set -uo pipefail
d=${1:?copy dir}
source /workspace/wt/replay-env/env.sh
export PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker:$d/render
export REPLAY_MODEL_VENVS=/workspace/wt/replay-env/venvs REPLAY_MODEL_DEVICE=cpu HF_HUB_OFFLINE=1
ev=$d/data/m13/ev
rm -rf "$ev" && mkdir -p "$ev/data/games" "$ev/shots"
cp -al "$d/data/demo/games/." "$ev/data/games/"
export REPLAY_CACHE_DIR=$d/data/demo/cache
cd "$d" || exit 1
REPLAY_DATA_DIR=$ev/data REPLAY_PIPELINE=worker python -m uvicorn replay_api.main:app \
  --host 127.0.0.1 --port 8091 >"$ev/api.log" 2>&1 &
api=$!
trap 'kill $api' EXIT
for _ in $(seq 30); do curl -sf http://127.0.0.1:8091/games >/dev/null && break; sleep 1; done
cd apps/tv || exit 1
flock /workspace/wt/replay-env/.pw.lock env REPLAY_TV_API=http://localhost:8091 \
  REPLAY_TV_EVIDENCE_DIR="$ev/shots" REPLAY_TV_EVIDENCE_GAME=g_demo_basketball \
  REPLAY_TV_EVIDENCE_NET_GAME=g_demo_pickleball \
  pnpm exec playwright test --project=evidence --workers=1 2>&1 | tail -40
ls -la "$ev/shots"
