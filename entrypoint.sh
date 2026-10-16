#!/bin/sh
# audit: fail fast — a failed mkdir/secret-gen must abort boot, not run the
# app with a missing data dir or unusable secret key
set -eu
# Ensure data dir + secret key exist
mkdir -p /app/data
if [ ! -f /app/data/secret ]; then
  head -c 32 /dev/urandom | base64 > /app/data/secret
  chmod 600 /app/data/secret
fi
# Xvfb removed Sep 2026: headless=True proven safe (anti-bot bypass via
# webdriver strip + --disable-blink-features). See skill: srm-portal-attendance
#
# Everything above runs as ROOT for one reason only: the prod volume predates
# non-root, so /app/data ships root-owned and only root can fix it (compose
# cap_drop: ALL leaves CHOWN for this line, SETUID/SETGID for the next one).
# chown BEFORE the drop so the app — running as opensrm — can write srm.db,
# secret, fernet.key, timetable.json and opensrm.log into the volume.
chown -R opensrm:opensrm /app/data

# setpriv execs CMD in place: PID 1 becomes the app itself, uid 10001, with
# CapPrm/CapEff zeroed (verified: /proc/1/status Uid 10001, CapEff 0000000000000000).
exec setpriv --reuid=10001 --regid=10001 --init-groups -- "$@"
