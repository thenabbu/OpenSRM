#!/bin/bash
# gates.sh — the ONE local pre-push bar. If this exits 0, a push is safe.
#
# AGENTS.md points here instead of listing every suite; the suite list itself is
# derived from tests.yml (see --list), so adding a CI suite never leaves this
# script behind again.
#
# Usage:
#   bash scripts/gates.sh              # full bar: lint + static gates + unit + e2e
#   bash scripts/gates.sh --fast       # lint + static gates only (~15 s)
#   bash scripts/gates.sh --list       # print the suites it would run, exit
#   bash scripts/gates.sh test_sw ...  # lint + static + only the named suites
#
# Env:
#   VENV   interpreter to use (default .venv). Worktrees have no venv:
#          VENV=/opt/data/opensrm-repo/.venv
#   SKIP_E2E=1  skip the browser suites (they need playwright + a browser)
set -uo pipefail
cd "$(dirname "$0")/.."

V=${VENV:-.venv}
FAIL=0
# uv/uvx are not on the default PATH in the hermes container; find them anyway.
for d in /opt/data/home/.local/bin "$HOME/.local/bin" /usr/local/bin; do
  [ -x "$d/uv" ] && PATH="$d:$PATH"
done
export PATH
step() { printf '\n== %s\n' "$*"; }
ok()   { printf '   PASS  %s\n' "$*"; }
bad()  { printf '   FAIL  %s\n' "$*"; FAIL=1; }
run_step() {                       # name, then the command
  local name=$1; shift
  if "$@" >/tmp/gate-$$.log 2>&1; then ok "$name"; else
    bad "$name"; sed -n '1,40p' /tmp/gate-$$.log | sed 's/^/         /'
  fi
}

# The e2e suites CI runs, read out of tests.yml — never a second hand-kept list.
e2e_suites() {
  sed -n '/bash scripts\/ci_e2e_http.sh/,/:eof\|^$/p' .github/workflows/tests.yml \
    | grep -oE 'test_[a-z_0-9]+' | sort -u
}

if [ "${1:-}" = "--list" ]; then
  echo "unit suites (from tests.yml):"
  grep -oE 'tests/unit/test_[a-z_0-9]+\.py' .github/workflows/tests.yml | sort -u | sed 's/^/  /'
  echo
  echo "e2e suites (from tests.yml):"
  e2e_suites | sed 's/^/  /'
  exit 0
fi

if [ "${1:-}" = "--fast" ]; then FAST=1; shift; else FAST=""; fi

# --- 1. Lint (mirrors lint.yml) -------------------------------------------
step "lint (== CI Lint job)"
if command -v uvx >/dev/null && uvx --quiet ruff check app/ >/tmp/ruff-$$.log 2>&1; then
  ok "ruff check app/"
else
  bad "ruff check app/"; sed -n '1,40p' /tmp/ruff-$$.log 2>/dev/null | sed 's/^/         /'
fi
if uv lock --check >/tmp/lock-$$.log 2>&1; then ok "uv lock --check"; else
  bad "uv lock --check (run: uv lock)"; sed -n '1,10p' /tmp/lock-$$.log | sed 's/^/         /'
fi
# app.css is committed; a stale build can never ship.
if bash scripts/build-css.sh >/tmp/css-$$.log 2>&1 && git diff --quiet app/static/app.css; then
  ok "committed app.css is current"
else
  bad "app.css stale (run scripts/build-css.sh and commit app/static/app.css)"
  sed -n '1,20p' /tmp/css-$$.log | sed 's/^/         /'
fi

# --- 2. Static gates (cheap, no server) -----------------------------------
step "static gates"
run_step "architecture DAG (check_architecture.py)" \
  env PYTHONPATH=. "$V/bin/python" scripts/check_architecture.py
run_step "doc consistency (check_docs.py)" \
  env PYTHONPATH=. "$V/bin/python" scripts/check_docs.py

[ -n "$FAST" ] && { printf '\n== fast mode: stopping before unit suites\n'; exit $FAIL; }

# --- 3. Unit suites (every one CI runs) -----------------------------------
step "unit suites (== CI Tests/unit job)"
if [ $# -gt 0 ]; then SUITES="$*"; else
  SUITES=$(grep -oE 'tests/unit/test_[a-z_0-9]+\.py' .github/workflows/tests.yml | sort -u)
fi
for f in $SUITES; do
  case "$f" in
    *test_scope_client*|*test_scope_academics*|*test_scope_campus*|\
    *test_scope_fees*|*test_scope_profile*|*test_hourwise_join*)
      env PYTHONPATH=. DATA_DIR="$(mktemp -d)" "$V/bin/python" "$f" >/tmp/u-$$.log 2>&1 ;;
    *) env DATA_DIR="$(mktemp -d)" "$V/bin/python" "$f" >/tmp/u-$$.log 2>&1 ;;
  esac
  rc=$?
  if [ $rc -eq 0 ]; then ok "$(basename "$f")"; else
    bad "$(basename "$f")"; tail -12 /tmp/u-$$.log | sed 's/^/         /'
  fi
done

# --- 4. Browser DUTs ------------------------------------------------------
if [ -z "${SKIP_E2E:-}" ] && [ $# -eq 0 ]; then
  step "e2e browser suites (== CI Tests/e2e job)"
  if [ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ]; then
    echo "   SKIP  PLAYWRIGHT_BROWSERS_PATH unset — export it to run browser suites"
  else
    DATA_DIR="$(mktemp -d)" PORT=18177 VENV="$V" bash scripts/ci_e2e_http.sh $(e2e_suites) \
      >/tmp/e2e-$$.log 2>&1 && ok "ci_e2e_http.sh ($(e2e_suites | wc -l) suites)" || {
      bad "ci_e2e_http.sh"; tail -25 /tmp/e2e-$$.log | sed 's/^/         /'; }
  fi
fi

printf '\n== %s\n' "$([ $FAIL -eq 0 ] && echo 'GATES GREEN — push is safe' || echo 'GATES RED — fix the failures above')"
rm -f /tmp/gate-$$.log /tmp/u-$$.log /tmp/ruff-$$.log /tmp/lock-$$.log /tmp/css-$$.log /tmp/e2e-$$.log
exit $FAIL
