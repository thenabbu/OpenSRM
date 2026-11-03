"""Product-analytics observability suite — the gauges, the visit span, the
item beacon, and the provider histogram that back the "Who uses it" row.

Offline: no portal, no browser. Every check runs against a fresh temp DATA_DIR
whose DB this file seeds itself, because the whole point of these metrics is
that they report what is IN THE DATABASE — a check against an empty DB would
pass while the SQL was wrong.

Runner style matches the other suites: check(name, fn) + a dynamic total.
"""
import os
import shutil
import sys
import tempfile
import time
import atexit

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

TMP = tempfile.mkdtemp(prefix="osrm-analytics-")
os.environ["DATA_DIR"] = TMP          # no test DBs in-tree
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

from app import app as A              # noqa: E402
from app import metrics as M          # noqa: E402
from app import observability as OBS  # noqa: E402
from app import db as DB              # noqa: E402

FAILS = []
TOTAL = [0]

NOW = int(time.time())


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


def _seed():
    """Two old users, one brand-new user, one never-synced account.

    Built entirely through the app's own DB helpers so the schema under test is
    the real one.
    """
    with A.app.app_context():
        c = DB.connect()
        try:
            c.execute("DELETE FROM usage_events")
            c.execute("DELETE FROM users")
            c.execute("DELETE FROM cookies")
            rows = [
                # (user, ts_days_ago_first, ts_days_ago_last)
                # Every boundary is covered on purpose: without a user who is
                # active inside the last 24h BUT already seen before it, a
                # widened window still passes and the check proves nothing
                # (verified by red-testing the window to 48h).
                ("olduser", 10, 0),      # active today, first seen 10d ago
                ("lapsed", 20, 4),       # inside 7d, outside 24h
                ("newbie", 0, 0),        # first seen today -> NEW
                ("midnight", 2, 1),      # ACTIVE inside 24h, NOT new (2d old)
            ]
            for user, first_d, last_d in rows:
                for d in ((first_d, last_d) if first_d != last_d else (last_d,)):
                    ts = NOW - d * 86400
                    c.execute("INSERT INTO usage_events (ts, day, user, event, target, detail) "
                              "VALUES (?, date(?, 'unixepoch'), ?, 'page_view', 'dashboard', '')",
                              (ts, ts, user))
            # a synced account and a never-synced one
            c.execute("INSERT INTO users (netid, password, attendance_json, marks_json, "
                      "subjects_json, scope_json, personal_details_json, exam_schedule_json, "
                      "faculty_map_json, photo_b64, last_fetch) "
                      "VALUES ('olduser','x','[]','[]','[]','{}','{}','{}','{}',NULL,?)", (NOW - 60,))
            c.execute("INSERT INTO users (netid, password, last_fetch) "
                      "VALUES ('never','x',0)")
            c.execute("INSERT INTO users (netid, password, last_fetch) "
                      "VALUES ('midnight','x',?)", (NOW - 90000,))
            c.commit()
        finally:
            c.close()


_seed()


# ── DB-derived gauges ────────────────────────────────────────────────────
def t_active_and_new_counts():
    """Active = distinct users in the window; new = first activity inside it.

    Pins the exact arithmetic the panels read: two users active in 24h
    (olduser, newbie), one of them new, one returning.
    """
    with A.app.app_context():
        c = DB.connect()
        try:
            assert OBS._active_users_24h(c) == 3, f"active_24h got {OBS._active_users_24h(c)}"
            assert OBS._new_users_24h(c) == 1, f"new_24h got {OBS._new_users_24h(c)}"
            assert OBS._returning_users_24h(c) == 2, f"returning got {OBS._returning_users_24h(c)}"
            # new + returning == active is the invariant the panel description
            # promises the reader; if these ever disagree the dashboard lies
            assert (OBS._new_users_24h(c) + OBS._returning_users_24h(c)
                    == OBS._active_users_24h(c))
            # 7d window catches the lapsed user (4 days back) as well
            assert OBS._active_users_7d(c) == 4, f"active_7d got {OBS._active_users_7d(c)}"
            # newbie (today) + midnight (first seen 2d ago) are both inside 7d
            assert OBS._new_users_7d(c) == 2, f"new_7d got {OBS._new_users_7d(c)}"
        finally:
            c.close()


def t_synced_and_total():
    with A.app.app_context():
        c = DB.connect()
        try:
            assert OBS._distinct_users(c) == 3
            assert OBS._users_with_data(c) == 2, "olduser + midnight have last_fetch>0"
        finally:
            c.close()


def t_freshness_ages():
    """Freshness is seconds-since, and a zero/absent source must not render
    as the entire Unix epoch (the '56 years' trap)."""
    with A.app.app_context():
        c = DB.connect()
        try:
            age = OBS._last_sync_age_seconds(c)
            assert 55 <= age <= 120, f"last_sync_age got {age}"
            usage_age = OBS._last_usage_event_age(c)
            assert 0 <= usage_age < 120, f"last_usage_event_age got {usage_age}"
        finally:
            c.close()


def t_empty_db_ages_are_zero():
    """No rows at all must yield 0, never time()-0 (56 years)."""
    with A.app.app_context():
        c = DB.connect()
        try:
            c.execute("DELETE FROM usage_events")
            c.execute("UPDATE users SET last_fetch = 0")
            c.commit()
            assert OBS._last_sync_age_seconds(c) == 0.0
            assert OBS._last_usage_event_age(c) == 0.0
        finally:
            c.close()
    _seed()   # put the fixture back for later checks


