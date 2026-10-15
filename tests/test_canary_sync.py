"""scripts/canary_sync.sh end-to-end against a self-booting local server whose
portal fetch is stubbed (no network, no logins, ONE sync per run).

Arms covered:
  zz9999  full stub payload   -> exit 0, payload lands in the DB, cookie dropped
  zz9996  no user row         -> non-zero, reason "no stored creds"
  zz9997  stub returns empty  -> non-zero, reason "attendance empty after sync"
The cookie row must be gone after EVERY run (the script's EXIT trap).
"""
import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

TMP = tempfile.mkdtemp(prefix="osrm-canary-")
os.environ["DATA_DIR"] = TMP   # seed + server + cookie helpers share THIS DB
atexit.register(__import__("shutil").rmtree, TMP, ignore_errors=True)

from app import app as A  # noqa: E402

FAILS = []
TOTAL = [0]


def check(desc, cond, detail=""):
    TOTAL[0] += 1
    print(("PASS " if cond else "FAIL ") + desc + ("" if cond else "  -> " + str(detail)[:500]))
    if not cond:
        FAILS.append(desc)


def _cookies(netid):
    c = A.db()
    n = c.execute("SELECT COUNT(*) FROM cookies WHERE netid=?", (netid,)).fetchone()[0]
    c.close()
    return n


def _free_port():
    for port in range(18177, 18189):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            s.close()
    sys.exit("FAIL: no free port in 18177-18188")


# ── seed: two users with stored (empty) data + encrypted password, one none ──
c = A.db()
empty = json.dumps({"courses": [], "monthly": [], "period": None, "daily_absent": {}})
for netid in ("zz9999", "zz9997"):
    c.execute("INSERT INTO users(netid, password, attendance_json, marks_json) VALUES(?,?,?,?)",
              (netid, A.encrypt_pw("pw"), empty, "[]"))
c.commit(); c.close()

port = _free_port()
GUN = os.path.join(os.path.dirname(sys.executable), "gunicorn")
if not os.path.exists(GUN):
    sys.exit(f"FAIL: no gunicorn next to {sys.executable} (pass VENV)")
log_path = os.path.join(TMP, "gunicorn.log")
srv = subprocess.Popen(
    [GUN, "-w", "1", "--threads", "4", "-b", f"127.0.0.1:{port}", "tests._canary_stub_app:app"],
    cwd=REPO, env=dict(os.environ, DATA_DIR=TMP),
    stdout=open(log_path, "w"), stderr=subprocess.STDOUT, start_new_session=True)

base = f"http://127.0.0.1:{port}"
up = False
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    if srv.poll() is not None:
        break
    try:
        with urllib.request.urlopen(base + "/login", timeout=2) as r:
            up = (r.status == 200)
    except Exception:
        pass
    if up:
        break
    time.sleep(0.3)
if not up:
    try:
        logtxt = open(log_path).read()[-2000:]
    except OSError:
        logtxt = ""
    print(f"FAIL: server never came up (rc={srv.poll()})\n{logtxt}")
    os.killpg(os.getpgid(srv.pid), signal.SIGKILL)
    sys.exit(1)


def run_canary(netid):
    env = dict(os.environ, DATA_DIR=TMP, CANARY_BASE=base,
               CANARY_MINT=f"{sys.executable} {REPO}/scripts/canary_cookie.py mint",
               CANARY_CHECK=f"{sys.executable} {REPO}/scripts/canary_cookie.py check",
               CANARY_DROP=f"{sys.executable} {REPO}/scripts/canary_cookie.py drop")
    return subprocess.run(["bash", os.path.join(REPO, "scripts", "canary_sync.sh"), netid],
                          cwd=REPO, env=env, capture_output=True, text=True, timeout=280)


try:
    # ── success arm ─────────────────────────────────────────────────────
    p = run_canary("zz9999")
    check("success run exits 0", p.returncode == 0,
          f"rc={p.returncode} stdout={p.stdout} stderr={p.stderr}")
    check("success run reports the one sync",
          "canary: OK" in p.stdout and "sync=1" in p.stdout, p.stdout + p.stderr)
    c = A.db()
    row = c.execute("SELECT attendance_json, marks_json FROM users WHERE netid='zz9999'").fetchone()
    c.close()
    att, marks = json.loads(row[0]), json.loads(row[1])
    check("stub payload landed in the DB (refresh really wrote)",
          att["courses"][0]["code"] == "TEST101" and marks[0]["code"] == "TEST101",
          f"att={att} marks={marks}")
    check("cookie deleted after success", _cookies("zz9999") == 0, _cookies("zz9999"))

    # ── no stored creds arm ─────────────────────────────────────────────
    p = run_canary("zz9996")
    check("no-user run exits non-zero", p.returncode != 0, p.returncode)
    check("no-user run states the reason", "no stored creds" in p.stderr,
          f"stdout={p.stdout} stderr={p.stderr}")
    check("cookie deleted after failure", _cookies("zz9996") == 0, _cookies("zz9996"))

    # ── empty-parse arm (sync ok, data empty -> canary must still fail) ──
    p = run_canary("zz9997")
    check("empty-parse run exits non-zero", p.returncode != 0, p.returncode)
    check("empty-parse run states the reason", "attendance empty" in p.stderr,
          f"stdout={p.stdout} stderr={p.stderr}")
    check("cookie deleted after empty-parse failure", _cookies("zz9997") == 0, _cookies("zz9997"))
finally:
    os.killpg(os.getpgid(srv.pid), signal.SIGTERM)
    end = time.monotonic() + 10
    while srv.poll() is None and time.monotonic() < end:
        time.sleep(0.2)
    if srv.poll() is None:
        os.killpg(os.getpgid(srv.pid), signal.SIGKILL)
    # port must actually be free again (lingering worker = false teardown)
    for _ in range(20):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            break
        except OSError:
            s.close()
            time.sleep(0.3)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("ok  canary_sync suite")
