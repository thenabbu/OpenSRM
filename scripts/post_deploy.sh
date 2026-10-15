#!/usr/bin/env bash
# post_deploy.sh — verify an OpenSRM deploy landed: purge changed statics from the
# Cloudflare edge, prove MISS + byte-identity, then an authenticated render smoke.
#
# Run AFTER:  ssh lab 'cd /docker/opensrm && docker compose pull && docker compose up -d opensrm'
# from a checkout whose origin/main is what you just deployed.
#
# Usage: bash scripts/post_deploy.sh [--prev <ref>] [--all-static] [--skip-purge] [--skip-smoke]
#   --prev <ref>    ref prod ran before this deploy (default: nearest release tag;
#                   over-purging is safe, under-purging is not)
#   --all-static    purge every file under app/static (always-correct fallback)
set -u

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "not inside a git repo"; exit 2; }
cd "$ROOT" || exit 2
git fetch origin --prune >/dev/null 2>&1

BASE_URL=https://srm.200871.xyz
ZONE=e7e0257dc67334eaea9e52603bd8adbf
PY=python3
[ -x /opt/data/opensrm-repo/.venv/bin/python ] && PY=/opt/data/opensrm-repo/.venv/bin/python

PREV="" ALL_STATIC=0 DO_PURGE=1 DO_SMOKE=1
while [ $# -gt 0 ]; do
  case $1 in
    --prev) PREV=$2; shift 2 ;;
    --all-static) ALL_STATIC=1; shift ;;
    --skip-purge) DO_PURGE=0; shift ;;
    --skip-smoke) DO_SMOKE=0; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

PASS_N=0 FAIL_N=0
res() { # res PASS|FAIL <name> <detail>
  printf '[%s] %-14s %s\n' "$1" "$2" "$3"
  if [ "$1" = PASS ]; then PASS_N=$((PASS_N + 1)); else FAIL_N=$((FAIL_N + 1)); fi
}

# ---- 0. prod really runs what origin/main says (image label org.opencontainers.image.revision)
REV=$(ssh lab 'docker inspect opensrm --format "{{index .Config.Labels \"org.opencontainers.image.revision\"}}"' 2>/dev/null)
HEAD=$(git rev-parse origin/main)
if [ -z "$REV" ]; then
  res FAIL deployed "no revision label on the running image — can't tell what shipped"
elif [ "${REV:0:7}" != "${HEAD:0:7}" ]; then
  res FAIL deployed "prod runs ${REV:0:7} but origin/main is ${HEAD:0:7} — deploy (or git pull) first"
else
  res PASS deployed "prod image built from origin/main ${HEAD:0:7}"
fi

# ---- 0.5. GET /healthz: the endpoint the compose healthcheck polls must answer
if [ "$DO_SMOKE" = 1 ]; then
  HC=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/healthz")
  if [ "$HC" = "200" ]; then
    res PASS healthz "GET /healthz -> 200 (compose healthcheck endpoint is live)"
  else
    res FAIL healthz "GET /healthz -> $HC (compose healthcheck expects 200)"
  fi
fi

# ---- 1. changed statics: git diff --name-only <merge-base>..origin/main -- app/static
if [ "$ALL_STATIC" = 1 ]; then
  FILES=$(cd app/static && find . -type f | sed 's|^\./||')
else
  [ -z "$PREV" ] && PREV=$(git describe --tags --abbrev=0 origin/main 2>/dev/null)
  if [ -z "$PREV" ]; then
    res FAIL changed-static "no PREV ref (no --prev, no release tag) — rerun with --all-static"
    FILES=""
  else
    MB=$(git merge-base "$PREV" origin/main 2>/dev/null)
    if [ -z "$MB" ]; then res FAIL changed-static "bad --prev ref: $PREV"; exit 1; fi
    FILES=$(git diff --name-only "$MB"..origin/main -- app/static | sed 's|^app/static/||')
    if [ -n "$FILES" ]; then
      res PASS changed-static "$(printf '%s\n' "$FILES" | wc -l) static file(s) changed since $PREV:"$'\n'"$(printf '%s\n' "$FILES" | sed 's|^|    |')"
    else
      res PASS changed-static "no static changes since $PREV — edge already current"
    fi
  fi
fi

