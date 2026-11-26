#!/usr/bin/env bash
# P4.1: install + typecheck + unit tests + production build on the laptop.
# Run from the repo ROOT (script lives in scripts/):  bash scripts/p41-laptop.sh
#
# Install: the lockfile goes stale whenever package.json changes (it is
# regenerated and copied back to the worktree), and pnpm 12 refuses an install
# while a dependency with a build script (vitest -> esbuild) is unapproved —
# hence the approve step. Both are installer plumbing, not app behaviour.
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
cd "$R/web"
rm -rf node_modules pnpm-lock.yaml
if ! pnpm install --no-frozen-lockfile >/tmp/p41-install.log 2>&1; then
  grep -q ERR_PNPM_IGNORED_BUILDS /tmp/p41-install.log && pnpm approve-builds esbuild >>/tmp/p41-install.log 2>&1
  pnpm install --no-frozen-lockfile >>/tmp/p41-install.log 2>&1 || { tail -30 /tmp/p41-install.log; exit 1; }
fi
echo "== tsc =="
./node_modules/.bin/tsc --noEmit || exit 1
echo "== vitest =="
./node_modules/.bin/vitest run 2>&1 | tail -30
echo "== build =="
pnpm build 2>&1 | tail -25
echo "== gzip sizes =="
cd "$R/app/static/dist"
for f in assets/*; do
  printf '%-38s raw=%7d gzip=%6d\n' "$(basename "$f")" "$(stat -c%s "$f")" "$(gzip -9c "$f" | wc -c)"
done
