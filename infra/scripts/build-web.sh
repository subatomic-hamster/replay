#!/usr/bin/env bash
# Build both web frontends for ReplayCloud (docs/aws-deploy.md):
#   apps/web          -> infra/build/web    (served at /)
#   apps/tv (web)     -> infra/build/tvapp  (served at /tvapp/, VITE_BASE=/tvapp/)
# Usage (hfbox):  source /workspace/wt/replay-env/env.sh && infra/scripts/build-web.sh [API_BASE]
# API_BASE (the stack's ApiUrl) is baked as VITE_REPLAY_API_BASE when given. Either way the
# deploy writes /config.json and /tvapp/config.json with {"apiBase": ApiUrl}.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
out=$repo/infra/build
api=${1:-}

# The bundles are public: never bake a key or the mock API into them.
unset VITE_REPLAY_API_KEY VITE_MOCK_API
if [[ -n $api ]]; then export VITE_REPLAY_API_BASE=${api%/}; else unset VITE_REPLAY_API_BASE; fi

mkdir -p "$out"
(
  cd "$repo/apps/web"
  pnpm install --frozen-lockfile
  pnpm exec vite build --outDir "$out/web" --emptyOutDir
)
(
  cd "$repo/apps/tv"
  pnpm install --frozen-lockfile
  VITE_BASE=/tvapp/ pnpm exec vite build --base /tvapp/ --outDir "$out/tvapp" --emptyOutDir
)
for d in web tvapp; do
  test -f "$out/$d/index.html" || { echo "no index.html in $out/$d" >&2; exit 1; }
  echo "$out/$d: $(du -sh "$out/$d" | cut -f1)"
done
