"""One runnable check for the internal-marks view model: formatting (dates,
maxima, scores), name-order sorting, IE-1 derivation + /50-/60 conversion,
confirmed-vs-derived override, the single accent, and the class-scoped key."""
import os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
# test_audit_findings forbids test-DB files in the repo root / tests dir
with tempfile.TemporaryDirectory() as td:
    os.environ["DATA_DIR"] = td
    from app.app import (_marks_view, _marks_summary, _week_marks, _fmt_date, _fmt_max,
                         _fmt_score, _derive_ie_roles, _internal_grade,
                         _class_key, _group_key)

# ── formatting ────────────────────────────────────────────────────────
assert _fmt_date("04/Sep/2026") == "04 Sep"
assert _fmt_date("21/Sep/2026") == "21 Sep"
assert _fmt_date("") == "" and _fmt_date(None) == "" and _fmt_date("junk") == "junk"
assert _fmt_max(15.0) == "15" and _fmt_max(10.0) == "10" and _fmt_max(20.0) == "20"
assert _fmt_max(15.5) == "15.50", _fmt_max(15.5)      # fractional maxima keep 2 decimals
assert _fmt_score(11.7) == "11.7" and _fmt_score(5) == "5"

# ── IE-1/IE-2 derivation: one pair per SUBJECT, never three IE-1s ────
# the repeated family at one max is the exam pair; earliest = IE-1, latest = IE-2
_ft = [{"name": f"FT-{n}", "entered": d, "scored": s, "max": m} for n, d, s, m in (
    ("I", "04/Sep/2026", 5.0, 5.0), ("II", "09/Sep/2026", 11.7, 15.0),
    ("III", "07/Oct/2026", 12.0, 15.0), ("IV", "19/Nov/2026", 8.5, 15.0))] + [
    {"name": "LLT-I", "entered": "02/Nov/2026", "scored": 8.0, "max": 10.0}]
assert _derive_ie_roles(_ft) == {"FT-II": "IE-1", "FT-IV": "IE-2"}, _derive_ie_roles(_ft)
# a practical subject: the FP pair is the exam, the wider PBL group is coursework
_prac = [{"name": "FP-I", "entered": "23/Sep/2026", "scored": 8.0, "max": 10.0},
         {"name": "FP-II", "entered": "16/Nov/2026", "scored": 5.7, "max": 10.0},
         {"name": "PBL-I", "entered": "09/Oct/2026", "scored": 20.0, "max": 20.0},
         {"name": "PBL-II", "entered": "16/Sep/2026", "scored": 20.0, "max": 20.0},
         {"name": "PBL-III", "entered": "26/Aug/2026", "scored": 20.0, "max": 20.0}]
assert _derive_ie_roles(_prac) == {"FP-I": "IE-1", "FP-II": "IE-2"}, _derive_ie_roles(_prac)
assert _derive_ie_roles([]) == {} and _derive_ie_roles(None) == {}
assert _derive_ie_roles([{"name": "FT-I", "entered": "04/Sep/2026", "max": 5.0}]) == {}

# ── internal-only (/100) courses show a grade, not a running total ────
assert _internal_grade(93.9) == "O" and _internal_grade(91) == "O"
assert _internal_grade(90.9) == "A+" and _internal_grade(82) == "A+"
assert _internal_grade(47.1) == "D" and _internal_grade(12) == "F"
assert _internal_grade(None) == "" and _internal_grade("junk") == ""

MARKS = [
    {"code": "21CSS201T", "title": "COMPUTER ORGANIZATION AND ARCHITECTURE",
     "components": [{"name": "FT-I", "entered": "04/Sep/2026", "scored": 4.5, "max": 5.0},
                    {"name": "FT-II", "entered": "09/Sep/2026", "scored": 11.7, "max": 15.0}],
     "scored_total": 16.2, "max_total": 20.0},
    {"code": "21MAB206T", "title": "NUMERICAL METHODS AND ANALYSIS",
     # portal order is by entry: FT-I was entered AFTER FT-II — name sort must win
     "components": [{"name": "FT-I", "entered": "21/Sep/2026", "scored": 5.0, "max": 5.0},
                    {"name": "FT-II", "entered": "07/Sep/2026", "scored": 8.4, "max": 15.0}],
     "scored_total": 13.4, "max_total": 20.0},
    {"code": "21LEM201T", "title": "PROFESSIONAL ETHICS",
     "components": [{"name": "FML-I", "entered": "09/Sep/2026", "scored": 17.5, "max": 20.0}],
     "scored_total": 17.5, "max_total": 20.0},
    {"code": "21CSC203P", "title": "ADVANCED PROGRAMMING PRACTICE",
     "components": [{"name": "FP-I", "entered": "23/Sep/2026", "scored": 7.2, "max": 10.0}],
     "scored_total": 7.2, "max_total": 10.0},
]
v = _marks_view(MARKS)
by = {s["code"]: s for s in v}

