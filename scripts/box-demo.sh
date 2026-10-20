#!/usr/bin/env bash
# Runs ON the box (`make demo`). Builds the demo games from generated SYNTHETIC footage
# through the worker, then serves the API + the TV web app + the phone companion.
#
#   box-demo.sh <copy dir> build    generate + process (cached: a re-run is all hits)
#   box-demo.sh <copy dir> serve    API :8090, TV web app :5190, phone companion :5191
#   box-demo.sh <copy dir> stop     stop the servers
#
# Deterministic by construction: seeded synthetic clips, the synthetic detector and
# ground-truth poses, template commentary (no LLM). Generative parts and their fallbacks:
#   TTS narration  Kokoro on the CPU if $REPLAY_MODEL_VENVS/tts exists, else captions only
#   search index   SigLIP on the CPU if $REPLAY_MODEL_VENVS/emb exists, else none (the TV
#                  falls back to the labelled keyword search)
#   SAM masks      SAM 2.1 on the GPU (box GPU lock); DEMO_FAKE_SEGMENT=1 = ellipse masks
#   Tier C lift    MotionBERT if $REPLAY_MODEL_VENVS/lift exists (GPU), else analytic
# Data + cache live in $DEMO_DIR (default <copy>/data/demo); delete it to start cold.
set -euo pipefail
d=$(cd "${1:?copy dir}" && pwd)
cmd=${2:-build}
source /workspace/wt/replay-env/env.sh
export PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker:$d/render
DEMO=${DEMO_DIR:-$d/data/demo}
export REPLAY_CACHE_DIR=$DEMO/cache REPLAY_DATA_DIR=$DEMO
export REPLAY_MODEL_VENVS=${REPLAY_MODEL_VENVS:-/workspace/wt/replay-env/venvs}
export REPLAY_MODEL_DEVICE=${REPLAY_MODEL_DEVICE:-cpu} # no GPU lock for TTS / embeddings
export HF_HUB_OFFLINE=1 # in-process SAM 2.1: use the box cache, never download
API_PORT=${DEMO_API_PORT:-8090}
TV_PORT=${DEMO_TV_PORT:-5190}
WEB_PORT=${DEMO_WEB_PORT:-5191}
TMUX_NAME=${DEMO_TMUX:-replay-demo}
BB=g_demo_basketball
PB=g_demo_pickleball
cd "$d"

phase() { printf '\n=== %s (%s)\n' "$1" "$(date +%T)"; }
secs() { echo $(($(date +%s) - $1))s; }

# Heavy CPU job: the shared CPU lock. The worker takes the GPU lock itself, per GPU task.
# Prints how long it waited for the lock, so wall times can be read net of other users.
worker() {
  T0=$(date +%s) flock /workspace/wt/replay-env/.cpu.lock bash -c \
    'echo "cpu lock wait $(($(date +%s) - T0))s"; exec python -m replay_worker run "$@"' \
    _ "$@" --detector synthetic
}

synth() { # <dir> <args...>: generate once; the clip is the cache key of everything after
  local out=$1
  shift
  [ -f "$out/clip.mp4" ] || python -m courtcam.cli synth --out "$out" "$@" >/dev/null
  sha256sum "$out/clip.mp4" | cut -c1-16
}

