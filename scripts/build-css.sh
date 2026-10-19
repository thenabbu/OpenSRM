#!/usr/bin/env bash
# OpenSRM CSS build (DESIGN §10.1 / §10.16): compiles app/static/app.css
# from app/static/src.css with a PINNED, sha256-verified toolchain.
#   - Tailwind CSS standalone CLI (no npm, no node_modules in the repo or
#     the runtime image: the binary + daisyUI package live in a cache dir)
#   - daisyUI npm tarball extracted as <cache>/node_modules/daisyui so that
#     @plugin "daisyui" resolves by directory walk-up from src.css (a
#     gitignored repo-root node_modules symlink points at the cache while
#     the build runs and is removed on exit)
# Output is COMMITTED; CI runs this script and fails on git diff.
# ponytail: linux-x64 only — add a platform case (mac arm/intel URLs +
# shas) in this same matrix if a non-linux dev appears.
set -euo pipefail

TW_VERSION=4.3.3
TW_SHA256=dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a
TW_URL="https://github.com/tailwindlabs/tailwindcss/releases/download/v${TW_VERSION}/tailwindcss-linux-x64"

DAISY_VERSION=5.7.46
DAISY_SHA256=bc7ec4d7d4a30daebd1f11bbb25f7a96527f818d473aead7679201b34c77590c
DAISY_URL="https://registry.npmjs.org/daisyui/-/daisyui-${DAISY_VERSION}.tgz"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="${OPENSRM_CSS_CACHE:-${HOME}/.cache/opensrm-css-build}"
mkdir -p "$CACHE"
cd "$REPO"

fetch() { # url dest sha256
  if [ ! -f "$2" ]; then
    curl -fsSL --retry 3 -o "$2" "$1"
  fi
  if ! echo "$3  $2" | sha256sum -c - >/dev/null 2>&1; then
    rm -f "$2"
    echo "build-css: sha256 mismatch for $2 (refusing to build)" >&2
    exit 1
  fi
}

fetch "$TW_URL" "$CACHE/tailwindcss-${TW_VERSION}" "$TW_SHA256"
chmod +x "$CACHE/tailwindcss-${TW_VERSION}"
fetch "$DAISY_URL" "$CACHE/daisyui-${DAISY_VERSION}.tgz" "$DAISY_SHA256"
if [ ! -d "$CACHE/node_modules/daisyui" ]; then
  mkdir -p "$CACHE/node_modules"
  rm -rf "$CACHE/node_modules/package"
  tar xzf "$CACHE/daisyui-${DAISY_VERSION}.tgz" -C "$CACHE/node_modules"
  mv "$CACHE/node_modules/package" "$CACHE/node_modules/daisyui"
fi

rm -f node_modules
ln -s "$CACHE/node_modules" node_modules
trap 'rm -f "$REPO/node_modules"' EXIT

"$CACHE/tailwindcss-${TW_VERSION}" -i app/static/src.css -o app/static/app.css --minify

GZ=$(gzip -c app/static/app.css | wc -c)
echo "build-css: app/static/app.css $(wc -c < app/static/app.css) bytes, ${GZ} gzipped"
if [ "$GZ" -gt 36864 ]; then
  echo "build-css: gzip size ${GZ} exceeds the 35 KB budget (36864 B)" >&2
  exit 1
fi