# ---- 2. Cloudflare purge (token = LAST CF_FULL_TOKEN= line of lab /docker/.env, '#' stripped)
if [ "$DO_PURGE" = 1 ] && [ -n "$FILES" ]; then
  TOK=$(ssh lab 'grep "^CF_FULL_TOKEN=" /docker/.env | tail -1 | cut -d= -f2- | cut -d"#" -f1' | tr -d '[:space:]')
  if [ -z "$TOK" ]; then
    res FAIL purge "CF_FULL_TOKEN not found in lab /docker/.env"
  else
    PAYLOAD=$(printf '%s\n' "$FILES" \
      | sed "s|^|$BASE_URL/static/|" \
      | "$PY" -c 'import json,sys; print(json.dumps({"files":[l.strip() for l in sys.stdin if l.strip()]}))')
    RESP=$(curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
                 -d "$PAYLOAD" "https://api.cloudflare.com/client/v4/zones/$ZONE/purge_cache")
    OK=$(printf '%s' "$RESP" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("success"))' 2>/dev/null)
    if [ "$OK" = "True" ]; then
      res PASS purge "purged $(printf '%s' "$PAYLOAD" | "$PY" -c 'import json,sys;print(len(json.load(sys.stdin)["files"]))') file URL(s)"
    else
      res FAIL purge "purge API error: $RESP"
    fi
  fi
fi

# ---- 3. re-curl: edge must MISS (not HIT) and the served bytes must equal origin/main's
if [ "$DO_PURGE" = 1 ] && [ -n "$FILES" ]; then
  BAD="" GOOD=""
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    WANT=$(git show "origin/main:app/static/$f" | sha256sum | cut -d' ' -f1)
    HDR=$(mktemp); try=0; STATUS=stale; GOT=nope
    while [ $try -lt 3 ]; do
      try=$((try + 1))
      curl -s -D "$HDR" -o "$HDR.body" "$BASE_URL/static/$f"
      STATUS=$(grep -i '^cf-cache-status:' "$HDR" | tr -d '\r' | awk '{print tolower($2)}')
      GOT=$(sha256sum < "$HDR.body" | cut -d' ' -f1)
      { [ "$GOT" = "$WANT" ] && [ "$STATUS" != "hit" ]; } && break
      sleep 2
    done
    rm -f "$HDR" "$HDR.body"
    if [ "$GOT" != "$WANT" ] || [ "$STATUS" = "hit" ]; then
      BAD="${BAD}    $f status=$STATUS sha_match=$([ "$GOT" = "$WANT" ] && echo yes || echo no)"$'\n'
    else
      GOOD="${GOOD}    $f status=$STATUS sha=ok"$'\n'
    fi
  done <<EOF
$FILES
EOF
  if [ -z "$BAD" ]; then
    res PASS recurl "every purged file fresh (not HIT) with origin/main bytes:"$'\n'"$GOOD"
  else
    res FAIL recurl "edge still stale / bytes differ:"$'\n'"$BAD"
  fi
fi

# ---- 4. authenticated render smoke (mint inside the container, delete the cookie row after)
if [ "$DO_SMOKE" = 1 ]; then
  NETID=$(ssh lab 'docker exec opensrm python -c "import sqlite3;c=sqlite3.connect(\"file:/app/data/srm.db?mode=ro\",uri=True);print(c.execute(\"select netid from users limit 1\").fetchone()[0])"')
  TOK=$(ssh lab "docker exec opensrm python -c \"from app.app import make_session_token; print(make_session_token('$NETID'))\"" | tail -1)
  BODY=$(mktemp)
  CODE=$(curl -s -o "$BODY" -w '%{http_code}' -b "srm_session=$TOK" "$BASE_URL/")
  HITS=$(grep -c "$NETID" "$BODY" || true)
  # since v1.20.3 rows store sha256(token) (migration 17) — the raw $TOK is
  # what the cookie holds, so hash it before addressing the row.
  CLEAN=$(ssh lab "docker exec opensrm python -c \"import hashlib,sqlite3;t=hashlib.sha256('$TOK'.encode()).hexdigest();c=sqlite3.connect('/app/data/srm.db');n=c.execute('delete from cookies where token=?',(t,)).rowcount;c.commit();left=c.execute('select count(*) from cookies where token=?',(t,)).fetchone()[0];print(n,left)\"")
  rm -f "$BODY"
  set -- $CLEAN
  if [ "$CODE" = "200" ] && [ "${HITS:-0}" -gt 0 ] && [ "${1:-0}" = "1" ] && [ "${2:-0}" = "0" ]; then
    res PASS smoke "GET / -> 200, netid literal x$HITS in real render, cookie row minted=$1 left=$2"
  else
    res FAIL smoke "http=$CODE netid_hits=$HITS cookie(minted=${1:-?} left=${2:-?})"
  fi
fi

printf '\npost_deploy: %d passed, %d failed\n' "$PASS_N" "$FAIL_N"
[ "$FAIL_N" -eq 0 ]
