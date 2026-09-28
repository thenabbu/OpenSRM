"""Tests for the end-sem schedule probe (ScribeInner leak).

Run: .venv/bin/python tests/test_exams.py   (plain script, repo convention)
Fixture HTML is SYNTHETIC — mirrors the live Sep 27 2026 structure exactly
(checkbox td + 6 data columns / 'No subject found' empty marker) with fake
subject codes and dates. Never commit real leaked schedule rows.
"""
import os
import sys
import tempfile
from datetime import datetime

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="exam-test-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.app import parse_exam_schedule  # noqa: E402  (import runs init_db)
from app.http_scraper import _merge_exam_results, exam_candidates  # noqa: E402

ROW = """<tr>
    <td><div class="form-check">
        <input type="checkbox" class="form-check-input clsScribeCheck" id="rdnSubjectList{n}"
               onchange="funCalculateAmount()" value="{sid}" data-amount="300.00">
    </div></td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">{code}</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">{name}</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">{date}</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">AN</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">T-EXT</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">300.00</td>
</tr>"""

FULL_PAGE = ('<div class="table-responsive"><table class="table"><thead>'
             '<tr><th colspan="7" class="bg-custom text-white">Subjects List</th></tr>'
             '<tr class="alert-primary"><th></th><th>Subject Code</th>'
             '<th>Subject Description</th><th>Date</th><th>Session</th>'
             '<th>Type</th><th>Scribe Amount</th></tr></thead><tbody>'
             + ROW.format(n=1, sid="40001", code="21AAA101J", name="TEST SUBJECT ONE", date="15-11-2029")
             + ROW.format(n=2, sid="40002", code="21BBB102T", name="TEST SUBJECT TWO", date="16-11-2029")
             + ROW.format(n=3, sid="40003", code="21CCC103P", name="TEST SUBJECT THREE", date="17-11-2029")
             + ROW.format(n=4, sid="40004", code="21DDD104T", name="TEST SUBJECT FOUR", date="18-11-2029")
             + "</tbody></table></div>")

EMPTY_PAGE = ('<div class="table-responsive"><table class="table"><thead><tr>'
              '<th colspan="7">Subjects List</th></tr></thead><tbody><tr><td colspan="7">'
              'No subject found</td></tr></tbody></table></div>')

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok  {name}")
    else:
        failed += 1
        print(f"FAIL  {name} {detail}")


# 1. full page -> 4 rows, exact fields
rows = parse_exam_schedule(FULL_PAGE)
check("4 rows parsed", len(rows) == 4, f"got {len(rows)}")
check("fields exact", rows and rows[0] == {"code": "21AAA101J", "name": "TEST SUBJECT ONE",
      "date": "15-11-2029", "session": "AN", "type": "T-EXT"}, rows[:1])
check("checkbox cell not leaked into code", all(r["code"][:3] == "21A" or r["code"][:2] in ("21",) for r in rows))
check("amount column not captured", all("300" not in r["type"] for r in rows))

# 2. empty marker -> []
check("empty page -> []", parse_exam_schedule(EMPTY_PAGE) == [])
check("No subject found text", parse_exam_schedule("No subject found") == [])
check("None/'' -> []", parse_exam_schedule(None) == [] and parse_exam_schedule("") == [])

# 3. junk does not throw and yields []
check("junk -> []", parse_exam_schedule("<html><body>maintenance</body></html>") == [])
check("login page -> []", parse_exam_schedule("<form id='youLogin'></form>") == [])

# 4. candidate windows (Sep 27 2026 — the verified live window)
c927 = exam_candidates(datetime(2026, 9, 27))
check("Sep2026 contains (11,2026)", (11, 2026) in c927, c927)
check("Sep2026 contains (12,2026)", (12, 2026) in c927, c927)
check("Sep2026 excludes past (5,2026)", (5, 2026) not in c927, c927)
check("Sep2026 excludes far (11,2027)", (11, 2027) not in c927, c927)
check("Sep2026 <= 6 candidates", len(c927) <= 6, c927)

# 5. year rollover: Jan 5 2027 must still probe the Dec-2026 session
c0105 = exam_candidates(datetime(2027, 1, 5))
check("Jan2027 still probes (12,2026)", (12, 2026) in c0105, c0105)
check("Jan2027 probes even-sem (4,2027)", (4, 2027) in c0105, c0105)

# 6. even-sem season: Apr 2027 probes its own window
c0401 = exam_candidates(datetime(2027, 4, 1))
check("Apr2027 contains (5,2027)", (5, 2027) in c0401, c0401)
check("Apr2027 contains (6,2027)", (6, 2027) in c0401, c0401)

# 7. merge: dedupe across overlapping windows, sort by real date
merged = _merge_exam_results([((11, 2026), FULL_PAGE), ((12, 2026), FULL_PAGE)])
check("merge dedupes windows", merged is not None and len(merged) == 4, merged)
check("merge sorted by date", merged and [r["date"] for r in merged] ==
      sorted((r["date"] for r in merged), key=lambda d: (d[6:], d[3:5], d[:2])), merged)
unsorted_page = EMPTY_PAGE.replace(
    "No subject found", "") + ROW.format(n=9, sid="40009", code="21ZZZ999T", name="LATE EXAM", date="02-12-2029")
m2 = _merge_exam_results([((11, 2026), FULL_PAGE), ((12, 2026), unsorted_page)])
check("merge sorts Nov before Dec", m2 and m2[-1]["date"] == "02-12-2029", m2)

# 8. merge contract: all-transport-fail -> None (preserve), garbage -> None
check("all None -> None", _merge_exam_results([None, None]) is None)
check("garbage -> None", _merge_exam_results([((11, 2026), "<html>blocked</html>")]) is None)
check("clean empty -> []", _merge_exam_results([((11, 2026), EMPTY_PAGE)]) == [])

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
