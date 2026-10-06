"""Attendance view model — frozen-table unit suite (spec §6.1).

TODAY is INJECTED as 2026-10-05 (never date.today()) so every number is
deterministic. Covers the meter-row fields (_course_view), the semester
budgets (_attendance_budgets), the spec §4 timetable join, degrade cases
(no exams → --, w=0 → hidden, C=0 → --, period absent → annotation
dropped) and the absences card (date · hours only). Offline: no server.
"""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# verify76 forbids test-DB files in the repo root / tests dir; mkdtemp (not a
# `with` block) so the DB dir outlives this module-level test body
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="osrm-att-view-")
from app.app import (_absences_view, _attendance_budgets, _attendance_index, _title_case,
                     _bunk_counts, _bunk_line, _course_view, _exam_stop,
                     _join_attendance, _tt_att_sig, _weekdays)

fails = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)

TODAY = date(2026, 10, 5)                     # frozen clock [F2]
PERIOD = {"from": "20/Jul/2026", "to": "25/Sep/2026"}
EXAMS = [{"code": "21CSC201J", "name": "Data Structures", "date": "24-12-2026", "session": "AN"}]
# spec §6.1 frozen table: name, A, C, w, pct, t75, (+skip/−attend), M90, M_end
TABLE = [
    ("DBMS",           31,  50, 4, 62, 38, ("skip", 0),  ("attend", 26), 0,  5),
    ("Networks",       34,  50, 3, 68, 38, ("skip", 0),  ("attend", 14), 0,  5),
    ("Electronics",    37,  50, 3, 74, 38, ("skip", 0),  ("attend", 2),  0,  8),
    ("Discrete Maths", 38,  50, 3, 76, 38, ("skip", 0),  None,           1,  9),
    ("OOP",            41,  50, 3, 82, 38, ("skip", 4),  None,           4,  12),
    ("DBMS Lab",       44,  50, 3, 88, 38, ("skip", 8),  None,           7,  15),
    ("Data Structures", 91, 100, 6, 91, 75, ("skip", 21), None,           18, 33),
]

# 1) _bunk_line semantics preserved through the _bunk_counts refactor [F10]
check("bunk_line 34/40 can-miss-5", _bunk_line(34, 40) == "Can miss 5 more classes and stay above 75%")
check("bunk_line 24/36 attend-12", _bunk_line(24, 36) == "Attend the next 12 classes in a row to reach 75%")
check("bunk_line 38/50 one-more-miss", _bunk_line(38, 50) == "One more miss drops you below 75%")
check("bunk_line C=0 None", _bunk_line(0, 0) is None)
check("bunk_counts total<=0 both None", _bunk_counts(0, 0) == (None, None))

# 2) frozen table: pct 0dp, t75, now-budgets, M90, M_end
stop = _exam_stop(EXAMS)
check("stop = first exam − 1 (23 Dec)", stop == date(2026, 12, 23), str(stop))
check("weekdays(6 Oct..stop) = 57", _weekdays(date(2026, 10, 6), stop) == 57)
check("weekdays(period.from..TODAY) = 56 (inclusive)", _weekdays(date(2026, 7, 20), TODAY) == 56)
for (name, A, C, w, pct, t75, _sk, _at, m90, m_end) in TABLE:
    cv = _course_view({"attended": A, "max_hours": C, "absent": C - A,
                       "code": name[:4].replace(" ", ""), "description": name})
    b = _attendance_budgets(A, C, w, PERIOD, EXAMS, TODAY)
    check(f"{name}: pct {pct}% (0dp)", cv["pct_disp"] == pct, str(cv["pct_disp"]))
    check(f"{name}: t75 {t75}", cv["t75"] == t75, str(cv["t75"]))
    now_ok = (cv["skip_now"] is None and cv["attend_now"] == _at[1]) if _at is not None \
        else (cv["skip_now"] == _sk[1] and cv["attend_now"] is None)
    check(f"{name}: now {'-%d' % _at[1] if _at is not None else '+%d' % _sk[1]}", now_ok,
          f"skip={cv['skip_now']} attend={cv['attend_now']}")
    check(f"{name}: M90 {m90}", b["m90"] == m90, str(b["m90"]))
    check(f"{name}: M_end {m_end}", b["m_end"] == m_end, str(b["m_end"]))
    check(f"{name}: fill exact 100·A/C", abs(cv["fill"] - 100.0 * A / C) < 1e-9, str(cv["fill"]))

b = _attendance_budgets(31, 50, 4, PERIOD, EXAMS, TODAY)
check("days_left_90 = 34", b["days_left_90"] == 34, str(b["days_left_90"]))
check("days_left_exam = 79", b["days_left_exam"] == 79, str(b["days_left_exam"]))

