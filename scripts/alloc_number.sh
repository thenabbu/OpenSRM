#!/usr/bin/env bash
# alloc_number.sh — ask the REMOTE what number is next, never guess locally.
# Usage: bash scripts/alloc_number.sh [--no-fetch]
#
# Why: a branch that reads VERSION / max(migration) from its own stale base
# always answers "the next number" correctly and always collides. The only
# answer that is not stale is one read from every ref that actually exists.
set -u
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "not inside a git repo" >&2; exit 2; }
cd "$ROOT" || exit 2
[ "${1:-}" = "--no-fetch" ] || git fetch origin --prune --tags -q 2>/dev/null || true

main_v=$(git show origin/main:VERSION 2>/dev/null | tr -d '[:space:]')
# every VERSION any live ref carries, so we skip numbers already taken on branches
taken=$(for ref in $(git for-each-ref --format='%(refname:short)' refs/heads refs/remotes/origin 2>/dev/null); do
          while IFS= read -r line; do
            printf '%s\n' "$(printf '%s' "$line" | sed 's/[[:space:]]//g')"
          done < <(git show "$ref:VERSION" 2>/dev/null)
        done | grep -E '^[0-9]+\.[0-9]+' | sort -uV | tr '\n' ' ')

mig_max=$(git show origin/main:app/migrations.py 2>/dev/null \
          | grep -oE '@migration\(version=[0-9]+' | grep -oE '[0-9]+$' | sort -n | tail -1)
mig_max=${mig_max:-0}

printf 'main VERSION      : %s\n' "${main_v:-<missing>}"
printf 'VERSIONs in flight: %s\n' "${taken:-<none>}"
printf 'main max migration: %s\n' "$mig_max"
printf 'next migration    : %s\n' "$((mig_max + 1))"
printf '\nRelease numbers are allocated ON MAIN by the chore(release) PR — a feature\n'
printf 'branch must NOT edit VERSION/pyproject/uv.lock. State `bump: minor|patch`\n'
printf 'in the PR body instead.\n'
