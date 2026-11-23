"""The "when are people using it" number must count PEOPLE, per HOUR, not series.

The bug this pins: the panel used
`count(count by (uid) (rate(opensrm_active_users_total[1h])))`, which is a
Prometheus mistake with two separate halves.

1. `count by (uid)` COUNTS SERIES inside each uid group. There is one series
   per uid, so every group value is exactly 1 — never an event count.
2. `count(...)` of those groups is then "how many uid series exist", i.e. the
   all-time signup count. It only climbs: a deploy or a new user adds a series
   and nothing ever removes one.

Measured on prod: the panel read 11 while 1 person had been active in the last
5 minutes and 3 in the last hour.

The replacement metric is built from usage_events instead of a counter, so these
tests attack the query and the render path directly.

Runner style: plain script, check(name, fn), self-contained (temp SQLite, no
server, no network). CI: tests.yml unit job.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import metrics, observability  # noqa: E402

FAILS = []
TOTAL = [0]

# 2026-06-15 00:00 IST as a UTC epoch. Fixed so the buckets are checkable.
BASE_IST = 1781461800


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


def _db():
    """In-memory usage_events table with the columns the query reads."""
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE usage_events (
        id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, day TEXT NOT NULL DEFAULT '',
        user TEXT NOT NULL DEFAULT '', event TEXT NOT NULL DEFAULT '',
        target TEXT DEFAULT '', detail TEXT DEFAULT '')""")
    return c


def _ev(c, ts, user, event="page_view"):
    c.execute("INSERT INTO usage_events (ts, user, event) VALUES (?,?,?)",
              (ts, user, event))


def _by_hour(conn, now):
    """Run the real query against `now` instead of the wall clock."""
    real = observability._now_sql
    observability._now_sql = lambda: str(now)
    try:
        return {dict(labels)["hour"]: v
                for labels, v in observability._activity_by_hour(conn)}
    finally:
        observability._now_sql = real


def case_counts_people_not_events():
    c = _db()
    for _ in range(5):
        _ev(c, BASE_IST + 9 * 3600, "alice")          # 09:00, five events
    _ev(c, BASE_IST + 9 * 3600 + 1800, "bob")         # 09:30, same hour
    got = _by_hour(c, now=BASE_IST + 10 * 3600)
    assert got.get("09") == 2, (
        f"09:00 must be 2 PEOPLE (alice's 5 events collapse to 1), got {got}")
    assert len(got) == 1, f"only one hour has data, got {sorted(got)}"


def case_uses_ist_not_utc():
    c = _db()
    # 2026-06-15 18:30 UTC == 2026-06-16 00:00 IST -> bucket "00".
    utc = 1781548200
    _ev(c, utc, "carol")
    got = _by_hour(c, now=utc + 60)
    assert "00" in got, (
        f"18:30 UTC is 00:00 IST, expected bucket 00, got {sorted(got)}")


def case_window_excludes_old_rows():
    c = _db()
    now = BASE_IST + 2 * 86400 + 6 * 3600
    _ev(c, now - 8 * 86400, "ancient")   # 8 days back -> outside the 7d window
    _ev(c, now - 3600, "recent")         # 05:00 -> inside
    got = _by_hour(c, now=now)
    assert got == {"05": 1}, f"only the 05:00 row counts, got {got}"


def case_future_rows_ignored():
    """A row stamped after `now` must not count.

    Clock skew (or a restored backup from a box with a fast clock) would
    otherwise inflate the profile with activity that has not happened yet.
    """
    c = _db()
    now = BASE_IST + 6 * 3600
    _ev(c, now - 3600, "real")           # 05:00
    _ev(c, now + 3600, "from-the-future")  # 07:00, must be skipped
    got = _by_hour(c, now=now)
    assert got == {"05": 1}, f"the future row leaked in, got {got}"


def case_anonymous_excluded():
    c = _db()
    _ev(c, BASE_IST + 3600, "")                  # logged-out traffic
    _ev(c, BASE_IST + 3600, "dave")
    got = _by_hour(c, now=BASE_IST + 7200)
    assert sum(got.values()) == 1, (
        f"anonymous must not count as a person, got {got}")


def case_unreadable_source_renders_nothing():
    """A dead DB must produce NO lines, never a page of zeroes."""
    metrics.gauge_family("opensrm_test_broken", lambda: None)
    text = metrics.render()
    assert "opensrm_test_broken" not in text, "a None family must render nothing"


def case_series_is_renderable():
    metrics.gauge_family("opensrm_test_hours",
                         lambda: [((("hour", "07"),), 3), ((("hour", "09"),), 1)])
    text = metrics.render()
    assert 'opensrm_test_hours{hour="07"} 3' in text, text[-400:]
    assert 'opensrm_test_hours{hour="09"} 1' in text, text[-400:]


check("counts people, not events or series", case_counts_people_not_events)
check("buckets are IST hour-of-day, not UTC", case_uses_ist_not_utc)
check("7-day window excludes old rows", case_window_excludes_old_rows)
check("future-dated rows are ignored", case_future_rows_ignored)
check("anonymous traffic is not a person", case_anonymous_excluded)
check("unreadable source renders no series", case_unreadable_source_renders_nothing)
check("hour series renders with labels", case_series_is_renderable)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} passed")
sys.exit(1 if FAILS else 0)