# 3) orange rule: pct ≥ 75 AND skip_now == 0 → warn tint (Discrete Maths)
cv = _course_view({"attended": 38, "max_hours": 50, "absent": 12, "code": "D", "description": "Discrete Maths"})
check("orange rule 76%/skip-0 → warn", cv["tint"] == "warn", cv["tint"])
check("below 75 → red tint", _course_view({"attended": 31, "max_hours": 50, "absent": 19, "code": "B", "description": "DBMS"})["tint"] == "red")
check("comfortable → gray tint", _course_view({"attended": 91, "max_hours": 100, "absent": 9, "code": "S", "description": "DS"})["tint"] == "gray")

# 4) negative clamp: budgets never go below 0
b = _attendance_budgets(0, 100, 5, None, EXAMS, TODAY)
check("negative clamp M90 ≥ 0", b["m90"] >= 0, str(b["m90"]))
b = _attendance_budgets(0, 100, 5, PERIOD, EXAMS, TODAY)
check("negative clamp M_end ≥ 0", b["m_end"] >= 0, str(b["m_end"]))

# 5) degrade cases [F9]
nb = _attendance_budgets(31, 50, 4, PERIOD, [], TODAY)
check("no exams → M_end None (--)", nb["m_end"] is None and nb["days_left_exam"] is None)
check("no exams → M90 still computed", nb["m90"] == 0)
z = _attendance_budgets(31, 50, 0, PERIOD, EXAMS, TODAY)
check("w=0 → both budgets None (hidden)", z["m90"] is None and z["m_end"] is None)
c0 = _course_view({"attended": 0, "max_hours": 0, "absent": 0, "code": "Z", "description": "Zero"})
check("C=0 → pct --, no fill", c0["pct_disp"] is None and c0["fill"] is None)
check("C=0 → no pinned numbers", c0["skip_now"] is None and c0["attend_now"] is None)
pa = _attendance_budgets(31, 50, 4, None, EXAMS, TODAY)
check("period absent → days_left_90 dropped", pa["days_left_90"] is None)
check("period absent → budgets kept", pa["m90"] == 0 and pa["m_end"] == 5)
pj = _attendance_budgets(31, 50, 4, {"from": "junk", "to": "x"}, EXAMS, TODAY)
check("period junk → days_left_90 dropped", pj["days_left_90"] is None)
check("junk exam dates skipped", _exam_stop([{"date": "junk"}, {"date": "24-12-2026"}]) == date(2026, 12, 23))

# 6) spec §4 join unit test [F9]
courses = [_course_view({"attended": 38, "max_hours": 50, "absent": 12, "code": "21X", "description": "DBMS"}),
           _course_view({"attended": 91, "max_hours": 100, "absent": 9, "code": "21Y", "description": "Data Structures"})]
idx = _attendance_index(courses)
check("custom → neutral (before name match)", _join_attendance(idx, {"21X"}, "21X", "DBMS") is None)
check("unmatched → neutral", _join_attendance(idx, set(), "ZZZ", "Nothing") is None)
check("code-exact → matched", (_join_attendance(idx, set(), "21X", "whatever") or {}).get("code") == "21X")
check("name fallback → matched", (_join_attendance(idx, set(), "nope", "  dbms ") or {}).get("code") == "21X")
none_join = _join_attendance(idx, set(), "ZZZ", "Nothing")
check("unmatched never yields numeric 0%", none_join is None or none_join["pct_disp"] != 0)
check("empty index → neutral", _join_attendance(None, set(), "21X", "DBMS") is None)

# 7) glance sig derives from the joined course (neutral for None)
check("sig: danger for a must-attend subject",
      (_tt_att_sig(_course_view({"attended": 31, "max_hours": 50, "absent": 19, "code": "21X",
                                  "description": "DBMS"})) or {}).get("cls") == "danger")
check("sig: can-skip → ok", (_tt_att_sig(courses[1]) or {}).get("text") == "can skip 21")
warn_course = _course_view({"attended": 38, "max_hours": 50, "absent": 12, "code": "D", "description": "Discrete Maths"})
check("sig: skip-0 → warn no-margin", (_tt_att_sig(warn_course) or {}).get("text") == "no margin")
check("sig: neutral for no-join", _tt_att_sig(None) is None)

# 8) absences rows: date · hours ONLY (no subject column) [R5]
av = _absences_view(json.loads(json.dumps({"SEP / 2026": [{"date": "03-09-2026", "hours": "3"}]})))
check("absences grouped by month", av and av[0]["label"] == "Sep 2026", str(av))
check("absences row keys = date·hours", av and all(set(r) == {"date", "hours"} for r in av[0]["rows"]), str(av))
check("absences date rendered", av and av[0]["rows"][0]["date"] == "03 Sep" and av[0]["rows"][0]["hours"] == "3", str(av))
check("absences empty → []", _absences_view({}) == [])
check("absences junk date shown raw", _absences_view({"X": [{"date": "?", "hours": "1"}]})[0]["rows"][0]["date"] == "?")
check("title-case: ALL CAPS portal name", _title_case("DATABASE MANAGEMENT SYSTEMS") == "Database Management Systems")
check("title-case: mixed-case custom untouched", _title_case("CN Lab") == "CN Lab")

print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
