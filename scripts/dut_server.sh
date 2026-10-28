#!/usr/bin/env bash
# dut_server.sh — one canonical DUT/dev server boot. Replaces the hand-typed
# "cd <wt> && DATA_DIR=... PLAYWRIGHT_BROWSERS_PATH=... <venv>/python -m gunicorn"
# incantation that every session used to re-derive (218 call sites' worth).
#
# Usage:
#   bash scripts/dut_server.sh start [port] [slug]   # prints port + DATA_DIR
#   bash scripts/dut_server.sh stop  [port]
#   bash scripts/dut_server.sh status [port]
#
# Env overrides: VENV, PLAYWRIGHT_BROWSERS_PATH, LOG_LEVEL.
# Port default: first free in 18177..18188 (18447 is foreign — never used).
set -u

VENV=${VENV:-/opt/data/opensrm-repo/.venv}
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-/opt/data/cache/scratch/pw-browsers}
LOG_LEVEL=${LOG_LEVEL:-WARNING}

cmd=${1:-status}
port=${2:-}
slug=${3:-dut}

free_port() {
  for p in $(seq 18177 18188); do
    # bind probe: no ss on this host, and a listener check via /proc is racy
    if ! (echo >/dev/tcp/127.0.0.1/$p) 2>/dev/null; then echo "$p"; return 0; fi
  done
  return 1
}

# who owns this port — the listener's cwd tells you whose tree it serves
port_owner() {
  local p=$1 inode pid hex
  # compare the port as an uppercase hex string: mawk has no strtonum()
  hex=$(printf '%04X' "$p")
  inode=$(awk -v h="$hex" 'NR>1 {split($2,a,":"); if (a[2]==h && $4=="0A") print $10}' /proc/net/tcp 2>/dev/null | head -1)
  [ -z "$inode" ] && return 1
  for fd in /proc/[0-9]*/fd/*; do
    [ "$(readlink "$fd" 2>/dev/null)" = "socket:[$inode]" ] || continue
    pid=${fd#/proc/}; pid=${pid%%/*}
    echo "$pid $(readlink /proc/$pid/cwd 2>/dev/null)"
    return 0
  done
  return 1
}

case "$cmd" in
  start)
    [ -z "$port" ] && { port=$(free_port) || { echo "no free port in 18177-18188" >&2; exit 1; }; }
    if own=$(port_owner "$port"); then
      echo "REFUSING: port $port already served by pid/cwd: $own" >&2
      echo "  (another agent's server; pick another port or reuse it deliberately)" >&2
      exit 1
    fi
    [ -x "$VENV/bin/python" ] || { echo "no venv at $VENV — run: uv sync --extra browser" >&2; exit 1; }
    data=${DATA_DIR:-/tmp/dut-$slug-$port}
    mkdir -p "$data"
    log=/tmp/dut-$slug-$port.log
    ( cd "$(git rev-parse --show-toplevel)" && \
      env DATA_DIR="$data" LOG_LEVEL="$LOG_LEVEL" \
      "$VENV/bin/python" -m gunicorn -w 1 --threads 4 -b 127.0.0.1:"$port" app.app:app \
      >"$log" 2>&1 & echo $! > /tmp/dut-$slug-$port.pid )
    printf 'DUT_BASE=http://127.0.0.1:%s\nDATA_DIR=%s\nLOG=%s\nPID=%s\n' \
      "$port" "$data" "$log" "$(cat /tmp/dut-$slug-$port.pid)"
    ;;
  stop)
    [ -z "$port" ] && { echo "need a port" >&2; exit 2; }
    if own=$(port_owner "$port"); then
      set -- $own; kill "$1" 2>/dev/null
      for _ in $(seq 1 20); do port_owner "$port" >/dev/null || { echo "stopped $port"; exit 0; }; sleep 0.25; done
      echo "port $port still held after SIGTERM (workers?)" >&2; exit 1
    fi
    echo "nothing listening on $port"
    ;;
  status)
    if own=$(port_owner "${port:-}" 2>/dev/null); then echo "UP  $port -> $own"; else echo "DOWN ${port:-<none>}"; fi
    ;;
  *) echo "usage: $0 start|stop|status [port] [slug]" >&2; exit 2;;
esac
