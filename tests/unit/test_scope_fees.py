"""SCOPE fees suite — ##-row parser, dues logic, narration clause, ledger
sort, feature gate (mission contract agents/fees.md).

Checks:
  - ##-split parser: the real fixture row -> all six fields (amount with
    .00, date "13-Aug-2025", year "2025-2026", trailing "0").
  - dues logic: paid==total + trailing 0 -> 0; synthetic paid=100 total=150
    trailing=0 -> 50; synthetic trailing=50 -> 50 (due_of / fees_view sum),
    and a disagreeing row now SURFACES as its own named charge.
  - the deadline pair: lastdateforfeepaymentwithoutlatefee -> the cheap
    deadline, penaltydate + feewithlatefee -> the late-fee delta, days_left
    from an injected today, overdue when it is past.
  - money is Indian-grouped with no bare ".00"; all three SCOPE date shapes
    parse day-first and render as "23 Nov 2026".
  - unicode/garbage narration -> first-clause split never raises and never
    leaks tab/CR/LF into the clause; the receipt head is one short line.
  - ledger sort: newest voucherdate first.
  - feature gate off -> no tab: _fees_view(features w/o 'fees') is None AND
    the dashboard template guards the navbar item + panel on {% if fees %}.

Self-contained: fixture rows are literals copied from the mission's live
fixtures (fees.txt / finance.txt) — no server, no network, no DB, no DATA_DIR.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from datetime import date  # noqa: E402

from app.views.fees import (_date, _due_of, _exam_dues, _fees_view, _first_clause,  # noqa: E402
                            _cycle, _fmt, _head_of, _level, _money, _parse_fee_rows, _title,
                            _worst)
from app.scope.ops import enabled_features  # noqa: E402

# verbatim from fixtures/fees.txt + fixtures/finance.txt (mission scope-integration)
FEE_ROWS = [
    {"feedetails": "Registration Fee##10000.00##10000.00##13-Aug-2025##2025-2026##0"},
    {"feedetails": "Tuition Fees##200000.00##200000.00##13-Aug-2025##2025-2026##0"},
    {"feedetails": "Exam Fees##3150.00##3150.00##24-Sep-2026##2026-2027##0"},
]
FIN_ROWS = [
    {"amount": "111000.00", "vouchertype": "Receipt",
     "narration": "being recd. fee for the yr.2025-26 THRU 08-08-2025\t\tIMPS/P2A/522013235148/UMASHANK/ICICIBAN/SRMFinal\r\n\r\n",
     "voucherdate": "2025-11-21", "vouchernumber": "17174"},
    {"amount": "4050.00", "vouchertype": "Receipt",
     "narration": "Being Fee received from student for Exam Fees fee paid through online using Pay U (Axis) with bank transaction id 1116435793 on 2025-11-23 23:53:02.177",
     "voucherdate": "2025-11-26", "vouchernumber": "17720"},
    {"amount": "200000.00", "vouchertype": "Receipt",
     "narration": "Being Fee received from student for College Fees fee paid through online using Pay U (Axis) with bank transaction id 1221229971 on 2026-06-29 23:13:37.86",
     "voucherdate": "2026-07-02", "vouchernumber": "8162"},
]


# verbatim from the live getStudentExamFeesDetails call (2026-11-04, netid ng2776):
# the student OWES 3150 on the exam fee while the getFeeDetails row above shows
# Exam Fees as 3150/3150 paid and trailing 0 — this fixture is the regression.
EXAM_ROWS = [
    {"partpaymentapplicable": 0, "studentname": "NAVYA GUPTA", "startdate": "21-09-2026",
     "minamount": 3150, "amounttopay": 3150, "studentid": "709245", "paidamount": 0,
     "enddate": "25-11-2026", "penaltystatus": 0, "sno": "2440869", "officeid": "20",
     "amountwithoutpenalty": 3150, "penaltydate": "24-11-2026", "ischeckvisible": "t",
     "appln_category_id": "1"},
]


# the FULL live shape as of 2026-11-26 (netid ds4647 family): feetype, the
# cheap-payment deadline, the penalty date and the total WITH the late fee.
LIVE_EXAM = [{
    "academicyear": "NOVEMBER-2026", "studentname": "DRISHYA SINGHAL", "minamount": 3150,
    "concessionamount": 0, "amounttopay": 3150, "paidamount": 0, "studentid": "690833",
    "enddate": "24-11-2026", "penaltystatus": 0, "penaltyamount": 1000, "sno": "2440838",
    "officeid": "20", "amountwithoutpenalty": 3150, "feetype": "Exam Fees", "feetypeid": "2",
    "ischeckvisible": "t", "penaltydate": "24-11-2026",
    "lastdateforfeepaymentwithoutlatefee": "23-11-2026", "feewithlatefee": 4150,
}]

# a pinned clock: every days_left assertion is relative to this, so the suite
# does not rot into "overdue" next week
TODAY = date(2026, 11, 20)


def _scope(fee_rows=None, fin_rows=None, exam_rows=None):
    return {"getFeeDetails": {"data": FEE_ROWS if fee_rows is None else fee_rows, "ts": 1},
            "getFinanceDetails": {"data": FIN_ROWS if fin_rows is None else fin_rows, "ts": 1},
            "getStudentExamFeesDetails": {"data": EXAM_ROWS if exam_rows is None else exam_rows, "ts": 1}}


def t_parser_fixture_row_fields():
    rows = _parse_fee_rows(FEE_ROWS)
    assert len(rows) == 3, rows
    r = rows[1]
    assert r["head"] == "Tuition Fees", r
    assert r["paid"] == "200000.00" and r["total"] == "200000.00", r   # amount with .00
    assert r["date"] == "13-Aug-2025", r
    assert r["year"] == "2025-2026" and r["trailing"] == "0", r
    assert rows[2]["date"] == "24-Sep-2026", rows[2]
    # junk never raises: not-a-list, non-dict items, headless/short rows
    assert _parse_fee_rows(None) == []
    assert _parse_fee_rows([{"nope": "x"}, {"feedetails": ""}, {"feedetails": "OnlyHead"}]) == [
        {"head": "OnlyHead", "paid": "", "total": "", "date": "", "year": "", "trailing": ""}]


def t_dues_zero_when_paid_equals_total():
    rows = _parse_fee_rows(FEE_ROWS)                       # all 3 real rows: paid==total, trailing 0
    assert [_due_of(r) for r in rows] == [0.0, 0.0, 0.0]
    v = _fees_view(_scope(exam_rows=[]), {"fees"})          # legacy path: no exam op yet
    assert v["due"] == 0.0 and v["due_disp"] == "" and v["level"] == "", v


def t_dues_partial_amount_is_total_minus_paid():
    row = _parse_fee_rows([{"feedetails": "Tuition##100.00##150.00##01-Jan-2026##2025-2026##0"}])[0]
    assert _due_of(row) == 50.0, row


def t_dues_trailing_field_wins():
    row = _parse_fee_rows([{"feedetails": "Tuition##150.00##150.00##01-Jan-2026##2025-2026##50"}])[0]
    assert _due_of(row) == 50.0, row
    v = _fees_view(_scope(fee_rows=[{"feedetails": "Tuition##100.00##150.00##01-Jan-2026##2025-2026##0"},
                                    {"feedetails": "Exam##50.00##50.00##01-Jan-2026##2025-2026##25"}],
                                 exam_rows=[]),
                   {"fees"})
    assert v["due"] == 75.0 and v["due_disp"] == "75", v
    # a dateless charge has no deadline, so it earns no status hue
    assert v["level"] == "", v
    # a disagreeing row is not folded into a silent sum: it becomes a named
    # charge, because "you owe 75" with no explanation is not an answer
    assert [(d["head"], d["amt"]) for d in v["dues"]] == [("Exam", "25"), ("Tuition", "50")], v["dues"]
    # 2 charges -> the sum line earns its ink; 1 charge -> it would be a dup
    assert v["due_sum"] == "75", v["due_sum"]


def t_narration_first_clause_never_raises():
    # unicode + control garbage straight off the real row + synthetic junk
    for text in ("being recd. fee\tyr\r\nnext\u0000\u200bdetails", "\t\t\r\n", "", None, 123,
                 "№ unpaid — ₹1,00,000 ✓ …", ".", "no terminator at all"):
        clause = _first_clause(text)                        # must not raise
        assert isinstance(clause, str)
        assert "\t" not in clause and "\r" not in clause and "\n" not in clause, clause
    assert _first_clause(FIN_ROWS[0]["narration"]) == "being recd. fee for the yr.2025-26 THRU 08-08-2025"
    assert _first_clause(FIN_ROWS[1]["narration"]).startswith("Being Fee received")


def t_receipt_head_is_one_line():
    """Receipt head = the one line the collapsed row shows: no channel tail,
    no duplicated amount, no abbreviation cut, and junk never raises."""
    assert _head_of(FIN_ROWS[0]["narration"]) == "recd. fee for the yr.2025-26"
    assert _head_of(FIN_ROWS[1]["narration"]) == "Fee received from student for Exam Fees"
    # a real admission-fee narration: the "Accounted with bank transaction id
    # …" tail is cut, and the collapsed row's label is capped on a word
    assert _head_of("Being Admission FEE  for the academic year 2025 - 2026  Accounted with bank transaction id 520623190760 on 2025-07-25") \
        == "Admission FEE for the academic year 2025"
    # the ERP auto-posted shape names the head once, then dumps the gateway
    # trail — that token is the only honest label in the string
    assert _head_of("Fee Collection - Auto Posting - Dt 20-05-2025 Mode : Bank Receipt  "
                    "Applicant Name : 25011022766 ADITYA VERMA Fee heads : Advance Fees "
                    "Online Payment Date : 2025-05-20 ERP Online Receipt Id :203370") == "Advance Fees"
    # and no head is ever long enough to eat a phone row
    for n in (FIN_ROWS[0]["narration"], FIN_ROWS[1]["narration"],
              "Being bus fees received for the year 2025-2026 Bus Pass No : 68920 Institution Name : SRM"):
        assert len(_head_of(n)) <= 44, _head_of(n)
    for junk in ("", "   ", "\t\t&\r\n", None, 12):
        assert isinstance(_head_of(junk), str)
    assert "\t" not in _head_of("a\tb") and "\n" not in _head_of("a\nb")


def t_ledger_sorted_newest_first():
    v = _fees_view(_scope(exam_rows=[]), {"fees"})
    dates = [e["date"] for e in v["ledger"]]
    assert dates == ["2 Jul 2026", "26 Nov 2025", "21 Nov 2025"], dates
    assert v["ledger"][0]["amt"] == "2,00,000" and v["ledger"][0]["vno"] == "8162", v["ledger"][0]


def t_feature_gate_off_no_tab():
    # view side: feature off (or no data at all) -> None -> template shows nothing
    assert _fees_view(_scope(exam_rows=[]), set()) is None
    assert _fees_view(_scope(exam_rows=[]), {"hourwise", "academics"}) is None
    assert _fees_view({}, {"fees"}) is None                  # feature on, but no data
    # env side: SCOPE_FEATURES without 'fees' disables the slug
    old = os.environ.get("SCOPE_FEATURES")
    os.environ["SCOPE_FEATURES"] = "hourwise"
    try:
        assert "fees" not in enabled_features()
    finally:
        if old is None:
            os.environ.pop("SCOPE_FEATURES", None)
        else:
            os.environ["SCOPE_FEATURES"] = old
    # template side: the navbar item is guarded in base.html (it owns the nav)
    # and the panel is guarded in fees.html - each asserted where it is written.
    for path, needle in (("base.html", 'id="tab-fees-tab"'), ("fees.html", 'id="tab-fees"')):
        tpl = (REPO / "app" / "templates" / path).read_text()
        i = tpl.index(needle)
        guard = tpl.rfind("{% if fees %}", 0, i)
        endif = tpl.rfind("{% endif %}", 0, i)
        assert guard != -1 and guard > endif, f"{needle} in {path} not inside {{% if fees %}} guard"


def t_exam_dues_beat_the_paid_row():
    """THE regression: real data has Exam Fees 3150/3150 paid + trailing 0 in
    getFeeDetails, while getStudentExamFeesDetails says 3150 is still owed and
    due 25-11-2026. The hero must show 3150, not 0."""
    assert _due_of(_parse_fee_rows(FEE_ROWS)[2]) == 0.0        # the trap
    total, rows = _exam_dues(EXAM_ROWS, today=TODAY)
    assert total == 3150.0, total
    # no feetype on this older row -> the op's own name, never a bare "Fee"
    assert rows[0]["head"] == "Exam fee", rows
    assert rows[0]["amt"] == "3,150" and rows[0]["deadline"] == "24 Nov 2026", rows
    assert rows[0]["overdue"] is False and rows[0]["days_left"] == 4, rows
    v = _fees_view(_scope(), {"fees"}, today=TODAY)
    assert v["due"] == 3150.0 and v["due_disp"] == "3,150", v
    assert v["level"] == "text-warning", v
    assert len(v["dues"]) == 1 and v["dues"][0]["amt"] == "3,150", v["dues"]
    assert v["due_sum"] == "", v["due_sum"]   # one charge: no dup total line


def t_exam_dues_partial_and_penalty():
    """amounttopay - paidamount is the money owed (minamount is only the
    part-payment floor), and penaltystatus latches the warning."""
    data = [{"amounttopay": 5000, "paidamount": 2000, "minamount": 1000,
             "enddate": "01-12-2026", "penaltydate": "01-12-2026", "penaltystatus": 1}]
    total, rows = _exam_dues(data, today=TODAY)
    assert total == 3000.0, total
    assert rows[0]["penalised"] is True, rows
    # fully paid row is not a due
    assert _exam_dues([{**data[0], "paidamount": 5000}], today=TODAY)[0] == 0.0


def t_exam_dues_envelope_means_nothing_owed():
    """The 'No Details found' envelope is an ALIVE-EMPTY, not a due — and junk
    never raises (getStudentTuitionFeesDetails returns exactly this shape)."""
    for data in ({"Status": "Success", "Message": "No Details found", "Data": ""},
                 [], None, "", [{"junk": 1}], [None], 5):
        assert _exam_dues(data, today=TODAY) == (0.0, []), data
    # envelope-shaped and nothing else -> a zero-dues view, hero absent
    v = _fees_view(_scope(exam_rows={"Status": "Success", "Message": "No Details found", "Data": ""}),
                   {"fees"})
    assert v["due"] == 0.0 and v["due_disp"] == "" and v["dues"] == [], v


def t_exam_dues_alone_still_shows_the_tab():
    """An exam-fee due with no getFeeDetails/getFinanceDetails rows must not
    self-hide: the tab is keyed on having ANY fee source with data."""
    v = _fees_view({"getStudentExamFeesDetails": {"data": EXAM_ROWS, "ts": 1}}, {"fees"}, today=TODAY)
    assert v is not None and v["due"] == 3150.0, v
    # a due with no payment history says so once instead of looking broken
    assert v["years"] == [] and v["paid_total"] == "", v




def t_deadline_pair_and_late_fee_delta():
    """The redesign's core: the page must answer "by when, and what does it
    cost me if I miss it" from fields the old view threw away."""
    total, rows = _exam_dues(LIVE_EXAM, today=TODAY)
    r = rows[0]
    assert total == 3150.0, total
    assert r["head"] == "Exam Fees" and r["cycle"] == "Nov 2026", r   # date-like, not a code
    # cheap deadline is its OWN field, not penaltydate minus a day
    assert r["deadline"] == "23 Nov 2026", r
    assert r["late_on"] == "24 Nov 2026", r
    # the delta, never the 4,150 total the field actually carries
    assert r["late_extra"] == "1,000", r
    assert r["days_left"] == 3 and r["overdue"] is False, r
    # penaltyamount is the fallback when feewithlatefee is absent
    no_total = [{k: v for k, v in LIVE_EXAM[0].items() if k != "feewithlatefee"}]
    assert _exam_dues(no_total, today=TODAY)[1][0]["late_extra"] == "1,000", no_total