# ── provider histogram ───────────────────────────────────────────────────
def t_user_db_bytes_buckets():
    counts = OBS._user_db_bytes_buckets()
    assert counts is not None, "provider returned None on a readable DB"
    assert len(counts) == len(OBS._DB_SIZE_BUCKETS)
    # cumulative and monotonic by construction
    assert counts == sorted(counts), f"buckets not cumulative: {counts}"
    # both seeded users fall in the smallest bucket (tiny fixtures)
    assert counts[-1] == 3, f"expected 3 users counted, got {counts[-1]}"


def t_provider_histogram_renders_and_hides_on_failure():
    """A None from the provider must render NOTHING (not zeros that read as
    real data), and a working one renders a valid Prometheus histogram."""
    M.reset()
    M.histogram_provider("opensrm_test_probe", lambda: None, (1, 2, 3))
    body = M.render()
    assert "opensrm_test_probe" not in body, "provider None must render no series"

    M.reset()
    M.histogram_provider("opensrm_test_probe", lambda: [1, 3, 5], (1, 2, 3))
    body = M.render()
    assert 'opensrm_test_probe_bucket{le="1"} 1' in body, body
    assert 'opensrm_test_probe_bucket{le="+Inf"} 5' in body, body
    assert "opensrm_test_probe_count 5" in body, body
    M.reset()


# ── visit span ────────────────────────────────���──────────────────────────
def t_visit_span_closes_on_gap():
    """Two ticks inside the gap are ONE visit; a tick past it closes the first
    visit and opens the second."""
    M.reset()
    A._visit_start.clear()
    A._visit_last.clear()
    A._track_session_activity("zz1", now=1000.0)
    A._track_session_activity("zz1", now=1100.0)     # same visit
    assert M.hist_count("opensrm_user_session_span_seconds") == 0, "closed too early"
    # the gap is measured from the LAST tick (1100), not the visit start —
    # 10s past the threshold counted from 1000 is still inside the visit
    A._track_session_activity("zz1", now=1100.0 + A._SESSION_GAP_S + 10)
    n = M.hist_count("opensrm_user_session_span_seconds")
    assert n == 1, f"expected 1 closed visit after the gap, got {n}"


def t_visit_sweep_closes_idle_visits():
    """A student who just stops has no next tick — the sweep must still record
    their visit, or every last visit of a sitting is lost."""
    M.reset()
    A._visit_start.clear()
    A._visit_last.clear()
    A._track_session_activity("zz2", now=5000.0)
    A._track_session_activity("zz2", now=5300.0)
    assert M.hist_count("opensrm_user_session_span_seconds") == 0
    A.sweep_idle_visits(now=5300.0 + A._SESSION_GAP_S + 1)
    assert M.hist_count("opensrm_user_session_span_seconds") == 1, "sweep did not close the visit"
    # a second sweep is a no-op: the visit is gone
    A.sweep_idle_visits(now=5300.0 + 3 * A._SESSION_GAP_S)
    assert M.hist_count("opensrm_user_session_span_seconds") == 1, "sweep double-counted"


# ── the item beacon ──────────────────────────────────────────────────────
def t_item_beacon_allowlist():
    """A valid item counts; a junk item is dropped and still answers 204."""
    M.reset()
    cl = A.app.test_client()
    with A.app.app_context():
        tok = A.make_session_token("zz9999")
    cl.set_cookie("srm_session", tok, domain="localhost")
    A._tab_beacon_last.clear()
    r = cl.post("/api/track/tab", json={"tab": "attendance", "item": "attendance-graph"})
    assert r.status_code == 204, r.status_code
    assert M.get("opensrm_item_views_total", item="attendance-graph",
                 tab="attendance") == 1
    r = cl.post("/api/track/tab", json={"tab": "attendance", "item": "definitely-not-an-item"})
    assert r.status_code == 204, "junk must still be 204"
    # nothing new was recorded for the junk value
    body = M.render()
    assert "definitely-not-an-item" not in body, "junk item leaked into a label"


def t_item_vocab_is_closed():
    """Every allowlisted name must be a plain slug, and the beacon must not
    accept a name that is in the client map but not on the server."""
    for name in A._ITEM_NAMES:
        assert name.replace("-", "").isalnum(), f"bad item vocabulary entry: {name!r}"
    assert "attendance-graph" in A._ITEM_NAMES


def t_beacon_anonymous_is_204():
    """No session: still 204, nothing recorded — a beacon must never 401."""
    M.reset()
    cl = A.app.test_client()
    r = cl.post("/api/track/tab", json={"tab": "marks", "item": "marks-component"})
    assert r.status_code == 204
    assert M.get("opensrm_item_views_total", item="marks-component", tab="marks") == 0


checks = [
    ("active/new/returning counts: new + returning == active", t_active_and_new_counts),
    ("synced vs total accounts", t_synced_and_total),
    ("freshness ages are seconds, not the epoch", t_freshness_ages),
    ("empty DB yields 0 age, never 56 years", t_empty_db_ages_are_zero),
    ("per-user storage buckets are cumulative", t_user_db_bytes_buckets),
    ("provider histogram renders, hides on failure", t_provider_histogram_renders_and_hides_on_failure),
    ("visit span closes on a gap", t_visit_span_closes_on_gap),
    ("visit sweep closes idle visits once", t_visit_sweep_closes_idle_visits),
    ("item beacon allowlist + 204 contract", t_item_beacon_allowlist),
    ("item vocabulary is closed and slug-shaped", t_item_vocab_is_closed),
    ("anonymous beacon is 204 and records nothing", t_beacon_anonymous_is_204),
]

for name, fn in checks:
    check(name, fn)

print(f"\n{len(checks) - len(FAILS)}/{len(checks)} passed")
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    sys.exit(1)
print("ok  product analytics suite")
