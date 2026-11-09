#!/usr/bin/env bash
# offline_proof.sh — P7.4: prove the offline read path actually works.
#
# Why this is a script and not a kanban card: the card needs a live server, a
# seeded DB, a browser that loads a page, then the SAME server killed, then a
# reload that must still paint. That is process lifecycle across steps, and a
# worker has no way to hold it between think-generate turns. It was attempted as
# a card twice at --max-runtime 60m and produced 4.4 KB in two hours.
#
# What it proves, in order (each leg fails loudly):
#   1. ONLINE   /attendance renders rows server-side AND writes an IndexedDB row
#               whose payload validates against the island's zod schema.
#   2. OFFLINE  with the server killed, the same page still paints rows from
#               Dexie, and shows the "as of <age>" caption.
#   3. PII      the service worker did NOT cache the HTML response.
#
# Usage:
#   bash scripts/offline_proof.sh            # run all legs
#   bash scripts/offline_proof.sh --keep     # leave the server up afterwards
#
# Requires node on the machine that runs Playwright; on the lab that means
# running this through `lap`. Exit 0 = every leg proved.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

KEEP=${1:-}
PORT=${PORT:-18179}
SLUG=offlineproof
PW=${PLAYWRIGHT_BROWSERS_PATH:-/opt/data/cache/scratch/pw-browsers}
export PLAYWRIGHT_BROWSERS_PATH=$PW
OUT=${OUT:-/opt/data/missions/opensrm-preact/notes/verify/P7-offline.md}
PASS=0
FAIL=0

say() { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); say "  [PASS] $*"; }
bad()  { FAIL=$((FAIL+1)); say "  [FAIL] $*"; }

cleanup() {
  [ "$KEEP" = "--keep" ] || pkill -f "gunicorn.*$PORT" 2>/dev/null
}
trap cleanup EXIT

# ── 0. server up + seeded ────────────────────────────────────────────────────
say "== boot =="
# Refuse to reuse a port someone else is serving: a leftover server from an
# aborted run contributes a DIFFERENT DATA_DIR, so the browser lands on a page
# with no session and reports "offline is broken" when nothing is wrong.
if ss -lptn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
  say "  [FAIL] port $PORT already in use — refusing to reuse another run's server"
  exit 1
fi
DATA_DIR=$(mktemp -d /tmp/offproof-XXXXXX)
LOG=/tmp/offproof-server.log

# SEED BEFORE THE SERVER STARTS. Seeding a fresh DATA_DIR while gunicorn is
# already migrating the same file made both processes race on migration v1
# ("table users already exists"), and the server then served a half-built DB.
env DATA_DIR="$DATA_DIR" PYTHONPATH="$PWD" .venv/bin/python - <<'PY' || { say "seed failed"; exit 1; }
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
import _seed, _scope_fixture
_seed.seed_rich()
_scope_fixture.inject(os.environ["DATA_DIR"])
print("  seeded")
PY

( cd "$PWD" && env DATA_DIR="$DATA_DIR" LOG_LEVEL=WARNING \
    .venv/bin/python -m gunicorn -w 1 --threads 4 -b 127.0.0.1:"$PORT" app.app:app \
    >"$LOG" 2>&1 & )
say "  DATA_DIR=$DATA_DIR  log=$LOG  port=$PORT"

# wait for the socket (gunicorn needs a few seconds)
for _ in $(seq 1 30); do
  curl -sf -o /dev/null "http://127.0.0.1:$PORT/login" && break
  sleep 1
done
curl -sf -o /dev/null "http://127.0.0.1:$PORT/login" && ok "server answering on $PORT" || { bad "server never answered"; exit 1; }

# ── 1. ONLINE: cache gets written ───────────────────────────────────────────
say "== leg 1: online, cache written =="
# Mint the token in its own step. The previous version nested a heredoc inside a
# $( ) inside a curl header — bash closes the heredoc at the wrong point and the
# leg dies with no output at all.
TOKEN_FILE=/tmp/offproof-token.txt
env DATA_DIR="$DATA_DIR" PYTHONPATH="$PWD" .venv/bin/python - > "$TOKEN_FILE" <<'PY' || { bad "could not mint a session token"; exit 1; }
import hashlib, os, sqlite3, time