def t_level_follows_the_deadline_not_the_amount():
    """Colour is TIME, not size: a big bill with weeks left is not an error."""
    assert _level(30) == ""                  # 2,00,000 due in a month: no hue
    assert _level(8) == ""
    assert _level(7) == "text-warning"
    assert _level(0) == "text-warning"       # last day still counts as live
    assert _level(-1) == "text-error"
    assert _level(None) == ""                # dateless charge: nothing to say
    assert _level(40, penalised=True) == "text-error"
    assert _worst(["", "text-warning"]) == "text-warning"
    assert _worst(["text-warning", "text-error"]) == "text-error"
    assert _worst([]) == ""


def t_overdue_and_last_day_wording():
    past = _exam_dues(LIVE_EXAM, today=date(2026, 11, 26))[1][0]
    assert past["days_left"] == -3 and past["overdue"] is True, past
    last = _exam_dues(LIVE_EXAM, today=date(2026, 11, 23))[1][0]
    assert last["days_left"] == 0 and last["overdue"] is False, last


def t_part_payment_floor_only_when_offered():
    """minamount is a floor only when the backend says part payment is on."""
    on = [{"amounttopay": 5000, "paidamount": 0, "minamount": 1000,
           "partpaymentapplicable": 1, "feetype": "Exam Fees"}]
    assert _exam_dues(on, today=TODAY)[1][0]["min"] == "1,000"
    off = [{**on[0], "partpaymentapplicable": 0}]
    assert _exam_dues(off, today=TODAY)[1][0]["min"] == "", off


