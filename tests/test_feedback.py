"""Tests for the mid-sem feedback harvester + faculty map.

Run: .venv/bin/python tests/test_feedback.py   (plain script, repo convention)
Fixture HTML is SYNTHETIC — mirrors the live Oct 2026 MidSemFeedback structure
exactly (value-before-id hidden inputs, txtCourseTitle/txtCourseStaff selects,
6-option rating scale, 'ALREADY REGISTERED' / 'SAVED SUCCESSFULLY' markers).
Never commit real staff ids harvested from the portal.
"""
import os
import sys
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="fb-test-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.app import _faculty_view  # noqa: E402
from app.http_scraper import _fb_common, _fb_registered, _fb_staff_options, _fb_subjects  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name} {detail}")


FRAG = """<form id="feedback1" name="feedback1">
<input type="hidden" value="999001" id="hdnStudentId" />
<input type="hidden" value="2737" id="hdnCourseId"/>
<input type="hidden" value="26" id="hdnAcademicYearId" />
<input type="hidden" value="38172" id="hdnPgsecid" />
<input type="hidden" value="2" id="hdnFeedbackTypeId"/>
<input type="hidden" value="3" id="hdntxtSem" />
<input type="hidden" value="B.Tech.Computer Science and Engineering with specialization in Cloud Computing" id="hdntxtProgramme" />
<input type="hidden" value="Section : A" id="hdntxtSection" />
<input type="hidden" value="44" id="hdnStudentCount" />
<input type="hidden" value="12" id="hdnTotalFeedBack" />
<input type="hidden" value="3" id="previousSemester" />
<select id="txtCourseTitle" class="form-control w-75" name="txtCourseTitle">
  <option value="90001">DATA STRUCTURES AND ALGORITHMS</option>
  <option value="90002">OPERATING SYSTEMS</option>
  <option value="90003">ADVANCED PROGRAMMING PRACTICE</option>
</select>
<select id="txtCourseStaff" class="form-control w-50" name="txtCourseStaff">
  <option value="50001">Dr.Test One-Theory</option>
  <option value="50002">Dr.Test Two-Theory</option>
</select>
</form>"""

# SAVED response: the success body is a small table whose hidden flag carries
# value BEFORE id (captured live — an id-first regex misses it entirely)
SAVED = """<table class="table" id="home"><tr><td>
    <font color="Green" size="3"> SAVED SUCCESSFULLY </font>
    <input type="hidden" value="1" id="hdnRegisterFeedBack" />
</td></tr></table>"""

ALREADY = "<div class='alert alert-danger'>ALREADY REGISTERED YOUR FEED BACK  FOR THIS SUBJECT</div>"
NOT_REGISTERED = FRAG  # form with selects = open for this subject

print("== _fb_common (value-before-id attribute order) ==")
c = _fb_common(FRAG)
check("studenId", c["studenId"] == "999001", repr(c["studenId"]))
check("programme", c["programme"].startswith("B.Tech.Computer"), repr(c["programme"]))
check("section", c["section"] == "Section : A", repr(c["section"]))
check("classstrenth", c["classstrenth"] == "44", repr(c["classstrenth"]))
check("academicyearid", c["academicyearid"] == "26", repr(c["academicyearid"]))
check("courseid", c["courseid"] == "2737", repr(c["courseid"]))
check("hdnPgsecid", c["hdnPgsecid"] == "38172", repr(c["hdnPgsecid"]))
check("semesterId", c["semesterId"] == "3", repr(c["semesterId"]))
check("totalFeedBack", c["totalFeedBack"] == "12", repr(c["totalFeedBack"]))
check("feedbacktypeId", c["feedbacktypeId"] == "2", repr(c["feedbacktypeId"]))
check("previousSemester", c["previousSemester"] == "3", repr(c["previousSemester"]))

print("== _fb_subjects ==")
subs = _fb_subjects(FRAG)
check("3 subjects", len(subs) == 3, repr(subs))
check("ids+names", subs[0] == ("90001", "DATA STRUCTURES AND ALGORITHMS"), repr(subs[0]))

print("== _fb_staff_options ==")
staff = _fb_staff_options(FRAG)
check("2 staff", len(staff) == 2, repr(staff))
check("id+name-kind", staff[0] == ("50001", "Dr.Test One-Theory"), repr(staff[0]))

print("== _fb_registered ==")
check("ALREADY REGISTERED text", _fb_registered(ALREADY) is True)
check("SAVED value-before-id", _fb_registered(SAVED) is True, "value-before-id flag must parse")
check("id-first value=1", _fb_registered('<input type="hidden" id="hdnRegisterFeedBack" value="1" />') is True)
check("value=0", _fb_registered('<input type="hidden" id="hdnRegisterFeedBack" value="0" />') is False)
check("open form", _fb_registered(NOT_REGISTERED) is False)

print("== _faculty_view ==")
fmap = {
    "DATA STRUCTURES AND ALGORITHMS": {"subject_id": "90001",
                                       "staff": [["50001", "Dr.Priyanka  Gupta-Theory"],
                                                 ["50002", "Dr. Dinesh  Kumar-Theory"]]},
    "PROFESSIONAL ETHICS": {"subject_id": "90002",
                            "staff": [["50003", "Dr.Niharika  Shukla-Theory"]]},
    "SOME UNLISTED SUBJECT": {"subject_id": "90003", "staff": [["0", "Unknown"]]},
}
courses = [{"code": "21CSC201J", "name": "DATA STRUCTURES AND ALGORITHMS", "credits": 4},
           {"code": "21LEM201T", "name": "PROFESSIONAL ETHICS", "credits": 0}]
