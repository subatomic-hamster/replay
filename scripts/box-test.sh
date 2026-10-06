#!/usr/bin/env bash
# Runs ON the box (make test): the same checks as .github/workflows/ci.yml, with the
# shared venv instead of `uv sync` and the box's locks. Every step runs; the exit code
# is non-zero if any failed. Usage: box-test.sh <copy dir>
set -uo pipefail
d=${1:?copy dir}
source /workspace/wt/replay-env/env.sh
export PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker:$d/render
export REPLAY_API_CMD="python -m uvicorn" # the box has no real `uv` for playwright's API
CPU="flock /workspace/wt/replay-env/.cpu.lock"
PW="flock /workspace/wt/replay-env/.pw.lock" # fixed ports 5177/5178/8000: one run box-wide
cd "$d" || exit 1

# Playwright's `reuseExistingServer` silently tests whatever already listens on a dev-server
# port (a stale vite from another copy once held 5181 for 3 h). Run this INSIDE the pw lock,
# right before playwright: fails, naming the port and the owning PID, if a port is taken.
# Never kills anything. Ports are read from the playwright config (the non-opt-in ones).
# Reads /proc/net/tcp{,6} (no ss/lsof on the box); on a runner the ports are simply free.
cfg_ports() { grep -hoE "^const (PORT|LIVE_PORT|API_PORT) = [0-9]+" "$1" | grep -oE "[0-9]+$" | tr '\n' ' '; }
port_guard() {
  local p ino pid rc=0
  for p in "$@"; do
    ino=$(awk -v h=$(printf ':%04X$' "$p") '$4 == "0A" && $2 ~ h {print $10; exit}' /proc/net/tcp /proc/net/tcp6 2>/dev/null)
    [ -n "$ino" ] || continue
    pid=$(find /proc/[0-9]*/fd -lname "socket:\[$ino\]" 2>/dev/null | head -1 | cut -d/ -f3)
    echo "PORT GUARD: port $p is already in use (owner pid ${pid:-unknown, not readable}): $(tr '\0' ' ' </proc/${pid:-0}/cmdline 2>/dev/null | cut -c1-120)" >&2
    echo "  Playwright would reuse that server and test someone else's code. Stop it yourself; not killing." >&2
    rc=1
  done
  return $rc
}
export -f port_guard

failed=()
step() {
  local name=$1
  shift
  echo
  echo "=== $name"
  bash -c "$*" || failed+=("$name")
}

step ruff "ruff check courtcam services render"
step courtcam "cd courtcam && $CPU python -m pytest -q"
step api "cd services/api && $CPU python -m pytest -q"
step worker "cd services/worker && $CPU python -m pytest -q"
step render "cd render && $CPU python -m pytest -q"
step dag-drift "python -m replay_worker dag | diff - infra/dag.json"
step infra "cd infra && npm ci --no-audit --no-fund >/dev/null && npx tsc --noEmit && npx cdk synth --quiet"
step web-install "cd apps/web && pnpm install --frozen-lockfile >/dev/null"
step tsc "cd apps/web && pnpm exec tsc --noEmit"
step eslint "cd apps/web && pnpm exec eslint ."
step playwright "cd apps/web && $PW bash -c 'port_guard $(cfg_ports apps/web/playwright.config.ts) && pnpm exec playwright test --project=chromium --project=live --workers=4'"
# apps/tv has its own pnpm workspace, lockfile and react-native-video patch
step tv-install "cd apps/tv && pnpm install --frozen-lockfile --offline >/dev/null"
step tv-tsc "cd apps/tv && pnpm exec tsc --noEmit"
step tv-eslint "cd apps/tv && pnpm exec eslint ."
# shaders + SceneMath of the native scene view (needs glslangValidator and the Gradle cache's Kotlin)
step scene-check 'if command -v glslangValidator >/dev/null; then source /workspace/wt/replay-env/android/env.sh && bash apps/tv/android/scene-check.sh; else echo "skipped: glslangValidator not installed"; fi'
step tv-playwright "cd apps/tv && $PW bash -c 'port_guard $(cfg_ports apps/tv/playwright.config.ts) && pnpm exec playwright test --project=tv'"

echo
if [ ${#failed[@]} -eq 0 ]; then
  echo "ALL GREEN"
else
  echo "FAILED: ${failed[*]}"
  exit 1
fi
