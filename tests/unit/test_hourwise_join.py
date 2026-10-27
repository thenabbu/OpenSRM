"""Hourwise join — self-contained suite (temp DATA_DIR, seeded in-test).

Covers the join contract (DESIGN-followed grid, "Detailed attendance"):
weekday match against the user's group slots, missing hour key = no class
(never an absence), OD never counted as absent, slot-miss fallback (NULL code
/ CL / custom / no row) = state kept but no subject name, period 7 unknown
when the timetable has one (never a state), weekend rows unnamed, the
per-subject cross-check vs fixtures/scope-attendance-subject.txt (tolerance
±1, documented in t_cross_check_subject_totals), the month grid shape, and
the gate: OFF / empty scope / no group all render the Absences card exactly
as on main (chip text asserted verbatim) with no detailed section.

Fixture rows = tests/fixtures/scope-attendance-hour.txt (byte-copy of the
mission's LIVE getHourwiseAttendance output); slots = the seeded group's
timetable (GRID fit, shared with scripts/seed_hourwise.py).
Run: .venv/bin/python tests/unit/test_hourwise_join.py  (offline, no server)
"""
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# the audit suite forbids test-DB files in the repo root / tests dir; mkdtemp
# so the DB dir outlives this module-level test body
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="osrm-hourwise-")

from app.app import _hourwise_data, hourwise_view  # noqa: E402  (DATA_DIR first)
from app import app as A  # noqa: E402
from app.db import day_slots, group_id, group_subjects  # noqa: E402

# the seed module is the single source of GRID + fixture wiring (dev server too)
_spec = importlib.util.spec_from_file_location(
    "seed_hourwise", REPO / "scripts" / "seed_hourwise.py")
seedmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seedmod)

NETID = "zzhw01"
FIX_ROWS = seedmod.load_hourwise_rows()          # 61 fixture rows + 3 probes
PORTAL = {s["subjectcode"]: int(s["absent"]) for s in seedmod.load_subjects()}
CLIENT = A.app.test_client()

seedmod.seed(NETID)
GK = A._group_key(seedmod.PERSONAL)
TOK = A.make_session_token(NETID)
CLIENT.set_cookie("srm_session", TOK)
SLOTS = day_slots(GK)                            # the seeded group's slots
CUSTOM = {r[0] for r in group_subjects(group_id(GK)) if r[3] and r[0]}
JOIN = hourwise_view(FIX_ROWS, SLOTS, CUSTOM)    # pure join over fixture rows
BY_LABEL = {m["label"]: m for m in JOIN["months"]}


def _day(date):
    """The grid row for a `dd Mon` date, whatever month it sits in."""
    for m in JOIN["months"]:
        for d in m["days"]:
            if d["date"] == date:
                return d
    raise AssertionError(f"no grid row for {date}")


def _cell(date, n):
    return next(c for c in _day(date)["cells"] if c["n"] == n)


def _get(env=None):
    prev = os.environ.get("SCOPE_FEATURES")
    if env is None:
        os.environ.pop("SCOPE_FEATURES", None)
    else:
        os.environ["SCOPE_FEATURES"] = env
    try:
        return CLIENT.get("/").get_data(as_text=True)
    finally:
        if prev is None:
            os.environ.pop("SCOPE_FEATURES", None)
        else:
            os.environ["SCOPE_FEATURES"] = prev


# ── join rules ──────────────────────────────────────────────────────────────
def t_fixture_weekday_match():
    """Every A cell joins the group's slot for that weekday + period."""
    # 15-Oct-2026 = Thursday, Thu p1 = 21CSC201J
    c = _cell("15 Oct", 1)
    assert c["state"] == "A" and c["code"] == "21CSC201J", c
    assert "DATA STRUCTURES AND ALGORITHMS" in c["subject"], c
    # 14-Oct-2026 = Wednesday: h1 = Wed p1 (OS), h2 = Wed p2 (MATH)
    assert _cell("14 Oct", 1)["code"] == "21CSC202J", _cell("14 Oct", 1)
    assert _cell("14 Oct", 2)["code"] == "21MAB206T", _cell("14 Oct", 2)
    # every A cell in the grid is an hour the scope row literally says "A"
    rows = {r["attendancedate"]: r for r in FIX_ROWS if "attendancedate" in r}
    from datetime import datetime
    disp = {datetime.strptime(d, "%d-%b-%Y").strftime("%d %b"): r for d, r in rows.items()}
    for m in JOIN["months"]:
        for d in m["days"]:
            for c in d["cells"]:
                if c["state"] == "A":
                    assert disp[d["date"]]["h%d" % c["n"]] == "A", (d["date"], c)


