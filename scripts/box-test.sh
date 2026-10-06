#!/usr/bin/env bash
# Runs ON the box (make test): the same checks as .github/workflows/ci.yml, with the
# shared venv instead of `uv sync` and the box's locks. Every step runs; the exit code
# is non-zero if any failed. Usage: box-test.sh <copy dir>
set -uo pipefail
d=${1:?copy dir}
source /workspace/wt/replay-env/env.sh
export PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker
export REPLAY_API_CMD="python -m uvicorn" # the box has no real `uv` for playwright's API
CPU="flock /workspace/wt/replay-env/.cpu.lock"
PW="flock /workspace/wt/replay-env/.pw.lock" # fixed ports 5177/5178/8000: one run box-wide
cd "$d" || exit 1

failed=()
step() {
  local name=$1
  shift
  echo
  echo "=== $name"
  bash -c "$*" || failed+=("$name")
}

step ruff "ruff check courtcam services"
step courtcam "cd courtcam && $CPU python -m pytest -q"
step api "cd services/api && $CPU python -m pytest -q"
step worker "cd services/worker && $CPU python -m pytest -q"
step dag-drift "python -m replay_worker dag | diff - infra/dag.json"
step infra "cd infra && npm ci --no-audit --no-fund >/dev/null && npx tsc --noEmit && npx cdk synth --quiet"
step web-install "cd apps/web && pnpm install --frozen-lockfile >/dev/null"
step tsc "cd apps/web && pnpm exec tsc --noEmit"
step eslint "cd apps/web && pnpm exec eslint ."
step playwright "cd apps/web && $PW pnpm exec playwright test --project=chromium --project=live --workers=4"

echo
if [ ${#failed[@]} -eq 0 ]; then
  echo "ALL GREEN"
else
  echo "FAILED: ${failed[*]}"
  exit 1
fi
