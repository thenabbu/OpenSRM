"""Academics tab suite — CGPA/SGPA math, parsers, envelope sections,
feature gate (zero-footprint) + rendered tab registration.

Checks (mission contract):
  - CGPA: hand-computed 5-subject case, ROUND_HALF_UP at the x.xx5 edge
    (Decimal beats banker's round()), F counts as 0, grade "-" skipped,
    non-released rows skipped, 0-credit rows can't weight.
  - semesters: one dropdown row per monthyear (Semester N left / DEC 2025
    right / SGPA + released credits in the summary), newest first.
  - parsers: exam-details fixtures -> semester buckets; the combined
    credits+subjects card (8 categories, overall, pending-FIRST /
    completed-LAST ordering, success fill ONLY at 100%).
  - {Status,Data} wrapper: provisional empty -> section absent; synthetic
    non-empty -> present (shape-driven, no field hardcoding).
  - courses op: credit-total cross-check ONLY (never rendered, YAGNI).
  - feature gate: disabled -> academics_view() is None AND the rendered
    page carries no tab registration (button/panel/rule absent).
  - rendered gate: seeded scope_json -> the Academics tab registers and all
    four self-hiding sections render.

Self-contained: temp DATA_DIR, seeded fixtures + minted cookie inside the
test; no server, no network, no real credentials (fabricated netid — the
repo is public, AGENTS.md).
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# verify76 forbids test-DB files in the repo root / tests dir; the dir must
# outlive this module's import (tests run after the import block).
_td = tempfile.mkdtemp(prefix="osrm-scopeacad-")
atexit.register(shutil.rmtree, _td, True)
os.environ["DATA_DIR"] = _td          # direct assignment: stale env must not win
os.environ["OCR_PREWARM"] = "0"
os.environ.pop("SCOPE_FEATURES", None)  # the gate test owns its own env

from app.views.academics import (  # noqa: E402
    GRADE_POINTS,
    _courses_view,
    _credits_view,
    _envelope_rows,
    _gpa,
    _semesters_view,
    academics_view,
)

FX = Path(__file__).resolve().parent.parent / "fixtures" / "scope"
NETID = "zz9999"                       # fabricated — repo is public


def fx(name):
    return json.loads((FX / f"{name}.json").read_text())


# ── CGPA math ────────────────────────────────────────────────────────
def t_cgpa_hand_computed():
    # 5 subjects: O*4 + A+*3 + A*2 + B*1 + F*0
    #   points = 40 + 27 + 16 + 7 + 0 = 90 ; credits = 4+3+2+1+3 = 13
    #   90/13 = 6.923076... -> 6.92 (2dp)
    rows = [
        {"grade": "O", "credit": "4", "result": "Pass"},
        {"grade": "A+", "credit": "3", "result": "Pass"},
        {"grade": "A", "credit": "2", "result": "Pass"},
        {"grade": "B", "credit": "1", "result": "Pass"},
        {"grade": "F", "credit": "3", "result": "Fail"},
    ]
    val, credits = _gpa(rows)
    assert val == "6.92", val
    assert credits == 13, credits
    assert GRADE_POINTS == {"O": 10, "A+": 9, "A": 8, "B": 7, "C": 6, "D": 5, "F": 0}


def t_cgpa_half_up_rounding():
    # 10*1 + 9*1 + 8*3 + 7*1 + 6*1 + 5*1 = 61 over 8 credits = 7.625
    rows = [{"grade": g, "credit": c, "result": "Pass"} for g, c in
            [("O", 1), ("A+", 1), ("A", 3), ("B", 1), ("C", 1), ("D", 1)]]
    val, credits = _gpa(rows)
    assert (val, credits) == ("7.63", 8), (val, credits)
    # the reason this is Decimal: float round() is banker's and says 7.62
    assert round(61 / 8, 2) == 7.62


def t_cgpa_fail_counts_and_dash_skipped():
    base = [{"grade": "A", "credit": "4", "result": "Pass"},
            {"grade": "A", "credit": "4", "result": "Pass"}]   # 8.00
    assert _gpa(base) == ("8.00", 8)
    # F row counts with 0 points for its credits (drags the mean down)
    with_f = base + [{"grade": "F", "credit": "4", "result": "Fail"}]
    assert _gpa(with_f) == ("5.33", 12), _gpa(with_f)   # 64/12 = 5.333
    # grade "-" = not released: skipped, never counted as 0
    assert _gpa(base + [{"grade": "-", "credit": "4", "result": "Pass"}]) == ("8.00", 8)
    # non-released result (non-Pass, non-F) is out of the pool
    assert _gpa(base + [{"grade": "A", "credit": "4", "result": "Absent"}]) == ("8.00", 8)
    # 0-credit rows cannot weight anything
    assert _gpa(base + [{"grade": "O", "credit": "0", "result": "Pass"}]) == ("8.00", 8)
    assert _gpa([]) == (None, 0)


def t_semester_rows_newest_first():
    rows = [
        {"grade": "O", "credit": "4", "result": "Pass", "monthyear": "DEC 2025", "semester": "1"},
        {"grade": "A", "credit": "4", "result": "Pass", "monthyear": "DEC 2025", "semester": "1"},
        {"grade": "A+", "credit": "4", "result": "Pass", "monthyear": "MAY 2026", "semester": "2"},
        {"grade": "B", "credit": "4", "result": "Pass", "monthyear": "JUNK"},
    ]
    sems = _semesters_view(rows)
    labels = [x["label"] for x in sems]
    assert labels[0] == "MAY 2026", labels      # newest first
    assert labels[-1] == "JUNK"                 # unparsable sorts oldest
    by = {x["label"]: x for x in sems}
    assert by["DEC 2025"]["sgpa"] == "9.00" and by["DEC 2025"]["credits"] == 8
    assert by["MAY 2026"]["sgpa"] == "9.00" and by["MAY 2026"]["credits"] == 4
    assert by["DEC 2025"]["sem"] == 1 and by["MAY 2026"]["sem"] == 2
    assert len(by["DEC 2025"]["rows"]) == 2
    # a label that is not a real month is NOT a semester: the portal rows
    # carry the semester id, so the junk bucket keeps its neighbour's id
    assert by["JUNK"]["sem"] == 1, by["JUNK"]["sem"]
    assert _semesters_view([]) == []


# ── parsers over the real fixtures ───────────────────────────────────
def t_semester_rows_fixtures():
    sems = _semesters_view(fx("exam-details"))
    assert [x["label"] for x in sems] == ["MAY 2026", "DEC 2025"]
    assert [x["sem"] for x in sems] == [2, 1]
    assert [len(x["rows"]) for x in sems] == [7, 9]
    first = sems[0]["rows"][0]
    assert first["code"] and first["title"] and not first["title"].isupper(), first
    assert all(r["grade"] and r["completed"] for x in sems for r in x["rows"])
    assert all(r["code"] for x in sems for r in x["rows"])


def t_subject_row_shape():
    """`CODE | NAME` one-liners: the grade letter is the cue (O = soft blue,
    a fail = faint red), so neither tint is ever the only signal."""
    from app.views.academics import _subject_row
    o = _subject_row("21CSC201J", "DATA STRUCTURES", "O")
    assert (o["code"], o["title"], o["completed"]) == ("21CSC201J", "Data Structures", True)
    assert o["tint_o"] is True and o["tint_f"] is False
    f = _subject_row("21MAB101T", "CALCULUS", "F")
    assert f["tint_f"] is True and f["tint_o"] is False and f["completed"] is True
    a = _subject_row("21CSC202J", "OPERATING SYSTEMS", "A+")
    assert a["tint_o"] is False and a["tint_f"] is False
    p = _subject_row("21BTB101T", "APPLIED BIOLOGY", "-")
    assert p["completed"] is False and p["tint_o"] is False and p["tint_f"] is False


def t_courses_combined_pending_first():
    """ONE combined card: per-category dropdowns whose subjects are PENDING
    on top and completed at the bottom (navya's ordering)."""
    status = _credits_view(fx("course-status"))
    v = _courses_view(status, fx("program-subjects"))
    assert len(v["cats"]) == 8
    assert v["overall"] == {"req": 163, "acq": 43}, v["overall"]
    assert v["total"] == 63 and v["pending"] == 52, (v["total"], v["pending"])
    for c in v["cats"]:
        assert not any(r["completed"] for r in c["pending"]), c["name"]
        assert all(r["completed"] for r in c["completed"]), c["name"]
        assert c["n"] == len(c["pending"]) + len(c["completed"])
    basic = next(c for c in v["cats"] if c["name"].startswith("Basic Science"))
    assert basic["pending"] and basic["completed"], basic["name"]
    # a completed subject carries its month; pending rows stay bare
    assert all(r["month"] for r in basic["completed"])
    assert all(not r["month"] for r in basic["pending"])
    # the retake note survives the merge
    retake = _courses_view(
        {"cats": [{"name": "Basic Science Courses (B)", "req": 5, "acq": 5, "pct": 100.0,
                   "done": True, "fill": "width:100.0%;background:var(--color-success)"}],
         "overall": {"req": 5, "acq": 5}},
        [{"subjectcategory": "Basic Science Courses (B)", "description": "CHEMISTRY",
          "subjectcode": "21CYB101J", "grade": "C", "credit": "5", "noofattempts": "2",
          "completedmonthandyear": "DEC-2025"}])
    assert retake["cats"][0]["completed"][0]["attempts"] == 2
    assert retake["cats"][0]["pending"] == []
    assert _courses_view(None, fx("program-subjects")) is None


def t_credits_view():
    v = _credits_view(fx("course-status"))
    assert len(v["cats"]) == 8
    assert v["overall"] == {"req": 163, "acq": 43}, v["overall"]
    # HTML entity in the portal payload is unescaped for display
    names = [c["name"] for c in v["cats"]]
    assert any(n.startswith("Humanities & Social") for n in names), names
    assert not any("&amp;" in n for n in names)
    # neutral fill everywhere; width derived route-side
    assert all("background" not in c["fill"] for c in v["cats"]), v["cats"]
    assert all(c["fill"].startswith("width:") for c in v["cats"])
    # synthetic: a finished category takes the success fill, 100% width
    done = _credits_view([{"subjectcategory": "Non Credit Courses (M)",
                           "requiredcredits": "3", "acquiredcredits": "3"}])
    c = done["cats"][0]
    assert c["done"] is True and c["pct"] == 100.0
    assert c["fill"] == "width:100.0%;background:var(--color-success)", c["fill"]
    # acquired > required clamps at 100, never a >100% bar
    over = _credits_view([{"subjectcategory": "X (X)", "requiredcredits": "3",
                           "acquiredcredits": "5"}])
    assert over["cats"][0]["pct"] == 100.0
    assert _credits_view([]) is None


def t_envelope_empty_and_synthetic():
    # the live fixture: alive-empty ("No Details Found ...") -> no subsection
    assert _envelope_rows(fx("exam-provisional")) == []
    assert _envelope_rows(fx("exam-revaluation")) == []
    assert _envelope_rows({"Status": "Success", "Message": "No data found", "Data": ""}) == []
    assert _envelope_rows(None) == []
    # season payload: renders whatever fields arrive, shape-driven
    rows = _envelope_rows({"Status": "Success", "Message": "ok", "Data": [
        {"subjectcode": "21CSC201J", "subjectdesc": "DATA STRUCTURES",
         "grade": "A+", "result": "Pass", "monthyear": "APR 2026", "credit": "4"},
        {"subjectcode": "", "subjectdesc": "", "grade": "", "result": ""},  # junk row
    ]})
    assert len(rows) == 1, rows
    r = rows[0]
    assert r["code"] == "21CSC201J" and r["grade"] == "A+"
    assert r["title"] == "Data Structures", r["title"]
    assert ("result", "Pass") in r["meta"] and ("monthyear", "APR 2026") in r["meta"]
    # a non-empty envelope attaches to the newest semester row, not a card
    blob = json.loads(_full_row()["scope_json"])
    blob["getStudentExamProvisionalResult"]["data"] = {"Status": "Success", "Data": [
        {"subjectcode": "21CSC201J", "subjectdesc": "DATA STRUCTURES", "grade": "A+"}]}
    v = academics_view({"scope_json": json.dumps(blob), "scope_fetched_at": 1}, {"academics"})
    assert v["cgpa"]["sems"][0]["provisional"], v["cgpa"]["sems"][0]
    assert v["cgpa"]["sems"][1]["provisional"] == []


def t_courses_credit_crosscheck():
    """courses op is the credit-total cross-check ONLY (never rendered)."""
    shared = mismatch = 0
    for r in fx("courses"):
        _sem, code, _name, credit = r["subjectdetails"].split("##")
        ps = next((p for p in fx("program-subjects") if p["subjectcode"] == code), None)
        if ps and ps["credit"] != "-":
            shared += 1
            mismatch += int(int(ps["credit"]) != int(credit))
    assert shared == 16 and mismatch == 0, (shared, mismatch)
    # released results sum exactly to the courses ledger for those semesters
    exam = {}
    for r in fx("exam-details"):
        exam[r["semester"]] = exam.get(r["semester"], 0) + int(r["credit"])
    led = {}
    for r in fx("courses"):
        sem, _c, _n, cr = r["subjectdetails"].split("##")
        led[sem] = led.get(sem, 0) + int(cr)
    assert exam == {s: led[s] for s in exam}, (exam, led)


# ── feature gate: zero footprint when off ────────────────────────────
def _full_row():
    """A users.scope_json row carrying every academics op (as the cold sync
    stores them)."""
    blob = {
            "getExamDetails": {"data": fx("exam-details"), "ts": 1},
            "getSubCategoryWiseStatus": {"data": fx("course-status"), "ts": 1},
            "getSubCategorySemesterWiseStatus": {"data": fx("course-status-sem"), "ts": 1},
            "getProgramSubCategoryWiseSubjects": {"data": fx("program-subjects"), "ts": 1},
            "getStudentExamProvisionalResult": {"data": fx("exam-provisional"), "ts": 1},
            "getStudentExamRevaluationResult": {"data": fx("exam-revaluation"), "ts": 1},
            "getSubjects": {"data": fx("courses"), "ts": 1},
        }
    return {"scope_json": json.dumps(blob), "scope_fetched_at": 1760000000}


def t_feature_gate_off_or_no_data():
    row = _full_row()
    assert academics_view(row, {"academics"}) is not None
    assert academics_view(row, set()) is None, "feature disabled -> no tab"
    assert academics_view(row, {"fees", "placement"}) is None
    assert academics_view({"scope_json": "{}", "scope_fetched_at": 0},
                          {"academics"}) is None, "no academics ops stored -> no tab"
    # op keys present but every payload empty -> still no orphan tab
    empty = {"scope_json": json.dumps({"getExamDetails": {"data": [], "ts": 1}}),
             "scope_fetched_at": 0}
    assert academics_view(empty, {"academics"}) is None
    assert academics_view(None, {"academics"}) is None
    # enabled + data -> exactly the hero (with its semester rows) + the
    # combined card; nothing else
    v = academics_view(row, {"academics", "fees"})
    assert set(v) == {"cgpa", "courses"}, sorted(v)
    assert v["cgpa"]["credits_disp"] == "43/163 credits earned"
    assert [s["label"] for s in v["cgpa"]["sems"]] == ["MAY 2026", "DEC 2025"]
    assert sum(len(s["rows"]) for s in v["cgpa"]["sems"]) == 16
    assert v["cgpa"]["sems"][0]["provisional"] == []
    assert v["courses"]["total"] == 63 and v["courses"]["pending"] == 52


def t_rendered_tab_registers_and_gates():
    import sqlite3
    from app import app as A

    conn = sqlite3.connect(os.path.join(_td, "srm.db"))
    conn.execute("INSERT OR REPLACE INTO users(netid, password, last_fetch) VALUES(?,?,?)",
                 (NETID, "pw", int(time.time())))
    conn.commit()
    conn.close()
    tok = A.make_session_token(NETID)
    # seed the academics blob the cold sync would store
    conn = sqlite3.connect(os.path.join(_td, "srm.db"))
    conn.execute("UPDATE users SET scope_json=?, scope_fetched_at=? WHERE netid=?",
                 (_full_row()["scope_json"], 1760000000, NETID))
    conn.commit()
    conn.close()

    cl = A.app.test_client()
    cl.set_cookie("srm_session", tok)
    html = cl.get("/").get_data(as_text=True)
    assert 'id="tab-academics-tab"' in html, "tab button missing with feature on"
    assert 'id="tab-academics"' in html, "tabpanel missing with feature on"
    assert 'data-tab="academics"' in html
    for needle in ("CGPA", "43/163 credits earned", "Credits &amp; subjects",
                   "Semester", "DEC 2025", "MAY 2026", "SGPA", "52 of 63 subjects pending"):
        assert needle in html, f"{needle} missing from the rendered tab"
    # the reorganisation removed these: no estimated label, no pass pill, no
    # standalone Results/Credits/Subjects cards, no relative-time caption
    tab = html[html.index('id="tab-academics"'):html.index("</main>")]
    for gone in ("(est.)", "est. = scale not officially published", ">Pass<",
                 ">Results<", ">Credits<", ">Subjects<", "sync-line"):
        assert gone not in tab, f"{gone} must be gone from the academics tab"
    # one line per subject: `CODE | NAME`, never a stacked name-over-code row
    assert tab.count('aria-hidden="true">|</span>') >= 2
    assert 'class="block mt-0.5 font-mono' not in tab
    for needle in ("Provisional", "Revaluation"):
        assert needle not in html, f"{needle} must stay hidden while empty"
    # every semester row is a dropdown: N semesters -> N <details> in the hero
    assert html.count('class="acad-sem') == 2, html.count('class="acad-sem')
    assert html.count('class="acad-cat') == 8, html.count('class="acad-cat')

    # disabled -> no tab registration at all (view context AND markup)
    os.environ["SCOPE_FEATURES"] = "hourwise,fees"
    try:
        row = A.user_scope_data(NETID)
        assert academics_view(row, A.enabled_features()) is None, "view context"
        html = cl.get("/").get_data(as_text=True)
        assert 'tab-academics' not in html, "disabled tab leaked into the page"
        assert 'data-tab="academics"' not in html
    finally:
        os.environ.pop("SCOPE_FEATURES", None)


TESTS = [
    ("CGPA hand-computed 5-subject case", t_cgpa_hand_computed),
    ("CGPA ROUND_HALF_UP at the x.xx5 edge", t_cgpa_half_up_rounding),
    ("CGPA F=0 / '-' skipped / unreleased skipped", t_cgpa_fail_counts_and_dash_skipped),
    ("semester dropdown rows, newest first", t_semester_rows_newest_first),
    ("exam-details fixtures -> semester rows", t_semester_rows_fixtures),
    ("subject row: O tinted, fail tinted, '-' pending", t_subject_row_shape),
    ("combined credits+subjects: pending first, done last", t_courses_combined_pending_first),
    ("credits: 8 categories + success fill only at 100%", t_credits_view),
    ("{Status,Data}: empty hidden, synthetic present", t_envelope_empty_and_synthetic),
    ("courses credit-total cross-check", t_courses_credit_crosscheck),
    ("feature gate: off / no data -> no view", t_feature_gate_off_or_no_data),
    ("rendered: tab registers only when enabled", t_rendered_tab_registers_and_gates),
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