def t_missing_key_no_class():
    """Missing hour key = no class scheduled: empty cell, never P or A."""
    out = hourwise_view([{"attendancedate": "09-Nov-2026", "h1": "A"}], SLOTS, CUSTOM)
    day = out["months"][0]["days"][0]
    assert day["date"] == "09 Nov" and day["cells"][0]["state"] == "A", day
    assert all(c["state"] is None for c in day["cells"][1:]), day["cells"]
    # fixture 10-Oct has NO h4 key -> h4 empty, and never named
    assert _cell("10 Oct", 4)["state"] is None, _cell("10 Oct", 4)


def t_od_never_absent():
    """OD is on-duty, not an absence: its own state, counted separately."""
    assert _cell("05 Nov", 1)["state"] == "OD", _cell("05 Nov", 1)
    assert _cell("05 Nov", 2)["state"] == "A", _cell("05 Nov", 2)
    nov = [m for m in JOIN["months"] if any(d["date"] == "05 Nov" for d in m["days"])][0]
    assert nov["od"] >= 1, nov


def t_slot_miss_bare_fallback():
    """NULL code / CL / custom / no slot row -> state kept, name dropped."""
    slots = {"Monday": {1: {"code": "", "name": "JUNK"},
                        2: {"code": "CL", "name": "CLASS IN CHARGE"},
                        3: {"code": "CCLAB99", "name": "CLOUD COMPUTING LAB"}}}
    row = [{"attendancedate": "12-Oct-2026", "h1": "A", "h2": "A",
            "h3": "A", "h4": "A"}]  # 12-Oct-2026 = Monday; h4 has no slot row
    out = hourwise_view(row, slots, custom={"CCLAB99"})
    cells = out["months"][0]["days"][0]["cells"]
    assert [c["state"] for c in cells] == ["A"] * 4, cells
    assert all(c["subject"] is None for c in cells), cells
    assert cells[0]["title"].endswith("no subject on the timetable"), cells[0]


def t_period7_unknown():
    """SCOPE has no h7: a legacy Thu-p7 timetable slot must never name it —
    the probe row's h7 is empty and unnamed, and the h7 column stays empty
    for every other date (a junk h7 value is not a state either)."""
    assert SLOTS.get("Thursday", {}).get(7), "seed must carry the legacy p7 slot"
    c = _cell("06 Nov", 7)
    assert c["state"] is None and c["subject"] is None, c
    assert all(_cell(d["date"], 7)["state"] is None for d in _all_days()), "h7 never a state"
    out = hourwise_view([{"attendancedate": "09-Nov-2026", "h7": "A"}], SLOTS, CUSTOM)
    assert out["months"][0]["days"][0]["cells"][-1]["state"] is None, out["hours"]


def _all_days():
    return [d for m in JOIN["months"] for d in m["days"]]


def t_weekend_row_unnamed():
    """Saturday row: states render, but no weekday slots -> no subject name."""
    day = _day("10 Oct")  # 2026-10-10 = Saturday
    assert [c["state"] for c in day["cells"][:6]] == ["A", "A", "A", None, "A", "A"], day
    assert all(c["subject"] is None for c in day["cells"]), day


