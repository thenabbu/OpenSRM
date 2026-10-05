#!/bin/bash
# Push DUT runner: boots the three gunicorn instances the push DUTs need.
#   18185  DATA_DIR=/tmp/push-sw2       unconfigured   (test_push_sw)
#   18186  DATA_DIR=/tmp/push-ui        PUSH_ENABLED=1 + VAPID_* (test_push_ui pass 2)
#   18187  DATA_DIR=/tmp/push-ui        same DB, push env stripped (test_push_ui pass 1)
# Ephemeral VAPID test keys are generated fresh each run (never a production
# key; the real pair lives only in lab /docker/.env). Exit 0 = both green.
set -u
cd "$(dirname "$0")/.."
V=${VENV:-.venv}
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-/opt/data/cache/scratch/pw-browsers}
PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done; }
trap cleanup EXIT

rm -rf /tmp/push-sw2 /tmp/push-ui
DATA_DIR=/tmp/push-sw2 LOG_LEVEL=WARNING "$V/bin/gunicorn" -w 1 --threads 4 -b 127.0.0.1:18185 app.app:app >/tmp/gun-pushsw.log 2>&1 &
PIDS+=($!)

"$V/bin/python" - << 'EOF' > /tmp/push-ui-env.sh
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
k = ec.generate_private_key(ec.SECP256R1())
priv = k.private_numbers().private_value.to_bytes(32, 'big')
pub = k.public_key().public_bytes(serialization.Encoding.X962,
                                  serialization.PublicFormat.UncompressedPoint)
print("export VAPID_PUBLIC_KEY=" + base64.urlsafe_b64encode(pub).rstrip(b"=").decode())
print("export VAPID_PRIVATE_KEY=" + base64.urlsafe_b64encode(priv).rstrip(b"=").decode())
print("export VAPID_SUBJECT=mailto:test@example.com")
EOF
chmod 600 /tmp/push-ui-env.sh
set -a; . /tmp/push-ui-env.sh; set +a
DATA_DIR=/tmp/push-ui PUSH_ENABLED=1 LOG_LEVEL=WARNING "$V/bin/gunicorn" -w 1 --threads 4 -b 127.0.0.1:18186 app.app:app >/tmp/gun-pushui.log 2>&1 &
PIDS+=($!)

# Wait for 18185+18186 first: migrations run at import and two processes on
# one FRESH db race schema_version inserts (UNIQUE). Prod runs one container.
for i in $(seq 1 30); do
  s1=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18185/login || true)
  s2=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18186/login || true)
  [ "$s1" = 200 ] && [ "$s2" = 200 ] && break
  sleep 1
done
# Unconfigured server for pass 1: same (now migrated) DB, push env stripped.
DATA_DIR=/tmp/push-ui LOG_LEVEL=WARNING \
  env -u VAPID_PUBLIC_KEY -u VAPID_PRIVATE_KEY -u VAPID_SUBJECT -u PUSH_ENABLED \
  "$V/bin/gunicorn" -w 1 --threads 4 -b 127.0.0.1:18187 app.app:app >/tmp/gun-pushui2.log 2>&1 &
PIDS+=($!)
for i in $(seq 1 30); do
  s3=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18187/login || true)
  [ "$s3" = 200 ] && break
  sleep 1
done
echo "servers: 18185=$s1 18186=$s2 18187=$s3"
[ "$s1" = 200 ] && [ "$s2" = 200 ] && [ "$s3" = 200 ] || {
  echo "SERVERS NOT UP"; for f in /tmp/gun-pushsw.log /tmp/gun-pushui.log /tmp/gun-pushui2.log; do echo "== $f"; tail -n 8 "$f"; done; exit 1; }

DUT_BASE=http://127.0.0.1:18185 "$V/bin/python" tests/test_push_sw.py; rc1=$?
DUT_BASE_UNCONF=http://127.0.0.1:18187 DUT_BASE_CONF=http://127.0.0.1:18186 "$V/bin/python" tests/test_push_ui.py; rc2=$?
[ $rc1 -eq 0 ] && [ $rc2 -eq 0 ] && echo "PUSH DUTS GREEN" || { echo "PUSH DUTS FAILED (sw=$rc1 ui=$rc2)"; exit 1; }
