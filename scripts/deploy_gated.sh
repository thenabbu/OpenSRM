#!/bin/bash
# Gated deploy: pin a digest, deploy it, prove it, roll back if it is red.
#
# Runs ON THE LAB (the box behind the tunnel). CI cannot reach it: 192.168.29.7
# is NAT'd and nothing listens for an inbound runner, so the deploy is a pull,
# never a push - this script is invoked by the deploy workflow through the
# existing outbound path, or by hand.
#
# Why this exists at all: CONTRIBUTING says deploy is manual and there is no
# watcher, because a blind auto-deploy is unacceptable. This is not that. It
# deploys ONE digest that a human approved in the `production` GitHub
# Environment, and it reverts itself if the box does not come back healthy. The
# approval stays a human decision; only the steps after it are automated.
#
# What it fixes, from the runbook's own history: on 2026-10-16 the live compose
# file had drifted from the repo copy and rollback silently did not work. Here
# the tag is written into the project .env, so rollback is a file edit this
# script can do itself, not a procedure someone must remember.
#
# Usage: bash scripts/deploy_gated.sh <tag-or-digest>
#        DEPLOY_DRY_RUN=1 for a rehearsal that changes nothing.
set -euo pipefail

TARGET=${1:?usage: deploy_gated.sh <tag-or-digest>}
COMPOSE_DIR=${COMPOSE_DIR:-/docker/opensrm}
ENVF="$COMPOSE_DIR/.env"
HEALTH_URL=${HEALTH_URL:-https://srm.200871.xyz/healthz}
PUBLIC_URL=${PUBLIC_URL:-https://srm.200871.xyz}
SNAP_DIR=${SNAP_DIR:-/data/ssd120/backups/opensrm}
DRY=${DEPLOY_DRY_RUN:-0}

say() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

cd "$COMPOSE_DIR" || die "no $COMPOSE_DIR"

# The image reference goes in .env, never in the compose file: the repo copy is
# the source of truth for everything else, and this is the one knob a deploy is
# allowed to move.
set_tag() { # set_tag <ref>
  if grep -q '^OPENSRM_TAG=' "$ENVF" 2>/dev/null; then
    sed -i "s|^OPENSRM_TAG=.*|OPENSRM_TAG=$1|" "$ENVF"
  else
    printf 'OPENSRM_TAG=%s\n' "$1" >> "$ENVF"
  fi
}
current_tag() { grep -E '^OPENSRM_TAG=' "$ENVF" 2>/dev/null | cut -d= -f2- || true; }

PREV_TAG="$(current_tag)"
PREV_TAG=${PREV_TAG:-latest}
say "currently deployed: $PREV_TAG"
say "target:             $TARGET"

if [ "$DRY" = 1 ]; then
  say "DRY RUN - would snapshot, set OPENSRM_TAG=$TARGET, up -d, verify,"
  say "          and roll back to $PREV_TAG if verification failed."
  exit 0
fi

# ---- 0. snapshot before touching anything (migrations are why the runbook
#         asks for this; a rollback of the image does not roll back the schema)
mkdir -p "$SNAP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
SNAP="$SNAP_DIR/srm.predeploy-$STAMP.db"
if docker exec opensrm test -f /app/data/srm.db 2>/dev/null; then
  # The container rootfs is read_only and /app/data is NOT writable (only the
  # db FILE is owned by the app; the directory is not) - writing the snapshot
  # next to the db fails with "unable to open database file". /tmp is the
  # tmpfs, and is where every writable scratch path in this image lives.
  DB_BYTES=$(docker exec opensrm stat -c %s /app/data/srm.db)
  TMP_FREE=$(docker exec opensrm sh -c 'df -k /tmp | tail -1 | awk "{print \$4}"')
  if [ "$DB_BYTES" -gt $((TMP_FREE * 1024)) ]; then
    die "db is ${DB_BYTES}B but /tmp tmpfs has ${TMP_FREE}K free - snapshot would be truncated"
  fi
  docker exec opensrm python -c "
import sqlite3
s = sqlite3.connect('/app/data/srm.db')
d = sqlite3.connect('/tmp/srm.predeploy.snapshot.db')
s.backup(d); d.close(); s.close()
print('snapshot ok')" >/dev/null || die "snapshot failed - refusing to deploy"
  # `docker cp` cannot see files on this container's /tmp tmpfs (verified on
  # the live box: the file is listed by ls inside, and cp still reports "Could
  # not find the file"). Stream it out instead - byte-identical and it works.
  docker exec opensrm cat /tmp/srm.predeploy.snapshot.db > "$SNAP" \
    || die "could not copy the snapshot out - refusing to deploy"
  docker exec opensrm rm -f /tmp/srm.predeploy.snapshot.db
  # A snapshot nobody verified is a file, not a backup.
  CNT=$(python3 -c "import sqlite3;print(sqlite3.connect('$SNAP').execute('SELECT COUNT(*) FROM users').fetchone()[0])")
  say "snapshot: $SNAP (users=$CNT)"
  [ "$CNT" -gt 0 ] || die "snapshot has no users - that is not this deployment's data"
else
  say "no existing DB - first install, nothing to snapshot"
fi

# ---- 1. pull BEFORE stopping anything, so a bad tag leaves prod running
say "pulling $TARGET"
docker pull "ghcr.io/thenabbu/opensrm:$TARGET" >/dev/null || die "pull failed - prod left untouched"

# ---- 2. deploy
set_tag "$TARGET"
say "recreating with OPENSRM_TAG=$TARGET"
docker compose up -d opensrm >/dev/null || die "compose up failed"

# ---- 3. prove it: the same assertions CI makes, against the real edge
verify() {
  local ok=0
  for _ in $(seq 1 60); do
    H=$(docker inspect opensrm --format '{{.State.Health.Status}}' 2>/dev/null || echo none)
    [ "$H" = healthy ] && { ok=1; break; }
    [ "$H" = unhealthy ] && break
    sleep 2
  done
  [ "$ok" = 1 ] || { say "container health=$H"; return 1; }

  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL" || echo 000)
  [ "$code" = 200 ] || { say "public /healthz -> $code"; return 1; }

  # The Oct 8 failure class: /login green while every authenticated dashboard
  # 500'd. The render smoke is the only thing that catches it.
  docker exec opensrm python -c "
import urllib.request
urllib.request.urlopen('http://localhost:8080/login', timeout=10)" 2>/dev/null \
    || { say "in-container /login failed"; return 1; }
  return 0
}

if verify; then
  say "healthy: $TARGET is live"
  docker inspect opensrm --format 'deployed revision: {{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || true
  exit 0
fi

# ---- 4. roll back. The image reverts; the schema does not, which is exactly
#         why the snapshot above exists.
say "VERIFICATION FAILED - rolling back to $PREV_TAG"
set_tag "$PREV_TAG"
docker compose up -d opensrm >/dev/null || die "rollback compose up failed (prod is DOWN - snapshot at $SNAP)"
if verify; then
  say "rolled back to $PREV_TAG; prod is healthy again"
else
  die "rollback did NOT come back healthy - prod is down. Snapshot: $SNAP"
fi
exit 1
