#!/bin/bash
# CI docker smoke: the image must boot on an EMPTY volume, migrate a fresh DB,
# and render an AUTHENTICATED dashboard for a seeded fabricated user.
#
# Guards the Oct 8 2026 failure class: every authenticated dashboard 500'd
# while /login stayed green — /login alone only proves the shell boots, not
# that stored-data paths render. Hence: seed a user, mint its cookie inside
# the container, assert GET / is 200 and carries the seeded literal.
#
# It boots with PROD'S HARDENING, read from docker-compose.yml rather than
# restated here. A plain `docker run` proved a different container than the one
# that ships: read_only + a 128MB /tmp tmpfs + cap_drop ALL are exactly the
# constraints that break a process writing outside /app/data, and the app has
# already had an incident of that class. Restating the flags here would let
# the two drift, so the compose file is the source of truth.
#
# Usage: IMAGE=opensrm:ci PORT=18080 bash scripts/ci_docker_smoke.sh
set -euo pipefail

IMAGE=${IMAGE:-opensrm:ci}
PORT=${PORT:-18080}
NAME="opensrm-ci-$$"
NETID=zz9999

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# Booted by DOCKER COMPOSE against the real docker-compose.yml, not by a
# hand-rolled `docker run`. Prod's guarantees come from that file - read_only,
# the 128MB /tmp tmpfs, cap_drop ALL, the resource limits AND the healthcheck -
# and restating any of them here is how a smoke ends up proving a container
# that is not the one that ships. Compose also translates its own healthcheck
# argv correctly; re-deriving it as a --health-cmd shell string did not (the
# probe died on /bin/sh quoting, which is how this was found).
#
# The override only renames the container and remaps the port so CI cannot
# collide with prod; everything that matters still comes from the real file.
OVERRIDE=$(mktemp --suffix=.-compose.yml)
trap 'rm -f "$OVERRIDE"; docker compose -p "osrm-ci-door" -f docker-compose.yml -f "$OVERRIDE" down -v >/dev/null 2>&1 || true; docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
cat > "$OVERRIDE" <<YAML
services:
  opensrm:
    image: ${IMAGE}
    container_name: ${NAME}
    restart: "no"
    ports: !override
      - "127.0.0.1:${PORT}:8080"
YAML

COMPOSE=(docker compose -p "osrm-ci-$$" -f docker-compose.yml -f "$OVERRIDE")

# 1. boot on an EMPTY volume: a fresh DB must migrate at import, under prod's
#    own hardening, and reach a healthy healthcheck.
"${COMPOSE[@]}" up -d --wait 2>&1 | tail -5
echo "ok  compose up --wait: prod hardening + healthcheck (container $NAME)"

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
# Runs as uid 10001, the user the entrypoint dropped to. A root `docker exec`
# here would create root-owned files on the volume that the hardened app then
# cannot read - which is exactly how this smoke failed the first time it was
# run under prod's flags (PermissionError on /app/data/secret).
TOK=$(docker exec -i -u 10001 "$NAME" python - <<'PY'
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

# 5. the compose HEALTHCHECK must pass in this container. Prod restarts on it,
#    and it runs `setpriv --reuid=10001` under cap_drop ALL — the combination
#    that would break if the runtime user or the /healthz route changed.
#    Polling the container's own health status proves the probe, not just that
#    curl from the runner can reach the port.
# The probe runs on compose's own schedule (interval 30s, start_period 15s), so
# the first verdict can be ~45s after boot. Wait past that rather than assuming
# a 1s cadence - the loop is polling DOCKER'S status, not running the probe.
hc=""
for i in $(seq 1 90); do
  hc=$(docker inspect -f '{{.State.Health.Status}}' "$NAME" 2>/dev/null || echo "none")
  [ "$hc" = "healthy" ] && break
  [ "$hc" = "unhealthy" ] && break
  sleep 1
done
if [ "$hc" != "healthy" ]; then
  echo "FAIL: container health never reached 'healthy' (last=$hc) — the compose"
  echo "      healthcheck is what prod restarts on; a green boot without it is"
  echo "      a container that would flap in production."
  docker inspect -f '{{json .State.Health}}' "$NAME" 2>/dev/null | head -c 800
  echo
  docker logs "$NAME" | tail -40
  exit 1
fi
echo "ok  compose healthcheck probe reports healthy"
