#!/usr/bin/env bash
# ci_wait.sh — wait for a commit's CI checks by POLLING, not by sleeping blind.
# Replaces the `sleep 90 && curl .../actions/runs` pattern (111 sleep call sites,
# ~49 min of pure blocking wait across the audit window).
#
# Usage:  bash scripts/ci_wait.sh [sha] [timeout_s] [interval_s]
#   sha      default: HEAD
#   timeout  default: 900
#   interval default: 15 (exponential up to 60)
# Exit: 0 all green · 1 a check failed · 2 timeout · 3 no checks found
set -u
GH=${GH:-/opt/data/home/bin/gh}
sha=${1:-$(git rev-parse HEAD)}
timeout_s=${2:-900}
interval=${3:-15}
REPO=${REPO:-thenabbu/OpenSRM}

start=$(date +%s)
while :; do
  out=$("$GH" pr checks "$sha" --repo "$REPO" 2>/dev/null || true)
  if [ -z "$out" ]; then
    # no PR for this sha: fall back to the push run on main
    state=$("$GH" run list --repo "$REPO" --commit "$sha" --limit 1 \
            --json status,conclusion --jq '.[0] | "\(.status) \(.conclusion)"' 2>/dev/null || true)
    case "$state" in
      "completed success") echo "GREEN  $sha (push run)"; exit 0;;
      "completed "* )      echo "FAILED $sha -> $state"; exit 1;;
      "")                  echo "no checks for $sha yet"; sleep "$interval";;
      *)                   echo "  waiting: $state"; sleep "$interval";;
    esac
  else
    if printf '%s' "$out" | grep -qE '\bfail\b|\bpending\b'; then
      if printf '%s' "$out" | grep -qE '\bfail\b'; then
        echo "FAILED $sha:"; printf '%s\n' "$out" | grep -E '\bfail\b'
        exit 1
      fi
      echo "  pending: $(printf '%s' "$out" | grep -cE '\bpending\b') check(s)"
      sleep "$interval"
    else
      echo "GREEN  $sha:"; printf '%s\n' "$out" | head -8; exit 0
    fi
  fi
  now=$(date +%s)
  if [ $((now - start)) -ge "$timeout_s" ]; then
    echo "TIMEOUT after ${timeout_s}s waiting on $sha"; exit 2
  fi
  # widen the interval; a failing curl once cost a whole chain
  [ "$interval" -lt 60 ] && interval=$((interval + 15))
done
