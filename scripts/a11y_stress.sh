#!/usr/bin/env bash
# a11y_stress.sh — boot one seeded authenticated server, run the axe audit and
# the stress leg against it, tear it down.
#
# Why a script: both legs need a live, seeded, LOGGED-IN server. A worker cannot
# hold that across think-generate turns, and inline-wiring them into gates.sh
# would duplicate the seeding dance that offline_proof.sh already knows.
#
# Exit 0 = both legs passed.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PORT=${PORT:-18185}
DD=$(mktemp -d)
# The environment sets PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/tools, which EXISTS
# but holds no browsers — so a directory test passes and every leg then dies with
# "Executable doesn't exist at /opt/hermes/tools/chromium_headless_shell-*".
# Test for the browser itself, not for the directory.
_pw_ok() { ls "${1:-}"/*/chrome-headless-shell*/chrome-headless-shell >/dev/null 2>&1 \
        || ls "${1:-}"/*/chrome-linux/chrome >/dev/null 2>&1; }
if ! _pw_ok "${PLAYWRIGHT_BROWSERS_PATH:-}"; then
  export PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers
fi
export PYTHONPATH="$PWD"
V=.venv/bin/python
FAIL=0

say() { printf '%s\n' "$*"; }

cleanup() {
  for p in $(pgrep -f "gunicorn.*$PORT" 2>/dev/null); do
    kill -9 "$p" 2>/dev/null
  done
  rm -rf "$DD"
}
trap cleanup EXIT

say "== seed $DD =="
PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD" DATA_DIR="$DD" $V - <<'PY' || exit 1
import sys, os
sys.path.insert(0, 'tests')
import _seed, _scope_fixture
_seed.seed_rich()
_scope_fixture.inject(os.environ['DATA_DIR'])
print('seeded')
PY

say "== boot =="
DATA_DIR="$DD" LOG_LEVEL=ERROR \
  SCOPE_FEATURES=hourwise,academics,fees,profile,attendance,marks,campus \
  $V -m gunicorn -w 1 --threads 4 -b "127.0.0.1:$PORT" app.app:app >/tmp/a11y_stress_srv.log 2>&1 &
for i in $(seq 1 40); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/login" && break
  sleep 0.5
done

# Mint the session cookie the legs need. Anonymous routes 302 to /login and
# every assertion then reports 0 rows — that is a broken harness, not a bug.
DATA_DIR="$DD" $V - <<'PY'
import hashlib, os, sqlite3, time
d = os.environ['DATA_DIR']
for f in sorted(os.listdir(d)):
    p = os.path.join(d, f)
    if not f.endswith(('.db', '.sqlite3')):
        continue
    n = {r[0] for r in sqlite3.connect(p).execute("select name from sqlite_master where type='table'")}
    if 'cookies' in n and 'users' in n:
        tok = 'a11ystress'
        dig = hashlib.sha256(tok.encode()).hexdigest()
        c = sqlite3.connect(p)
        c.execute('DELETE FROM cookies WHERE token=?', (dig,))
        c.execute('INSERT INTO cookies(token,netid,created) VALUES(?,?,?)', (dig, 'zz9999', int(time.time())))
        c.commit()
        print('minted')
        break
PY

BASE="http://127.0.0.1:$PORT"

say "== leg: a11y (axe-core, 9 routes) =="
if ! $V tests/e2e/a11y.py "$BASE" a11ystress; then FAIL=$((FAIL+1)); fi

say "== leg: stress (slow / flaky / reloads) =="
if ! $V tests/e2e/stress.py "$BASE" a11ystress; then FAIL=$((FAIL+1)); fi

say ""
if [ "$FAIL" -eq 0 ]; then
  say "RESULT: a11y + stress both passed"
else
  say "RESULT: $FAIL leg(s) failed"
fi
[ "$FAIL" -eq 0 ]
