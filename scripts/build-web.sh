#!/usr/bin/env bash
# P2.1 web build (Vite + TS + Tailwind v4). Output: app/static/dist/.
#   scripts/build-web.sh            clean build (rm -rf dist, install, build)
#   scripts/build-web.sh --check    build, then fail if app/static/dist/ != git
set -euo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
# The build writes TWO committed artifacts: app/static/dist/ (the chunks) and
# app/static/sw.js (the workbox manifest, whose cache name carries a build
# hash). Checking only dist/ let a stale sw.js through - it is the file the
# service worker actually caches.
CHECKED="app/static/dist/ app/static/sw.js"
if [ "${1:-}" = "--check" ] && ! command -v pnpm >/dev/null 2>&1; then
  # no pnpm here (e.g. the lab): skip the rebuild, only check the working
  # tree's dist/ for uncommitted drift
  cd "$R"
  if ! git diff --exit-code -- $CHECKED; then
    echo "build-web: $CHECKED differs from the committed output — rebuild and commit" >&2
    exit 1
  fi
  echo "build-web: (no pnpm, rebuild skipped) $CHECKED matches committed output"
  exit 0
fi
cd "$R/web"
rm -rf "$R/app/static/dist"
pnpm install --frozen-lockfile
pnpm build
if [ "${1:-}" = "--check" ]; then
  cd "$R"
  if ! git diff --exit-code -- $CHECKED; then
    echo "build-web: $CHECKED differs from the committed output — rebuild and commit" >&2
    exit 1
  fi
  echo "build-web: $CHECKED matches committed output"
fi