def t_charges_sorted_soonest_first_dateless_last():
    data = [{"amounttopay": 100, "feetype": "Late One", "pewnaltydate": "", "penaltydate": "30-12-2026"},
            {"amounttopay": 200, "feetype": "Soon", "penaltydate": "22-11-2026"},
            {"amounttopay": 300, "feetype": "No Date"}]
    rows = _exam_dues(data, today=TODAY)[1]
    assert [r["head"] for r in rows] == ["Soon", "Late One", "No Date"], rows


def t_money_indian_grouping():
    assert _money(3150.0) == "3,150"
    assert _money(200000.0) == "2,00,000"
    assert _money(1250000.0) == "12,50,000"
    assert _money(4150.5) == "4,150.50"
    assert _money(0.0) == "0"
    assert _money(999.999) == "1,000"          # paise round into the rupee
    assert _money("junk") == "junk"            # never raises, never reformats junk


def t_dates_parse_day_first_and_render_one_way():
    """Three shapes ship on one page; numeric triplets are dd-mm (SRM's own
    format) — a month-first read would silently move every deadline."""
    assert _date("31-Jul-2025") == date(2025, 7, 31)
    assert _date("24-11-2026") == date(2026, 11, 24)      # not 2026-24-11
    assert _date("2025-11-03") == date(2025, 11, 3)
    for junk in ("", " ", None, "nope", "31-Foo-2025", "31-02-2025", 12, "2026-13-01"):
        assert _date(junk) is None, junk
    assert _fmt("24-11-2026") == "24 Nov 2026"
    assert _fmt("nope") == "nope"                          # raw, not a crash
    assert _title("NOVEMBER-2026") == "November-2026"        # the generic caser
    assert _cycle("NOVEMBER-2026") == "Nov 2026"             # the exam cycle
    assert _cycle("DECEMBER-2026") == "Dec 2026"
    assert _cycle("2025-2026") == "2025-2026"                # an academic year, not a month
    assert _cycle("") == "" and _cycle(None) == ""
    assert _title("Tuition Fees") == "Tuition Fees"


