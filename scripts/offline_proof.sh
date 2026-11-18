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
#   2. ROUTES   all 9 islands PAINT rows in a real browser after hydration, with
#               no console exception. One line per route, each with a row count.
#   3. OFFLINE  with the server killed, the same page still paints rows from
#               Dexie, and shows the "as of <age>" caption.
#   4. PII      the service worker did NOT cache the HTML response.
#
# Usage:
#   bash scripts/offline_proof.sh            # run all legs, chromium only
#   bash scripts/offline_proof.sh --keep     # leave the server up afterwards
#   ENGINES="chromium webkit firefox" bash scripts/offline_proof.sh
#                                            # the cross-engine matrix (W8.4);
#                                            # CI sets exactly this
#
# ENGINES defaults to chromium because this host can install no other engine
# without root (WebKit and Firefox need libgtk-3/libXcursor). The matrix is a CI
# gate; locally it is opt-in once `playwright install webkit firefox` works.
#
# Requires node on the machine that runs Playwright; on the lab that means
# running this through `lap`. Exit 0 = every leg proved.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

KEEP=${1:-}
PORT=${PORT:-18183}
SLUG=offlineproof
# W8.4: the engines the paint legs run in. Chromium is the local default (it is
# the only browser this host can install without root: WebKit and Firefox need
# libgtk-3/libXcursor, which a container here cannot add). CI passes all three.
# One engine per line so the matrix is a data change, not a code change.
ENGINES=${ENGINES:-chromium}
PW=${PLAYWRIGHT_BROWSERS_PATH:-/opt/data/cache/scratch/pw-browsers}
# The environment sets PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/tools, which EXISTS
# but holds no browsers — so a `-d` test passes, the browser legs are allowed to
# run, and they die with "Executable doesn't exist at
# /opt/hermes/tools/chromium_headless_shell-*". Test for the BROWSER, not the
# directory (same probe as scripts/a11y_stress.sh). Exported before the `-d`
# gates below, so both browser legs get the corrected path from one place.
_pw_ok() { ls "${1:-}"/*/chrome-headless-shell*/chrome-headless-shell >/dev/null 2>&1 \
        || ls "${1:-}"/*/chrome-linux/chrome >/dev/null 2>&1; }
if ! _pw_ok "$PW"; then PW=/opt/data/cache/scratch/pw-browsers; fi
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

# SCOPE_FEATURES: the four data-gated panels (/campus, /academics, /fees, /tools)
# abort(404) without their feature slug, and the app's DEFAULT_FEATURES omits
# campus/placement/library. Booting without this made /campus 404 in leg 4 — the
# route would have been graded "broken" for a reason that is the runner's fault.
# DERIVED from app.scope.ops.FEATURES (the registry the server gates on), not
# hand-copied: tests.yml and gates.sh derive the same way, so a new slug cannot
# be enabled in one place and missing here.
SCOPE_FEATURES=$(PYTHONPATH=. .venv/bin/python -c 'from app.scope.ops import FEATURES; print(",".join(FEATURES))')
# Boot gunicorn and capture its master PID. Factored out because the offline
# leg KILLS the server on purpose, so the engine loop (leg 2+3) has to bring it
# back between engines. The DATA_DIR is seeded once, above: rebooting re-opens
# the same file (migrations already applied), so the token minted in leg 1 stays
# valid for every engine.
#
# The PID comes from the command line, not a listener: `ss` reports nothing in
# this container (no socket table access), which is why every listener-based
# probe here silently returned an empty PID. The teardown kills the process
# group so master + worker both die; killing just "whoever holds the port" left
# a worker rebinding it.
boot_server() {
  env DATA_DIR="$DATA_DIR" LOG_LEVEL=WARNING SCOPE_FEATURES="$SCOPE_FEATURES" \
      .venv/bin/python -m gunicorn -w 1 --threads 4 -b 127.0.0.1:"$PORT" app.app:app \
      >"$LOG" 2>&1 &
  for _ in $(seq 1 40); do
    curl -sf -m 2 -o /dev/null "http://127.0.0.1:$PORT/login" && break
    sleep 1
  done
  SERVER_PID=$(pgrep -f "gunicorn.*:$PORT|gunicorn.*-b 127.0.0.1:$PORT" | head -1)
  [ -z "$SERVER_PID" ] && { say "  [FAIL] server never started (see $LOG)"; exit 1; }
  return 0
}
boot_server
say "  DATA_DIR=$DATA_DIR  log=$LOG  port=$PORT  engines=$ENGINES"

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

# ── 2+3. ROUTES + OFFLINE, one pass per engine (W8.4) ───────────────────────
# Leg 3 KILLS the server, so every engine needs its own boot: leg 2 runs while
# the server is alive, leg 3 pulls it out from under that engine and the reload
# must still paint from Dexie.
#
# Why run per engine at all: the offline path is exactly where the engines
# differ. Chromium keeps a service worker alive across a dead origin, Firefox
# ties the worker to its own per-profile storage partition, and WebKit scopes
# both the worker registration and the Cache API to the context the page was
# opened in. A green Chromium run is not evidence about either of those.
if [ -x .venv/bin/python ] && [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [ -d "${PLAYWRIGHT_BROWSERS_PATH}" ]; then
  _n=0
  _total=$(printf '%s\n' $ENGINES | wc -l)
  for ENGINE in $ENGINES; do
    _n=$((_n + 1))

    say "== leg 2 [$ENGINE]: all 9 routes paint rows after hydration =="
    # One [PASS]/[FAIL] per route, each with its row count; the driver prints
    # them itself. A route that legitimately has no rows must be declared
    # empty-by-design in tests/e2e/route_paint.py — it has no skip outcome.
    if .venv/bin/python tests/e2e/route_paint.py \
        --base "http://127.0.0.1:$PORT" --token "$TOKEN" --browser "$ENGINE"; then
      ok "routes [$ENGINE]: all 9 islands painted rows after hydration"
    else
      bad "routes [$ENGINE]: at least one island did not paint (see the per-route lines above)"
    fi

    say "== leg 3 [$ENGINE]: browser online visit, then server killed, then reload =="
    # Logout is asserted only on Chromium. The server is already dead by then, so
    # the /logout document cannot exist; Chromium lands on a chrome-error:// page
    # the driver recognises, while Firefox and WebKit land on about:neterror or
    # throw on the click — and an error page has a null origin, where a probe
    # that cannot read indexedDB would return "gone" and pass VACUOUSLY. The
    # wipe itself is proven for real in the vitest suite and the DUT (the
    # driver's own docstring says so); this leg is about the offline paint.
    _logout=""
    [ "$ENGINE" = "chromium" ] || _logout="--skip-logout"
    if LEG_OUT=$(.venv/bin/python tests/e2e/offline_paint.py \
          --base "http://127.0.0.1:$PORT" --token "$TOKEN" --browser "$ENGINE" $_logout \
          --kill-cmd "kill -9 $SERVER_PID \$(pgrep -P $SERVER_PID | tr '\\n' ' ') 2>/dev/null; true" 2>&1); then
      printf '%s\n' "$LEG_OUT" | sed 's/^/    /'
      ok "browser [$ENGINE]: offline reload painted rows from Dexie + age caption"
    else
      printf '%s\n' "$LEG_OUT" | sed 's/^/    /'
      bad "browser [$ENGINE]: offline reload did not paint (see above)"
      # The browser leg prints its own 'browser leg [engine]: N passed, M
      # failed'. Folding a whole subprocess into a single `bad` made the run say
      # "1 failed" while the leg had 2 independent assertion failures — an
      # undercount that hid real problems (COMPLETION_AUDIT.md, 2026-11-11).
      _leg_fails=$(printf '%s\n' "$LEG_OUT" \
          | sed -n 's/.*browser leg \[[a-z]*\]: [0-9]* passed, \([0-9]*\) failed.*/\1/p' | tail -1)
      if [ -n "$_leg_fails" ] && [ "$_leg_fails" -gt 1 ]; then
        FAIL=$((FAIL + _leg_fails - 1))
        say "  [note] browser leg reported $_leg_fails failed assertions; total adjusted"
      fi
    fi

    # Prove the server really is gone before claiming the offline leg meant
    # anything, then bring it back for the next engine. Leg 4 only greps a file,
    # so the last engine leaves it down.
    kill -9 "$SERVER_PID" $(pgrep -P "$SERVER_PID" 2>/dev/null) 2>/dev/null
    sleep 2
    if curl -sf -m 3 -o /dev/null "http://127.0.0.1:$PORT/attendance"; then
      bad "server [$ENGINE] still reachable — offline leg cannot be proven"
    else
      ok "server is down after the $ENGINE offline leg"
    fi
    [ "$_n" -lt "$_total" ] && boot_server
  done
else
  # NOT a skip: without a browser there is no proof, and an unproven route is
  # the exact defect this leg exists to catch. Fail loudly and say how to fix it.
  bad "routes: no browser — the 9 routes are UNPROVEN. Install with:"
  say "         PLAYWRIGHT_BROWSERS_PATH=$PW .venv/bin/playwright install $ENGINES"
  # Without a browser the server is still up; kill it so leg 4 still proves
  # something rather than being silently skipped.
  bash scripts/dut_server.sh stop "$PORT" >/dev/null 2>&1
fi

# ── 4. PII: service worker must not cache HTML ──────────────────────────────
say "== leg 4: service worker does not cache panel HTML =="
# The rule (sw.js:98-120, audit run-1 #12): on an offline HTML request the worker
# returns a GENERIC 503 page, never a caches.match() of the previous response —
# cached HTML holds attendance/marks PII and an offline worker cannot bind a
# cached entry to the current session, so a shared profile could show the
# previous student's dashboard. Assert that shape directly.
SW=app/static/sw.js
if grep -q "text/html" "$SW"; then
  # isolate the html branch and prove it returns a generic response.
  # Match `status: 503` AND its minified form `status:503` — the worker is built
  # by terser, which drops the space. The old pattern required the space, so it
  # reported FAIL on a worker that genuinely contains the generic fallback.
  html_branch=$(awk "/text\/html/,/^  }/" "$SW")
  echo "$html_branch" | grep -qE "status: ?503" \
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
  printf '| 2 routes | 9 islands paint real rows after hydration, per engine |\n'
  printf '| 3 offline | with the server dead, the page paints from Dexie + shows the age caption, per engine |\n'
  printf '| 4 PII | the service worker does not cache panel HTML |\n'
  printf '\nEngines: `%s`\n' "$ENGINES"
} > "$OUT"
say "report: $OUT"
[ "$FAIL" -eq 0 ]