# ── subject level: title-case, integer maxima, neutral outlier rule ───
assert by["21CSS201T"]["title"] == "Computer Organization And Architecture"
assert by["21CSS201T"]["scored_disp"] == "16.2" and by["21CSS201T"]["max_disp"] == "20"
assert by["21CSS201T"]["pct"] == 81.0
assert [s["pct"] for s in v] == [81.0, 67.0, 87.5, 72.0]
# the rendered percent keeps its one decimal: a JS Number would print the
# float as "81" and the hydrated card disagreed with the no-JS paint.
assert [s["pct_disp"] for s in v] == ["81.0", "67.0", "87.5", "72.0"]
# exactly one accent: unique lowest (67.0) AND below the 75 target
assert [s["code"] for s in v if s["outlier"]] == ["21MAB206T"], \
    [s["code"] for s in v if s["outlier"]]
v2 = _marks_view([MARKS[0], MARKS[2]])              # 81.0 vs 87.5 -> nobody is an outlier
assert not any(s["outlier"] for s in v2)

# ── component level: name sort beats date order ──────────────────────
assert [c["name"] for c in by["21MAB206T"]["components"]] == ["FT-I", "FT-II"]
assert [c["date_disp"] for c in by["21MAB206T"]["components"]] == ["21 Sep", "07 Sep"]
coa = {c["name"]: c for c in by["21CSS201T"]["components"]}
assert coa["FT-I"]["score_disp"] == "4.5" and coa["FT-I"]["max_disp"] == "5"
assert coa["FT-I"]["date_disp"] == "04 Sep" and coa["FT-I"]["ie"] is None
assert coa["FT-I"]["derived"] == "" and coa["FT-I"]["confirmed"] is None

# ── no repeated component family => no derived IE at all ──────────────
assert coa["FT-II"]["derived"] == "" and coa["FT-II"]["ie"] is None
pe = by["21LEM201T"]["components"][0]                # Professional Ethics: no tag
assert pe["ie"] is None and pe["max_disp"] == "20"
prac = by["21CSC203P"]["components"][0]              # single FP: nothing to pair with
assert prac["ie"] is None

# ── derived IE pair: earliest -> /50, latest -> /60, middle unlabelled ─
_pair = _marks_view([{"code": "21MAB206T", "title": "NUMERICAL METHODS AND ANALYSIS",
                      "components": _ft, "scored_total": 45.2, "max_total": 60.0}])[0]
pc = {c["name"]: c for c in _pair["components"]}
assert pc["FT-II"]["derived"] == "IE-1" and pc["FT-II"]["ie"]["confirmed"] is False
assert pc["FT-II"]["ie"]["score_disp"] == "39" and pc["FT-II"]["ie"]["max_disp"] == "50"
assert pc["FT-IV"]["derived"] == "IE-2" and pc["FT-IV"]["ie"]["score_disp"] == "34"
assert pc["FT-III"]["derived"] == "" and pc["FT-III"]["ie"] is None   # middle repeat: no guess
assert pc["FT-I"]["derived"] == ""                                    # /5 is never an IE

# ── headline: scored/max, or the grade for an internal-only /100 course ─
assert by["21CSS201T"]["head_disp"] == "16.2/20" and by["21CSS201T"]["sub_disp"] == ""
assert by["21CSS201T"]["internal"] is False and by["21CSS201T"]["grade"] == ""
_internal = _marks_view([{"code": "21LEM201T", "title": "PROFESSIONAL ETHICS",
                          "components": [{"name": "FML-II", "entered": "16/Nov/2026",
                                          "scored": 91.0, "max": 100.0}],
                          "scored_total": 91.0, "max_total": 100.0}])[0]
