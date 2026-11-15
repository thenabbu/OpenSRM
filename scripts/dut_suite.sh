#!/usr/bin/env bash
# dut_suite.sh — run the 10 DUT scripts that nothing was running.
#
# Why they were orphans: every one of them needs DUT_BASE (a live seeded server)
# and DATA_DIR. Invoked bare they exit 1 immediately, so nobody ever wired them
# into the gate — 10 tests covering 10 real behaviours, silently dead.
#
# This boots ONE seeded server and passes both env vars to each script.
# Exit 0 = all passed. A script that genuinely fails is reported as FAIL, never
# skipped: a silently-skipped test is the exact defect this file fixes.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

# 18189: 18183 offline_proof · 18185 a11y_stress · 18186/18187 run_push_duts.
PORT=${PORT:-18189}
DD=$(mktemp -d)
export DATA_DIR="$DD"
export DUT_BASE="http://127.0.0.1:$PORT"
# Browsers: the lab keeps Chromium off its root disk, so default to that path
# only where it really exists. Everywhere else leave the var unset and let
# Playwright use its own default (~/.cache/ms-playwright on Linux,
# %LOCALAPPDATA%\ms-playwright on Windows) — a blind pin made a non-lab run read
# as 10 broken tests instead of one missing browser.
if [ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [ -d /opt/data/cache/scratch/pw-browsers ]; then
  export PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers
fi
if [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [ ! -d "$PLAYWRIGHT_BROWSERS_PATH" ]; then
  echo "PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH does not exist — browsers are not installed there." >&2
  echo "  install: ${VENV:-.venv}/bin/python -m playwright install chromium" >&2
  exit 2
fi
export PYTHONPATH="$PWD"
V=${VENV:-.venv}/bin/python

pkill -f "gunicorn.*$PORT" 2>/dev/null
cleanup() {
  for p in $(pgrep -f "gunicorn.*$PORT" 2>/dev/null); do kill -9 "$p" 2>/dev/null; done
  rm -rf "$DD"
}
trap cleanup EXIT

$V - <<'PY' || exit 1
import sys, os
sys.path.insert(0, 'tests')
import _seed, _scope_fixture
_seed.seed_rich()
_scope_fixture.inject(os.environ['DATA_DIR'])
PY

LOG_LEVEL=ERROR SCOPE_FEATURES=hourwise,academics,fees,profile,attendance,marks,campus \
  $V -m gunicorn -w 1 --threads 4 -b "127.0.0.1:$PORT" app.app:app \
  >/tmp/dut_suite_srv.log 2>&1 &
for i in $(seq 1 40); do
  curl -s -o /dev/null "$DUT_BASE/login" && break
  sleep 0.5
done

# Session cookie: every DUT visits authenticated routes.
$V - <<'PY'
import hashlib, os, sqlite3, time
d = os.environ['DATA_DIR']
for f in sorted(os.listdir(d)):
    p = os.path.join(d, f)
    if not f.endswith(('.db', '.sqlite3')):
        continue
    n = {r[0] for r in sqlite3.connect(p).execute(
        "select name from sqlite_master where type='table'")}
    if 'cookies' in n and 'users' in n:
        dig = hashlib.sha256(b'dutsuite').hexdigest()
        c = sqlite3.connect(p)
        c.execute('DELETE FROM cookies WHERE token=?', (dig,))
        c.execute('INSERT INTO cookies(token,netid,created) VALUES(?,?,?)',
                  (dig, 'zz9999', int(time.time())))
        c.commit()
        break
PY

PASS=0; FAIL=0; FAILED=""
SCRIPTS="test_att_dut test_delete_dut test_feedback_dut test_fees_dut test_lowtier_dut test_marks_dut test_pull_dut test_scope_profile_dut test_softrefresh_dut test_touchfeel_dut"

for s in $SCRIPTS; do
  printf '  %-26s ' "$s"
  if timeout 120 $V "tests/e2e/$s.py" >/tmp/dut_$s.log 2>&1; then
    echo "PASS"; PASS=$((PASS+1))
  else
    echo "FAIL"; FAIL=$((FAIL+1)); FAILED="$FAILED $s"
  fi
done

echo ""
echo "RESULT: $PASS passed, $FAIL failed"
[ -n "$FAILED" ] && echo "FAILED:$FAILED  (logs: /tmp/dut_<name>.log)"
[ "$FAIL" -eq 0 ]
