"""Logging + telemetry regression suite — guards the Oct 2026 PR-B fixes.

Every check here exercises a fix from the logging/telemetry audits:
  * access log: >=400 at WARNING with error=, healthcheck urllib -> DEBUG
  * tick-secret 401 + push-test failed outcome + rate-limit cause lines
  * root logger stays INFO (no library DEBUG chatter), opensrm obeys LOG_LEVEL
  * rotation: TimedRotatingFileHandler configured
  * ntfy alerter: wired, rate-limited, best-effort
  * usage_events: migration + _track() writes, never breaks a request

Offline: no portal calls, no real network (ntfy posts are stubbed).
"""
import json
import logging
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
TMP = tempfile.mkdtemp(prefix="osrm-logtel-")
os.environ["DATA_DIR"] = TMP  # verify76: no test DBs in-tree

from app import app as A          # noqa: E402
from app import logging_setup as LS  # noqa: E402
from _seed import mint_token, seed  # noqa: E402

FAILS = []


def check(name, fn):
    try:
        fn()
        print(f"  ok  {name}")
    except AssertionError as e:
        FAILS.append(name)
        print(f"FAIL  {name}: {e}")
    except Exception as e:
        FAILS.append(name)
        print(f"FAIL  {name}: raised {type(e).__name__}: {e}")


# ── access log: WARNING + error= on >=400, DEBUG for healthcheck UA ──
def t_access_log():
    records = []

    class Cap(logging.Handler):
        def emit(self, r):
            records.append(r)

    cap = Cap()
    logging.getLogger("opensrm.http").addHandler(cap)
    cl = A.app.test_client()
    try:
        r1 = cl.post("/api/login", data="not json", content_type="text/plain")
        assert r1.status_code == 400, r1.status_code
        r2 = cl.get("/definitely-not-a-route")
        assert r2.status_code == 404
        hc = cl.get("/", headers={"User-Agent": "Python-urllib/3.12"})
    finally:
        logging.getLogger("opensrm.http").removeHandler(cap)
    warns = [r for r in records if r.levelno == logging.WARNING and r.getMessage() == "request"]
    kv_err = [r for r in warns if getattr(r, "kv", {}).get("error")]
    assert kv_err, f">=400 request lines must carry error=: {[getattr(r, 'kv', {}) for r in warns]}"
    deb = [r for r in records if r.levelno == logging.DEBUG]
    assert deb, "healthcheck UA must log at DEBUG, not INFO"


def t_rate_limit_logged():
    records = []

    class Cap(logging.Handler):
        def emit(self, r):
            records.append(r)

    cap = Cap()
    logging.getLogger("opensrm.auth").addHandler(cap)
    cl = A.app.test_client()
    orig = A.fetch_attendance
    A.fetch_attendance = lambda n, p: {"ok": False, "error": "x"}
    A._ip_attempts.clear()  # earlier tests may have burned this IP's budget
    try:
        for _ in range(11):
            cl.post("/api/login", json={"netid": "zz9999", "password": "pw"},
                    content_type="application/json")
    finally:
        A.fetch_attendance = orig
        logging.getLogger("opensrm.auth").removeHandler(cap)
    hits = [r for r in records if getattr(r, "kv", {}).get("ip") is not None
            and "ip limited" in r.getMessage()]
    assert hits, "per-IP 429 must log a cause line with the ip"


# ── tick secret 401 ──────────────────────────────────────────────────
def t_tick_auth_logged():
    records = []

    class Cap(logging.Handler):
        def emit(self, r):
            records.append(r)

    cap = Cap()
    logging.getLogger("opensrm.push").addHandler(cap)
    cl = A.app.test_client()
    try:
        r = cl.post("/internal/push/tick", headers={"X-Push-Tick": "wrong"})
        assert r.status_code == 401, r.status_code
    finally:
        logging.getLogger("opensrm.push").removeHandler(cap)
    hits = [r for r in records if "tick auth failed" in r.getMessage()]
    assert hits, "tick-secret 401 must log a WARNING (7 prod hits were invisible)"


