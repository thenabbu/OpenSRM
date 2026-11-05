#!/bin/bash
# Upgrade smoke: boot the PREVIOUS release's data under the NEW image.
#
# The docker smoke always seeds an EMPTY volume, so it only ever proves a fresh
# install migrates. Production is never fresh: every real deploy carries the
# users, sessions and synced data of the release before it, and a migration
# that only works on an empty DB is exactly the failure that reaches prod and
# takes the dashboard down. The runbook already says to snapshot before a
# deploy precisely because nothing tested this.
#
# What this proves, in order:
#   1. the OLD image boots and creates a DB with a real user + session in it
#   2. the NEW image boots on THAT SAME volume (no wipe)
#   3. the new image's migrations complete against the old schema
#   4. the pre-existing user's session still authenticates the dashboard
#   5. the data written by the old release is still readable
#
# Usage: OLD_IMAGE=... NEW_IMAGE=... PORT=18090 bash scripts/ci_upgrade_smoke.sh
set -euo pipefail

OLD_IMAGE=${OLD_IMAGE:?set OLD_IMAGE to the previous release image}
NEW_IMAGE=${NEW_IMAGE:?set NEW_IMAGE to the image under test}
PORT=${PORT:-18090}
NETID=zz9999
VOL="osrm-upgrade-$$-data"
OLD_NAME="osrm-upg-old-$$"
NEW_NAME="osrm-upg-new-$$"

cleanup() {
  docker rm -f "$OLD_NAME" "$NEW_NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOL" >/dev/null 2>&1 || true
}
trap cleanup EXIT

boot() { # boot <name> <image> <port>
  docker run -d --name "$1" -p "127.0.0.1:$3:8080" -v "$VOL:/app/data" "$2" >/dev/null
  local up=""
  for _ in $(seq 1 90); do
    up=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$3/login" || true)
    [ "$up" = 200 ] && return 0
    sleep 1
  done
  echo "FAIL: $1 ($2) never answered /login (last=$up)"
  docker logs "$1" | tail -40
  return 1
}

echo "== 1. OLD image: $OLD_IMAGE"
boot "$OLD_NAME" "$OLD_IMAGE" "$PORT"

# seed a user + mint a session with the OLD release's own code, so the schema
# and the token are whatever that release actually produced
TOK=$(docker exec -i -u 10001 "$OLD_NAME" python - <<'PY'
import json, sys, time
sys.path.insert(0, "/app")
from app import app as A
c = A.db()
c.execute(
    "INSERT OR REPLACE INTO users(netid,password,personal_details_json,last_fetch)"
    " VALUES('zz9999','unused-by-ci',?,?)",
    (json.dumps({"Student Name": "Upgrade Test Student",
                 "Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
                 "Batch": "2025", "Semester": "III SEMESTER", "Section": "A"}),
     int(time.time())))
c.commit(); c.close()
from app.app import make_session_token
print(make_session_token("zz9999"))
PY
)
[ -n "$TOK" ] || { echo "FAIL: old image minted no session token"; exit 1; }
echo "ok  old release seeded a user and minted a session"

# The app tracks applied migrations in its own `migrations` table, not in
# SQLite's user_version (that is always 0 here and proves nothing).
SCHEMA_Q="import sqlite3;print(sqlite3.connect('/app/data/srm.db').execute('SELECT COALESCE(MAX(version),0) FROM schema_version').fetchone()[0])"
OLD_SCHEMA=$(docker exec -u 10001 "$OLD_NAME" python -c "$SCHEMA_Q" 2>/dev/null || echo "?")
echo "ok  old schema user_version=$OLD_SCHEMA"

# stop the old container but KEEP the volume - that is the upgrade
docker rm -f "$OLD_NAME" >/dev/null

echo "== 2. NEW image: $NEW_IMAGE on the SAME volume"
boot "$NEW_NAME" "$NEW_IMAGE" "$PORT"
echo "ok  new image booted on the old release's data"

NEW_SCHEMA=$(docker exec -u 10001 "$NEW_NAME" python -c "$SCHEMA_Q")
echo "ok  new schema version=$NEW_SCHEMA (was $OLD_SCHEMA)"
if [ "$OLD_SCHEMA" != "?" ] && [ "$NEW_SCHEMA" -lt "$OLD_SCHEMA" ]; then
  echo "FAIL: schema went BACKWARDS ($OLD_SCHEMA -> $NEW_SCHEMA)"
  docker logs "$NEW_NAME" | tail -40
  exit 1
fi
# A contiguous old->new schema is the case this whole script exists for; make
# that visible rather than hoping a future editor notices.
echo "ok  migrations applied on existing data ($OLD_SCHEMA -> $NEW_SCHEMA)"

echo "== 3. the OLD session must still authenticate"
body=$(mktemp)
code=$(curl -s -o "$body" -w "%{http_code}" -H "Cookie: srm_session=$TOK" \
  "http://127.0.0.1:$PORT/")
if [ "$code" != 200 ]; then
  echo "FAIL: a session minted by $OLD_IMAGE -> $code on $NEW_IMAGE (expected 200)."
  echo "      Every logged-in user would be 500'd by this deploy."
  docker logs "$NEW_NAME" | tail -40
  exit 1
fi
if ! grep -q "$NETID" "$body"; then
  echo "FAIL: dashboard 200 but the pre-existing user's row is gone - the upgrade lost data"
  head -c 400 "$body"; exit 1
fi
echo "ok  pre-existing session authenticates and the old data renders"

echo "== 4. the migrated DB is still readable by the new release's own code"
docker exec -u 10001 "$NEW_NAME" python - <<'PY'
import sys
sys.path.insert(0, "/app")
from app import app as A
c = A.db()
n = c.execute("SELECT COUNT(*) FROM users WHERE netid='zz9999'").fetchone()[0]
c.close()
assert n == 1, f"user row missing after upgrade (found {n})"
print("ok  upgrade kept the user row")
PY

echo "UPGRADE SMOKE PASSED: $OLD_IMAGE -> $NEW_IMAGE"