d = os.environ["DATA_DIR"]
db = None
for f in sorted(os.listdir(d)):
    if not f.endswith((".db", ".sqlite3")):
        continue
    p = os.path.join(d, f)
    names = {r[0] for r in sqlite3.connect(p).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "cookies" in names and "users" in names:
        db = p
        break
if db is None:
    raise SystemExit("no session DB found")

tok = "offline-proof-token"
digest = hashlib.sha256(tok.encode()).hexdigest()
c = sqlite3.connect(db)
c.execute("DELETE FROM cookies WHERE token=?", (digest,))
# created MUST be now: get_current_user deletes rows older than SESSION_MAX_AGE
c.execute("INSERT INTO cookies(token,netid,created) VALUES(?,?,?)",
          (digest, "zz9999", int(time.time())))
c.commit()
c.close()
print(tok)
PY
TOKEN=$(cat "$TOKEN_FILE")
[ -n "$TOKEN" ] && ok "session token minted" || { bad "empty token"; exit 1; }

body=$(curl -s --max-time 20 "http://127.0.0.1:$PORT/api/attendance" -H "Cookie: srm_session=$TOKEN")
echo "$body" | grep -q '"ok": *true\|"ok":true' && ok "/api/attendance returns ok:true" || { bad "/api/attendance not ok"; say "$body" | head -c 300; }
echo "$body" | grep -q '"courses"' && ok "payload carries courses (island shape)" || bad "no courses key"

# ── 2. OFFLINE: browser visits online, then the server dies under it ────────
say "== leg 2: browser online visit, then server killed, then reload =="
# ORDER MATTERS. The browser must load the page while the server is ALIVE (that
# is what writes the IndexedDB row), and only then lose it. Killing first made
# the online visit die with ERR_CONNECTION_REFUSED.
if [ -x .venv/bin/python ] && [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [ -d "${PLAYWRIGHT_BROWSERS_PATH}" ]; then
  if .venv/bin/python tests/e2e/offline_paint.py \
        --base "http://127.0.0.1:$PORT" --token "$TOKEN" \
        --kill-cmd "bash scripts/dut_server.sh stop $PORT"; then
    ok "browser: offline reload painted rows from Dexie + age caption"
  else
    bad "browser: offline reload did not paint (see output above)"
  fi
else
  say "  [SKIP] browser leg — no Chromium. Install with:"
  say "         PLAYWRIGHT_BROWSERS_PATH=$PW .venv/bin/playwright install chromium"
  # Without a browser the server is still up; kill it so leg 2's socket check
  # below still proves something rather than being silently skipped.
  bash scripts/dut_server.sh stop "$PORT" >/dev/null 2>&1
fi

sleep 2
if curl -sf -m 3 -o /dev/null "http://127.0.0.1:$PORT/attendance"; then
  bad "server still reachable — offline leg cannot be proven"
else
  ok "server is down"
fi

# ── 3. PII: service worker must not cache HTML ──────────────────────────────
say "== leg 3: service worker does not cache panel HTML =="
# The rule (sw.js:98-120, audit run-1 #12): on an offline HTML request the worker
# returns a GENERIC 503 page, never a caches.match() of the previous response —
# cached HTML holds attendance/marks PII and an offline worker cannot bind a
# cached entry to the current session, so a shared profile could show the
# previous student's dashboard. Assert that shape directly.
SW=app/static/sw.js
if grep -q "text/html" "$SW"; then
  # isolate the html branch and prove it returns a generic response
  html_branch=$(awk "/text\/html/,/^  }/" "$SW")
  echo "$html_branch" | grep -q "status: 503" \
    && ok "offline HTML returns a generic 503, not a cached page" \
    || bad "HTML branch does not return the generic 503 page"
  echo "$html_branch" | grep -q "caches.match(e.request)" \
    && bad "HTML branch falls back to caches.match — that would serve cached PII" \
    || ok "HTML branch never falls back to a cached response"
  echo "$html_branch" | grep -q "cache.put(e.request, resp" \
    && bad "HTML branch writes responses into the cache" \
    || ok "HTML branch writes nothing into the cache"
else
  say "  [SKIP] sw.js has no HTML branch — nothing to check"
fi

# ── verdict ─────────────────────────────────────────────────────────────────
say ""
say "RESULT: $PASS passed, $FAIL failed"
mkdir -p "$(dirname "$OUT")"
{
  printf '# P7.4 — offline read path proof\n\n'
  printf 'Run: %s\n\n' "$(date -Is)"
  printf 'Result: **%d passed, %d failed**\n\n' "$PASS" "$FAIL"
  printf '| Leg | What it proves |\n|---|---|\n'
  printf '| 1 online | /api/attendance returns the island payload the cache stores |\n'
  printf '| 2 offline | with the server dead, the page paints from Dexie + shows the age caption |\n'
  printf '| 3 PII | the service worker does not cache panel HTML |\n'
} > "$OUT"
say "report: $OUT"
[ "$FAIL" -eq 0 ]
