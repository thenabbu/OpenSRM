"""Card/widget engine contracts (v1.16.0): LAYOUT registry spans + widget ids,
WIDGETS partials exist, `when` filtering drops all-empty cards (no orphan
shell), unknown widget ids render NOTHING and never 500, widget derivations
(budget rows risk-first, teacher initials/mode, ticker states), and the
dashboard stylesheet block the partials depend on. Red-proof: breaks if the
grid, the guards or the derivations drift.
Run: DATA_DIR=/tmp/osrm-layout .venv/bin/python tests/test_layout.py"""
import json, os, sys, time
os.environ.setdefault("DATA_DIR", "/tmp/osrm-layout")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from app import app as A  # noqa: E402  (DATA_DIR first)

results = []
def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok else ""))

# ── seed: profile + marks + faculty (incl. a Practical) + attendance ───────
PERSONAL = {"Program": "B.Tech", "Batch": "2025", "Semester": "III SEMESTER",
            "Section": "A", "Student Name": "Test Student"}
MARKS = [{"code": "21CSC201J", "title": "DATA STRUCTURES",
          "components": [{"name": "FT-I", "entered": "04/Sep/2026",
                          "scored": 17.5, "max": 20.0}],
          "scored_total": 17.5, "max_total": 20.0}]
FACULTY = {"DATA STRUCTURES AND ALGORITHMS": {
    "subject_id": "90001",
    "staff": [["50001", "Dr. Test Alpha-Theory"],
              ["50002", "Dr. Beta Gamma-Practical"]]},
    "PROFESSIONAL ETHICS": {
        "subject_id": "90002",
        # portal writes no space after Dr. — widget must normalise for display
        "staff": [["50003", "Dr.Solo Faculty-Theory"]]}}
COURSES = [
    # comfortable (skip 2), at-limit (skip 0), below-line (attend 3), dropped
    {"code": "21CSC201J", "description": "DATA STRUCTURES AND ALGORITHMS",
     "attended": 10, "max_hours": 10},
    {"code": "21LEM201T", "description": "PROFESSIONAL ETHICS",
     "attended": 9, "max_hours": 12},
    {"code": "21CSC202J", "description": "DISCRETE STRUCTURES",
     "attended": 3, "max_hours": 5},
    {"code": "21CSC999X", "description": "EMPTY ROW",
     "attended": 0, "max_hours": 0},
]