def t_year_header_never_duplicates_the_total():
    """One year: the year moves onto the heading. Two: each keeps its header."""
    one_year = [{"feedetails": "Tuition Fees##200000.00##200000.00##13-Aug-2025##2025-2026##0"}]
    one = _fees_view(_scope(fee_rows=one_year, exam_rows=[]), {"fees"}, today=TODAY)
    assert one["multi_year"] is False and one["year_label"] == "2025-2026", one
    assert one["years"][0]["total"] == "2,00,000" == one["paid_total"], one   # one number, twice at most
    two = _scope(exam_rows=[])
    two["getFeeDetails"]["data"] = FEE_ROWS                # 2025-2026 + 2026-2027
    v = _fees_view(two, {"fees"}, today=TODAY)
    assert v["multi_year"] is True and v["year_label"] == "", v
    assert [y["year"] for y in v["years"]] == ["2026-2027", "2025-2026"], v["years"]
    assert v["paid_total"] == "2,13,150", v   # 10,000 + 2,00,000 + 3,150


def t_garbage_amounts_never_crash_or_print_none():
    v = _fees_view(_scope(fee_rows=[{"feedetails": "Fees##abc##xyz##01-Jan-2026##2025-2026##0"}],
                          fin_rows=[{"amount": "n/a", "voucherdate": "x", "vouchernumber": "",
                                     "narration": None}],
                          exam_rows=[{"amounttopay": "n/a"}]),
                   {"fees"}, today=TODAY)
    assert v["ledger"][0]["amt"] == "n/a" and v["ledger"][0]["vno"] == "", v["ledger"]
    assert v["years"][0]["rows"][0]["amt"] == "abc", v["years"]   # raw string, never "None"
    assert "None" not in str(v)


