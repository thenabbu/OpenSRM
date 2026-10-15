#!/usr/bin/env bash
# One canary sync: mint a session cookie, POST /api/refresh ONCE, assert the
# sync left non-empty attendance and marks, delete the cookie. Exit is
# non-zero with the reason on stderr. Exactly one sync per run.
#
# Usage: scripts/canary_sync.sh <netid>
#   The netid is an ARGUMENT — never hard-code it here, never commit one.
#
# Defaults target the prod container; every leg is overridable so the same
# script runs against a local server (tests/test_canary_sync.py does):
#   CANARY_BASE   base URL                 (default https://srm.200871.xyz)
#   CANARY_MINT   cmd <netid> -> token     (default: docker exec opensrm ... cookie mint)
#   CANARY_CHECK  cmd <netid> -> exit!=0 with the reason if attendance/marks empty
#   CANARY_DROP   cmd <token> -> deletes the cookie
#
# No cron installed here — run it by hand (or wire it into your own scheduler).
set -u

NETID="${1:-}"
[ -n "$NETID" ] || { echo "usage: canary_sync.sh <netid>" >&2; exit 2; }

BASE="${CANARY_BASE:-https://srm.200871.xyz}"
MINT="${CANARY_MINT:-docker exec opensrm python /app/scripts/canary_cookie.py mint}"
CHECK="${CANARY_CHECK:-docker exec opensrm python /app/scripts/canary_cookie.py check}"
DROP="${CANARY_DROP:-docker exec opensrm python /app/scripts/canary_cookie.py drop}"

fail() { echo "canary: FAIL $*" >&2; exit 1; }

TOKEN=$($MINT "$NETID") || fail "mint failed for netid=$NETID"
TOKEN=$(printf '%s' "$TOKEN" | head -n1 | tr -d '\r')
[ -n "$TOKEN" ] || fail "mint returned an empty token"

BODY=$(mktemp)
ERR=$(mktemp)
# the cookie is deleted no matter which assertion fires after this point
trap 'rm -f "$BODY" "$ERR"; [ -n "${TOKEN:-}" ] && $DROP "$TOKEN" >/dev/null 2>&1' EXIT

# 1) exactly ONE sync per run
code=$(curl -sS -o "$BODY" -w '%{http_code}' --max-time 200 \
       -X POST "$BASE/api/refresh" -H "Cookie: srm_session=$TOKEN" 2>"$ERR") \
    || fail "refresh request failed: $(head -c 300 "$ERR" "$BODY" 2>/dev/null)"
grep -Eq '"ok":[[:space:]]*true' "$BODY" \
    || fail "refresh not ok (http $code): $(head -c 300 "$BODY")"

# 2) the sync must have left non-empty attendance AND marks
reason=$($CHECK "$NETID" 2>&1) || fail "$reason"

echo "canary: OK netid=$NETID sync=1 $reason"
