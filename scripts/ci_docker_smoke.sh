#!/bin/bash
# CI docker smoke: the image must boot on an EMPTY volume, migrate a fresh DB,
# and render an AUTHENTICATED dashboard for a seeded fabricated user.
#
# Guards the Oct 8 2026 failure class: every authenticated dashboard 500'd
# while /login stayed green — /login alone only proves the shell boots, not
# that stored-data paths render. Hence: seed a user, mint its cookie inside
# the container, assert GET / is 200 and carries the seeded literal.
#
# Usage: IMAGE=opensrm:ci PORT=18080 bash scripts/ci_docker_smoke.sh
set -euo pipefail

IMAGE=${IMAGE:-opensrm:ci}
PORT=${PORT:-18080}
NAME="opensrm-ci-$$"
NETID=zz9999

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# 1. boot with an EMPTY named volume: a fresh DB must migrate at import
docker run -d --name "$NAME" -p "127.0.0.1:$PORT:8080" \
  -v "$NAME-data:/app/data" "$IMAGE" >/dev/null

# 2. wait for the shell to answer /login
up=""
for i in $(seq 1 60); do
  up=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/login" || true)
  [ "$up" = 200 ] && break
  sleep 1
done
if [ "$up" != 200 ]; then
  echo "FAIL: /login never returned 200 (last=$up)"
  docker logs "$NAME" | tail -40
  exit 1
fi
echo "ok  /login -> 200 after ${i}s"

# 3. seed a FABRICATED user + mint its session cookie inside the container.
#    No real NetID ever enters this file (public repo).
TOK=$(docker exec -i "$NAME" python - <<'PY'
import json, sys, time
sys.path.insert(0, "/app")
from app import app as A
c = A.db()
c.execute(
    "INSERT OR REPLACE INTO users(netid,password,personal_details_json,last_fetch)"
    " VALUES('zz9999','unused-by-ci',?,?)",
    (json.dumps({"Student Name": "Fabricated CI Student",
                 "Personal Email ID": "zz9999@example.test",
                 "Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
                 "Batch": "2025", "Semester": "III SEMESTER", "Section": "A"}),
     int(time.time())))
c.commit(); c.close()
from app.app import make_session_token
print(make_session_token("zz9999"))
PY
)
if [ -z "$TOK" ]; then
  echo "FAIL: minting a session token inside the container produced nothing"
  docker logs "$NAME" | tail -40
  exit 1
fi
echo "ok  seeded user $NETID + session minted"

# 4. authenticated render: 200 AND the seeded literal is actually on the page
body=$(mktemp)
code=$(curl -s -o "$body" -w "%{http_code}" -H "Cookie: srm_session=$TOK" \
  "http://127.0.0.1:$PORT/")
if [ "$code" != 200 ]; then
  echo "FAIL: authenticated GET / -> $code (expected 200)"
  docker logs "$NAME" | tail -40
  exit 1
fi
if ! grep -q "$NETID" "$body"; then
  echo "FAIL: authenticated / was 200 but the seeded literal $NETID is missing"
  head -c 400 "$body"
  exit 1
fi
echo "ok  authenticated / -> 200 with seeded literal $NETID"
