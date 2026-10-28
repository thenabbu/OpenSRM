#!/usr/bin/env bash
# prod_logs.sh — read prod logs the way the incident procedure needs them.
# Replaces hand-built `ssh lab 'docker logs opensrm --since 168h 2>&1 | grep ...'`
# shapes (469 ssh calls in one audit window, 63 distinct).
#
# Usage:
#   bash scripts/prod_logs.sh [auth|http|portal|errors|all] [window]
#     window: docker --since value, default 24h (e.g. 168h, 30m)
#
# Why a script: `docker logs` only holds the CURRENT container's stdout — every
# deploy wipes it. For anything older use `bash scripts/prod_logs.sh durable`.
set -u
WHAT=${1:-errors}
SINCE=${2:-24h}
HOST=${HOST:-lab}

case "$WHAT" in
  auth)    pat='opensrm\.auth' ;;
  http)    pat='opensrm\.http' ;;
  portal)  pat='opensrm\.portal' ;;
  errors)  # status lines are "method path status duration"; a bare 5xx elsewhere is noise
           pat='ERROR|Traceback|error=| (5[0-9][0-9]) [0-9]+' ;;
  all)     pat='opensrm\.(auth|http|portal)|ERROR|Traceback' ;;
  durable)
    # survives deploys: file handler inside the opensrm-data volume
    dpat=${3:-ERROR}
    ssh "$HOST" "docker exec opensrm sh -c 'grep -aE \"$dpat\" /app/data/opensrm.log | tail -200'" \
      || { echo "durable log read failed" >&2; exit 1; }
    exit 0 ;;
  *) echo "usage: $0 [auth|http|portal|errors|all|durable] [window]" >&2; exit 2;;
esac

# 3xx/4xx too: a WARNING-only view walks past DEBUG-logged failures
ssh "$HOST" "docker logs opensrm --since $SINCE 2>&1 | grep -aE '$pat'" | tail -200
rc=${PIPESTATUS[0]}
[ "$rc" -ne 0 ] && { echo "(no matching lines in the last $SINCE — check the LOG_LEVEL: healthcheck traffic is demoted to DEBUG)" >&2; }
exit 0
