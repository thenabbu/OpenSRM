#!/usr/bin/env bash
# dev-lan.sh — LAN-accessible dev build of OpenSRM for testing from a laptop/phone.
#
#   scripts/dev-lan.sh start    # boot the container (fresh seeded data dir)
#   scripts/dev-lan.sh status   # running? + URLs
#   scripts/dev-lan.sh url      # print the detected LAN URL
#   scripts/dev-lan.sh stop     # remove the container (keeps the data dir)
#
# No `ip` dependency: the default-route interface comes from /proc/net/route and
# its address from an ioctl, both stdlib. Works on a bare host and inside a slim
# container alike.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

NAME=opensrm-dev-lan
IMAGE=${IMAGE:-opensrm-scan:20261112-1406}
PORT=${PORT:-8080}
DATA=${DATA:-$PWD/.dev-lan-data}
NETID=${DEV_NETID:-devuser}
PASSWORD=${DEV_PASSWORD:-devpass123}

lan_ip() {
  python3 - "$@" <<'PY'
import fcntl, socket, struct
iface = next((f[0] for f in (l.split() for l in open('/proc/net/route').read().splitlines()[1:])
              if f[1] == '00000000' and int(f[3], 16) & 0x2), None)
if iface:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        print(socket.inet_ntoa(fcntl.ioctl(
            s.fileno(), 0x8915, struct.pack('256s', iface.encode()[:15]))[20:24]))
    except OSError:
        pass
PY
}
IP=$(lan_ip)

# Seed a users row + a live session row straight into the DB. /api/login is a
# real SRM portal scrape (app/routes_sync.py:412 fetch_attendance) — there is no
# local-password path, so a dev build authenticates by seeding instead.
#
# The seeded user needs scope_json too: presentation() gates a panel the student
# has no data for by aborting 404 (app/blueprints/shell.py:81-82), so a bare
# users row leaves /campus /academics /fees /tools returning 404 and 4 of the 9
# routes look broken. tests/_scope_fixture.py is the existing injection path.
seed() {
  docker exec -i "$NAME" python3 - "$NETID" "$PASSWORD" <<'PY' || return 1
import hashlib, json, os, sqlite3, sys, time
netid, pw = sys.argv[1], sys.argv[2]
db = os.path.join(os.environ.get("DATA_DIR", "/app/data"), "srm.db")
for _ in range(60):                      # migrations run on boot
    if os.path.exists(db):
        try:
            c = sqlite3.connect(db)
            if c.execute("select 1 from users limit 1").fetchone() is not None or \
               c.execute("select name from sqlite_master where name='users'").fetchone():
                c.execute("INSERT OR REPLACE INTO users(netid,password,personal_details_json,last_fetch)"
                          " VALUES(?,?,?,?)",
                          (netid, pw, json.dumps({"Student Name": "Dev User",
                                                  "Program": "DEV BUILD", "Semester": "I SEMESTER",
                                                  "Batch": "2026", "Section": "A"}), int(time.time())))
                c.execute("DELETE FROM cookies WHERE netid=?", (netid,))
                c.execute("INSERT INTO cookies(token,netid,created) VALUES(?,?,?)",
                          (hashlib.sha256(pw.encode()).hexdigest(), netid, int(time.time())))
                c.commit(); c.close()
                print("seeded", netid); break
        except sqlite3.Error:
            pass
    time.sleep(0.5)
else:
    sys.exit("seed failed: srm.db never became writable")
PY
  # NOTE: /campus /academics /fees /tools will 404 on a seeded dev user.
  # That is by design, not a bug: app/views/campus.py:181 returns
  # {"show": bool(cards)} and app/blueprints/shell.py:81-82 aborts 404 for any
  # panel with no data. Those panels need real scope_json payloads, which the
  # image cannot synthesise (tests/_scope_fixture.py is not shipped in the
  # image). The 5 always-on routes — / /attendance /timetable /marks /settings —
  # work fully. See docs/DEV_LAN.md.
}

case "${1:-status}" in
start)
  docker rm -f "$NAME" >/dev/null 2>&1
  mkdir -p "$DATA" || exit 1
  docker run -d --name "$NAME" \
    -p "$PORT:8080" \
    -e LOG_LEVEL=INFO \
    -e OCR_PREWARM=0 \
    -v "$DATA:/app/data" \
    "$IMAGE" >/dev/null || exit 1
  for i in $(seq 1 60); do
    curl -fsS -o /dev/null "http://127.0.0.1:$PORT/healthz" && break
    sleep 1
  done
  seed || { echo "seeded: FAILED (see docker logs $NAME)"; exit 1; }
  echo "started  http://localhost:$PORT  ·  http://${IP:-<no-lan-ip>}:$PORT"
  echo "login    $NETID / $PASSWORD"
  ;;
stop)
  docker rm -f "$NAME" >/dev/null 2>&1 && echo "stopped $NAME" || echo "not running"
  ;;
url)
  [ -n "$IP" ] || { echo "no default-route LAN IP detected" >&2; exit 1; }
  echo "http://$IP:$PORT"
  ;;
status)
  if docker ps --filter "name=^${NAME}$" --format '{{.Status}}' | grep -q .; then
    echo "running: $(docker ps --filter "name=^${NAME}$" --format '{{.Status}}')"
    echo "  local: http://localhost:$PORT"
    echo "  lan:   http://${IP:-<none>}:$PORT"
    printf '  / -> '; curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$PORT/"
  else
    echo "stopped — run: scripts/dev-lan.sh start"
    exit 1
  fi
  ;;
*)
  echo "usage: $0 {start|stop|status|url}" >&2; exit 2 ;;
esac