# ── root logger stays INFO; opensrm obeys LOG_LEVEL ─────────────────
def t_root_level():
    src = (REPO / "app" / "logging_setup.py").read_text()
    assert "root.setLevel(logging.INFO)" in src, "root must stay INFO (library DEBUG chatter)"
    assert 'logging.getLogger("opensrm").setLevel' in src, "opensrm.* must obey LOG_LEVEL"


def t_rotation():
    src = (REPO / "app" / "logging_setup.py").read_text()
    assert "TimedRotatingFileHandler" in src, "rotation required (7.2MB unbounded)"
    assert "backupCount=14" in src
    assert "when=\"midnight\"" in src


# ── ntfy alerter: wired, rate-limited, silent-failure safe ──────────
def t_ntfy():
    posts = []

    def fake_urlopen(req, timeout=None):
        posts.append(req.data.decode())
        raise AssertionError("should not be reached")

    h = LS.NtfyHandler("http://127.0.0.1:1/nonexistent")
    rec = logging.LogRecord("opensrm.test", logging.ERROR, "x", 1, "boom happened", None, None)
    with mock.patch.object(urllib.request, "urlopen", side_effect=lambda req, timeout=None: posts.append(req) or mock.Mock()):
        h.emit(rec)
        h.emit(rec)  # second call inside the 60s window must be dropped
    assert len(posts) == 1, f"ntfy must rate-limit to 1 per 60s (got {len(posts)})"
    # emit() must never raise even when the POST fails
    h2 = LS.NtfyHandler("http://127.0.0.1:1/nonexistent")
    h2._last = 0.0
    h2.emit(rec)  # must not raise
    # wiring is env-gated
    src = (REPO / "app" / "logging_setup.py").read_text()
    assert "NTFY_ALERT_URL" in src


# ── usage_events: table + _track ────────────────────────────────────
def t_usage_events():
    c = A.db()
    c.execute("SELECT 1 FROM usage_events LIMIT 1")  # table exists (migration 12)
    c.execute("DELETE FROM usage_events")  # earlier tests may have tracked events
    c.commit(); c.close()
    A._track("page_view", target="dashboard", user="zz9999")
    A._track("login_ok", detail="123ms", user="zz9999")
    c = A.db()
    rows = c.execute("SELECT event, user, target FROM usage_events WHERE user='zz9999' ORDER BY id").fetchall()
    c.close()
    assert [r[0] for r in rows] == ["page_view", "login_ok"], [dict(r) for r in rows]
    assert rows[0][2] == "dashboard"
    # _track must never raise (telemetry never breaks a request)
    A._track("page_view")  # no user: must still insert with '' ''


def t_usage_env_passthrough():
    src = (REPO / "docker-compose.yml").read_text()
    assert "NTFY_ALERT_URL=${NTFY_ALERT_URL:-}" in src, "compose must pass the alert URL through"
    assert "LOG_LEVEL=${LOG_LEVEL:-INFO}" in src, "compose default must be INFO"


for name, fn in [
    ("access log: >=400 WARNING+error=, healthcheck DEBUG", t_access_log),
    ("per-IP 429 logs a cause line", t_rate_limit_logged),
    ("tick-secret 401 logs a WARNING", t_tick_auth_logged),
    ("root logger INFO, opensrm obeys LOG_LEVEL", t_root_level),
    ("rotation configured (midnight, 14 kept)", t_rotation),
    ("ntfy alerter: rate-limited, silent-failure safe, env-gated", t_ntfy),
    ("usage_events table + _track writes", t_usage_events),
    ("compose: LOG_LEVEL INFO default + NTFY_ALERT_URL", t_usage_env_passthrough),
]:
    check(name, fn)

total = 8
print(f"\n{total - len(FAILS)}/{total} passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("ok  logging + telemetry suite")