c = A.db()
c.execute("DELETE FROM component_tags")
c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
             marks_json, attendance_json, faculty_map_json, last_fetch)
             VALUES('zz9999','x',?,?,?,?,?)""",
          (json.dumps(PERSONAL), json.dumps(MARKS),
           json.dumps({"courses": COURSES, "monthly": [], "period": None,
                       "daily_absent": {}}),
           json.dumps(FACULTY), int(time.time())))
# timetable: 3 class slots on EVERY weekday (any-day ticker runs)
gk = A._group_key(PERSONAL)
c.execute("""INSERT OR IGNORE INTO timetable_groups(group_key, program, batch,
             semester, section) VALUES(?, 'CSE CC', 2025, 3, 'A')""", (gk,))
gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()[0]
for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
    # periods 1..3 = class slots (period 0 is the break marker in SLOTS)
    for p, code in ((1, "21CSC201J"), (2, "21CSC202J"), (3, "21LEM201T")):
        c.execute("""INSERT OR IGNORE INTO timetable_slots(group_id, day, period,
                     subject_code, subject_name, location)
                     VALUES(?,?,?,?,?,?)""", (gid, d, p, code, "Test Subject", "R1"))
c.commit(); c.close()

TOKEN = A.make_session_token("zz9999")
def GET(path="/"):
    cl = A.app.test_client()
    cl.set_cookie("srm_session", TOKEN)
    return cl.get(path)

# ── 1. registry coherence ──────────────────────────────────────────────────
expect_layout = [("day", 4, 2), ("assess", 8, None), ("people", 8, None)]
got = [(c_["id"], c_["span"], c_.get("row_span")) for c_ in A.LAYOUT]
check("LAYOUT spans/row_spans exact", got == expect_layout, str(got))
ids = [w for c_ in A.LAYOUT for w in c_["widgets"]]
check("every LAYOUT widget id registered", all(w in A.WIDGETS for w in ids),
      str([w for w in ids if w not in A.WIDGETS]))
check("every WIDGETS partial exists on disk",
      all(os.path.isfile(os.path.join(REPO, "app", "templates", v["partial"]))
          for v in A.WIDGETS.values()))
check("min_w contract >= 250 for all widgets",
      all(v["min_w"] >= 250 for v in A.WIDGETS.values()), str(A.WIDGETS))
check("assess/people carry `when` guards",
      "when" in A.LAYOUT[1] and "when" in A.LAYOUT[2])

# ── 2. derivations ─────────────────────────────────────────────────────────
views = [A._course_view(x) for x in COURSES]
rows = A._budget_rows(views)
check("budget rows: risk-first order + dropped empty + names + signed margin",
      rows == [("Data Structures And Algorithms", "+3", 2),
               ("Professional Ethics", "0", 1),
               ("Discrete Structures", "-3", 0)], str(rows))
tg = A._teacher_groups(A._faculty_view(FACULTY, []))
staff0 = {s["name"]: s for s in tg[0]["staff"]}
check("teacher initials + mode parsed (honorific stripped)",
      staff0["Dr. Test Alpha"]["ini"] == "TA"
      and staff0["Dr. Test Alpha"]["mode"] == "Theory"
      and staff0["Dr. Beta Gamma"]["ini"] == "BG"
      and staff0["Dr. Beta Gamma"]["mode"] == "Practical", str(tg))

# ticker states via a fake clock (seed has 3 classes every weekday)
class FakeDT:
    @staticmethod
    def now():
        import datetime as _dt
        return FakeDT._t
class RealDT:  # restore helper
    pass
_s = A.SLOTS
# slots for OUR seeded periods (0/1/2) — SLOTS order may lead with others
_own = {1, 2, 3}
_first_start = next(s["start"] for s in _s
                    if s["type"] == "class" and s["period"] in _own)
_last_end = [s for s in _s if s["type"] == "class" and s["period"] in _own][-1]["end"]

def at(day, hhmm):
    import datetime as _dt
    FakeDT._t = _dt.datetime.strptime(f"2026-10-12 {hhmm}", "%Y-%m-%d %H:%M")
    # 2026-10-12 is a Monday; strftime('%A') from FakeDT.now drives the day
    A.datetime = type("M", (), {"now": staticmethod(lambda: FakeDT._t)})
    return A._today_ticker(gk)

import datetime as _dt
real_dt = A.datetime
FakeDT._t = _dt.datetime(2026, 10, 12, 9, 45)  # Monday placeholder
mid_first = _dt.datetime.strptime(_first_start, "%H:%M") + _dt.timedelta(minutes=10)
done_t = _dt.datetime.strptime(_last_end, "%H:%M") + _dt.timedelta(minutes=5)
t1 = at("Monday", mid_first.strftime("%H:%M"))
solo = [g for g in tg if g["name"] == "Professional Ethics"][0]["staff"][0]
check("honorific spacing normalised for display",
      solo["name"] == "Dr. Solo Faculty", str(solo))
check("ticker in-class: state=now, prev None, next scheduled",
      t1 and t1["state"] == "now" and t1["prev"] is None
      and t1["now"]["code"] == "21CSC201J" and t1["next"]["code"] == "21CSC202J",
      str(t1))
t2 = at("Monday", done_t.strftime("%H:%M"))
check("ticker day-done: state=done, prev = last class",
      t2 and t2["state"] == "done" and t2["now"] is None
      and t2["prev"]["code"] == "21LEM201T", str(t2))
FakeDT._t = _dt.datetime(2026, 10, 18, 10, 0)  # Sunday: no timetable day
t3 = A._today_ticker(gk)
check("ticker weekend/no-timetable day -> None (widget hidden)", t3 is None, str(t3))
A.datetime = real_dt

# ── 3. HTTP renders ────────────────────────────────────────────────────────
r = GET()
html = r.get_data(as_text=True)
check("GET / 200", r.status_code == 200, str(r.status_code))
check("full-width engine grid renders", 'lg:grid-cols-12' in html)
check("day card spans 4 + row-span 2", 'lg:col-span-4' in html and 'lg:row-span-2' in html)
check("assess + people cards present (when-filter OR-semantics)",
      html.count('lg:col-span-8') == 2, str(html.count('lg:col-span-8')))
check("marks chip renders", 'Internal marks' in html and '17.5/20' in html)
check("attendance budget rows + alert class",
      'can skip' in html and 'att-neg' in html and 'attend 3' in html)
check("people card lays widgets out 2-up (cols contract)",
      'sm:grid-cols-2' in html, "cols wrapper missing")
check("teachers grouped + Practical mode tag",
      'From the mid-sem feedback form' in html and 'Practical' in html
      and 'Dr. Beta Gamma' in html)
check("notices: New badge exactly once", html.count('>New<') == 1,
      str(html.count('>New<')))
check("stylesheet block present (wlabel/wbox/att-neg)",
      all(k in html for k in ('.wlabel{', '.wbox{', '.att-neg{')))
check("institute email, no Gmail", "zz9999@srmist.edu.in" in html)

# unknown widget id renders nothing, never 500
orig = A.LAYOUT
A.LAYOUT = orig + [{"id": "bogus-card", "span": 4, "widgets": ["nope"]}]
r2 = GET()
A.LAYOUT = orig
h2 = r2.get_data(as_text=True)
check("unknown widget id: 200 and renders nothing",
      r2.status_code == 200 and 'nope' not in h2, f"{r2.status_code}")

# all-empty cards dropped: strip marks+faculty+attendance -> only day card
c = A.db()
c.execute("""UPDATE users SET marks_json='[]', faculty_map_json='{}',
             attendance_json=? WHERE netid='zz9999'""",
          (json.dumps({"courses": [], "monthly": [], "period": None,
                       "daily_absent": {}}),))
c.commit(); c.close()
h3 = GET().get_data(as_text=True)
check("all-empty cards hidden (no orphan shells)",
      'lg:col-span-4' in h3 and 'lg:col-span-8' not in h3)
check("day card still renders its widgets", 'Notices' in h3 and 'This week' in h3)

fails = [n for n, ok in results if not ok]
print(f"\n{len(results)-len(fails)}/{len(results)} PASS" + (f" | FAILED: {fails}" if fails else ""))
sys.exit(1 if fails else 0)
