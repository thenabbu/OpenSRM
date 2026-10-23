"""Observability suite — counters/timers, /internal/metrics auth,
usage_events retention, and every >=400 status line carrying error=.

Offline: the portal fetch is stubbed (never the network), no server, no
browser. Runner style: check(name, fn) + dynamic TOTAL (test_logging_telemetry).
"""
import json
import logging
import os
import sys
import tempfile
import time
import atexit
import shutil
import threading

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

TMP = tempfile.mkdtemp(prefix="osrm-metrics-")
os.environ["DATA_DIR"] = TMP   # test_audit_findings: no test DBs in-tree
# A10: offline — the held-slot test must refuse instantly (busy), never sit
# out the real SYNC_QUEUE_WAIT_S default (read per-request by fetch)
os.environ.setdefault("SYNC_QUEUE_WAIT_S", "0")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

from app import app as A           # noqa: E402
from app import http_scraper as H  # noqa: E402
from app import metrics as M       # noqa: E402

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


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, r):
        self.records.append(r)


# ── counters are thread-safe (contract: thread-safe in-process counters) ──
def t_thread_safety():
    M.reset()

    def worker():
        for _ in range(500):
            M.inc("opensrm_sync_total", pipeline="http", result="ok", error="")
            M.observe("opensrm_sync_duration_seconds", 0.01, pipeline="http")

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    got = M.get("opensrm_sync_total", pipeline="http", result="ok", error="")
    assert got == 4000, f"8x500 incs must total 4000, got {got}"
    assert M.hist_count("opensrm_sync_duration_seconds", pipeline="http") == 4000,         f"8x500 observes must total 4000, got {M.hist_count('opensrm_sync_duration_seconds', pipeline='http')}"


# ── sync outcome + duration via a stubbed fetch (never the network) ──────
def t_sync_counter_http_ok():
    M.reset()
    A._portal_ok()
    orig = H.fetch
    H.fetch = lambda *a, **k: {"ok": True, "data": {"courses": [{"code": "T1"}]},
                               "personal": {}, "courses": [], "marks": [{"code": "T1"}],
                               "subjects": {}, "fetched": int(time.time())}
    try:
        res = A.fetch_attendance("zz9999", "pw")
    finally:
        H.fetch = orig
    assert res.get("ok"), res
    got = M.get("opensrm_sync_total", pipeline="http", result="ok", error="")
    assert got == 1, f"pipeline=http result=ok must be 1, got {got}"
    d = M.hist_count("opensrm_sync_duration_seconds", pipeline="http")
    assert d == 1, f"duration timer must have 1 observation, got {d}"


def t_sync_counter_error_class():
    M.reset()
    A._portal_ok()
    orig = H.fetch
    H.fetch = lambda *a, **k: {"ok": False,
                               "error": "invalid credentials — check your NetID/password"}
    try:
        res = A.fetch_attendance("zz9991", "pw")
    finally:
        H.fetch = orig
    assert not res.get("ok"), res
    got = M.get("opensrm_sync_total", pipeline="http", result="error", error="auth")
    assert got == 1, f"error class auth must be counted, got {got}"
    other = M.get("opensrm_sync_total", pipeline="http", result="error", error="other")
    assert other == 0, f"no sync may fall into class other, got {other}"

    # typed results: kind (the KIND_STATUS vocabulary) wins as the label
    orig = H.fetch
    H.fetch = lambda *a, **k: A.sync_error("bad_credentials",
                                           "invalid credentials — check your NetID/password")
    try:
        res = A.fetch_attendance("zz9991b", "pw")
    finally:
        H.fetch = orig
    assert not res.get("ok"), res
    got = M.get("opensrm_sync_total", pipeline="http", result="error", error="bad_credentials")
    assert got == 1, f"typed kind must win as the error label, got {got}"


def t_sync_counter_playwright():
    M.reset()
    A._portal_ok()
    orig_fetch, orig_pw = H.fetch, A._fetch_rich_optimized

    def _raise(*a, **k):
        raise H.HttpScraperError("transport boom")

    async def _pw(netid, password, cold=True):
        return {"ok": False, "error": "captcha OCR failed — try again"}

    H.fetch = _raise
    A._fetch_rich_optimized = _pw
    try:
        res = A.fetch_attendance("zz9992", "pw")
    finally:
        H.fetch, A._fetch_rich_optimized = orig_fetch, orig_pw
        A._portal_ok()
    assert not res.get("ok"), res
    got = M.get("opensrm_sync_total", pipeline="playwright", result="error", error="captcha")
    assert got == 1,         f"HttpScraperError fallback must record pipeline=playwright error=captcha, got {got}"


