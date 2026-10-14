#!/bin/bash
# CI e2e runner for the browser suites that need an externally booted server.
# One gunicorn backs every suite in the list (fresh DATA_DIR, free port), and
# the suite's own require_own_server() guard aborts instantly if the listener
# is foreign or reads a different DATA_DIR — a phantom green is impossible.
#
# Usage: DATA_DIR=<fresh dir> PORT=18177 bash scripts/ci_e2e_http.sh test_sw test_xss ...
# Exits non-zero if ANY suite fails; per-suite rc is printed either way.
set -uo pipefail
cd "$(dirname "$0")/.."
V=${VENV:-.venv}
PORT=${PORT:-18177}
DATA_DIR=${DATA_DIR:-$(mktemp -d)}
export DATA_DIR

[ $# -gt 0 ] || { echo "FAIL[guard]: no suites named"; exit 2; }

"$V/bin/gunicorn" -w 1 --threads 4 -b 127.0.0.1:"$PORT" app.app:app \
  >/tmp/gunicorn-ci.log 2>&1 &
GPID=$!
kill_server() { kill "$GPID" 2>/dev/null || true; }
trap kill_server EXIT

up=""
for i in $(seq 1 60); do
  up=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/login" || true)
  [ "$up" = 200 ] && break
  sleep 1
done
if [ "$up" != 200 ]; then
  echo "FAIL[guard]: no server on :$PORT after ${i}s (last=$up)"
  tail -30 /tmp/gunicorn-ci.log
  exit 1
fi
echo "server up on :$PORT after ${i}s (DATA_DIR=$DATA_DIR)"

rc_total=0
for s in "$@"; do
  st=$(date +%s)
  timeout 300 env DUT_BASE="http://127.0.0.1:$PORT" "$V/bin/python" "tests/$s.py" \
    >/tmp/suite-$s.log 2>&1
  rc=$?
  [ $rc -ne 0 ] && rc_total=1
  echo "$s | rc=$rc | $(( $(date +%s) - st ))s | $(tail -1 /tmp/suite-$s.log | tr -d '\n' | cut -c1-110)"
  [ $rc -ne 0 ] && { echo "--- last 25 lines of $s ---"; tail -25 /tmp/suite-$s.log; }
done
exit $rc_total
