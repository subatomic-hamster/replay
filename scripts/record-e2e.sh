#!/usr/bin/env bash
# Runs ON the box (`make record-e2e`): the recorded end-to-end run of the product.
#   1. builds the `make demo` games (box-demo.sh build; cached after the first run)
#   2. generates a 20 s SYNTHETIC half-court clip to upload (courtcam synth, seeded)
#   3. serves the real API (REPLAY_PIPELINE=worker) + TV web build + phone companion
#   4. runs the `recording` Playwright project (apps/tv/e2e-recording), video on
#   5. composites TV + phone + captions into $OUT/replay-e2e-full.mp4 and a <= 25 MB copy
# Usage: record-e2e.sh <copy dir>. Exit code = the Playwright run's (beats can fail).
#
# REC_REAL=basketball|volleyball (`make record-e2e-real`): the same run on REAL footage,
# LOCAL ONLY (D-7; the volleyball clip is CC BY but shows minors, D-76). No demo games: the
# upload is a 90 s cut of a samples/real clip, calibrated by hand from its tracked
# landmarks.json, and the API runs the worker with the opt-in replay + 2.5D scene stages
# (REPLAY_WORKER_STAGES) so the TV beats can open Free view on it. Output: $d/out-real-<sport>.
set -uo pipefail
d=$(cd "${1:?copy dir}" && pwd)
source /workspace/wt/replay-env/env.sh
export PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker:$d/render
REAL=${REC_REAL:-}
DEMO=${DEMO_DIR:-$d/data/demo}
OUT=${REC_OUT:-$d/out${REAL:+-real-$REAL}}
SRC=$d/data/recording-src${REAL:+-$REAL}
# The run changes what it serves (an upload, a phone-tap clip, a trim, a review answer, a
# profile and its link), so it serves a fresh copy of the demo games, with an empty worker
# cache: the uploaded clip's pipeline run is cold every time.
REC=$d/data/recording${REAL:+-$REAL}
export DEMO_API_PORT=${DEMO_API_PORT:-8093} DEMO_TV_PORT=${DEMO_TV_PORT:-5193} DEMO_WEB_PORT=${DEMO_WEB_PORT:-5194}
export DEMO_TMUX=${DEMO_TMUX:-replay-recording-serve}
API=http://localhost:$DEMO_API_PORT
CPU="flock /workspace/wt/replay-env/.cpu.lock"
PW="flock /workspace/wt/replay-env/.pw.lock"
cd "$d" || exit 1

TITLE="Replay — recorded end-to-end test"
CAVEAT="SYNTHETIC footage only  ·  TV = react-native-web build of apps/tv in Chrome, NOT a Fire TV  ·  real services/api + worker pipeline on hfbox, no mocks"
if [ -n "$REAL" ]; then
  # <samples/real clip> <start s> <length s> per sport: 90 s of live play, re-encoded to H.264
  case $REAL in
  basketball) clip=basketball_kennesawwide_240s ss=130 ;;
  volleyball) clip=volleyball_westwashington_240s ss=0 ;;
  *) echo "REC_REAL must be basketball or volleyball" >&2 && exit 2 ;;
  esac
  len=90
  mkdir -p "$SRC"
  [ -f "$SRC/clip.mp4" ] || $CPU ffmpeg -v error -y -ss $ss -t $len -i "samples/real/$clip.mp4" \
    -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart \
    "$SRC/clip.mp4" || exit 1
  cp "samples/real/$clip.landmarks.json" "$SRC/landmarks.json" || exit 1
  export REPLAY_WORKER_STAGES=${REPLAY_WORKER_STAGES:-hype,replays,scene}
  LABEL="${len} s of REAL $clip (t ${ss}–$((ss + len)) s)"
  TITLE="Replay — recorded end-to-end test on REAL $REAL footage"
  local_rule="local test only (D-7)"
  [ "$REAL" = volleyball ] && local_rule="local test only (D-76: CC BY, but minors — never published)"
  CAVEAT="REAL footage — $local_rule  ·  TV = react-native-web build in Chrome, NOT a Fire TV  ·  real API + worker (YOLO) on hfbox"
else
  DEMO_DIR=$DEMO bash scripts/box-demo.sh "$d" build || exit 1
  [ -f "$SRC/clip.mp4" ] || $CPU python -m courtcam.cli synth --out "$SRC" --sport basketball \
    --variant half --duration 20 --seed 7 --size 1280x720 >/dev/null || exit 1
fi

rm -rf "$REC" "$OUT" && mkdir -p "$REC/games" "$OUT"
[ -n "$REAL" ] || cp -a "$DEMO"/games/g_demo_* "$REC/games/"
DEMO_DIR=$REC bash scripts/box-demo.sh "$d" serve || exit 1
(
  cd apps/tv && [ -d node_modules ] || pnpm install --frozen-lockfile --offline >/dev/null
  # CPU lock for the whole run: the upload is processed by the real pipeline inside the API.
  $PW $CPU env REPLAY_REC_API=$API REPLAY_REC_TV=http://127.0.0.1:$DEMO_TV_PORT \
    REPLAY_REC_PHONE=http://127.0.0.1:$DEMO_WEB_PORT REPLAY_REC_CLIP="$SRC/clip.mp4" \
    REPLAY_REC_LANDMARKS="$SRC/landmarks.json" REPLAY_REC_OUT="$OUT" \
    REPLAY_REC_REAL=${REAL:+1} REPLAY_REC_SPORT=${REAL:-basketball} REPLAY_REC_CLIP_LABEL="${LABEL:-}" \
    pnpm exec playwright test --project=recording --workers=1 2>&1 | tee "$OUT/playwright.log"
)
rc=$? # pipefail: playwright's, not tee's
bash scripts/box-demo.sh "$d" stop
# the worker's per-task log of the upload (stage wall times for the README)
[ -n "$REAL" ] && cp "$REC"/games/g_*/_work/worker.jsonl "$OUT/" 2>/dev/null

$CPU python scripts/record_e2e_compose.py "$OUT/beats.json" "$OUT/replay-e2e-full.mp4" \
  "$OUT/replay-e2e.mp4" --title "$TITLE" --caveat "$CAVEAT" | tee "$OUT/beats.md"
echo "playwright: $([ "$rc" = 0 ] && echo PASS || echo FAIL) · $OUT/replay-e2e-full.mp4 · $OUT/replay-e2e.mp4"
exit "$rc"