def t_scrape_lock_rejection():
    M.reset()
    assert A._scrape_lock.acquire(blocking=False)
    try:
        res = A.fetch_attendance("zz9993", "pw")
    finally:
        A._scrape_lock.release()
    assert "Sync in progress" in res.get("error", ""), res
    got = M.get("opensrm_scrape_lock_rejections_total", op="sync")
    assert got == 1, f"a busy scrape lock must be counted, got {got}"


def t_preflight_fates():
    M.reset()
    orig = (H._route, H._make_opener, H._prepare)
    try:
        H._route = lambda: ("https://sp.srmist.edu.in", {})
        H._make_opener = lambda: (object(), object())
        H._prepare = lambda *a, **k: {"ocr": ""}          # OCR produces nothing
        H.preflight("zz9995")
        assert M.get("opensrm_preflight_total", outcome="wasted") == 1,             "empty-OCR preflight must count as wasted"
        H._prepare = lambda *a, **k: {"ocr": "1234"}
        H.preflight("zz9995")
        assert M.get("opensrm_preflight_total", outcome="ready") == 1,             "stored warm login must count as ready"
    finally:
        H._route, H._make_opener, H._prepare = orig
    H._PREFLIGHT["zz9995"] = {"opener": object(), "jar": object(),
                              "ctx": {"ocr": "1234"}, "ts": time.time()}
    assert H.take_preflight("zz9995") is not None, "fresh entry must be consumed"
    assert M.get("opensrm_preflight_total", outcome="consumed") == 1,         "fresh take must count as consumed"
    H._PREFLIGHT["zz9995"] = {"opener": object(), "jar": object(),
                              "ctx": {"ocr": "1234"}, "ts": time.time() - 999}
    assert H.take_preflight("zz9995") is None, "stale entry must be dropped"
    assert M.get("opensrm_preflight_total", outcome="wasted") == 2,         "stale take must count as wasted (stored but never consumed)"
    H._PREFLIGHT.pop("zz9995", None)


def t_parse_empty():
    M.reset()
    keys = ("_make_opener", "_req", "_login", "_jsp_post", "_exam_post",
            "exam_candidates", "_after_login")
    saved = {k: getattr(H, k) for k in keys}
    saved_pa, saved_pm = A.parse_attendance, A.parse_marks

    class _Jar(list):
        pass

    try:
        H._make_opener = lambda: (object(), _Jar())
        H._req = lambda opener, url, headers, data=None, timeout=25: (url, b"<html>stub</html>")
        H._login = lambda *a, **k: (True, None)
        H._jsp_post = lambda opener, base, xheaders, path, fid: (fid, "<html>%s</html>" % fid)
        H._exam_post = lambda *a, **k: None
        H.exam_candidates = lambda now=None: []
        H._after_login = lambda *a, **k: None
        helpers = {"portal_fail_once": lambda: None, "portal_ok": lambda: None,
                   "save_session": lambda n, j: None, "load_session": lambda n: None,
                   "clear_session": lambda n: None, "set_progress": lambda *a: None}

        # attendance page parses to nothing -> sync fails, counter fires
        A.parse_attendance = lambda html: {"courses": []}
        res = H.fetch("zz9994", "pw", helpers, cold=False)
        assert res.get("ok") is False and "Attendance page" in res.get("error", ""), res
        got = M.get("opensrm_parse_empty_total", page="attendance", pipeline="http")
        assert got == 1, f"attendance parse-empty must be counted, got {got}"

        # attendance parses, marks page parses to nothing -> sync ok, counter fires
        A.parse_attendance = lambda html: {"courses": [{"code": "T1", "name": "T"}], "monthly": []}
        A.parse_marks = lambda html: ([], {})
        res = H.fetch("zz9994", "pw", helpers, cold=False)
        assert res.get("ok") is True, res
        got = M.get("opensrm_parse_empty_total", page="marks", pipeline="http")
        assert got == 1, f"marks parse-empty must be counted, got {got}"
    finally:
        for k, v in saved.items():
            setattr(H, k, v)
        A.parse_attendance, A.parse_marks = saved_pa, saved_pm
        H._PREFLIGHT.clear()