def t_cross_check_subject_totals():
    """Joined A-count per subjectcode within ±1 of attendance-subject totals.

    Tolerance ±1 because the portal counts may include hours outside timetable
    scope (Saturday classes + CL have no Mon-Fri slot: the fixture's 34 A
    hours minus 6 Saturday hours = 28 joinable vs the portal's 35 total).
    CL is deliberately excluded from the ±1 loop and asserted joined==0:
    class-in-charge is never on a timetable (join spec: bare-hN fallback),
    so its portal count (2) can never be joined — the >1 delta is explained,
    not investigated away. Any OTHER >1 delta fails the suite.
    """
    with open(REPO / "tests" / "fixtures" / "scope-attendance-hour.txt") as f:
        fixture_only = json.load(f)  # 61 LIVE rows — probes excluded
    fx = hourwise_view(fixture_only, SLOTS, CUSTOM)
    joined = Counter()
    for m in fx["months"]:
        for d in m["days"]:
            for c in d["cells"]:
                if c["state"] == "A" and c["code"]:
                    joined[c["code"]] += 1
    assert set(joined) <= set(PORTAL), f"invented codes: {set(joined) - set(PORTAL)}"
    lines = []
    for code, portal_n in sorted(PORTAL.items()):
        got = joined.get(code, 0)
        delta = got - portal_n
        lines.append(f"  cross-check {code}: joined={got} portal={portal_n} delta={delta:+d}")
        if code == "CL":
            assert got == 0, "CL must never join (never on a timetable)"
        else:
            assert abs(delta) <= 1, f"{code} delta {delta:+d} > ±1\n" + "\n".join(lines)
    print("    " + "\n    ".join(lines))


def t_grid_shape():
    """One entry per SCOPE month, days newest-first, 6 columns, closed states."""
    from datetime import datetime as _dt
    labels = sorted(m["label"] for m in JOIN["months"])
    raw = sorted({_dt.strptime(r["attendancedate"], "%d-%b-%Y").strftime("%b %Y")
                  for r in FIX_ROWS})
    assert labels == raw, ("labels", labels, "raw", raw)
    oct_m = BY_LABEL["Oct 2026"]
    days = [_dt.strptime(d["full"], "%d %b %Y") for d in oct_m["days"]]
    assert days == sorted(days, reverse=True), "days must be newest-first"
    assert all(len(d["cells"]) == len(JOIN["hours"]) for d in _all_days())
    assert all(c["n"] <= len(JOIN["hours"]) for d in _all_days() for c in d["cells"])
    assert all(c["state"] in (None, "P", "A", "OD") for d in _all_days() for c in d["cells"])
    # counts on the row summary are the grid's own cells, not a second source
    assert oct_m["a"] == sum(1 for d in oct_m["days"] for c in d["cells"] if c["state"] == "A")
    assert oct_m["p"] == sum(1 for d in oct_m["days"] for c in d["cells"] if c["state"] == "P")


def t_month_labels_follow_portal():
    """Grid months align to the portal's `MMM / YYYY` labels; strays go last."""
    out = hourwise_view(FIX_ROWS, SLOTS, CUSTOM, portal_months={
                        "Oct / 2026": {"label": "Oct / 2026", "pct": 78},
                         "Sep / 2026": {"label": "Sep / 2026", "pct": 71}})
    got = [m["label"] for m in out["months"]]
    assert got.index("Oct 2026") == 0 and got.index("Sep 2026") == 1, got
    # every month SCOPE reported still renders, nothing dropped for being early
    assert len(out["months"]) == len({d["full"][3:] for d in _all_days()}), out["months"]
    # a month the portal never reported still renders, after the known ones
    assert out["months"][0]["side"] == "Oct / 2026" and out["months"][0]["pct"] == 78
    row = FIX_ROWS + [{"attendancedate": "20-Jul-2026", "h1": "P"}]
    out = hourwise_view(row, SLOTS, CUSTOM,
                        portal_months={"Oct / 2026": {"label": "Oct / 2026"}})
    got = [m["label"] for m in out["months"]]
    assert got.index("Oct 2026") == 0 and got[-1] == "Sep 2026" and "Jul 2026" in got, got


