"""One runnable check for _exams_view (the dashboard card's view model)."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# verify76 forbids test-DB files in the repo root / tests dir
with tempfile.TemporaryDirectory() as td:
    import os
    os.environ["DATA_DIR"] = td
    from app.app import _exams_view

rows = [
    {"code": "21MAB206T", "name": "NUMERICAL METHODS AND ANALYSIS", "date": "25-11-2026", "session": "AN"},
    {"code": "21CSC201J", "name": "DATA STRUCTURES AND ALGORITHMS", "date": "27-11-2026", "session": "AN"},
]
v = _exams_view(json.loads(json.dumps(rows)))   # round-trip like the DB does
assert v is not None
assert [r["short"] for r in v["rows"]] == ["25 Nov", "27 Nov"], v["rows"]
assert [r["day"] for r in v["rows"]] == ["25", "27"]
assert v["rows"][0]["dow"] in ("Tue", "Wed"), v["rows"][0]["dow"]   # 25 Nov 2026 = Wednesday
assert v["rows"][0]["name_disp"] == "Numerical Methods And Analysis"
assert v["label"] == "Nov 2026" and v["days_until"] > 0
# junk date falls back to the raw value, never crashes
v2 = _exams_view([{"code": "X", "name": "A B", "date": "junk", "session": "FN"}])
assert v2["rows"][0]["short"] == "junk" and v2["rows"][0]["dow"] == ""
# month-range label when rows span months (session crossing the new year)
v3 = _exams_view([{"code": "X", "name": "A B", "date": "28-12-2026", "session": "AN"},
                  {"code": "Y", "name": "C D", "date": "03-01-2027", "session": "AN"}])
assert v3["label"] == "Dec 2026\u2013Jan 2027", v3["label"]
assert _exams_view([]) is None
print("ok  exams view model")
