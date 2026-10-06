#!/usr/bin/env bash
# Runs ON the box (`make record-e2e`): the recorded end-to-end run of the product.
#   1. builds the `make demo` games (box-demo.sh build; cached after the first run)
#   2. generates a 20 s SYNTHETIC half-court clip to upload (courtcam synth, seeded)
#   3. serves the real API (REPLAY_PIPELINE=worker) + TV web build + phone companion
#   4. runs the `recording` Playwright project (apps/tv/e2e-recording), video on
#   5. composites TV + phone + captions into $OUT/replay-e2e-full.mp4 and a <= 25 MB copy
# Usage: record-e2e.sh <copy dir>. Exit code = the Playwright run's (beats can fail).
set -uo pipefail
d=$(cd "${1:?copy dir}" && pwd)
source /workspace/wt/replay-env/env.sh
export PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker:$d/render
DEMO=${DEMO_DIR:-$d/data/demo}
OUT=${REC_OUT:-$d/out}
SRC=$d/data/recording-src
# The run changes what it serves (an upload, a phone-tap clip, a trim, a review answer, a
# profile and its link), so it serves a fresh copy of the demo games, with an empty worker
# cache: the uploaded clip's pipeline run is cold every time.
REC=$d/data/recording
export DEMO_API_PORT=${DEMO_API_PORT:-8093} DEMO_TV_PORT=${DEMO_TV_PORT:-5193} DEMO_WEB_PORT=${DEMO_WEB_PORT:-5194}
export DEMO_TMUX=${DEMO_TMUX:-replay-recording-serve}
API=http://localhost:$DEMO_API_PORT
CPU="flock /workspace/wt/replay-env/.cpu.lock"
PW="flock /workspace/wt/replay-env/.pw.lock"
cd "$d" || exit 1

DEMO_DIR=$DEMO bash scripts/box-demo.sh "$d" build || exit 1

[ -f "$SRC/clip.mp4" ] || $CPU python -m courtcam.cli synth --out "$SRC" --sport basketball \
  --variant half --duration 20 --seed 7 --size 1280x720 >/dev/null || exit 1

rm -rf "$REC" "$OUT" && mkdir -p "$REC/games" "$OUT"
cp -a "$DEMO"/games/g_demo_* "$REC/games/"
DEMO_DIR=$REC bash scripts/box-demo.sh "$d" serve || exit 1
(
  cd apps/tv && [ -d node_modules ] || pnpm install --frozen-lockfile --offline >/dev/null
  # CPU lock for the whole run: the upload is processed by the real pipeline inside the API.
  $PW $CPU env REPLAY_REC_API=$API REPLAY_REC_TV=http://127.0.0.1:$DEMO_TV_PORT \
    REPLAY_REC_PHONE=http://127.0.0.1:$DEMO_WEB_PORT REPLAY_REC_CLIP="$SRC/clip.mp4" \
    REPLAY_REC_LANDMARKS="$SRC/landmarks.json" REPLAY_REC_OUT="$OUT" \
    pnpm exec playwright test --project=recording --workers=1 2>&1 | tee "$OUT/playwright.log"
)
rc=$? # pipefail: playwright's, not tee's
bash scripts/box-demo.sh "$d" stop

$CPU python scripts/record_e2e_compose.py "$OUT/beats.json" "$OUT/replay-e2e-full.mp4" \
  "$OUT/replay-e2e.mp4" | tee "$OUT/beats.md"
echo "playwright: $([ "$rc" = 0 ] && echo PASS || echo FAIL) · $OUT/replay-e2e-full.mp4 · $OUT/replay-e2e.mp4"
exit "$rc"
