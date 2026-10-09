"""Tests for the end-sem schedule probe (ScribeInner leak).

Run: .venv/bin/python tests/test_exams.py   (plain script, repo convention)
Fixture HTML is SYNTHETIC — mirrors the live Sep 27 2026 structure exactly
(checkbox td + 6 data columns / 'No subject found' empty marker) with fake
subject codes and dates. Never commit real leaked schedule rows.
"""
import json
import os
import sys
import tempfile
from datetime import datetime

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="exam-test-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app import push_store  # noqa: E402
from app.app import (  # noqa: E402  (import runs init_db)
    _exam_events, _notify_exam_events, parse_exam_schedule, parse_exam_timetable,
)
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

# 9. Oct 2026 incident: portal lists subjects but blanked Date/Session cells.
#    That is NOT a clean empty — treating it as one wiped stored schedules.
BLANK_ROW = """<tr>
    <td><div class="form-check"><input type="checkbox" class="form-check-input clsScribeCheck"
        id="rdnSubjectList{n}" onchange="funCalculateAmount()" value="{sid}" data-amount="300.00"></div></td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">{code}</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">{name}</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})"></td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})"></td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">T-EXT</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">300.00</td>
</tr>"""
BLANKED_PAGE = ('<div class="table-responsive"><table class="table"><tbody>'
                + BLANK_ROW.format(n=1, sid="39033", code="21CSC201J", name="DATA STRUCTURES AND ALGORITHMS")
                + BLANK_ROW.format(n=2, sid="39034", code="21CSC202J", name="OPERATING SYSTEMS")
                + "</tbody></table></div>")
check("blanked dates -> None (preserve)",
      _merge_exam_results([((11, 2026), BLANKED_PAGE)]) is None)
check("blanked + clean-empty window -> None (preserve)",
      _merge_exam_results([((11, 2026), BLANKED_PAGE), ((12, 2026), EMPTY_PAGE)]) is None)
check("blanked alongside real rows -> real rows win",
      _merge_exam_results([((11, 2026), FULL_PAGE), ((12, 2026), BLANKED_PAGE)]) is not None)

# 10. Official Exam Time Table (iden=126, verified live Oct 7 2026) —
#     `DD-MMM-YYYY AN  (02:00-05:00)` cells; subjects without a slot = `- -`.
#     Synthetic fixture, fake codes; mirrors the live row shape exactly.
ETT_ROW = """<tr>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">III</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">{code}</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">{name}</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})">{datecell}</td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})"></td>
    <td style="cursor: pointer;" onclick="funOnclickSubjectListTr({n})"></td>
</tr>"""
OFFICIAL_ETT = ('<html><head><title>Strike Out Grid Example</title></head><body>'
                '<div class="table-responsive"><table class="table"><tbody>'
                + ETT_ROW.format(n=1, code="21AAA101J", name="TEST SUBJECT ONE",
                                 datecell="25-NOV-2026 AN  (02:00-05:00)")
                + ETT_ROW.format(n=2, code="21BBB102T", name="TEST SUBJECT TWO",
                                 datecell="26-NOV-2026 AN  (02:00-05:00)")
                + ETT_ROW.format(n=3, code="21CCC103P", name="TEST SUBJECT THREE",
                                 datecell="- -")
                + "</tbody></table></div></body></html>")
OFFICIAL_EMPTY = ('<html><head><title>Strike Out Grid Example</title></head><body>'
                  '<div class="table-responsive"><table class="table"><tbody>'
                  '<tr><td colspan="8">No subjects found</td></tr>'
                  '</tbody></table></div></body></html>')

from app.app import parse_exam_timetable  # noqa: E402

ett = parse_exam_timetable(OFFICIAL_ETT)
check("ett parses dated rows only", len(ett) == 2, ett)
check("ett date DD-MMM -> dd-mm-yyyy",
      ett and ett[0]["date"] == "25-11-2026", ett and ett[0]["date"])