# ── /internal/metrics auth: unset = off, bare 401, secret works ──────────
def t_metrics_auth():
    cap = _Cap()
    logging.getLogger("opensrm.metrics").addHandler(cap)
    cl = A.app.test_client()
    old = os.environ.pop("METRICS_SECRET", None)
    try:
        r = cl.get("/internal/metrics")
        assert r.status_code == 401 and r.data == b"", \
            f"secret unset -> endpoint OFF: got {r.status_code} body={r.data!r}"
        os.environ["METRICS_SECRET"] = "s3kr3t-metrics"
        r = cl.get("/internal/metrics")
        assert r.status_code == 401 and r.data == b"", \
            f"no header -> bare 401: got {r.status_code} body={r.data!r}"
        r = cl.get("/internal/metrics", headers={"X-Metrics-Token": "wrong"})
        assert r.status_code == 401 and r.data == b"", \
            f"wrong token -> bare 401: got {r.status_code} body={r.data!r}"
        r = cl.get("/internal/metrics", headers={"X-Metrics-Token": "wro\u00e9ng"})
        assert r.status_code == 401 and r.data == b"", \
            f"non-ASCII token must fail closed as bare 401 (audit #16 class): got {r.status_code}"
        M.reset()
        M.inc("opensrm_sync_total", pipeline="http", result="ok", error="")
        r = cl.get("/internal/metrics", headers={"X-Metrics-Token": "s3kr3t-metrics"})
        assert r.status_code == 200, f"valid token -> 200, got {r.status_code}"
        body = r.data.decode()
        assert "# TYPE opensrm_sync_total counter" in body, body[:300]
        assert 'opensrm_sync_total{error="",pipeline="http",result="ok"} 1' in body, body[:300]
        assert "opensrm_portal_cooldown_seconds" in body, "cooldown gauge must render"
        assert r.headers["Content-Type"].startswith("text/plain"), r.headers["Content-Type"]
    finally:
        if old is None:
            os.environ.pop("METRICS_SECRET", None)
        else:
            os.environ["METRICS_SECRET"] = old
        logging.getLogger("opensrm.metrics").removeHandler(cap)
    hits = [r for r in cap.records if "metrics auth failed" in r.getMessage()]
    assert hits, "every metrics auth failure must log a WARNING with its reason"


# ── usage_events retention: env-configurable, once a day, count logged ──
def t_usage_retention():
    os.environ.pop("USAGE_EVENTS_RETENTION_DAYS", None)
    assert A._usage_retention_days() == 365, \
        f"default retention must be 365 days, got {A._usage_retention_days()}"
    now = int(time.time())
    c = A.db()
    c.execute("DELETE FROM usage_events")
    c.execute("INSERT INTO usage_events(ts, day, user, event) VALUES(?,?,?,?)",
              (now - 400 * 86400, "2025-09-10", "", "ancient"))
    c.execute("INSERT INTO usage_events(ts, day, user, event) VALUES(?,?,?,?)",
              (now, "today", "", "fresh"))
    c.commit(); c.close()

    cap = _Cap()
    logging.getLogger("opensrm").addHandler(cap)
    try:
        A._usage_prune_last = 0.0
        A._track("retention_probe")
        c = A.db()
        rows = [r[0] for r in c.execute("SELECT event FROM usage_events").fetchall()]
        c.close()
        assert "ancient" not in rows and "fresh" in rows, \
            f"400d-old row must be pruned, fresh kept: {rows}"
        pruned = [r.getMessage() for r in cap.records if "usage_events pruned" in r.getMessage()]
        assert any("rows=1" in m and "retention_days=365" in m for m in pruned), \
            f"pruned count must be logged with the window: {pruned}"

        # at most once a day: a second _track in the same slot prunes nothing
        c = A.db()
        c.execute("INSERT INTO usage_events(ts, day, user, event) VALUES(?,?,?,?)",
                  (now - 400 * 86400, "2025-09-10", "", "ancient"))
        c.commit(); c.close()
        A._track("retention_probe")
        c = A.db()
        rows = [r[0] for r in c.execute("SELECT event FROM usage_events").fetchall()]
        c.close()
        assert "ancient" in rows, f"second prune in the same day must be a no-op: {rows}"
        A._usage_prune_last = 0.0     # next day: slot re-armed
        A._track("retention_probe")
        c = A.db()
        rows = [r[0] for r in c.execute("SELECT event FROM usage_events").fetchall()]
        c.close()
        assert "ancient" not in rows, f"re-armed slot must prune again: {rows}"

        # env override
        os.environ["USAGE_EVENTS_RETENTION_DAYS"] = "30"
        assert A._usage_retention_days() == 30, A._usage_retention_days()
        c = A.db()
        c.execute("INSERT INTO usage_events(ts, day, user, event) VALUES(?,?,?,?)",
                  (now - 40 * 86400, "old", "", "over30"))
        c.execute("INSERT INTO usage_events(ts, day, user, event) VALUES(?,?,?,?)",
                  (now - 10 * 86400, "ok", "", "under30"))
        c.commit(); c.close()
        A._usage_prune_last = 0.0
        A._track("retention_probe")
        c = A.db()
        rows = [r[0] for r in c.execute("SELECT event FROM usage_events").fetchall()]
        c.close()
        assert "over30" not in rows and "under30" in rows, \
            f"USAGE_EVENTS_RETENTION_DAYS=30 must keep 10d and drop 40d: {rows}"
    finally:
        os.environ.pop("USAGE_EVENTS_RETENTION_DAYS", None)
        logging.getLogger("opensrm").removeHandler(cap)
        A._usage_prune_last = 0.0


