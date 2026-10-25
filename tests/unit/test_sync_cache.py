"""Sync-cache suite — SYNC_MIN_INTERVAL_S window + per-netid single flight
on /api/refresh.

Offline: fetch_attendance is stubbed wherever a sync must really run; the
portal is never touched. Self-contained: temp DATA_DIR + seed + mint here.
Contract pinned (block A9 PROOF):
  * a refresh inside the window answers {ok, cached, age_s} — zero portal
    calls, zero quota charges, one kv line + metrics + usage event
  * expired window / window 0 / never-synced -> a real sync runs; a login
    always syncs, window or not
  * N concurrent refreshes for one netid make exactly ONE portal call:
    joiners wait on the runner's flight, share its result, and the
    per-netid quota moves exactly once (the runner's charge)
  * a joiner whose runner outlives the wait falls back to today's busy 503
Runner style: check(name, fn) + dynamic TOTAL (test_metrics).
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

TMP = tempfile.mkdtemp(prefix="osrm-synccache-")
os.environ["DATA_DIR"] = TMP   # test_audit_findings: no test DBs in-tree
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

from app import app as A           # noqa: E402
from app import metrics as M       # noqa: E402
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


def _fake():
    """A complete ok sync payload (fault_handling's FAKE_EMPTY shape) with a
    fresh fetch timestamp — persist_sync writes it as users.last_fetch."""
    return {"ok": True, "data": {"courses": [], "monthly": [], "period": None},
            "personal": {}, "photo": "", "courses": [], "marks": [],
            "subjects": {}, "fetched": int(time.time())}


def _prepare(window, last_fetch):
    """Fresh seed: window env, password, and the requested last_fetch."""
    if window is None:
        os.environ.pop("SYNC_MIN_INTERVAL_S", None)
    else:
        os.environ["SYNC_MIN_INTERVAL_S"] = str(window)
    seed()
    c = A.db()
    c.execute("UPDATE users SET password=?, last_fetch=? WHERE netid='zz9999'",
              (A.encrypt_pw("pw"), last_fetch))
    c.execute("DELETE FROM usage_events WHERE event='sync_cached'")
    c.commit()
    c.close()
    M.reset()


def _post():
    cl = A.app.test_client()
    cl.set_cookie("srm_session", mint_token())
    r = cl.post("/api/refresh")
    return r


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, r):
        self.records.append(r)


def _with_auth_log(fn):
    cap = _Cap()
    lg = logging.getLogger("opensrm.auth")
    lg.addHandler(cap)
    try:
        return fn(), cap
    finally:
        lg.removeHandler(cap)


def _quota():
    return list(A._login_attempts.get("zz9999", []))


# ── 1. a refresh inside the window: cached answer, portal untouched ───
def t_cached_answer_inside_interval():
    _prepare(600, int(time.time()) - 120)
    calls = []
    orig = A.fetch_attendance
    A.fetch_attendance = lambda n, p, **kw: (calls.append(n), _fake())[1]
    try:
        (r, cap) = _with_auth_log(_post)
    finally:
        A.fetch_attendance = orig
    j = r.get_json() or {}
    assert r.status_code == 200 and j.get("ok") is True, r.data[:200]
    assert j.get("cached") is True, f"inside the window the answer must carry cached=true: {j}"
    assert isinstance(j.get("age_s"), int) and 115 <= j["age_s"] <= 130, \
        f"age_s must be ~120 (the seeded last_fetch): {j.get('age_s')}"
    assert calls == [], f"a cache hit must make ZERO portal calls, made: {calls}"
    assert _quota() == [], f"cache hits must not move the per-netid quota: {_quota()}"
    assert M.get("opensrm_sync_cached_total") == 1, \
        f"cached answer must bump opensrm_sync_cached_total: {M.get('opensrm_sync_cached_total')}"
    kv_hits = [getattr(x, "kv", {}) for x in cap.records
               if x.getMessage() == "sync cached"]
    assert any(h.get("netid") == "zz9999" and h.get("window_s") == 600
               and isinstance(h.get("age_s"), int) for h in kv_hits), \
        f"cached answer must log one key=value line (netid/age_s/window_s), got: {kv_hits}"
    c = A.db()
    n = c.execute("SELECT COUNT(*) FROM usage_events WHERE user='zz9999' "
                  "AND event='sync_cached'").fetchone()[0]
    c.close()
    assert n == 1, f"exactly one sync_cached usage event per cached answer, got {n}"


# ── 2. expired window -> the sync really runs (plain ok, no cached) ────
def t_expired_window_runs_sync():
    _prepare(600, int(time.time()) - 900)
    calls = []
    orig = A.fetch_attendance
    A.fetch_attendance = lambda n, p, **kw: (calls.append(n), _fake())[1]
    try:
        r = _post()
    finally:
        A.fetch_attendance = orig
    j = r.get_json() or {}
    assert r.status_code == 200 and j.get("ok") is True, r.data[:200]
    assert not j.get("cached"), f"a real sync must not be marked cached: {j}"
    assert calls == ["zz9999"], f"expired window must run exactly one sync: {calls}"


# ── 3. window 0 disables the cache; unset -> data-derived default 300 ──
def t_window_disabled_and_default():
    _prepare(0, int(time.time()) - 5)   # fresh last_fetch, window off
    calls = []
    orig = A.fetch_attendance
    A.fetch_attendance = lambda n, p, **kw: (calls.append(n), _fake())[1]
    try:
        r = _post()
    finally:
        A.fetch_attendance = orig
    j = r.get_json() or {}
    assert r.status_code == 200 and j.get("ok") is True and not j.get("cached"), \
        f"SYNC_MIN_INTERVAL_S=0 must disable the window: {j}"
    assert calls == ["zz9999"], f"window 0 must always sync: {calls}"
    os.environ.pop("SYNC_MIN_INTERVAL_S", None)
    assert A._sync_min_interval_s() == 300, "unset env must fall back to the default 300"
    os.environ["SYNC_MIN_INTERVAL_S"] = "900"
    assert A._sync_min_interval_s() == 900, "integer env must be honoured"
    os.environ["SYNC_MIN_INTERVAL_S"] = "-5"
    assert A._sync_min_interval_s() == 0, "negative disables like 0"
    os.environ["SYNC_MIN_INTERVAL_S"] = "abc"
    assert A._sync_min_interval_s() == 300, "non-integer falls back to the default"


# ── 4. N concurrent refreshes -> ONE portal call, quota charged once ───
def t_single_flight_one_portal_call():
    _prepare(0, int(time.time()) - 99999)   # window off: prove the FLIGHT
    calls = []
    entered = threading.Event()
    release = threading.Event()

    def runner_fetch(n, p, **kw):
        calls.append(n)
        A._charge_rate(n)        # the real quota counter: only a runner charges
        entered.set()
        assert release.wait(30), "test never released the runner"
        return _fake()

    orig = A.fetch_attendance
    A.fetch_attendance = runner_fetch
    NJOIN = 5
    results = {}
    cap = _Cap()
    lg = logging.getLogger("opensrm.auth")
    lg.addHandler(cap)

    def post(tag):
        try:
            r = _post()
            results[tag] = (r.status_code, r.get_json() or {})
        except Exception as e:            # noqa: BLE001 — surfaced by the asserts
            results[tag] = ("exc", repr(e))

    try:
        leader = threading.Thread(target=post, args=("leader",))
        leader.start()
        assert entered.wait(10), "runner never reached fetch_attendance"
        joiners = [threading.Thread(target=post, args=(f"j{i}",)) for i in range(NJOIN)]
        for t in joiners:
            t.start()
        # deterministic barrier: a joiner increments the counter the moment
        # it parks on the runner's flight — release only once they all did
        deadline = time.time() + 10
        while M.get("opensrm_sync_joined_total") < NJOIN and time.time() < deadline:
            time.sleep(0.02)
        assert M.get("opensrm_sync_joined_total") == NJOIN, \
            f"joiners never parked on the flight: joined={M.get('opensrm_sync_joined_total')}"
        release.set()
        leader.join(30)
        for t in joiners:
            t.join(30)
        assert not leader.is_alive() and not any(t.is_alive() for t in joiners), "a thread hung"
        assert len(results) == NJOIN + 1, f"missing responses: {sorted(results)}"
        assert len(calls) == 1, \
            f"{NJOIN + 1} concurrent refreshes must make ONE portal call, made {len(calls)}: {results}"
        for tag, (code, j) in results.items():
            assert code == 200 and j.get("ok") is True, f"{tag}: {code} {j}"
            assert not j.get("cached"), f"{tag} shares the runner's REAL result, not a cache hit: {j}"
        assert len(_quota()) == 1, \
            f"quota must move exactly once (runner only): {len(_quota())} entries"
        joined_logs = [getattr(x, "kv", {}) for x in cap.records
                       if x.getMessage() == "sync joined"]
        assert len(joined_logs) == NJOIN and all(h.get("outcome") == "shared" for h in joined_logs), \
            f"each joiner must log sync joined outcome=shared: {joined_logs}"
    finally:
        lg.removeHandler(cap)
        release.set()
        A.fetch_attendance = orig


# ── 5. joiner whose runner outlives the wait -> today's busy 503 ───────
def t_flight_timeout_falls_back_to_busy():
    _prepare(0, int(time.time()) - 99999)
    entered = threading.Event()
    release = threading.Event()
    orig_fetch = A.fetch_attendance
    orig_wait = A._SYNC_FLIGHT_WAIT_S

    def slow_fetch(n, p, **kw):
        entered.set()
        assert release.wait(30), "test never released the runner"
        return _fake()

    A.fetch_attendance = slow_fetch
    A._SYNC_FLIGHT_WAIT_S = 0.2
    out = {}

    def post(tag):
        r = _post()
        out[tag] = (r.status_code, r.get_json() or {})

    try:
        leader = threading.Thread(target=post, args=("leader",))
        leader.start()
        assert entered.wait(10), "runner never reached fetch_attendance"
        jnr = threading.Thread(target=post, args=("joiner",))
        jnr.start()
        jnr.join(15)
        release.set()
        leader.join(15)
        assert "joiner" in out and "leader" in out, f"missing: {sorted(out)}"
        code, j = out["joiner"]
        assert code == 503 and j.get("ok") is False and "Sync in progress" in str(j.get("error", "")), \
            f"a joiner past the wait must fall back to the busy answer: {code} {j}"
        assert out["leader"][0] == 200 and out["leader"][1].get("ok") is True, \
            f"runner must still succeed: {out['leader']}"
    finally:
        release.set()
        A.fetch_attendance = orig_fetch
        A._SYNC_FLIGHT_WAIT_S = orig_wait


# ── 6. a real login always syncs, window or not ────────────────────────
def t_login_always_syncs():
    _prepare(600, int(time.time()) - 10)   # window satisfied for refresh
    calls = []
    orig = A.fetch_attendance
    A.fetch_attendance = lambda n, p, **kw: (calls.append(n), _fake())[1]
    try:
        cl = A.app.test_client()
        r = cl.post("/api/login", json={"netid": "zz9999", "password": "pw"})
    finally:
        A.fetch_attendance = orig
    j = r.get_json() or {}
    assert r.status_code == 200 and j.get("ok") is True, r.data[:200]
    assert calls == ["zz9999"], f"a login with credentials must always sync: {calls}"
    assert "srm_session" in (r.headers.get("Set-Cookie") or ""), "login must set the session cookie"


for name, fn in [
    ("refresh inside SYNC_MIN_INTERVAL_S answers cached, portal+quota untouched, kv+metric+usage", t_cached_answer_inside_interval),
    ("expired window runs a real sync (no cached flag)", t_expired_window_runs_sync),
    ("window 0 disables the cache; env parsing (unset 300 / 900 / -5 / abc)", t_window_disabled_and_default),
    ("N concurrent refreshes = ONE portal call, quota charged once, shared result", t_single_flight_one_portal_call),
    ("joiner past the wait falls back to busy 503, runner still succeeds", t_flight_timeout_falls_back_to_busy),
    ("login with credentials always syncs inside the window", t_login_always_syncs),
]:
    check(name, fn)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("ok  sync-cache suite")
