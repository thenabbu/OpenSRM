"""SCOPE fees suite — ##-row parser, dues logic, narration clause, ledger
sort, feature gate (mission contract agents/fees.md).

Checks:
  - ##-split parser: the real fixture row -> all six fields (amount with
    .00, date "13-Aug-2025", year "2025-2026", trailing "0").
  - dues logic: paid==total + trailing 0 -> 0; synthetic paid=100 total=150
    trailing=0 -> 50; synthetic trailing=50 -> 50 (due_of / fees_view sum).
  - unicode/garbage narration -> first-clause split never raises and never
    leaks tab/CR/LF into the clause.
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

from app.views.fees import _due_of, _fees_view, _first_clause, _head_of, _parse_fee_rows  # noqa: E402
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


def _scope(fee_rows=None, fin_rows=None):
    return {"getFeeDetails": {"data": FEE_ROWS if fee_rows is None else fee_rows, "ts": 1},
            "getFinanceDetails": {"data": FIN_ROWS if fin_rows is None else fin_rows, "ts": 1}}


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
    v = _fees_view(_scope(), {"fees"})
    assert v["due"] == 0.0 and v["due_disp"] == "" and v["level"] == "", v


def t_dues_partial_amount_is_total_minus_paid():
    row = _parse_fee_rows([{"feedetails": "Tuition##100.00##150.00##01-Jan-2026##2025-2026##0"}])[0]
    assert _due_of(row) == 50.0, row


def t_dues_trailing_field_wins():
    row = _parse_fee_rows([{"feedetails": "Tuition##150.00##150.00##01-Jan-2026##2025-2026##50"}])[0]
    assert _due_of(row) == 50.0, row
    v = _fees_view(_scope(fee_rows=[{"feedetails": "Tuition##100.00##150.00##01-Jan-2026##2025-2026##0"},
                                    {"feedetails": "Exam##50.00##50.00##01-Jan-2026##2025-2026##25"}]),
                   {"fees"})
    assert v["due"] == 75.0 and v["due_disp"] == "75.00" and v["level"] == "text-warning", v


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
    assert _head_of(FIN_ROWS[0]["narration"]) == "being recd. fee for the yr.2025-26"
    assert _head_of(FIN_ROWS[1]["narration"]) == "Being Fee received from student for Exam Fees"
    # a real admission-fee narration: the "Accounted with bank transaction id
    # …" tail is cut, the year stays
    assert _head_of("Being Admission FEE  for the academic year 2025 - 2026  Accounted with bank transaction id 520623190760 on 2025-07-25") \
        == "Being Admission FEE  for the academic year 2025 - 2026"
    for junk in ("", "   ", "\t\t&\r\n", None, 12):
        assert isinstance(_head_of(junk), str)
    assert "\t" not in _head_of("a\tb") and "\n" not in _head_of("a\nb")


def t_ledger_sorted_newest_first():
    v = _fees_view(_scope(), {"fees"})
    dates = [e["date"] for e in v["ledger"]]
    assert dates == sorted(dates, reverse=True), dates
    assert dates[0] == "2026-07-02" and dates[-1] == "2025-11-21", dates
    assert v["ledger"][0]["amt"] == "200,000.00" and v["ledger"][0]["vno"] == "8162", v["ledger"][0]


def t_feature_gate_off_no_tab():
    # view side: feature off (or no data at all) -> None -> template shows nothing
    assert _fees_view(_scope(), set()) is None
    assert _fees_view(_scope(), {"hourwise", "academics"}) is None
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
    # template side: navbar item AND panel both guarded by {% if fees %}
    tpl = (REPO / "app" / "templates" / "dashboard.html").read_text()
    for needle in ("id=\"tab-fees-tab\"", "id=\"tab-fees\""):
        i = tpl.index(needle)
        guard = tpl.rfind("{% if fees %}", 0, i)
        endif = tpl.rfind("{% endif %}", 0, i)
        assert guard != -1 and guard > endif, f"{needle} not inside {{% if fees %}} guard"


TESTS = [
    ("##-split parser: fixture row -> fields (+ junk rows)", t_parser_fixture_row_fields),
    ("dues: paid==total + trailing 0 -> 0", t_dues_zero_when_paid_equals_total),
    ("dues: paid=100 total=150 trailing=0 -> 50", t_dues_partial_amount_is_total_minus_paid),
    ("dues: trailing wins + view sum/level", t_dues_trailing_field_wins),
    ("narration first-clause split on unicode/garbage", t_narration_first_clause_never_raises),
    ("receipt head is one clean line", t_receipt_head_is_one_line),
    ("ledger sorted newest voucherdate first", t_ledger_sorted_newest_first),
    ("feature gate off -> no tab (view + env + template guard)", t_feature_gate_off_no_tab),
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
