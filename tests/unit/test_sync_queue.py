"""Sync queue suite — bounded wait, login-before-refresh priority, waiter
positions, the timeout path, portal-budget buckets, and Playwright staying
serialized at any SYNC_MAX_CONCURRENCY.

Offline: the portal pipeline is stubbed everywhere (never the network), no
server, no browser. Barrier-driven: threads line up before racing for
slots, and one barrier lives INSIDE the pipeline so 'exactly C at once'
proves itself — a pool that under-admits breaks the barrier and fails
loudly instead of passing quietly. Runner style: check(name, fn) +
summary (test_metrics).
"""
import asyncio
import atexit
import os
import shutil
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

TMP = tempfile.mkdtemp(prefix="osrm-syncqueue-")   # test_audit_findings: no test DBs in-tree
os.environ["DATA_DIR"] = TMP
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

from app import app as A  # noqa: E402
from app import http_scraper as H  # noqa: E402
from app import metrics as M  # noqa: E402

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


def _wait_for(cond, timeout=5, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def _permit_free():
    got = A._scrape_lock.acquire(blocking=False)
    if got:
        A._scrape_lock.release()
    return got


def _reset():
    """Clear every gate that could refuse a sync, drain the queue, and
    verify no permit leaked from the previous test (a leaked permit would
    make the next test's assertions lie)."""
    A._portal_attempts.clear()
    A._portal_attempts_auth.clear()
    A._portal_attempts_pf.clear()
    A._portal_ip.clear()
    A._login_attempts.clear()
    A._preflight_last.clear()
    A._preflight_ip.clear()
    A._login_progress.clear()
    A._portal_ok()
    os.environ.pop("SYNC_QUEUE_WAIT_S", None)
    with A._queue_cond:
        A._sync_queue.clear()
    assert _permit_free(), "permit leaked by a previous test"


def _state():
    return {"lock": threading.Lock(), "active": 0, "max": 0, "order": [],
            "broken": False}


def _pipe(st, delay=0.05, block=None):
    """Stubbed H.fetch recording pipeline concurrency in st."""
    def fake(netid, password, helpers, cold=True, prepared=None, deadline=None):
        with st["lock"]:
            st["active"] += 1
            st["max"] = max(st["max"], st["active"])
            st["order"].append(netid)
        try:
            if block is not None:
                try:
                    block.wait(10)   # overlap proof: breaks if the pool under-admits
                except threading.BrokenBarrierError:
                    st["broken"] = True
                    return {"ok": False, "kind": "internal",
                            "error": "pipelines never overlapped (barrier broke)"}
            time.sleep(delay)
        finally:
            with st["lock"]:
                st["active"] -= 1
        return {"ok": True, "data": {}, "personal": {}, "courses": [],
                "marks": [], "subjects": []}
    return fake


def _run(n, fn, timeout=20):
    """n threads hit fn(i) together on a start barrier; returns results."""
    start = threading.Barrier(n, timeout=timeout)
    out = [None] * n

    def worker(i):
        start.wait()
        out[i] = fn(i)

    ths = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(timeout)
    assert not any(t.is_alive() for t in ths), "queued threads hung"
    return out


# ── 1. exactly C run at once, C = default 1 ────────────────────────────────
def t_serial_at_default_concurrency():
    _reset()
    st = _state()
    orig = H.fetch
    H.fetch = _pipe(st, delay=0.05)
    try:
        res = _run(6, lambda i: A.fetch_attendance(f"zzq100{i}", "pw"))
    finally:
        H.fetch = orig
    assert st["max"] == 1, \
        f"SYNC_MAX_CONCURRENCY=1 must run exactly one pipeline at a time, saw {st['max']}"
    assert len(st["order"]) == 6, \
        f"every queued sync must eventually run, got {len(st['order'])}/6: {st['order']}"
    assert all(r.get("ok") for r in res), [r.get("error") for r in res]
    assert A._sync_queue_depth() == 0, "the queue must drain after the burst"


# ── 2. exactly C run at once, C = 2 (the pool size is real) ────────────────
def t_pool_of_two_overlaps_two():
    _reset()
    st = _state()
    barrier = threading.Barrier(2, timeout=10)   # inside the pipeline
    orig_fetch, orig_lock = H.fetch, A._scrape_lock
    H.fetch = _pipe(st, delay=0.05, block=barrier)
    A._scrape_lock = threading.BoundedSemaphore(2)
    try:
        res = _run(4, lambda i: A.fetch_attendance(f"zzq200{i}", "pw"))
    finally:
        H.fetch, A._scrape_lock = orig_fetch, orig_lock
    assert not st["broken"], \
        "pool=2 must admit two pipelines concurrently (barrier never tripped)"
    assert st["max"] == 2, f"a pool of 2 must peak at exactly 2, saw {st['max']}"
    assert len(st["order"]) == 4 and all(r.get("ok") for r in res), st["order"]


# ── 3. ordering + priority: login before refresh ───────────────────────────
def t_login_parks_ahead_of_refresh():
    _reset()
    st = _state()
    orig = H.fetch
    H.fetch = _pipe(st, delay=0.02)
    assert A._scrape_lock.acquire(blocking=False), "slot must start free"
    held = True
    results = {}
    try:
        # a refresh arrives first and parks (slot busy)
        tr = threading.Thread(
            daemon=True,
            target=lambda: results.__setitem__(
                "refresh", A.fetch_attendance("zzq310", "pw", authorized=True)))
        tr.start()
        _wait_for(lambda: A._sync_queue_depth() == 1, what="refresh to park")
        # a login arrives second — it must park AHEAD of the refresh
        tl = threading.Thread(
            daemon=True,
            target=lambda: results.__setitem__(
                "login", A.fetch_attendance("zzq311", "pw", authorized=False)))
        tl.start()
        _wait_for(lambda: A._sync_queue_depth() == 2, what="login to park")
        assert A._sync_queue[0].prio == 0, \
            "the login must park ahead of the earlier-queued refresh"
        A._scrape_release()
        held = False
        tr.join(15)
        tl.join(15)
    finally:
        if held:
            A._scrape_release()
        H.fetch = orig
    order = st["order"]
    assert order == ["zzq311", "zzq310"], \
        f"login must be admitted before the refresh queued ahead of it, ran={order}"
    assert results["refresh"].get("ok") and results["login"].get("ok"), results


# ── 4. waiters publish their position to the progress tracker ──────────────
def t_waiters_publish_position():
    _reset()
    st = _state()
    orig = H.fetch
    H.fetch = _pipe(st, delay=0.05)
    os.environ["SYNC_QUEUE_WAIT_S"] = "30"
    assert A._scrape_lock.acquire(blocking=False), "slot must start free"
    held = True
    try:
        t1 = threading.Thread(daemon=True, target=lambda: A.fetch_attendance(
            "zzq410", "pw", attempt="tokq1"))
        t1.start()
        _wait_for(lambda: A._sync_queue_depth() == 1, what="first waiter")
        _wait_for(lambda: (A._login_progress.get("tokq1", {}).get("step") or "")
                  .startswith("Waiting for 1 ahead"),
                  what="first waiter's position publish")
        t2 = threading.Thread(daemon=True, target=lambda: A.fetch_attendance(
            "zzq411", "pw", attempt="tokq2"))
        t2.start()
        _wait_for(lambda: A._sync_queue_depth() == 2, what="second waiter")
        _wait_for(lambda: (A._login_progress.get("tokq2", {}).get("step") or "")
                  .startswith("Waiting for 2 ahead"),
                  what="second waiter's position publish")
        A._scrape_release()
        held = False
        t1.join(15)
        t2.join(15)
    finally:
        if held:
            A._scrape_release()
        H.fetch = orig
        os.environ.pop("SYNC_QUEUE_WAIT_S", None)
    # on admission the HTTP path takes over the same progress key
    assert (A._login_progress.get("tokq1", {}).get("step") or "") \
        .startswith("Connecting to SRM portal"), \
        f"admission must hand progress over to the pipeline, got {A._login_progress.get('tokq1')}"


# ── 5. the timeout path: busy kind, 503, metric, quota untouched ───────────
def t_timeout_returns_busy():
    _reset()
    M.reset()
    A._login_attempts.pop("zzq510", None)
    os.environ["SYNC_QUEUE_WAIT_S"] = "1"
    assert A._scrape_lock.acquire(blocking=False), "slot must start free"
    try:
        t0 = time.monotonic()
        res = A.fetch_attendance("zzq510", "pw")
        waited = time.monotonic() - t0
    finally:
        A._scrape_release()
        os.environ.pop("SYNC_QUEUE_WAIT_S", None)
    assert res.get("kind") == "busy" and A.sync_status(res) == 503, res
    assert "Sync in progress" in res["error"], res
    assert 0.8 <= waited <= 6, \
        f"a queued caller must WAIT before the busy answer, took {waited:.2f}s"
    assert A._sync_queue_depth() == 0, "a timed-out waiter must leave the queue"
    assert "zzq510" not in A._login_attempts, "a timeout must not consume the quota"
    assert M.get("opensrm_scrape_lock_rejections_total", op="sync") == 1, \
        "the timeout must count as a scrape-lock rejection"


# ── 6. bucket accounting: three buckets, totals at today's numbers ─────────
def t_budget_buckets():
    _reset()
    # per-IP share still binds inside the preflight bucket
    for _ in range(A._PORTAL_IP_CAP):
        assert A._check_portal_budget("7.7.7.1", bucket="preflight") is True
    assert A._check_portal_budget("7.7.7.1", bucket="preflight") is False, \
        "per-IP share cap must reject preflight"
    A._portal_attempts_pf.clear()
    A._portal_ip.clear()
    # preflight stops at its own share...
    for i in range(A._PORTAL_PREFLIGHT_CAP):
        assert A._check_portal_budget(f"8.8.{i}.1", bucket="preflight") is True
    assert A._check_portal_budget("8.8.88.1", bucket="preflight") is False, \
        "preflight must stop at its own cap"
    assert A._portal_attempts == [], \
        "preflight tokens must not land in the full-login bucket"
    # ...while login keeps the rest of the shared unauth pool (20 - 10)
    n = 0
    while A._check_portal_budget(f"6.6.6.{n}"):
        n += 1
    assert n == (A._PORTAL_CAP - A._PORTAL_AUTH_FLOOR) - A._PORTAL_PREFLIGHT_CAP, \
        f"login must fill the rest of the unauth pool, got {n}"
    # refresh reaches the unchanged aggregate: 20 unauth + 10 floor = 30
    m = 0
    while A._check_portal_budget(f"5.5.5.{m}", authorized=True):
        m += 1
    assert m == A._PORTAL_CAP - (A._PORTAL_CAP - A._PORTAL_AUTH_FLOOR), \
        f"refresh must reach the aggregate 30 minus unauth spent, got {m}"
    _reset()


# ── 7. preflight refusal = queue depth > 0 (not a held lock) ───────────────
def t_preflight_refused_by_queue_depth():
    _reset()
    cl = A.app.test_client()
    orig_pf = H.preflight
    spawned = []
    H.preflight = lambda netid: spawned.append(netid)
    try:
        # depth > 0 -> 503, no spawn, no recorded preflight, no token
        A._sync_queue.append(A._QueueWaiter(1))
        try:
            r = cl.post("/api/login/preflight", json={"netid": "zzq710"})
        finally:
            A._sync_queue.pop()
        assert r.status_code == 503, r.data
        assert spawned == [], "a refused preflight must not spawn work"
        assert "zzq710" not in A._preflight_last, "a refused preflight must not be recorded"
        assert A._portal_attempts_pf == [], "503 must spend no budget token"
        # depth 0 -> admitted
        r = cl.post("/api/login/preflight", json={"netid": "zzq711"})
        assert r.status_code == 200, r.data
        _wait_for(lambda: spawned == ["zzq711"], what="preflight thread to run")
        _wait_for(_permit_free, what="the preflight thread to release its slot")
    finally:
        H.preflight = orig_pf
        A._preflight_last.clear()
        A._preflight_ip.clear()


# ── 8. Playwright stays serialized whatever the pool size ──────────────────
def t_playwright_serialized_at_pool_two():
    _reset()
    st = _state()
    pyst = {"active": 0, "max": 0}
    barrier = threading.Barrier(2, timeout=10)
    orig_fetch, orig_pwfn, orig_lock = H.fetch, A._fetch_rich_optimized, A._scrape_lock

    def raise_to_fallback(netid, password, helpers, cold=True, prepared=None, deadline=None):
        with st["lock"]:
            st["order"].append(netid)
            st["active"] += 1
        try:
            barrier.wait(10)   # both syncs must be past admission together
        except threading.BrokenBarrierError:
            st["broken"] = True
            return {"ok": False, "kind": "internal",
                    "error": "pipelines never overlapped (barrier broke)"}
        finally:
            with st["lock"]:
                st["active"] -= 1
        raise H.HttpScraperError("transport boom")   # -> Playwright fallback

    async def fake_pw(netid, password, cold=True):
        pyst["active"] += 1
        pyst["max"] = max(pyst["max"], pyst["active"])
        await asyncio.sleep(0.1)      # yield: a missing _pw_lock lets the second in
        pyst["active"] -= 1
        return {"ok": False, "error": "captcha OCR failed — try again"}

    H.fetch = raise_to_fallback
    A._fetch_rich_optimized = fake_pw
    A._scrape_lock = threading.BoundedSemaphore(2)
    # the fallback is archived off by default — this test opts it in
    os.environ["PLAYWRIGHT_FALLBACK"] = "enabled"
    A._portal_ok()
    try:
        res = _run(2, lambda i: A.fetch_attendance(f"zzq810{i}", "pw"))
    finally:
        os.environ.pop("PLAYWRIGHT_FALLBACK", None)
        H.fetch, A._fetch_rich_optimized, A._scrape_lock = orig_fetch, orig_pwfn, orig_lock
        A._portal_ok()
    assert not st["broken"], \
        "pool=2 must overlap two syncs past admission (barrier never tripped)"
    assert pyst["max"] == 1, \
        f"the Playwright fallback must stay serialized at pool=2, saw {pyst['max']} concurrent"
    assert all(not r.get("ok") for r in res), res
    assert A._sync_queue_depth() == 0, "the queue must drain"


# ── 9. The fallback is archived off by default ────────────────────────────
def t_fallback_archived_by_default():
    """PLAYWRIGHT_FALLBACK unset (the shipped default): an HTTP pipeline
    failure must never reach the browser — typed portal_down result counted
    as pipeline=http, and the playwright path stays untouched."""
    _reset()
    st = _state()
    orig_fetch, orig_pw = H.fetch, A._fetch_rich_optimized

    def raise_transport(netid, password, helpers, cold=True, prepared=None, deadline=None):
        raise H.HttpScraperError("transport boom")

    def must_not_run(netid, password, cold=True):
        st["ran"] = True
        raise AssertionError("playwright fallback ran although PLAYWRIGHT_FALLBACK is unset")

    H.fetch = raise_transport
    A._fetch_rich_optimized = must_not_run
    M.reset()
    os.environ.pop("PLAYWRIGHT_FALLBACK", None)
    A._portal_ok()
    try:
        res = A.fetch_attendance("zzq9990", "pw")
    finally:
        H.fetch, A._fetch_rich_optimized = orig_fetch, orig_pw
        A._portal_ok()
    assert not st.get("ran"), "the archived playwright path must not run when the knob is unset"
    assert not res.get("ok"), res
    assert res.get("kind") == "portal_down", \
        f"a transport failure with the fallback archived must be portal_down, got {res!r}"
    got = M.get("opensrm_sync_total", pipeline="http", result="error", error="portal_down")
    assert got == 1, f"must count as pipeline=http error=portal_down, got {got}"
    assert M.get("opensrm_sync_total", pipeline="playwright", result="error", error="internal") == 0, \
        "no playwright-pipeline metric may be recorded while archived"


for name, fn in [
    ("exactly C run at once (default C=1, 6 racing threads)", t_serial_at_default_concurrency),
    ("exactly C run at once (pool=2, barrier inside the pipeline)", t_pool_of_two_overlaps_two),
    ("login parks ahead of an earlier refresh, runs first", t_login_parks_ahead_of_refresh),
    ("waiters publish 'Waiting for N ahead…' to the progress tracker", t_waiters_publish_position),
    ("queue timeout -> busy kind, 503, metric, quota untouched", t_timeout_returns_busy),
    ("budget buckets: preflight cap, shared unauth pool, aggregate 30", t_budget_buckets),
    ("preflight refused by queue depth > 0, admitted at 0", t_preflight_refused_by_queue_depth),
    ("Playwright fallback stays serialized at pool=2", t_playwright_serialized_at_pool_two),
    ("fallback archived by default: portal_down, no browser, pipeline=http", t_fallback_archived_by_default),
]:
    check(name, fn)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("ok  sync queue suite")