check("ett session extracted from datecell", ett and ett[0]["session"] == "AN")
check("ett clock slot extracted", ett and ett[0]["slot"] == "02:00-05:00")
check("ett pending rows (- -) dropped", not any(r["code"] == "21CCC103P" for r in ett))
check("ett empty -> []", parse_exam_timetable(OFFICIAL_EMPTY) == [])
check("ett garbage -> []", parse_exam_timetable("<html>x</html>") == [])
ett_fn = parse_exam_timetable(ETT_ROW.format(n=5, code="21DDD104T", name="FN SUB",
                                             datecell="01-DEC-2026 FN  (09:30-12:30)"))
check("ett FN + morning slot", ett_fn and ett_fn[0]["session"] == "FN"
      and ett_fn[0]["slot"] == "09:30-12:30", ett_fn)

# 11. merge: official wins per code; scribe fills official-pending subjects
merged_off = _merge_exam_results([((11, 2026), FULL_PAGE)], official_html=OFFICIAL_ETT)
check("official + scribe merge -> 4 rows", merged_off is not None and len(merged_off) == 4, merged_off)
check("official replaces scribe row for same code",
      merged_off and not any(r["code"] == "21AAA101J" and r.get("slot", "") == ""
                             for r in merged_off), merged_off)
check("scribe fills official-pending code",
      merged_off and any(r["code"] == "21CCC103P" and r.get("slot", "") == "" for r in merged_off),
      merged_off)
check("scribe fills code absent from official",
      merged_off and any(r["code"] == "21DDD104T" for r in merged_off), merged_off)
only_off = _merge_exam_results([], official_html=OFFICIAL_ETT)
check("official alone -> 2 rows", only_off is not None and len(only_off) == 2, only_off)
off_empty = _merge_exam_results([((11, 2026), FULL_PAGE)], official_html=OFFICIAL_EMPTY)
check("official empty + scribe rows -> scribe wins",
      off_empty is not None and len(off_empty) == 4, off_empty)
check("official garbage + scribe rows -> scribe wins",
      _merge_exam_results([((11, 2026), FULL_PAGE)], official_html="<html>blocked</html>") is not None)
check("official table no transport + no scribe -> None",
      _merge_exam_results([None, None], official_html=OFFICIAL_EMPTY) is None)

# ── 12. official-timetable adaptability: header-driven columns ──────────────
HDR_ETT = """<table><tbody><tr><th>Sem/Year/Trim</th><th>Subject Code</th>
<th>Subject Description</th><th>Date &amp; Session</th><th>Hall No.</th>
<th>Seat No.</th><th>November -2026</th></tr>
<tr><td>III</td><td>21AAA101J</td><td>TEST SUBJECT A</td>
<td>25-NOV-2026 AN  (02:00-05:00)</td><td>12</td><td>08</td><td></td></tr>
<tr><td>III</td><td>21BBB102J</td><td>TEST SUBJECT B</td>
<td>26-NOV-2026 FN  (09:30-12:30)</td><td>12</td><td>09</td><td></td></tr>
</tbody></table>"""
hdr_rows = parse_exam_timetable(HDR_ETT)
check("header row: 2 rows parsed", hdr_rows is not None and len(hdr_rows) == 2, hdr_rows)
check("header row: hall/seat read",
      hdr_rows and hdr_rows[0]["hall"] == "12" and hdr_rows[0]["seat"] == "08", hdr_rows)
check("header row: FN session + slot",
      hdr_rows and hdr_rows[1]["session"] == "FN" and hdr_rows[1]["slot"] == "09:30-12:30",
      hdr_rows)
# portal INSERTS an extra column (header + rows both grow) -> known fields still resolve
EXTRA_ETT = (HDR_ETT.replace("<th>Date &amp; Session</th>",
                             "<th>Reporting Time</th><th>Date &amp; Session</th>")
             .replace("<td>25-NOV-2026", "<td>08:45</td><td>25-NOV-2026")
             .replace("<td>26-NOV-2026", "<td>08:45</td><td>26-NOV-2026"))
extra_rows = parse_exam_timetable(EXTRA_ETT)
check("extra column inserted -> date/hall still resolve by header",
      extra_rows and len(extra_rows) == 2 and extra_rows[0]["date"] == "25-11-2026"
      and extra_rows[0]["hall"] == "12", extra_rows)
