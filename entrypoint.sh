#!/bin/sh
# Ensure data dir + secret key exist
mkdir -p /app/data
if [ ! -f /app/data/secret ]; then
  head -c 32 /dev/urandom | base64 > /app/data/secret
  chmod 600 /app/data/secret
fi
# Xvfb removed Sep 2026: headless=True proven safe (anti-bot bypass via
# webdriver strip + --disable-blink-features). See skill: srm-portal-attendance
exec "$@"