fv = _faculty_view(fmap, courses)
check("2 rows (Unknown staff hidden)", len(fv) == 2, repr(fv))
check("sorted by name", [r["name"] for r in fv] == ["Data Structures And Algorithms", "Professional Ethics"])
check("code joined", fv[0]["code"] == "21CSC201J" and fv[1]["code"] == "21LEM201T", repr(fv))
check("staff title-cased", fv[0]["staff"][0][1] == "Dr.Priyanka Gupta", repr(fv[0]["staff"]))
check("kind split", fv[0]["staff"][0][2] == "Theory", repr(fv[0]["staff"]))
# prod regression (Oct 8 2026): real attendance_json courses carry `description`,
# not `name` — c["name"] KeyError'd every dashboard load for users with any
# attendance data (dictcomp runs even with an empty faculty map)
fv2 = _faculty_view({}, [{"code": "21CSC201J", "description": "DATA STRUCTURES AND ALGORITHMS",
                          "absent": 2, "attended": 30, "max_hours": 40}])
check("prod course shape (description) — no KeyError, empty map -> []",
      fv2 == [], repr(fv2))
fv3 = _faculty_view({"Data Structures And Algorithms": {"staff": [["9", "Dr. X-Theory"]]}},
                    [{"code": "21CSC201J", "description": "DATA STRUCTURES AND ALGORITHMS"}])
check("prod course shape joins code via description",
      fv3 and fv3[0]["code"] == "21CSC201J", repr(fv3))
check("empty map -> []", _faculty_view({}, courses) == [])
check("empty courses -> blank codes", _faculty_view(fmap, [])[0]["code"] == "")
# whitespace drift between the form name and the scraped name must still join
courses_ws = [{"code": "21CSC201J", "name": "DATA  STRUCTURES AND ALGORITHMS ", "credits": 4}]
check("whitespace-normalised join", _faculty_view(fmap, courses_ws)[0]["code"] == "21CSC201J")

print("== comment literal ==")
from app.app import _fb_plan
check("comment is the literal 'none' (optional field)", _fb_plan(fmap)[0]["comment"] == "none")

print("== _fb_plan (preview == submission payload) ==")

plan = _fb_plan(fmap)
check("plan skips unknown-only subject", len(plan) == 3, repr(plan))  # DSA has TWO teachers -> 2 rows
check("plan fields", set(plan[0].keys()) == {"subject", "teacher", "staff_id", "comment"}, repr(plan[0]))
check("teacher name+kind", plan[0]["teacher"] == "Dr.Priyanka Gupta (Theory)", repr(plan[0]))
check("staff_id carried", plan[0]["staff_id"] == "50001", repr(plan[0]))
check("BOTH DSA teachers planned", [p["staff_id"] for p in plan if p["subject"] == "Data Structures And Algorithms"] == ["50001", "50002"],
      repr([p for p in plan if "Data" in p["subject"]]))
check("second teacher label", plan[1]["teacher"] == "Dr. Dinesh Kumar (Theory)", repr(plan[1]))
check("comment literal 'none'", plan[0]["comment"] == "none", repr(plan[0]["comment"]))
check("comment <= 250", all(len(p["comment"]) <= 250 for p in plan))
check("no-kind teacher label", _fb_plan({"X": {"subject_id": "9", "staff": [["5", "Dr. X"]]}})[0]["teacher"] == "Dr. X",
      repr(_fb_plan({"X": {"subject_id": "9", "staff": [["5", "Dr. X"]]}})))
check("empty map -> empty plan", _fb_plan({}) == [])
check("unknown-only -> empty plan", _fb_plan({"SOME UNLISTED SUBJECT": {"subject_id": "90003", "staff": [["0", "Unknown"]]}}) == [])
check("rows == total staff count (excl Unknown)", sum(len(e["staff"]) for k, e in fmap.items() if k != "SOME UNLISTED SUBJECT") == len(_fb_plan(fmap)))

print("== migration v12 (fresh DB) ==")
import sqlite3

db_path = os.path.join(os.environ["DATA_DIR"], "srm.db")
conn = sqlite3.connect(db_path)
cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
conn.close()
check("faculty_map_json column", "faculty_map_json" in cols, str(cols))

print("== fill endpoint guards (test client, no server) ==")
# require_login redirects unauthenticated traffic to /login (repo convention).
import app.app as AA

client = AA.app.test_client()
r = client.post("/api/feedback/fill")
check("unauthenticated -> 302 to /login",
      r.status_code == 302 and "/login" in (r.headers.get("Location") or ""),
      f"status={r.status_code} loc={r.headers.get('Location')}")
# logged-in but empty map -> honest 400 (no portal contact)
tok = AA.make_session_token("zz9999")  # no user row needed: get_current_user reads the cookie
client.set_cookie("srm_session", tok)
r2 = client.post("/api/feedback/fill")
j = r2.get_json() or {}
check("no feedback data -> 400", r2.status_code == 400 and not j.get("ok"),
      f"status={r2.status_code} body={j}")

print(f"\n{40 - len(FAILS)}/40 passed" if not FAILS else f"\nFAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
