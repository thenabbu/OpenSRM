#!/bin/bash
# gates.sh — the ONE local pre-push bar.
#
# VERDICT RULE (do not weaken): the last line is
#   GATES GREEN                              -> exit 0, a push is safe
#   GATES GREEN (PARTIAL: <what>) - not a push bar -> exit 3
#   GATES RED - fix the failures above …     -> exit 1
# Anything skipped downgrades the verdict. A run that skipped the browser suites
# has not proven the push is safe, and must not say that it has.
#
# Usage:
#   bash scripts/gates.sh              # full bar: lint + static + unit + e2e
#   bash scripts/gates.sh --fast       # lint + static only (~20 s)
#   bash scripts/gates.sh --list       # the run set AND the CI_ONLY table
#   bash scripts/gates.sh test_sw ...  # lint + static + only the named suites
#
# Env:
#   VENV   interpreter (default .venv). A worktree has none:
#          VENV=/opt/data/opensrm-repo/.venv
#   PLAYWRIGHT_BROWSERS_PATH  required for the e2e set; absent -> PARTIAL
#   SKIP_E2E=1               skip browsers deliberately -> PARTIAL
set -uo pipefail
cd "$(dirname "$0")/.."

V=${VENV:-.venv}
FAIL=0
SKIPPED=""

# uv/uvx are not on the default PATH in the hermes container; find them anyway.
for d in /opt/data/home/.local/bin "$HOME/.local/bin" /usr/local/bin; do
  [ -x "$d/uv" ] && PATH="$d:$PATH"
done
export PATH

# Suites that exist but are NOT in CI, with the reason. Any suite listed here is
# excluded from the parity check and from D9 in check_docs.py.
# Format: name|reason
read -r -d '' CI_ONLY <<'CIEOF'
DOCKER_BUILDKIT=1 docker build -t opensrm:ci .|needs a docker daemon and a multi-minute build; CI does this on every PR
bash scripts/ci_docker_smoke.sh|needs the image built above; CI job "docker"
uv sync --frozen --extra browser|CI runner setup, not a gate; locally the venv already exists
.venv/bin/playwright install --only-shell chromium|CI runner setup; locally set PLAYWRIGHT_BROWSERS_PATH instead
scope_ui_smoke (inside the CI docker job)|needs the built image
CIEOF
LOCAL_ONLY="test_login_guide_server|7 real portal logins per run; portal caps 10/hour/IP"

# The verdict. Called from every exit path so no path can print GREEN after a skip.
finish() {
  rm -f /tmp/gate-$$.log /tmp/u-$$.log /tmp/ruff-$$.log /tmp/lock-$$.log \
        /tmp/css-$$.log /tmp/e2e-$$.log /tmp/e-$$.log 2>/dev/null
  if [ $FAIL -ne 0 ]; then
    printf '\n== GATES RED - fix the failures above; this is not a push bar\n'; exit 1
  fi
  if [ -n "$SKIPPED" ]; then
    printf '\n== GATES GREEN (PARTIAL: %s) - not a push bar\n' "$SKIPPED"; exit 3
  fi
  printf '\n== GATES GREEN - push is safe\n'; exit 0
}

step() { printf '\n== %s\n' "$*"; }
ok()   { printf '   PASS  %s\n' "$*"; }
bad()  { printf '   FAIL  %s\n' "$*"; FAIL=1; }
skip() { printf '   SKIP  %s\n' "$*"; SKIPPED="${SKIPPED}${SKIPPED:+, }$1"; }

# The suites CI runs through one shared gunicorn, read out of tests.yml.
e2e_suites() {
  sed -n '/scripts\/ci_e2e_http.sh/,/^$/p' .github/workflows/tests.yml \
    | grep -oE '\btest_[a-z_0-9]+' | grep -v ci_e2e | sort -u
}
unit_suites() {
  sed -n '/^  unit:/,/^  docker:/p' .github/workflows/tests.yml \
    | grep -oE 'tests/unit/test_[a-z_0-9]+\.py' | sort -u
}

if [ "${1:-}" = "--list" ]; then
  echo "== run set (derived from .github/workflows/tests.yml)"
  echo "-- lint"
  echo "  uv run --locked ruff check app/"
  echo "  uv run --locked actionlint"
  echo "  uv lock --check"
  echo "  bash scripts/build-css.sh  + git diff --exit-code app/static/app.css"
  echo "-- static gates"
  echo "  scripts/check_architecture.py"
  echo "  scripts/check_docs.py"
  echo "  bash scripts/ci_promtool.sh"
  echo "  python3 scripts/build_dashboard.py --check"
  echo "-- unit suites"
  unit_suites | sed 's/^/  /'
  echo "-- e2e suites (via scripts/ci_e2e_http.sh)"
  e2e_suites | sed 's/^/  /'
  echo "  tests/e2e/test_dash_fit.py        (self-booting)"
  echo "  tests/e2e/test_dut_official_tt.py (self-booting)"
  echo "  bash tests/e2e/run_push_duts.sh   (boots 18185-18187 itself)"
  echo
  echo "== CI_ONLY (CI runs it, gates.sh cannot — with the reason)"
  printf '%s\n' "$CI_ONLY" | sed 's/^/  /'
  echo
  echo "== LOCAL_ONLY (exists on disk, deliberately not in CI)"
  printf '%s\n' "$LOCAL_ONLY" | sed 's/^/  /'
  exit 0
