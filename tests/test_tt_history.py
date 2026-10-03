"""One runnable check: timetable edit log (audit) + break-divider fix.

Covers: diff logging, no-op saves skipped, group (classmate) isolation,
401 when logged out, and timetable_html showing NO break divider after a
day's last class (hero + panels).
"""
import os
import sys
import tempfile
from datetime import datetime as real_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# verify76 forbids test-DB files in the repo root / tests dir; mkdtemp (not a
# `with` block) so the DB dir outlives this module-level test body
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="osrm-tt-")
import app.app as A

PERSONAL_A = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
              "Batch": "2025", "Semester": "III SEMESTER", "Section": "A",
              "Student Name": "Navya Gupta"}
PERSONAL_A2 = dict(PERSONAL_A, **{"Student Name": "Class Mate"})
PERSONAL_B = dict(PERSONAL_A, **{"Section": "B", "Student Name": "Other Section"})

fails = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)

import json
import time
c = A.db()
for netid, pers in (("ng2776", PERSONAL_A), ("aa1111", PERSONAL_A2), ("bb2222", PERSONAL_B)):
    c.execute("INSERT OR REPLACE INTO users(netid, password, personal_details_json, last_fetch) "
              "VALUES(?, 'unused-by-tests', ?, ?)", (netid, json.dumps(pers), int(time.time())))
gk = A._group_key(PERSONAL_A)
c.commit(); c.close()

cl = A.app.test_client()
tok = {n: A.make_session_token(n) for n in ("ng2776", "aa1111", "bb2222")}

# 1) logged out -> 401
check("history 401 when logged out", cl.get("/api/timetable/history").status_code == 401)

# 2) first save as ng2776 logs one entry
cl.set_cookie("srm_session", tok["ng2776"])
SLOTS = {"Monday-1": {"code": "21CSC101T", "name": "DATA STRUCTURES"},
         "Tuesday-6": {"code": "21MAB206T", "name": "NUMERICAL METHODS"}}
r = cl.post("/api/timetable", json={"slots": SLOTS, "custom_subjects": []})
check("save ok", r.get_json().get("ok") is True, str(r.get_json()))

# 3) a classmate sees the entry, sorted Monday first
cl.set_cookie("srm_session", tok["aa1111"])
e = cl.get("/api/timetable/history").get_json()
ent = e.get("entries") or []
check("classmate sees 1 entry", len(ent) == 1, str(e))
if ent:
    ch = ent[0]["changes"]
    check("editor recorded", ent[0]["netid"] == "ng2776" and ent[0]["name"] == "Navya Gupta", str(ent[0]))
    check("2 changes, Monday before Tuesday",
          len(ch) == 2 and ch[0]["day"] == "Monday" and ch[0]["period"] == 1
          and ch[1]["day"] == "Tuesday", str(ch))
    check("added action + payload", ch[0]["action"] == "added"
          and ch[0]["to"]["code"] == "21CSC101T", str(ch[0]))

# 4) identical re-save by the classmate = no-op, not logged
r = cl.post("/api/timetable", json={"slots": SLOTS, "custom_subjects": []})
e2 = cl.get("/api/timetable/history").get_json()
check("no-op save not logged", r.get_json().get("ok") and len(e2["entries"]) == 1, str(e2))

# 5) real edit by the classmate logs a 'changed' + 'removed' entry on top
SLOTS2 = dict(SLOTS, **{"Monday-1": {"code": "21CSC205T", "name": "OOPS"}})
SLOTS2.pop("Tuesday-6")   # drop a slot in the same save -> 'removed' action
cl.post("/api/timetable", json={"slots": SLOTS2, "custom_subjects": []})
e3 = cl.get("/api/timetable/history").get_json()
top = e3["entries"][0]
check("2 entries, newest is classmate's edit",
      len(e3["entries"]) == 2 and top["netid"] == "aa1111", str(e3["entries"])[:200])
acts = {c["action"]: c for c in top["changes"]}
ch = acts.get("changed", {})
check("changed action with from/to",
      ch.get("from", {}).get("code") == "21CSC101T" and ch.get("to", {}).get("code") == "21CSC205T",
      str(top["changes"]))
rm = acts.get("removed", {})
check("removed action with from",
      rm.get("day") == "Tuesday" and rm.get("period") == 6
      and rm.get("from", {}).get("code") == "21MAB206T", str(top["changes"]))

# 6) other section sees nothing (group isolation)
cl.set_cookie("srm_session", tok["bb2222"])
e4 = cl.get("/api/timetable/history").get_json()
check("other section isolated", e4.get("ok") is True and e4.get("entries") == [], str(e4))

# 7) break dividers: Monday P1..P7 -> 3, Tuesday P1,P2 -> 0, Wednesday P3 only -> 0
c = A.db()
gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()[0]
c.execute("DELETE FROM timetable_slots WHERE group_id=?", (gid,))
for day, periods in (("Monday", range(1, 8)), ("Tuesday", (1, 2)), ("Wednesday", (3,))):
    for p in periods:
        c.execute("INSERT INTO timetable_slots(group_id,day,period,subject_code,subject_name) "
                  "VALUES(?,?,?,?,?)", (gid, day, p, f"CODE{p}", f"Subject {p}"))
c.commit(); c.close()

html = A.timetable_html(gk)
parts = html.split('<div class=day-panel id=panel-')
panels = {}
for p in parts[1:]:
    day = p[:p.index(">")]
    panels[day] = p
check("Monday panel: 3 break dividers", panels.get("Monday", "").count("tt-divider") == 3,
      str(panels.get("Monday", "")[:120]))
check("Tuesday panel: no trailing/orphan break", "tt-divider" not in panels.get("Tuesday", ""),
      str(panels.get("Tuesday", "")))
check("Wednesday mid-only day: no orphan break", "tt-divider" not in panels.get("Wednesday", ""),
      str(panels.get("Wednesday", "")))

# 8) hero: break only when a class follows it that day (pinned clock)
class FakeDT(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(*FakeDT._now)
A.datetime = FakeDT

FakeDT._now = (2026, 9, 28, 11, 15)   # Monday 11:15 — mid-break, P3 at 11:20 follows
h = A.timetable_html(gk)
check("hero shows Break only between classes", "tt-hero--break" in h and "Until 11:20" in h, h[:200])

FakeDT._now = (2026, 9, 29, 15, 55)   # Tuesday 15:55 — last class was P2 at 11:10
h = A.timetable_html(gk)
check("hero: no Break after last class", "tt-hero--break" not in h and "Done for today" in h, h[:200])

A.datetime = real_datetime
print("ok  tt history + break fix" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
