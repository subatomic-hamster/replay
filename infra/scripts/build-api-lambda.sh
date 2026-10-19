#!/usr/bin/env bash
# Build infra/build/api-lambda.zip: services/api + courtcam and their runtime deps as
# linux/aarch64 CPython 3.12 wheels for the ReplayCloud Lambda (docs/aws-deploy.md).
# Run on hfbox:  source /workspace/wt/replay-env/env.sh && infra/scripts/build-api-lambda.sh
# boto3/botocore/s3transfer are left out: the Lambda python3.12 runtime provides them.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
out=$repo/infra/build
zip=$out/api-lambda.zip
limit=262144000 # Lambda's 250 MiB unzipped limit (function + layers)

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$out" "$work/wheels" "$work/pkg"

# Local projects become pure-python wheels first: --only-binary cannot build them, and
# naming the wheel files (not the project names) keeps PyPI look-alikes out.
python -m pip wheel --quiet --no-deps -w "$work/wheels" "$repo/courtcam" "$repo/services/api"

# Same versions as the tested workspace: every PyPI package pinned from uv.lock.
python - "$repo/uv.lock" >"$work/constraints.txt" <<'PY'
import sys, tomllib
lock = tomllib.load(open(sys.argv[1], "rb"))
for p in lock["package"]:
    if "registry" in p.get("source", {}):
        print(f"{p['name']}=={p['version']}")
PY

# Lambda arm64 runs Amazon Linux 2023 (glibc 2.34): accept manylinux tags up to 2_34.
python -m pip install --quiet --no-compile --target "$work/pkg" -c "$work/constraints.txt" \
  --implementation cp --python-version 3.12 --only-binary=:all: \
  --platform manylinux2014_aarch64 --platform manylinux_2_28_aarch64 \
  --platform manylinux_2_34_aarch64 \
  "$work"/wheels/*.whl

cd "$work/pkg"
rm -rf boto3 boto3-* botocore botocore-* s3transfer s3transfer-* bin
find . -depth -type d \( -name __pycache__ -o -name tests \) -exec rm -rf {} +
find . -name '*.pyc' -delete
test -f replay_api/__init__.py || { echo "replay_api missing from the bundle" >&2; exit 1; }
test -f replay_api/lambda_handler.py || echo "warning: replay_api/lambda_handler.py not found (handler replay_api.lambda_handler.handler)" >&2

size=$(du -sb . | cut -f1)
echo "unzipped: $((size / 1048576)) MiB ($size bytes)"
if ((size > limit)); then
  echo "too big for Lambda: $size > $limit bytes unzipped" >&2
  du -sm ./* | sort -rn | head -15 >&2
  exit 1
fi

rm -f "$zip"
python -m zipfile -c "$zip" .
echo "wrote $zip: $(($(stat -c %s "$zip") / 1048576)) MiB zipped"
