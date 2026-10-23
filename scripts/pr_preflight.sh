#!/usr/bin/env bash
# pr_preflight.sh — read-only pre-merge checks for OpenSRM.
# Usage: bash scripts/pr_preflight.sh [--no-fetch]
# Runs from anywhere inside the checkout. Writes nothing (fetch updates remote refs only).
set -u

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "not inside a git repo"; exit 2; }
cd "$ROOT" || exit 2
FETCH=1
[ "${1:-}" = "--no-fetch" ] && FETCH=0
PY=python3
[ -x /opt/data/opensrm-repo/.venv/bin/python ] && PY=/opt/data/opensrm-repo/.venv/bin/python

PASS_N=0 FAIL_N=0
res() { # res PASS|FAIL <name> <detail>
  printf '[%s] %-14s %s\n' "$1" "$2" "$3"
  if [ "$1" = PASS ]; then PASS_N=$((PASS_N + 1)); else FAIL_N=$((FAIL_N + 1)); fi
}

# ---- 1. freshness: origin/main must already be in HEAD (read the TEXT, not just $?)
[ "$FETCH" = 1 ] && git fetch origin --prune >/dev/null 2>&1
OUT=$(git merge-base --is-ancestor origin/main HEAD 2>&1); ST=$?
if [ "$ST" -eq 0 ]; then
  res PASS freshness "origin/main is an ancestor of HEAD"
elif printf '%s' "$OUT" | grep -qi fatal; then
  res FAIL freshness "merge-base error: $OUT"
else
  BEHIND=$(git log --oneline "$(git merge-base origin/main HEAD)"..origin/main | head -5)
  res FAIL freshness "main moved — merge it into the branch first:"$'\n'"$(printf '%s\n' "$BEHIND" | sed 's/^/    /')"
fi

# ---- 2. conflict preflight: real merge in a temp tree, no working-tree touch
MT=$(git merge-tree --write-tree --name-only HEAD origin/main 2>&1); ST=$?
case $ST in
  0) res PASS conflicts "merge-tree clean (tree $(printf '%s' "$MT" | head -1))" ;;
  1) FILES=$(printf '%s\n' "$MT" | awk 'NR > 1 && !NF {exit} NR > 1 {print}' | sed 's/^/    /')
     res FAIL conflicts "merge-tree exit 1 — conflicted files:"$'\n'"$FILES" ;;
  *) res FAIL conflicts "merge-tree error (exit $ST): $MT" ;;
esac

# ---- 3. duplicate @migration(version=N) in the registry
# (^ anchor: the module docstring's usage example contains a literal
#  " "@migration(version=15" that must not count as a registry entry)
DUP=$(grep -ohE '^@migration\(version=[0-9]+' app/migrations.py | sort | uniq -c \
      | awk '$1 > 1 {print $2 " x" $1}')
if [ -z "$DUP" ]; then
  res PASS migrations "no duplicate migration version ($(grep -c '^@migration(version=' app/migrations.py) decorators)"
else
  res FAIL migrations "duplicate migration versions (renumber to the next free N):"$'\n'"$(printf '%s\n' "$DUP" | sed 's/^/    /')"
fi

# ---- 4. version: trio equality (VERSION/pyproject/uv.lock) + number race across refs
CUR=$(tr -d '[:space:]' < VERSION)
PYV=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)
LOCKV=$(grep -A1 '^name = "opensrm"' uv.lock | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)
if [ "$CUR" = "$PYV" ] && [ "$CUR" = "$LOCKV" ]; then
  res PASS version-trio "VERSION = pyproject = uv.lock = $CUR"
else
  res FAIL version-trio "trio out of sync: VERSION=$CUR pyproject=$PYV uv.lock=$LOCKV"
fi

RACE=""
for sha in $(git log --all -S"$CUR" --format=%H -- VERSION); do
  git merge-base --is-ancestor "$sha" origin/main 2>/dev/null && continue
  who=$(git branch -a --contains "$sha" 2>/dev/null | tr -d ' *+' | grep -v '^origin/main$' | head -1)
  RACE="${RACE}    $sha ${who:-<detached>}"$'\n'
done
if [ -z "$RACE" ]; then
  res PASS version-race "no non-main ref carries $CUR in VERSION"
else
  res FAIL version-race "other refs already touched VERSION at $CUR — reuse that number, don't invent one:"$'\n'"$RACE"
fi

# ---- 5. sw.js cache name vs README (reuse tests/unit/test_audit_findings.py, checks L37 + D58)
V76=$("$PY" tests/unit/test_audit_findings.py 2>&1)
L37=$(printf '%s\n' "$V76" | grep -E '^L37' | head -1)
D58=$(printf '%s\n' "$V76" | grep -E '^D58' | head -1)
CACHE=$(grep -oE 'opensrm-v[0-9]+' app/static/sw.js | head -1)
if [ -n "$L37" ] && [ -n "$D58" ] \
   && printf '%s\n%s\n' "$L37" "$D58" | grep -q 'PASS' \
   && ! printf '%s\n%s\n' "$L37" "$D58" | grep -q 'FAIL'; then
  res PASS sw-cache "L37 + D58 pass (sw.js CACHE_NAME=$CACHE)"
else
  res FAIL sw-cache "test_audit_findings L37/D58 not both PASS:"$'\n'"$(printf '%s\n%s\n' "$L37" "$D58" | sed 's/^/    /')"
fi

printf '\npreflight: %d passed, %d failed\n' "$PASS_N" "$FAIL_N"
[ "$FAIL_N" -eq 0 ]
