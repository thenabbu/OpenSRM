#!/bin/sh
# Ensure data dir + secret key exist
mkdir -p /app/data
if [ ! -f /app/data/secret ]; then
  head -c 32 /dev/urandom | base64 > /app/data/secret
fi
# Clean up any stale Xvfb lock
rm -f /tmp/.X99-lock
# Start Xvfb (headful Chromium needs a display)
Xvfb :99 -screen 0 1280x1024x24 &
export DISPLAY=:99
sleep 1
exec "$@"
