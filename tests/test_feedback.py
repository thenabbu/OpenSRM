"""Tests for the mid-sem feedback harvester + faculty map.

Run: .venv/bin/python tests/test_feedback.py   (plain script, repo convention)
Fixture HTML is SYNTHETIC — mirrors the live Oct 2026 MidSemFeedback structure
exactly (value-before-id hidden inputs, txtCourseTitle/txtCourseStaff selects,
6-option rating scale, 'ALREADY REGISTERED' / 'SAVED SUCCESSFULLY' markers).
Never commit real staff ids harvested from the portal.
"""
import os
import re
import sys
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="fb-test-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.app import _fb_submit_comments, _faculty_view  # noqa: E402
from app.http_scraper import (  # noqa: E402
    _fb_common, _fb_registered, _fb_staff_options, _fb_subjects)

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
check("empty map -> []", _faculty_view({}, courses) == [])
check("empty courses -> blank codes", _faculty_view(fmap, [])[0]["code"] == "")
# whitespace drift between the form name and the scraped name must still join
courses_ws = [{"code": "21CSC201J", "name": "DATA  STRUCTURES AND ALGORITHMS ", "credits": 4}]
check("whitespace-normalised join", _faculty_view(fmap, courses_ws)[0]["code"] == "21CSC201J")

print("== _fb_submit_comments ==")
cs = _fb_submit_comments()
check("pool non-empty", len(cs) >= 5)
check("all <= 250 chars", all(len(x) <= 250 for x in cs), str([len(x) for x in cs]))
check("all non-empty", all(x.strip() for x in cs))

print("== migration v12 (fresh DB) ==")
import sqlite3
db_path = os.path.join(os.environ["DATA_DIR"], "srm.db")
conn = sqlite3.connect(db_path)
cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
conn.close()
check("faculty_map_json column", "faculty_map_json" in cols, str(cols))

print(f"\n{31 - len(FAILS)}/{31} passed" if not FAILS else f"\nFAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
