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
bash scripts/ci_upgrade_smoke.sh|needs BOTH images (a published release + the one built above); CI job "docker"
bash scripts/deploy_gated.sh|touches LIVE prod (snapshot, recreate, rollback) and runs on the lab, never a runner
uv sync --frozen --extra browser|CI runner setup, not a gate; locally the venv already exists
.venv/bin/playwright install --only-shell chromium|CI runner setup; locally set PLAYWRIGHT_BROWSERS_PATH instead
scope_ui_smoke (inside the CI docker job)|needs the built image
corepack enable && corepack prepare pnpm@9.15.9 --activate|CI runner setup (installs the pinned pnpm toolchain); locally pnpm is already on PATH or the web/ step SKIPs
bash scripts/build-web.sh --check|a full pnpm rebuild of web/ to prove the committed dist came from this source; CI does it once on the runner, and locally the tree you are testing IS the tree you are about to commit
scripts/vision_verify.py|needs GEMINI_API_KEY (a repository secret) and 18 vision calls; the local bar must not require a cloud key. Run it by hand before touching anything layout-shaped: GEMINI_API_KEY=... .venv/bin/python scripts/vision_verify.py --capture-dir tests/golden/v3
sudo apt-get update -qq && sudo apt-get install -y -qq --no-install-recommends libgtk-4-1 libgraphene-1.0-0 libevent-2.1-7t64 libopus0 libgstreamer-plugins-base1.0-0 libgstreamer1.0-0 libwoff1 libharfbuzz-icu0 libsecret-1-0 libhyphen0 libmanette-0.2-0 libgles2 libavif16 libflite1 libsoup-3.0-0 libwayland-server0|WebKit system libs (apt needs sudo); locally unavailable without root
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
  echo "  scripts/css_parity.py"
  echo "  bash scripts/ci_promtool.sh"
  echo "  python3 scripts/build_dashboard.py --check"
  echo "  bash scripts/ci_web.sh"
  echo "-- unit suites"
  unit_suites | sed 's/^/  /'
  echo "-- e2e suites (via scripts/ci_e2e_http.sh)"
  e2e_suites | sed 's/^/  /'
  echo "  tests/e2e/test_dash_fit.py        (self-booting)"
  echo "  tests/e2e/test_dut_official_tt.py (self-booting)"
  echo "  bash tests/e2e/run_push_duts.sh   (boots 18185-18187 itself)"
  echo "  bash scripts/offline_proof.sh     (own server on 18183, killed mid-run)"
  echo "  bash scripts/dut_suite.sh         (own server on 18189, 11 DUT scripts)"
  echo "  bash scripts/capture_golden.sh --check --no-screens  (golden drift, ~2.5 min)"
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
# run_step NAME [KEY=VALUE ... COMMAND ARGS...]
# Leading KEY=VALUE words are the step's OWN environment, in the step's own
# `env` — anything already set in the runner's environment (VENV, PLAYWRIGHT_*,
# PORT, PATH) is inherited. DO NOT go back to a bare `run_step "x" PORT=18185
# bash ...`: that form runs a program literally named `PORT=18185`, so the step
# fails in ~0ms with "PORT=18185: command not found" / "No such file or
# directory" and reads as a red gate while nothing was tested. And never wrap a
# command in `env` instead: it resets the environment (an exported PATH drops
# node/pnpm off the box).
run_step() {
  local n=$1; shift
  local -a vars=()
  while [ $# -gt 0 ] && [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; do vars+=("$1"); shift; done
  if env "${vars[@]}" "$@" >/tmp/gate-$$.log 2>&1; then ok "$n"; else
    bad "$n"; sed -n '1,40p' /tmp/gate-$$.log | sed 's/^/         /'; fi
}
run_step "architecture DAG (check_architecture.py)" env PYTHONPATH=. "$V/bin/python" scripts/check_architecture.py
run_step "doc consistency (check_docs.py)"          env PYTHONPATH=. "$V/bin/python" scripts/check_docs.py
# Unit 8.2: the icon set. Manifest + template wiring + real IHDR pixels, with a
# positive control inside the script so a green run proves the gate can go red.
run_step "PWA icons (check_icons.py)"               env PYTHONPATH=. "$V/bin/python" scripts/check_icons.py
# Phase 2.3: the Vite CSS must stay semantically equal to the committed
# app/static/app.css, and exactly one app-*.css may exist in dist/ (a stale
# build hash left behind is what once precached a 404 and killed offline).
run_step "CSS parity (css_parity.py)"               env PYTHONPATH=. "$V/bin/python" scripts/css_parity.py
# W7.3b: css_parity only proves legacy ⊆ dist — both entries could agree while
# BOTH lack a class web/src writes (that is how the update banner rendered
# 2400px off-screen). This reads the write sites and requires a rule.
run_step "CSS classes for web/src (check_css_classes.py)" env PYTHONPATH=. "$V/bin/python" scripts/check_css_classes.py
if command -v docker >/dev/null 2>&1; then
  run_step "promtool (observability config + rules)" bash scripts/ci_promtool.sh
else
  skip "promtool (no docker)"
fi
run_step "dashboard JSON is current (build_dashboard.py --check)" "$V/bin/python" scripts/build_dashboard.py --check
# Phase 2.4: the Preact islands. Same script CI runs, so the local repro is
# literally the CI line. Skipped only where pnpm is absent (CI always has it).
if command -v pnpm >/dev/null 2>&1; then
  run_step "web/ (tsc + design tsc + vitest via ci_web.sh)" bash scripts/ci_web.sh
else
  skip "web/ gate (no pnpm)"
fi

# W8.6 Panel of Judges - one adversarial judge per criterion E1-E14, in a
# fresh detached worktree at HEAD. Prose-only criteria (E12/E14) read files;
# everything else is a command whose exit code IS the verdict.
[ -z "$FAST" ] && run_step "Panel of Judges E1-E14 (scripts/poj.py)" env PYTHONPATH=. "$V/bin/python" scripts/poj.py --ref HEAD --round 0

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
  # SCOPE_FEATURES: the same value CI exports for this step. Without it the four
  # data-gated panels (/campus, /academics, /fees, /tools) abort(404), and
  # test_route_panels goes red 2/35 on a tree CI passes — a local-only false
  # failure that reads exactly like a broken deployment. gates.sh passing this
  # inline is the point: the local bar must not be a different environment.
  # Derived from app.scope.ops.FEATURES, the registry the server gates on —
  # tests.yml derives the same way. A hand-copied literal here is how a new slug
  # ends up enabled in CI and 404ing locally.
  SCOPE_FEATURES=$(PYTHONPATH=. "$V/bin/python" -c 'from app.scope.ops import FEATURES; print(",".join(FEATURES))')
  DATA_DIR="$(mktemp -d)" PORT=18177 VENV="$V" SCOPE_FEATURES="$SCOPE_FEATURES" \
    bash scripts/ci_e2e_http.sh $(e2e_suites) \
    >/tmp/e2e-$$.log 2>&1 && ok "ci_e2e_http.sh ($(e2e_suites | wc -l) suites)" || {
    bad "ci_e2e_http.sh"; tail -25 /tmp/e2e-$$.log | sed 's/^/         /'; }
  for s in test_dash_fit test_dut_official_tt test_offline_routes; do
    env DATA_DIR="$(mktemp -d)" "$V/bin/python" "tests/e2e/$s.py" >/tmp/e-$$.log 2>&1 \
      && ok "$s" || { bad "$s"; tail -12 /tmp/e-$$.log | sed 's/^/         /'; }
  done
  if command -v docker >/dev/null 2>&1; then
    run_step "push DUTs (run_push_duts.sh)" env VENV="$V" bash tests/e2e/run_push_duts.sh
  else
    skip "push DUTs (no docker)"
  fi
  # Offline read path: boots its own server on 18183 and kills it mid-run, so it
  # cannot share the ports above. Exits non-zero when any leg fails — assert that
  # rather than trusting a parsed log line.
  run_step "offline proof (offline_proof.sh)" env OUT=/tmp/offline-proof-$$.md \
    bash scripts/offline_proof.sh
  # a11y + stress: both need a seeded, LOGGED-IN server, so they share one boot
  # in a11y_stress.sh. Wiring them here is what stops them becoming orphans —
  # this mission has already lost 10 DUT scripts to exactly that.
  run_step "a11y + stress (a11y_stress.sh)" PORT=18185 \
    bash scripts/a11y_stress.sh
  # The 11 DUT scripts, booted by dut_suite.sh on its own port (18189).
  # HARD GATE (option a): it exits 1 when any script fails and that is the point.
  # Until P9.5b fixes the 6 known-red scripts this holds the bar at RED on
  # purpose — a suite wired and honestly red beats one that is green because
  # nothing runs it. P9.5b turning them green flips this to PASS with no edit.
  run_step "DUT suite (dut_suite.sh — 11 scripts)" VENV="$V" \
    bash scripts/dut_suite.sh
  # Golden drift (W3.3): re-captures the 9 routes and diffs them against the
  # committed tests/golden/v3. --no-screens because PNG bytes encode the
  # capture host's font stack — the same line CI runs, for the same reason.
  # ~2.5 min: it seeds its own DATA_DIR and boots its own gunicorn.
  # OPENSRM_PY: capture_golden.sh falls back to a bare `python3` when the tree has
  # no .venv (worktrees never do), and the system python3 has no playwright — the
  # check then "fails" on ModuleNotFoundError before comparing anything.
  run_step "golden drift (capture_golden.sh --check --no-screens)" OPENSRM_PY="$V/bin/python" \
    env OPENSRM_PY="$V/bin/python" bash scripts/capture_golden.sh --check --no-screens
fi

finish
