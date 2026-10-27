"""Seed one account with timetable group + SCOPE hourwise data for the
hourwise DUT / dev-server run (Phase 2 join).

Usage:
    DATA_DIR=/tmp/scope-hw python scripts/seed_hourwise.py

What it seeds (fabricated account hw0001, real fixture numbers):
  * personal_details_json -> group key (same _group_key the timetable tab uses)
  * timetable_groups + timetable_slots = GRID below
  * timetable_subjects incl. one is_custom=1 subject (bare-hN fallback probe)
  * scope_json["getHourwiseAttendance"] = tests/fixtures/scope-attendance-hour.txt
    (the LIVE op output, 61 rows) + 3 documented probe rows (OD / h7 / custom)
  * attendance_json: courses from scope-attendance-subject.txt (portal numbers),
    monthly + daily_absent DERIVED from the hourwise rows (real counts), plus
    one portal-side daily row with no scope A (per-row degrade probe)

GRID is fit so the join's per-subject A-counts reproduce
scope-attendance-subject.txt absent counts within ±1 (CL excluded: never on a
timetable by contract). tests/test_hourwise_join.py imports GRID/seed from
here so dev-server and test can never drift.
"""
import json
import os
import sys
import time
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(REPO, "tests", "fixtures")
sys.path.insert(0, REPO)  # import-safe from any cwd (test imports this module too)

PERSONAL = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
            "Batch": "2025", "Semester": "III SEMESTER", "Section": "A",
            "Student Name": "Test Student"}

NAMES = {
    "21CSC201J": "DATA STRUCTURES AND ALGORITHMS",
    "21CSC202J": "OPERATING SYSTEMS",
    "21CSC203P": "ADVANCED PROGRAMMING PRACTICE",
    "21CSS201T": "COMPUTER ORGANIZATION AND ARCHITECTURE",
    "21DCS201P": "DESIGN THINKING AND METHODOLOGY",
    "21LEM201T": "PROFESSIONAL ETHICS",
    "21MAB206T": "NUMERICAL METHODS AND ANALYSIS",
}
CUSTOM = ("CCLAB99", "CLOUD COMPUTING LAB")  # is_custom=1 -> bare hN chips

# (day, period, code) — 5x6 class grid + legacy p7. Fit against the fixture:
# Mon p1 COA / p5 MATH; Tue p1 DSA / p2 DT / p3+p4+p6 OS / p5 APP;
# Wed p1 OS / p2 MATH / p3 PE / p4 OS / p5 COA / p6 MATH; Thu p1 DSA /
# p2+p4+p5 APP / p3 DT / p6 MATH; Fri p1+p3 COA / p2 DSA / p4 MATH / p5 DT /
# p6 custom-lab; Thu p7 (SCOPE has no h7 -> never joins).
GRID = [
    ("Monday", 1, "21CSS201T"), ("Monday", 2, "21LEM201T"), ("Monday", 3, "21CSC201J"),
    ("Monday", 4, "21CSC203P"), ("Monday", 5, "21MAB206T"), ("Monday", 6, "21DCS201P"),
    ("Tuesday", 1, "21CSC201J"), ("Tuesday", 2, "21DCS201P"), ("Tuesday", 3, "21CSC202J"),
    ("Tuesday", 4, "21CSC202J"), ("Tuesday", 5, "21CSC203P"), ("Tuesday", 6, "21CSC202J"),
    ("Wednesday", 1, "21CSC202J"), ("Wednesday", 2, "21MAB206T"), ("Wednesday", 3, "21LEM201T"),
    ("Wednesday", 4, "21CSC202J"), ("Wednesday", 5, "21CSS201T"), ("Wednesday", 6, "21MAB206T"),
    ("Thursday", 1, "21CSC201J"), ("Thursday", 2, "21CSC203P"), ("Thursday", 3, "21DCS201P"),
    ("Thursday", 4, "21CSC203P"), ("Thursday", 5, "21CSC203P"), ("Thursday", 6, "21MAB206T"),
    ("Friday", 1, "21CSS201T"), ("Friday", 2, "21CSC201J"), ("Friday", 3, "21CSS201T"),
    ("Friday", 4, "21MAB206T"), ("Friday", 5, "21DCS201P"), ("Friday", 6, CUSTOM[0]),
    ("Thursday", 7, "21CSC201J"),  # legacy p7: SCOPE never sends h7
]
LOC = {"21CSC203P": "Lab 302"}  # labs carry a location, like the real timetable