TESTS = [
    ("##-split parser: fixture row -> fields (+ junk rows)", t_parser_fixture_row_fields),
    ("dues: paid==total + trailing 0 -> 0", t_dues_zero_when_paid_equals_total),
    ("dues: paid=100 total=150 trailing=0 -> 50", t_dues_partial_amount_is_total_minus_paid),
    ("dues: trailing wins + view sum/level", t_dues_trailing_field_wins),
    ("narration first-clause split on unicode/garbage", t_narration_first_clause_never_raises),
    ("receipt head is one clean line", t_receipt_head_is_one_line),
    ("ledger sorted newest voucherdate first", t_ledger_sorted_newest_first),
    ("feature gate off -> no tab (view + env + template guard)", t_feature_gate_off_no_tab),
    ("exam dues beat the 'paid' row (real regression)", t_exam_dues_beat_the_paid_row),
    ("exam dues: amounttopay-paidamount + penalty flag", t_exam_dues_partial_and_penalty),
    ("exam dues: 'No Details found' envelope = nothing owed", t_exam_dues_envelope_means_nothing_owed),
    ("exam dues alone still render the tab", t_exam_dues_alone_still_shows_the_tab),
    ("deadline pair + late fee delta (the redesign's core)", t_deadline_pair_and_late_fee_delta),
    ("colour follows the deadline, not the amount", t_level_follows_the_deadline_not_the_amount),
    ("overdue / last-day wording from an injected clock", t_overdue_and_last_day_wording),
    ("part-payment floor only when the backend offers it", t_part_payment_floor_only_when_offered),
    ("charges sorted soonest first, dateless last", t_charges_sorted_soonest_first_dateless_last),
    ("money is Indian-grouped, no bare .00", t_money_indian_grouping),
    ("dates parse day-first, render one way", t_dates_parse_day_first_and_render_one_way),
    ("year header never duplicates the total", t_year_header_never_duplicates_the_total),
    ("garbage amounts never crash or print None", t_garbage_amounts_never_crash_or_print_none),
]

if __name__ == "__main__":
    failed = 0
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
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