build() {
  avail=$(free -g | awk '/^Mem:/ {print $7}')
  if [ "$avail" -lt 8 ]; then echo "only ${avail} GB RAM available (< 8): try later" >&2; exit 1; fi
  mkdir -p "$DEMO/src" "$DEMO/games"
  # One build per demo dir: a re-run (e.g. after the laptop's ssh dropped while the
  # nohup'd build kept going) waits for it, then finds everything cached.
  exec 9>"$DEMO/.build.lock"
  flock -n 9 || { echo "another build of $DEMO is running; waiting for it"; flock 9; }
  t_all=$(date +%s)
  local sets=(--set highlights_n=3)
  [ "${DEMO_FAKE_SEGMENT:-0}" = 1 ] && sets+=(--set segment_fake=1)
  local tts=0 search=0
  [ -x "$REPLAY_MODEL_VENVS/tts/bin/python" ] && tts=1
  [ -x "$REPLAY_MODEL_VENVS/emb/bin/python" ] && [ "${DEMO_SEARCH:-1}" = 1 ] && search=1
  [ $tts = 1 ] || sets+=(--set commentary_tts=)
  echo "narration: $([ $tts = 1 ] && echo 'Kokoro TTS (cpu)' || echo 'captions only')," \
    "search index: $([ $search = 1 ] && echo 'SigLIP (cpu)' || echo 'none (keyword fallback)')"

  phase "synthetic footage"
  t=$(date +%s)
  echo "basketball clip sha256 $(synth "$DEMO/src/bb" --sport basketball --variant full \
    --duration 60 --seed 11 --size 1920x1080)"
  echo "pickleball clip sha256 $(synth "$DEMO/src/pb" --sport pickleball --variant doubles \
    --duration 60 --seed 11 --size 1920x1080)"
  echo "synth $(secs $t)"

  phase "basketball: pipeline, commentary, hype, Tier A/B/C replays$([ $search = 1 ] && echo ', search')"
  t=$(date +%s)
  # --stages names targets (their upstream runs too), so the redesigned TV's seek previews,
  # moment thumbs and hero art (storyboard, moments) are named explicitly.
  local stages=commentary,hype,director,tierc_manifest,storyboard,moments
  [ $search = 1 ] && stages+=,search_index
  worker "$DEMO/src/bb/clip.mp4" \
    --out "$DEMO/games/$BB" --game-id $BB --title "SYNTHETIC basketball (demo)" \
    --stages $stages "${sets[@]}"
  echo "basketball pass 1 $(secs $t)"

  phase "basketball: 9:16 export of the top highlight, broadcast rendition with narration"
  t=$(date +%s)
  python "$d/scripts/demo_vertical_spec.py" "$DEMO/games/$BB"
  local narr=()
  [ -f "$DEMO/games/$BB/commentary/narration.wav" ] &&
    narr=(--set "narration=$DEMO/games/$BB/commentary/narration.wav")
  worker "$DEMO/src/bb/clip.mp4" \
    --out "$DEMO/games/$BB" --game-id $BB --title "SYNTHETIC basketball (demo)" \
    --stages broadcast,vertical "${sets[@]}" "${narr[@]}"
  echo "basketball pass 2 $(secs $t)"

  phase "pickleball: pipeline, hype, condensed game + rally browser"
  t=$(date +%s)
  worker "$DEMO/src/pb/clip.mp4" \
    --out "$DEMO/games/$PB" --game-id $PB --title "SYNTHETIC pickleball doubles (demo)" \
    --sport pickleball --variant doubles --stages hype,condensed,storyboard,moments "${sets[@]}"
  echo "pickleball $(secs $t)"

  phase "summary"
  ls "$DEMO/games/$BB/replays"/*/manifest.json | sed "s|$DEMO/||"
  du -sh "$DEMO/games" "$DEMO/cache"
  echo "BUILD DONE in $(secs $t_all)"
}

serve() {
  stop_servers
  [ -d apps/tv/node_modules ] || (cd apps/tv && pnpm install --frozen-lockfile >/dev/null)
  [ -d apps/web/node_modules ] || (cd apps/web && pnpm install --frozen-lockfile >/dev/null)
  local base=http://localhost:$API_PORT
  # The first `tmux new-session` on the box starts the tmux server, whose global environment
  # is then copied into every later session of every agent. Keep the demo's variables in this
  # session only (-e), never in the server's global environment.
  local v keep=() strip=()
  for v in PYTHONPATH REPLAY_CACHE_DIR REPLAY_DATA_DIR REPLAY_MODEL_VENVS REPLAY_MODEL_DEVICE \
    HF_HUB_OFFLINE DEMO_TMUX DEMO_DIR DEMO_API_PORT DEMO_TV_PORT DEMO_WEB_PORT REPLAY_WORKER_STAGES; do
    strip+=(-u "$v")
    [ -n "${!v+x}" ] && keep+=(-e "$v=${!v}")
  done
  tmux() { env "${strip[@]}" tmux "$@"; }
  # Each window sources env.sh itself: the server's global PATH has neither the venv's python
  # (the API ran on /opt/venv's) nor the env's pnpm (corepack then prompts to download one).
  local sh="source /workspace/wt/replay-env/env.sh &&"
  # The phone pages the TV's QR codes open (Add game's /u/<id>, On your phone's /p/<id>)
  # are on the phone companion server; override for a phone that cannot reach 127.0.0.1.
  local web=${REPLAY_PUBLIC_WEB_BASE:-http://127.0.0.1:$WEB_PORT}
  tmux new-session -d -s "$TMUX_NAME" "${keep[@]}" -n api \
    "$sh cd $d && REPLAY_PIPELINE=worker REPLAY_PUBLIC_WEB_BASE=$web python -m uvicorn replay_api.main:app --host 127.0.0.1 --port $API_PORT 2>&1 | tee $DEMO/api.log"
  tmux new-window -t "$TMUX_NAME" -n tv \
    "$sh cd $d/apps/tv && VITE_REPLAY_API_BASE=$base pnpm exec vite --host 127.0.0.1 --port $TV_PORT --strictPort 2>&1 | tee $DEMO/tv.log"
  tmux new-window -t "$TMUX_NAME" -n phone \
    "$sh cd $d/apps/web && VITE_REPLAY_API_BASE=$base pnpm exec vite --host 127.0.0.1 --port $WEB_PORT --strictPort 2>&1 | tee $DEMO/phone.log"
  for _ in $(seq 60); do
    curl -sf "$base/games" >/dev/null && curl -sf "http://127.0.0.1:$TV_PORT/" >/dev/null &&
      curl -sf "http://127.0.0.1:$WEB_PORT/" >/dev/null && break
    sleep 1
  done
  echo "library: $(curl -sf "$base/games" | python -c 'import json,sys; print([(g["id"], g["status"]) for g in json.load(sys.stdin)])')"
  echo "SERVING in tmux '$TMUX_NAME': API :$API_PORT  TV :$TV_PORT/  phone :$WEB_PORT/companion"
}

stop_servers() { tmux kill-session -t "$TMUX_NAME" 2>/dev/null || true; }

case $cmd in
build) build ;;
serve) serve ;;
stop) stop_servers ;;
*) echo "usage: box-demo.sh <copy dir> build|serve|stop" >&2 && exit 2 ;;
esac
