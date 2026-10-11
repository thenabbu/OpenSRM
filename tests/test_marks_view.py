"""One runnable check for the internal-marks view model: formatting (dates,
maxima, scores), name-order sorting, IE-1 derivation + /50-/60 conversion,
confirmed-vs-derived override, the single accent, and the class-scoped key."""
import os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# verify76 forbids test-DB files in the repo root / tests dir
with tempfile.TemporaryDirectory() as td:
    os.environ["DATA_DIR"] = td
    from app.app import (_marks_view, _marks_summary, _fmt_date, _fmt_max, _fmt_score,
                         _derive_ie, _class_key, _group_key)

# ── formatting ────────────────────────────────────────────────────────
assert _fmt_date("04/Sep/2026") == "04 Sep"
assert _fmt_date("21/Sep/2026") == "21 Sep"
assert _fmt_date("") == "" and _fmt_date(None) == "" and _fmt_date("junk") == "junk"
assert _fmt_max(15.0) == "15" and _fmt_max(10.0) == "10" and _fmt_max(20.0) == "20"
assert _fmt_max(15.5) == "15.50", _fmt_max(15.5)      # fractional maxima keep 2 decimals
assert _fmt_score(11.7) == "11.7" and _fmt_score(5) == "5"

# ── IE-1 derivation (a guess until confirmed) ─────────────────────────
assert _derive_ie("21CSS201T", 15.0) == "IE-1"        # the /15 component
assert _derive_ie("21CSC203P", 10.0) == "IE-1"        # practical /10
assert _derive_ie("21CSS201T", 10.0) is None          # theory /10 is NOT an IE
assert _derive_ie("21LEM201T", 20.0) is None          # Professional Ethics: never
assert _derive_ie("21CSS201T", 5.0) is None           # FT-I /5: neither

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

# ── derived IE row: 11.7/15 -> 39/50 ──────────────────────────────────
assert coa["FT-II"]["derived"] == "IE-1" and coa["FT-II"]["confirmed"] is None
assert coa["FT-II"]["ie"]["role"] == "IE-1" and coa["FT-II"]["ie"]["confirmed"] is False
assert coa["FT-II"]["ie"]["score_disp"] == "39" and coa["FT-II"]["ie"]["max_disp"] == "50"
pe = by["21LEM201T"]["components"][0]                # Professional Ethics: no tag
assert pe["ie"] is None and pe["max_disp"] == "20"
prac = by["21CSC203P"]["components"][0]              # practical /10 -> 7.2/10 = 36/50
assert prac["ie"]["role"] == "IE-1" and prac["ie"]["score_disp"] == "36"

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
