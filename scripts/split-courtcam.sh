#!/usr/bin/env bash
# Publish courtcam/ (MIT) as its own repository with its history (Open Source challenge).
#
#   scripts/split-courtcam.sh <remote-url> [branch]       # e.g. git@github.com:<you>/courtcam.git
#
# What it does:
#   1. refuses unless the work tree is clean (the split reads committed history only);
#   2. `git subtree split --prefix courtcam -b courtcam-split` — a branch whose root is
#      courtcam/ and whose commits are every commit that touched courtcam/, rewritten;
#   3. pushes that branch to <remote-url> as <branch> (default main).
# Re-running later appends new courtcam commits (the split is deterministic), so the
# public repo can be refreshed with the same command. Nothing in this repo changes
# except the local `courtcam-split` branch.
#
# Before the first push, check (D-4 / preamble licensing rules):
#   - courtcam/LICENSE is MIT and courtcam/README.md stands alone (no replay-only paths);
#   - no weights, footage, or research-licensed code under courtcam/ (docs/licenses.md);
#   - courtcam/pyproject.toml has no workspace-only sources.
set -euo pipefail
remote=${1:?usage: $0 <remote-url> [branch]}
branch=${2:-main}
cd "$(git rev-parse --show-toplevel)"

if [ -n "$(git status --porcelain -- courtcam)" ]; then
  echo "courtcam/ has uncommitted changes; commit or stash first" >&2
  exit 1
fi
test -f courtcam/LICENSE || { echo "courtcam/LICENSE missing" >&2; exit 1; }

git subtree split --prefix courtcam -b courtcam-split
git push "$remote" "courtcam-split:$branch"
echo "pushed courtcam-split -> $remote $branch"