# ── every >=400 status line carries error= (the logging-gap rule) ────────
def t_status_line_reasons():
    cap = _Cap()
    logging.getLogger("opensrm.http").addHandler(cap)
    cl = A.app.test_client()
    try:
        r404 = cl.get("/definitely-not-a-route")
        assert r404.status_code == 404, r404.status_code
        rpf = cl.post("/api/login/preflight", json={"netid": "BAD-NETID!!"})
        assert rpf.status_code == 400, rpf.status_code
        rpg = cl.post("/api/login/progress", json={"attempt": "!!"})
        assert rpg.status_code == 400, rpg.status_code
        rtick = cl.post("/internal/push/tick")
        assert rtick.status_code == 401 and rtick.data == b"", \
            (rtick.status_code, rtick.data)
    finally:
        logging.getLogger("opensrm.http").removeHandler(cap)
    lines = [r for r in cap.records if r.getMessage() == "request"
             and getattr(r, "kv", {}).get("status", 0) >= 400]
    assert len(lines) >= 4, f"expected >=4 status lines, got {len(lines)}"
    missing = [dict(r.kv) for r in lines if not r.kv.get("error")]
    assert not missing, f">=400 status lines without error=: {missing}"
    kv = [dict(r.kv) for r in lines]
    assert any(k["status"] == 404 and k["error"] == "http_404" for k in kv), kv
    assert any(k["status"] == 400 and k["error"] == "invalid netid" for k in kv), kv
    assert any(k["status"] == 400 and k["error"] == "invalid attempt token" for k in kv), kv
    tick = [k for k in kv if k["status"] == 401 and "tick auth failed" in k["error"]]
    assert tick, \
        "the deliberately bare tick 401 must still carry its reason on the LOG line"


for name, fn in [
    ("counters + timers are thread-safe (8x500)", t_thread_safety),
    ("sync counter: pipeline http / ok + duration", t_sync_counter_http_ok),
    ("sync counter: error class auth, no junk class", t_sync_counter_error_class),
    ("sync counter: playwright fallback path", t_sync_counter_playwright),
    ("scrape-lock rejection counted", t_scrape_lock_rejection),
    ("preflight fates: ready/wasted/consumed", t_preflight_fates),
    ("parse-empty per page counted (attendance + marks)", t_parse_empty),
    ("/internal/metrics auth: off/unset, bare 401, secret 200", t_metrics_auth),
    ("usage_events retention: 365d default, env, once-a-day, logged", t_usage_retention),
    ("every >=400 status line carries error=", t_status_line_reasons),
]:
    check(name, fn)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("ok  observability suite")
