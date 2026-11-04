#!/usr/bin/env bash
# Create the tags + GitHub Releases that were never made.
#
# Every commit that touched VERSION is a release point (this repo bumps the
# trio in the release commit). Tags only exist up to v1.27.2, so everything
# after it has no Release at all - this walks history, keeps the LAST commit
# that set each version (a version can be written then corrected), skips tags
# that already exist, and publishes oldest-first so each Release's notes range
# is the previous version's tag.
#
# Idempotent: existing tags and Releases are left untouched.
# Usage: scripts/backfill_releases.sh [--dry-run]
set -euo pipefail
DRY="${1:-}"
command -v gh >/dev/null || { echo "gh not on PATH" >&2; exit 1; }

repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

# version -> sha of the LAST commit that set it. Conflict-marker junk is skipped
# (VERSION was once committed with merge markers in it; a tag named that breaks CI).
git log --format='%H' -- VERSION | while read -r sha; do
  ver="$(git show "$sha:VERSION" 2>/dev/null | head -1 | tr -d '[:space:]')"
  [[ "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || continue
  printf '%s %s\n' "$sha" "$ver"
done | awk '!seen[$2]++ { print }' | sort -k2 -V > /tmp/release_points.txt

total=$(wc -l < /tmp/release_points.txt)
echo "release points: $total"
n=0
prev=""
while read -r sha ver; do
  tag="v$ver"
  n=$((n+1))
  if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    echo "[$n/$total] $tag tag exists - skip"
  elif [ "$DRY" = "--dry-run" ]; then
    echo "[$n/$total] $tag would be created at ${sha:0:8} (from ${prev:-<none>})"
  else
    body="$(python3 scripts/release_notes.py --from "${prev:-$(git rev-list --max-parents=0 HEAD | tail -1)}" \
              --to "$sha" --title "$tag")"
    gh release create "$tag" --repo "$repo" --target "$sha" \
       --title "$tag" --notes "$body" >/dev/null
    # The next iteration's range starts at this tag, so it must exist in THIS
    # clone too — gh creates it remotely only. Skipping this fetch makes the
    # second iteration die on "unknown revision vX..sha".
    git fetch --tags --quiet origin
    echo "[$n/$total] $tag created at ${sha:0:8}"
  fi
  prev="$tag"
done < /tmp/release_points.txt

echo "latest release: $(gh release view --repo "$repo" --json tagName -q .tagName)"

# gh release create re-marks "latest" on EVERY creation, so a backfill running
# oldest->newest leaves an OLD tag flagged latest (observed: /releases/latest
# returned v2.10.0 while v2.11.0 was published). Re-mark the true newest.
if [ "$DRY" != "--dry-run" ]; then
  newest="$(git tag -l 'v*' | sort -V | tail -1)"
  [ -n "$newest" ] && gh release edit "$newest" --repo "$repo" --latest >/dev/null 2>&1 \
    && echo "marked $newest as latest"
fi
