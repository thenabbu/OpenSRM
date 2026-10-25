"""healthz suite — GET /healthz, the container healthcheck probe.

Offline: no portal, no network (socket.connect is booby-trapped in one check).
Self-contained: temp DATA_DIR + seed + mint here.

Contract (block A5 / healthz):
  * no auth — the probe works with no cookie AND with a real session
  * SELECT 1 on the DB is the whole job: no socket is ever opened
  * failure arm -> 503 {"status":"error"} (tiny body, nothing leaked)
  * _log_request demotes /healthz to DEBUG like the Python-urllib UA, so a
    30s poll can never fill opensrm.log again (the 2026-10-07 audit's
    66,003-line healthcheck problem); a 5xx still logs ERROR so ntfy pages
Runner style: check(name, fn) + dynamic TOTAL (test_metrics).
"""
import logging
import os
import socket
import sqlite3
import sys
import tempfile
import atexit
import shutil
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

TMP = tempfile.mkdtemp(prefix="osrm-healthz-")
os.environ["DATA_DIR"] = TMP   # test_audit_findings: no test DBs in-tree
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

from app import app as A           # noqa: E402
import app.db as DB                  # noqa: E402  (the connect() factory)
from _seed import mint_token, seed  # noqa: E402

FAILS = []
TOTAL = [0]


def check(name, fn):
    TOTAL[0] += 1
    try:
        fn()
        print(f"  ok  {name}")
    except AssertionError as e:
        FAILS.append(name)
        print(f"FAIL  {name}: {e}")
    except Exception as e:
        FAILS.append(name)
        print(f"FAIL  {name}: raised {type(e).__name__}: {e}")


class Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, r):
        self.records.append(r)


def _with_http_records(fn, level=logging.DEBUG):
    """Run fn(test_client) with every opensrm.http record captured, at `level`
    so DEBUG lines are not suppressed by LOG_LEVEL=INFO (log_with_kv gates on
    isEnabledFor). Restores the logger level afterwards."""
    lg = logging.getLogger("opensrm.http")
    cap = Cap()
    prev = lg.level
    lg.addHandler(cap)
    lg.setLevel(level)
    try:
        fn()
    finally:
        lg.removeHandler(cap)
        lg.setLevel(prev)
    return cap.records


# ── the probe itself ────────────────────────────────────────────────────────
def t_no_auth_tiny_body():
    seed()
    cl = A.app.test_client()
    r = cl.get("/healthz")
    assert r.status_code == 200, f"GET /healthz without a cookie must be 200, got {r.status_code}"
    assert r.get_json() == {"status": "ok"}, r.data
    assert r.headers.get("Content-Type", "").startswith("application/json"), r.headers.get("Content-Type")
    assert len(r.data) <= 32, f"health body must stay tiny, got {len(r.data)}B: {r.data!r}"


def t_auth_independent():
    seed()
    tok = mint_token()
    cl = A.app.test_client()
    cl.set_cookie("srm_session", tok)
    r = cl.get("/healthz")
    assert r.status_code == 200, f"a valid session must not change the probe: {r.status_code}"
    assert r.get_json() == {"status": "ok"}, r.data


def t_no_network_contact():
    """SELECT 1 on a file DB must be the entire job — no socket, no portal."""
    seed()
    cl = A.app.test_client()

    def boom(*a, **k):
        raise AssertionError("healthz opened a network connection")

    with mock.patch.object(socket.socket, "connect", boom):
        r = cl.get("/healthz")
    assert r.status_code == 200, r.status_code
    assert r.get_json() == {"status": "ok"}, r.data


def t_db_failure_is_503():
    seed()
    cl = A.app.test_client()

    def broken():
        raise sqlite3.OperationalError("disk I/O error")

    with mock.patch.object(DB, "connect", broken):
        r = cl.get("/healthz")
    assert r.status_code == 503, f"a dead DB must fail the probe, got {r.status_code}"
    body = r.get_json()
    assert body == {"status": "error"}, f"failure body must stay tiny and leak nothing: {body!r}"
    assert len(r.data) <= 40, len(r.data)


# ── logging: probe demoted, real fault still pages ──────────────────────────
def t_probe_demoted_to_debug():
    seed()
    cl = A.app.test_client()
    def hit():
        cl.get("/healthz")
        cl.get("/definitely-not-a-route")   # non-probe control in the same capture

    recs = _with_http_records(hit)
    probe_reqs = [r for r in recs if r.getMessage() == "request"
                  and getattr(r, "kv", {}).get("path") == "/healthz"]
    assert probe_reqs, f"no opensrm.http record for /healthz: {[r.getMessage() for r in recs]}"
    assert all(r.levelno == logging.DEBUG for r in probe_reqs), \
        f"/healthz must log at DEBUG (30s poll would fill the log otherwise): " \
        f"{[(r.levelno, r.getMessage()) for r in probe_reqs]}"
    # a non-probe request at the same level is NOT demoted — the gate is the path
    other = [r for r in recs if r.getMessage() == "request"
             and getattr(r, "kv", {}).get("path") != "/healthz"]
    assert other and any(r.levelno >= logging.INFO for r in other), \
        f"the demotion must be path-scoped, not global: {[getattr(r, 'kv', {}) for r in other]}"


def t_healthz_5xx_still_errors():
    """A failing probe IS a real fault — ERROR, so NtfyHandler pages."""
    seed()
    cl = A.app.test_client()

    def broken():
        raise sqlite3.OperationalError("database is locked")

    with mock.patch.object(DB, "connect", broken):
        recs = _with_http_records(lambda: cl.get("/healthz"))
    errs = [r for r in recs if r.levelno == logging.ERROR and r.getMessage() == "request"]
    assert errs, f"a 503 healthz must log at ERROR so ntfy pages: " \
                 f"{[(r.levelno, r.getMessage()) for r in recs]}"


for name, fn in [
    ("GET /healthz: no cookie -> 200, JSON {status:ok}, body <= 32B", t_no_auth_tiny_body),
    ("a valid session does not change the probe (auth-independent)", t_auth_independent),
    ("no socket is ever opened — SELECT 1 is the whole job", t_no_network_contact),
    ("DB failure -> 503 {status:error}, body leaks nothing", t_db_failure_is_503),
    ("/healthz request line logs at DEBUG, never INFO+", t_probe_demoted_to_debug),
    ("a 503 from /healthz still logs ERROR (ntfy pages on real faults)", t_healthz_5xx_still_errors),
]:
    check(name, fn)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("ok  healthz suite")