assert _internal["internal"] is True and _internal["grade"] == "O"
assert _internal["head_disp"] == "O" and _internal["sub_disp"] == "91/100"

# ── confirmed tags beat the derivation (incl. 'neither') ─────────────
tags = {("21CSS201T", "FT-II"): {"role": "IE-2", "raw_max": 60.0, "scaled_max": 15.0}}
c2 = {c["name"]: c for c in _marks_view(MARKS, tags)[0]["components"]}["FT-II"]
assert c2["confirmed"] == "IE-2" and c2["ie"]["confirmed"] is True
assert c2["ie"]["max_disp"] == "60" and c2["ie"]["score_disp"] == "46.8"   # 11.7*60/15
tags_none = {("21CSS201T", "FT-II"): {"role": "none", "raw_max": None, "scaled_max": 15.0}}
c3 = {c["name"]: c for c in _marks_view(MARKS, tags_none)[0]["components"]}["FT-II"]
assert c3["ie"] is None and c3["confirmed"] == "none"   # confirmed refusal hides the guess

# ── dashboard glance: ALL subjects (risk-first), chips, no % ──────────
s = _marks_summary(MARKS)
assert [x["code"] for x in s] == ["21MAB206T", "21CSC203P", "21CSS201T", "21LEM201T"], s
assert [(x["scored"], x["max"]) for x in s] == \
    [("13.4", "20"), ("7.2", "10"), ("16.2", "20"), ("17.5", "20")], s
assert all("pct" not in x for x in s)                      # % dropped from the glance
assert all(x["stale"] is False for x in s)                 # fresh rows never flagged
assert _marks_summary([dict(MARKS[0], stale=True)])[0]["stale"] is True  # preserved row carries it
assert _marks_summary([]) is None

# ── recent: portal "Entered on" is date-only, so last-24h == entered TODAY ──
from datetime import date as _date
assert all(x["recent"] is False and x["entered"] == "" for x in s), s  # Sep seeds are never "today"
_today = _date.today().strftime("%d/%b/%Y")
fresh = _marks_summary([{"code": "21CSC201J", "title": "DATA STRUCTURES",
                         "components": [{"name": "FT-I", "entered": _today,
                                         "scored": 4.0, "max": 5.0}],
                         "scored_total": 4.0, "max_total": 5.0}])
assert fresh[0]["recent"] is True and fresh[0]["entered"], fresh  # chip carries the tooltip date
stale_fresh = _marks_summary([{"code": "21X", "title": "T", "stale": True,
                               "components": [{"name": "FT-I", "entered": _today,
                                               "scored": 1.0, "max": 5.0}],
                               "scored_total": 1.0, "max_total": 5.0}])
assert stale_fresh[0]["recent"] is False  # stale wins the chip: no fresh entry shown

# ── week widget: components entered this Mon-Sun only ─────────────────────
_wk = _week_marks([{"code": "21CSC201J", "components": [
                       {"name": "FT-I", "entered": _today, "scored": 4, "max": 5},
                       {"name": "CT-1", "entered": (_date.today() - __import__("datetime").timedelta(days=8)).strftime("%d/%b/%Y"),
                        "scored": 4, "max": 5}]}])
assert [(r["code"], r["name"]) for r in _wk] == [("21CSC201J", "FT-I")], _wk
assert _week_marks([]) == [] and _week_marks(None) == []

# ── class key: year|branch|section (no semester) + per-student fallback ─
PROG = {"Program": "B.Tech.-Computer Science and Engineering with specialization in "
                   "Cloud Computing[UG - FT - ACADEMIC]", "Batch": "2025", "Section": "A"}
assert _class_key(PROG, "xx0001") == \
    "2025|Computer Science and Engineering Cloud Computing|A"
assert "III" not in _class_key(PROG, "xx0001")       # semester deliberately excluded
assert _class_key({"Batch": "2025"}, "xx0001") == "net:xx0001"   # never a shared '?' bucket
# refactor guard: _group_key output unchanged by the _program_short extraction
assert _group_key({**PROG, "Semester": "III SEMESTER"}) == \
    "Computer Science and Engineering Cloud Computing_2025_3_A"
print("ok  marks view model")