# header present but Hall No. column GONE -> "" (no positional guessing)
NOHALL_ETT = HDR_ETT.replace("<th>Hall No.</th>", "").replace("<td>12</td>", "")
nohall_rows = parse_exam_timetable(NOHALL_ETT)
check("hall column gone -> hall empty, seat still read",
      nohall_rows and nohall_rows[0]["hall"] == "" and nohall_rows[0]["seat"] == "08",
      nohall_rows)
# table present but nothing parses (label drift) -> None, never a clean empty
DRIFT = ("<table><tr><th>A</th><th>B</th><th>C</th><th>D</th></tr>"
         "<tr><td>1</td><td>2</td><td>3</td><td>4</td></tr></table>")
check("drifted table -> None (preserve, not wipe)", parse_exam_timetable(DRIFT) is None)
_drift_scribe = _merge_exam_results([((11, 2026), FULL_PAGE)], official_html=DRIFT)
check("drift + scribe rows -> scribe applied (official broken must not freeze updates)",
      _drift_scribe is not None and {r["code"] for r in _drift_scribe} >= {"21AAA101J", "21BBB102T"},
      _drift_scribe)
check("drift + NO scribe rows -> preserved (None)",
      _merge_exam_results([], official_html=DRIFT) is None)

# ── 13. transition detector (_exam_events) ──────────────────────────────────
est = [{"code": "21AAA101J", "date": "25-11-2026", "session": "AN"}]
off = [{"code": "21AAA101J", "date": "25-11-2026", "session": "AN", "slot": "02:00-05:00"}]
ev = _exam_events(json.dumps(est), off)
check("estimate->official fires release event",
      len(ev) == 1 and ev[0]["claim"] == "official-25-11-2026", ev)
check("release body carries the first exam date", "25 Nov" in ev[0]["body"], ev[0])
check("release claim stable across re-detection",
      _exam_events(json.dumps(est), off)[0]["claim"] == ev[0]["claim"])
check("fresh user (nothing stored) gets no release note", _exam_events(None, off) == [])
check("official->official: no event", _exam_events(json.dumps(off), off) == [])
off_h = [dict(off[0], hall="12", seat="08")]
hv = _exam_events(json.dumps(off), off_h)
check("hall publication fires one event",
      len(hv) == 1 and hv[0]["claim"].startswith("hall-"), hv)
check("hall body names room + seat",
      "Hall 12" in hv[0]["body"] and "Seat 08" in hv[0]["body"], hv[0])
check("same hall state -> no event", _exam_events(json.dumps(off_h), off_h) == [])
hv2 = _exam_events(json.dumps(off_h), [dict(off[0], hall="14", seat="09")])
check("room change re-notifies with a different claim",
      len(hv2) == 1 and hv2[0]["claim"] != hv[0]["claim"], (hv, hv2))
check("release + hall publish together -> both events",
      len(_exam_events(json.dumps(est), off_h)) == 2)

# ── 14. notifier: at-most-once claims + payload shape ───────────────────────
push_store.upsert_subscription("zz9999", "https://push.example/ep1", "p256dh", "auth", "DUT")
sent_payloads = []


def _fake_batch(jobs, deadline):
    for j in jobs:
        j["outcome"] = {"ok": True, "http_status": 201}
        sent_payloads.append(j["payload"])
    return jobs


conf = {"enabled": True, "configured": True, "dry_run": False, "allow": set()}
n1 = _notify_exam_events("zz9999", ev, conf=conf, send_batch=_fake_batch)
check("event push sends once", n1 == 1 and len(sent_payloads) == 1, (n1, sent_payloads))
p = sent_payloads[0] if sent_payloads else {}
check("payload shape (title/body/tag/url)",
      {"title", "body", "tag", "url"} <= set(p) and p.get("url") == "/", p)
check("second call: claim blocks (at-most-once)",
      _notify_exam_events("zz9999", ev, conf=conf, send_batch=_fake_batch) == 0)
check("dry-run sends nothing",
      _notify_exam_events("zz9999", hv, conf=dict(conf, dry_run=True),
                          send_batch=_fake_batch) == 0)
check("dry-run did NOT consume the claim -> live send works after",
      _notify_exam_events("zz9999", hv, conf=conf, send_batch=_fake_batch) == 1)
check("no subscriptions -> nothing sent",
      _notify_exam_events("nobody-here", ev, conf=conf, send_batch=_fake_batch) == 0)

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