fi

if [ "${1:-}" = "--fast" ]; then FAST=1; shift; else FAST=""; fi

# --- 1. Lint (mirrors lint.yml) -------------------------------------------
step "lint (== CI Lint job)"
if uv run --locked --quiet ruff check app/ >/tmp/ruff-$$.log 2>&1; then ok "ruff check app/"; else
  bad "ruff check app/"; sed -n '1,40p' /tmp/ruff-$$.log | sed 's/^/         /'
fi
if uv run --locked --quiet actionlint >/tmp/al-$$.log 2>&1; then ok "actionlint (workflow syntax)"; else
  bad "actionlint"; sed -n '1,20p' /tmp/al-$$.log | sed 's/^/         /'
fi
if uv lock --check >/tmp/lock-$$.log 2>&1; then ok "uv lock --check"; else
  bad "uv lock --check (run: uv lock)"; sed -n '1,10p' /tmp/lock-$$.log | sed 's/^/         /'
fi
if bash scripts/build-css.sh >/tmp/css-$$.log 2>&1 && git diff --quiet app/static/app.css; then
  ok "committed app.css is current"
else
  bad "app.css stale (run scripts/build-css.sh, commit app/static/app.css)"
  sed -n '1,20p' /tmp/css-$$.log | sed 's/^/         /'
fi

# --- 2. Static gates -------------------------------------------------------
step "static gates"
run_step() { local n=$1; shift; if "$@" >/tmp/gate-$$.log 2>&1; then ok "$n"; else
  bad "$n"; sed -n '1,40p' /tmp/gate-$$.log | sed 's/^/         /'; fi; }
run_step "architecture DAG (check_architecture.py)" env PYTHONPATH=. "$V/bin/python" scripts/check_architecture.py
run_step "doc consistency (check_docs.py)"          env PYTHONPATH=. "$V/bin/python" scripts/check_docs.py
if command -v docker >/dev/null 2>&1; then
  run_step "promtool (observability config + rules)" bash scripts/ci_promtool.sh
else
  skip "promtool (no docker)"
fi
run_step "dashboard JSON is current (build_dashboard.py --check)" python3 scripts/build_dashboard.py --check

[ -n "$FAST" ] && { finish; }

# --- 3. Unit suites (every one CI runs) ------------------------------------
step "unit suites (== CI Tests/unit job)"
if [ $# -gt 0 ]; then SUITES="$*"; else SUITES=$(unit_suites); fi
for f in $SUITES; do
  # PYTHONPATH=. for EVERY suite: a harmless superset. Deriving it per-suite
  # from tests.yml is the alternative, but then a new suite that needs it and
  # forgets to declare it fails locally and passes in CI — the worst split.
  env PYTHONPATH=. DATA_DIR="$(mktemp -d)" "$V/bin/python" "$f" >/tmp/u-$$.log 2>&1
  if [ $? -eq 0 ]; then ok "$(basename "$f")"; else
    bad "$(basename "$f")"; tail -12 /tmp/u-$$.log | sed 's/^/         /'
  fi
done

# --- 4. Browser DUTs -------------------------------------------------------
if [ -n "${SKIP_E2E:-}" ]; then
  skip "e2e (SKIP_E2E=1)"
elif [ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ]; then
  skip "e2e (PLAYWRIGHT_BROWSERS_PATH unset)"
elif [ $# -gt 0 ]; then
  skip "e2e (named-suite run)"
else
  step "e2e browser suites (== CI Tests/e2e job)"
  DATA_DIR="$(mktemp -d)" PORT=18177 VENV="$V" bash scripts/ci_e2e_http.sh $(e2e_suites) \
    >/tmp/e2e-$$.log 2>&1 && ok "ci_e2e_http.sh ($(e2e_suites | wc -l) suites)" || {
    bad "ci_e2e_http.sh"; tail -25 /tmp/e2e-$$.log | sed 's/^/         /'; }
  for s in test_dash_fit test_dut_official_tt; do
    env DATA_DIR="$(mktemp -d)" "$V/bin/python" "tests/e2e/$s.py" >/tmp/e-$$.log 2>&1 \
      && ok "$s" || { bad "$s"; tail -12 /tmp/e-$$.log | sed 's/^/         /'; }
  done
  if command -v docker >/dev/null 2>&1; then
    run_step "push DUTs (run_push_duts.sh)" env VENV="$V" bash tests/e2e/run_push_duts.sh
  else
    skip "push DUTs (no docker)"
  fi
fi

finish