# ── feature gate + render ───────────────────────────────────────────────────
def t_feature_off_no_join():
    prev = os.environ.get("SCOPE_FEATURES")
    os.environ["SCOPE_FEATURES"] = "off"
    try:
        assert _hourwise_data(NETID, GK) is None, "feature off -> no join data"
        html = CLIENT.get("/").get_data(as_text=True)
    finally:
        if prev is None:
            os.environ.pop("SCOPE_FEATURES", None)
        else:
            os.environ["SCOPE_FEATURES"] = prev
    assert "Detailed attendance" not in html, "section must be hidden"
    assert "15 Oct · 1h" in html, "old count chip must render verbatim"


def t_feature_on_grid_render():
    html = _get(env="hourwise")
    data = _hourwise_data(NETID, GK)
    assert data and data[3] > 0, data
    for want in (
        "Detailed attendance",                       # section title
        'id="hourwise-months"',
        'data-month="Oct 2026"',                     # month dropdown row
        # the section's month rows come from SCOPE months, never the portal guard
        '<span class="hk-label">Oct 2026</span>',
        "hw-c hw-c-a",                              # absent cell (letter + tint)
        "hw-c hw-c-od",                             # on-duty cell
        "Thursday · 15 Oct 2026 · h1 · absent · DATA STRUCTURES AND ALGORITHMS (21CSC201J)",
    ):
        assert want in html, f"missing from render: {want}"
    assert "Last 14 school days" not in html, "rejected strip must be gone"


def t_scope_empty_renders_as_today():
    row = A.db()
    saved = row.execute("SELECT scope_json FROM users WHERE netid=?", (NETID,)).fetchone()[0]
    row.execute("UPDATE users SET scope_json='{}' WHERE netid=?", (NETID,))
    row.commit()
    row.close()
    try:
        assert _hourwise_data(NETID, GK) is None, "empty scope -> no join"
        html = _get(env="hourwise")
        assert "Detailed attendance" not in html and "15 Oct · 1h" in html, \
            "empty scope must render today's Absences card unchanged"
    finally:
        row = A.db()
        row.execute("UPDATE users SET scope_json=? WHERE netid=?", (saved, NETID))
        row.commit()
        row.close()


def t_no_group_renders_as_today():
    row = A.db()
    gid = group_id(GK)
    saved = row.execute("SELECT day, period, subject_code, subject_name, location "
                        "FROM timetable_slots WHERE group_id=?", (gid,)).fetchall()
    row.execute("DELETE FROM timetable_slots WHERE group_id=?", (gid,))
    row.commit()
    row.close()
    try:
        assert _hourwise_data(NETID, GK) is None, "no slots -> no join"
        html = _get(env="hourwise")
        assert "Detailed attendance" not in html and "15 Oct · 1h" in html, \
            "no timetable group must render today's Absences card unchanged"
    finally:
        row = A.db()
        row.executemany("INSERT INTO timetable_slots(group_id, day, period, subject_code,"
                        " subject_name, location, source) VALUES(?,?,?,?,?,?,'manual')",
                        [(gid, *r) for r in saved])
        row.commit()
        row.close()


TESTS = [
    ("weekday match: every A cell joins its slot", t_fixture_weekday_match),
    ("missing hour key = no class, never an absence", t_missing_key_no_class),
    ("OD is on-duty, never an absence", t_od_never_absent),
    ("slot miss (NULL/CL/custom/no row) -> no name", t_slot_miss_bare_fallback),
    ("period 7 unknown: column only with a p7 slot, always empty", t_period7_unknown),
    ("weekend row never gets a subject name", t_weekend_row_unnamed),
    ("cross-check vs attendance-subject within ±1", t_cross_check_subject_totals),
    ("month grid: newest-first days x 6 hours, counted from cells", t_grid_shape),
    ("grid months align to the portal's month labels", t_month_labels_follow_portal),
    ("feature off -> no section, Absences card verbatim", t_feature_off_no_join),
    ("feature on -> detailed grid renders with titles", t_feature_on_grid_render),
    ("empty scope_json -> renders exactly as today", t_scope_empty_renders_as_today),
    ("no timetable group -> renders exactly as today", t_no_group_renders_as_today),
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
