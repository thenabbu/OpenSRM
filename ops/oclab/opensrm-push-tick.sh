#!/usr/bin/env bash
# OpenSRM class-reminder tick.
# Installed on oclab as /usr/local/bin/opensrm-push-tick.sh, fired every minute
# by /etc/cron.d/opensrm-push-tick. Replaces the cron-job.org / Hermes cron
# job: the box that runs the app also drives it.
#
# Silent on success in the cron mail sense (output is discarded), but every
# attempt lands one line in /var/log/opensrm-push-tick.log with the app's own
# JSON counters, so "did it fire" is answered from the host, not from memory.
# Exit code is 0 only on HTTP 200; a dead tick is caught by the Prometheus
# rule opensrm_push_tick_* (5m stale for 5m -> alertmanager -> ntfy), so this
# script does not duplicate the alerting.
set -u
ENVF=/docker/opensrm/.env
URL=https://srm.200871.xyz/internal/push/tick
LOG=/var/log/opensrm-push-tick.log
KEEP=10000

SECRET=$(sed -n 's/^PUSH_TICK_SECRET=//p' "$ENVF" 2>/dev/null | head -1 | tr -d '"[:space:]')
if [ -z "$SECRET" ]; then
  echo "$(date -Is) ERR PUSH_TICK_SECRET missing in $ENVF" >>"$LOG"
  exit 1
fi

OUT=$(curl -sS -m 25 -X POST -H "X-Push-Tick: $SECRET" -w $'\n%{http_code}' "$URL" 2>&1)
RC=$?
CODE=${OUT##*$'\n'}
BODY=$(printf '%s' "${OUT%$'\n'*}" | tr -d '\n')
printf '%s %s %s\n' "$(date -Is)" "$CODE" "$BODY" >>"$LOG"

if [ "$(wc -l <"$LOG")" -gt "$KEEP" ]; then
  tail -n $((KEEP / 2)) "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

[ "$RC" -eq 0 ] && [ "$CODE" = "200" ]