# documented probe rows appended after the 61 fixture rows (all after 16-Oct):
# (row, why)
PROBES = [
    # OD is never an absence hour: only h2 joins a chip (Thu p2 = APP)
    ({"attendancedate": "05-Nov-2026", "h1": "OD", "h2": "A", "h3": "P",
      "h4": "P", "h5": "P", "h6": "P"}, "OD probe: h1=OD never chips"),
    # SCOPE has no h7 -> bare h7 chip, never a subject
    ({"attendancedate": "06-Nov-2026", "h1": "P", "h2": "P", "h3": "P",
      "h4": "P", "h5": "P", "h6": "P", "h7": "A"}, "period-7 probe: bare h7"),
    # Fri p6 is the custom subject -> bare hN fallback
    ({"attendancedate": "23-Oct-2026", "h1": "P", "h2": "P", "h3": "P",
      "h4": "P", "h5": "P", "h6": "A"}, "custom-slot probe: bare h6"),
]
# portal-side daily_absent row with NO scope A that day -> keeps the old
# count chip (per-row degrade, feature stays on for every other date)
NO_A_ROW = {"date": "04-09-2026", "hours": "2"}


def load_hourwise_rows():
    with open(os.path.join(FIX, "scope-attendance-hour.txt")) as f:
        rows = json.load(f)
    return rows + [p[0] for p in PROBES]


def load_subjects():
    with open(os.path.join(FIX, "scope-attendance-subject.txt")) as f:
        return json.load(f)


def derive_monthly_daily(rows):
    """monthly + daily_absent straight from the hourwise rows: present = hour
    keys that are not A, absent = A count, OD parked in od_present (the
    portal's own OD(P)/OD(A) split is not in this op — seed notes it as a
    guess), ml=0. daily_absent lists every date with >=1 A (portal shape)."""
    monthly, daily = {}, {}
    for r in rows:
        try:
            d = datetime.strptime(r["attendancedate"], "%d-%b-%Y")
        except (KeyError, ValueError):
            continue
        label = d.strftime("%b / %Y").upper()
        m = monthly.setdefault(label, {"present": 0, "absent": 0, "od_present": 0,
                                       "od_absent": 0, "ml": 0})
        absent = 0
        for k, v in r.items():
            if not (k.startswith("h") and k[1:].isdigit()):
                continue
            if v == "A":
                absent += 1
            elif v == "OD":
                m["od_present"] += 1
            else:
                m["present"] += 1
        if absent:
            m["absent"] += absent
            daily.setdefault(label, []).append(
                {"date": d.strftime("%d-%m-%Y"), "hours": str(absent)})
    daily.setdefault("SEP / 2026", []).append(dict(NO_A_ROW))
    return monthly, daily


def seed(netid="hw0001"):
    """Write every leg into the DATA_DIR DB. Returns (netid, group_key)."""
    from app import app as A

    rows = load_hourwise_rows()
    subjects = load_subjects()
    monthly, daily = derive_monthly_daily(rows)
    courses = [{"code": s["subjectcode"], "description": s["subjectdesc"],
                "max_hours": s["total"], "attended": s["present"],
                "absent": s["absent"]} for s in subjects]
    attendance = {"courses": courses, "monthly": [
        {"month": k, **v} for k, v in monthly.items()],
        "period": {"from": "20/Jul/2026", "to": "16/Oct/2026"},
        "daily_absent": daily}
    scope = {"getHourwiseAttendance": {"data": rows, "ts": int(time.time())}}

    c = A.db()
    c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
                 attendance_json, scope_json, scope_fetched_at, last_fetch)
                 VALUES(?, 'unused-seed', ?, ?, ?, ?, ?)""",
              (netid, json.dumps(PERSONAL), json.dumps(attendance),
               json.dumps(scope), int(time.time()), int(time.time())))
    gk = A._group_key(PERSONAL)
    c.execute("""INSERT OR REPLACE INTO timetable_groups(group_key, program, batch,
                 semester, section) VALUES(?, 'CSE Cloud Computing', 2025, 3, 'A')""", (gk,))
    gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()[0]
    c.execute("DELETE FROM timetable_slots WHERE group_id=?", (gid,))
    c.execute("DELETE FROM timetable_subjects WHERE group_id=?", (gid,))
    c.executemany("""INSERT INTO timetable_slots(group_id, day, period, subject_code,
                     subject_name, location, source)
                     VALUES(?,?,?,?,?,?,'manual')""",
                  [(gid, d, p, code, NAMES.get(code, CUSTOM[1]), LOC.get(code, ""))
                   for d, p, code in GRID])
    for code, name in list(NAMES.items()) + [CUSTOM]:
        c.execute("""INSERT OR REPLACE INTO timetable_subjects(group_id, code, name,
                     credits, is_custom) VALUES(?,?,?,?,?)""",
                  (gid, code, name, 3, 1 if code == CUSTOM[0] else 0))
    c.commit()
    c.close()
    return netid, gk


def main():
    if not os.environ.get("DATA_DIR"):
        sys.exit("DATA_DIR is required, e.g. DATA_DIR=/tmp/scope-hw")
    from app import app as A  # noqa: F401  (applies DATA_DIR, runs migrations)
    netid, gk = seed()
    print(f"seeded netid={netid} group_key={gk} slots={len(GRID)} "
          f"hourwise_rows={len(load_hourwise_rows())}")


if __name__ == "__main__":
    main()
