"""First-paint gate for the Absences card — no stale card during a scope sync.

The bug this pins: the dashboard only knows the Detailed (hourwise) grid once
getHourwiseAttendance is stored, so a first login — or any visit whose blob is
older than the 30 min hot TTL — rendered the OLD monthly "Absences" card (hours
missed per date) for the whole sync wait and then swapped it under the user on
the post-sync refresh. Users reported having to pull-to-refresh to get the new
view; the real cause is that the pre-sync render is a *different card*, not a
slow one.

Contract pinned here:
  - state 'stale' / 'running' -> the Absences block is emitted inside a
    `data-scope-pending` wrapper carrying `hidden` (painted by nobody), so the
    user never sees the OLD card while a sync is in flight.
  - state 'complete' with hourwise stored -> Detailed attendance renders and no
    Absences wrapper is emitted at all (unchanged behaviour).
  - SCOPE off ('off') -> the wrapper carries no `hidden` class: the card is
    today's card, exactly as a non-SCOPE deployment shipped it.
  - the client poll budget covers a real cold sync (was 45 x 4s ~ 4 min and
    gave up silently while the server was still working).

Self-contained: temp DATA_DIR, seeded row + minted cookie, no server, no
network, fabricated netid (repo is public).
"""
import atexit
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

_td = tempfile.mkdtemp(prefix="osrm-attfp-")
atexit.register(shutil.rmtree, _td, True)
os.environ["DATA_DIR"] = _td          # direct assignment: stale env must not win
os.environ["OCR_PREWARM"] = "0"

from app import app as A  # noqa: E402

NETID = "zz9999"                      # fabricated — repo is public
DB = os.path.join(_td, "srm.db")

ATT = {
    "courses": [{"code": "21CSC201J", "description": "DATA STRUCTURES AND ALGORITHMS",
                 "max_hours": "46", "attended": "45", "absent": "1"}],
    "period": {"from": "20/Jul/2026", "to": "13/Oct/2026"},
    "monthly": [{"month": "OCT / 2026", "present": "19", "absent": "5",
                 "od_present": "0", "od_absent": "0", "ml": "0"}],
    "daily_absent": {"OCT / 2026": [{"date": "01-10-2026", "hours": "1"}]},
}
PERSONAL = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
            "Batch": "2025", "Semester": "III SEMESTER", "Section": "A"}
# two rows so the grid has a real month; shape follows getHourwiseAttendance
HOURWISE = {"data": [{"attendancedate": "02-Nov-2026", "h1": "P", "h2": "P", "h3": "A"},
                     {"attendancedate": "30-Oct-2026", "h1": "P", "h2": "A"}],
            "ts": 1760000000}


def _seed(scope_json, fetched_at):
    import sqlite3
    c = sqlite3.connect(DB)
    c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
                 attendance_json, last_fetch, scope_json, scope_fetched_at)
                 VALUES(?,?,?,?,?,?,?)""",
              (NETID, "pw", json.dumps(PERSONAL), json.dumps(ATT),
               int(time.time()), json.dumps(scope_json), fetched_at))
    # the hourwise join needs the group's timetable or it self-hides
    gk = A._group_key(PERSONAL)
    c.execute("""INSERT OR IGNORE INTO timetable_groups(group_key, program, batch, semester, section)
                 VALUES(?, 'CSE Cloud Computing', 2025, 3, 'A')""", (gk,))
    gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()[0]
    c.execute("DELETE FROM timetable_slots WHERE group_id=?", (gid,))
    for day in ("Monday", "Saturday"):
        for p in range(1, 4):
            c.execute("""INSERT INTO timetable_slots(group_id, day, period, subject_code, subject_name)
                         VALUES(?,?,?,?,?)""", (gid, day, p, "21CSC201J", "DATA STRUCTURES"))
    c.commit()
    c.close()


def _html(features=None):
    old = os.environ.get("SCOPE_FEATURES")
    if features is None:
        os.environ.pop("SCOPE_FEATURES", None)
    else:
        os.environ["SCOPE_FEATURES"] = features
    try:
        cl = A.app.test_client()
        cl.set_cookie("srm_session", A.make_session_token(NETID))
        return cl.get("/").get_data(as_text=True)
    finally:
        if old is None:
            os.environ.pop("SCOPE_FEATURES", None)
        else:
            os.environ["SCOPE_FEATURES"] = old


def _wrapper_class(html):
    """The class list on the data-scope-pending wrapper, or None when absent."""
    m = re.search(r'<div data-scope-pending class="([^"]*)"', html)
    return None if m is None else m.group(1)


def t_stale_hides_old_absences_card():
    # a fresh login: blob empty -> state 'stale', hourwise absent -> the server
    # WOULD render the Absences card; it must be marked hidden instead.
    _seed({}, 0)
    html = _html()
    assert 'data-scope-sync="stale"' in html, "expected a stale body marker"
    assert "<div class=\"att-h\">Absences</div>" in html, "card missing from markup"
    cls = _wrapper_class(html)
    assert cls is not None, "Absences wrapper [data-scope-pending] not emitted"
    assert "hidden" in cls.split(), f"old card NOT hidden while stale (class={cls!r})"


def t_complete_renders_detailed_and_drops_old_card():
    _seed({"getHourwiseAttendance": HOURWISE}, int(time.time()))
    html = _html()
    assert 'id="hourwise-months"' in html, "Detailed attendance grid missing"
    assert _wrapper_class(html) is None, "Absences card rendered alongside hourwise"


def t_scope_off_leaves_todays_card_untouched():
    _seed({}, 0)
    html = _html("off")
    assert 'data-scope-sync="off"' in html, "expected an off body marker"
    cls = _wrapper_class(html)
    assert cls is not None, "wrapper missing with SCOPE off"
    assert "hidden" not in cls.split(), \
        f"SCOPE off must render today's card (class={cls!r})"


def t_poll_budget_covers_a_real_cold_sync():
    js = Path(__file__).resolve().parent.parent.parent / "app" / "static" / "dash.js"
    src = js.read_text()
    m = re.search(r"MAX_TRIES\s*=\s*(\d+)", src)
    assert m, "MAX_TRIES not found in dash.js poll"
    tries = int(m.group(1))
    # 4s cadence, 8s once it backs off: the worst case must beat a measured
    # 27-31s cold sync by a wide margin (a 45-try cap was ~4 min and lost).
    worst_s = (10 * 4) + ((tries - 10) * 8)
    assert worst_s >= 900, f"poll gives up after {worst_s}s — too short for a cold sync"


TESTS = [
    ("stale state hides the old Absences card", t_stale_hides_old_absences_card),
    ("complete state renders Detailed, no old card", t_complete_renders_detailed_and_drops_old_card),
    ("SCOPE off leaves today's card untouched", t_scope_off_leaves_todays_card_untouched),
    ("poll budget covers a real cold sync", t_poll_budget_covers_a_real_cold_sync),
]

if __name__ == "__main__":
    failed = 0
    t0 = time.monotonic()
    for name, fn in TESTS:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed ({time.monotonic() - t0:.1f}s)")
    sys.exit(1 if failed else 0)
