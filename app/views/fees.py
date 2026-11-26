"""Fees view models: ##-row parser, dues logic, paid-by-year groups and the
receipt ledger for the Fees tab (SCOPE getFeeDetails + getFinanceDetails
from users.scope_json — the marks-tab pattern: server-rendered in
dashboard(), no new DB columns). Feature gate + empty data -> None, which
the template guards the navbar item and panel on (empty=hidden).

The page answers two questions in this order: "do I owe money, and by when
does it get more expensive?" then "what have I already paid, and where are
the vouchers?". So the dues rows carry the deadline pair the SCOPE rows
actually ship (`lastdateforfeepaymentwithoutlatefee` and `penaltydate` ->
`feewithlatefee`, i.e. the penalty delta), and every date on the page is
parsed once, formatted once, sorted on the parsed value.
"""

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# the first narration clause ends at the first tab, CR or LF —
# SCOPE narrations carry bank-ref / payer / PayU-Razorpay garbage after it
_CLAUSE = re.compile(r"[\t\r\n]")
# ...and the receipt's head cuts at the first real sentence end ("recd." and
# "yr.2025" are abbreviations, so a ".""+"space before a lowercase word is not
# one), at THRU (the amount after it duplicates the amount column), and at
# the bank-channel tail a PayU/Razorpay narration always carries.
_HEAD_END = re.compile(r"\.\s+(?=[A-Z])|\s+THRU\s+|\s+Accounted\s")
_CHANNEL = re.compile(r"\s+(?:fee\s+paid\s+)?through\s+online\b.*$", re.I)
# an ERP auto-posted receipt names the head once, then dumps the gateway trail:
# "… Fee heads : Advance Fees Online Payment Date : 2025-05-20 ERP Online …".
# That one token is the only short, honest label in the string.
_FEE_HEADS = re.compile(
    r"fee\s+heads?\s*:\s*(.{2,40}?)(?=\s{2,}|\s+(?:online|erp|bank|through|applicant|payment)\b|$)",
    re.I)
# a narration has no length limit and some have no sentence break at all, so
# the collapsed row's label is capped on a word boundary (the full text stays
# one tap away inside the receipt)
_CAP = 44

_MONTHS = {m.lower(): i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def _num(v):
    """Amount string -> float; junk/None -> None. Never raises: a bad amount
    renders its raw string, never a 500 (contract)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _money(v):
    """2-decimal Indian grouping: 200000.0 -> '2,00,000', 4150.5 -> '4,150.50'.

    Indian digit grouping (last three, then pairs) because every amount here is
    rupee money read by Indian students: '3,50,000' is one word to them, while
    '350,000.00' has to be re-counted. A whole-rupee amount drops the '.00' —
    the portal never sends paise, so '.00' on every row is pure noise. Non
    numeric input is returned as-is (callers pass raw junk through).
    """
    if not isinstance(v, (int, float)):
        return str(v)
    neg = v < 0
    v = abs(float(v))
    whole = int(v)
    paise = int(round((v - whole) * 100))
    if paise == 100:
        whole, paise = whole + 1, 0
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if neg else "") + (s if paise == 0 else f"{s}.{paise:02d}")


def _date(v):
    """Parse the three date shapes SCOPE ships -> date, else None.

    getFeeDetails -> '31-Jul-2025' · getStudentExamFeesDetails -> '24-11-2026'
    · getFinanceDetails -> '2025-11-03'. Numeric triplets are DAY-FIRST (SRM
    writes dd-mm-yyyy; a month-first read would silently move deadlines).
    Never raises: junk -> None, and the caller renders no date rather than a
    wrong one.
    """
    if not isinstance(v, str):
        return None
    t = v.strip()
    if not t:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3,9})-(\d{4})", t)
    if m and m[2][:3].lower() in _MONTHS:
        try:
            return date(int(m[3]), _MONTHS[m[2][:3].lower()], int(m[1]))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", t)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


def _fmt(v):
    """date|string -> '23 Nov 2026'; unparsable -> the raw string, trimmed."""
    d = v if isinstance(v, date) else _date(v)
    if d is None:
        return str(v).strip() if isinstance(v, str) else ""
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _title(v):
    """Portal ALL-CAPS text -> sentence case ('NOVEMBER-2026' -> 'November-2026')."""
    t = str(v or "").strip()
    return t.capitalize() if t.isupper() or t.islower() else t


_CYCLE = re.compile(r"^([A-Za-z]{3,9})[\s-]*(\d{4})$")


def _cycle(v):
    """The exam-fee academicyear -> a date-like tag: 'NOVEMBER-2026' -> 'Nov 2026'.

    It sits next to the charge's name, so it has to read as WHEN ("Exam Fees ·
    Nov 2026"), not as an opaque code. Anything that is not month+year is left
    sentence-cased by _title.
    """
    t = str(v or "").strip()
    m = _CYCLE.match(t)
    if m and m[1][:3].lower() in _MONTHS:
        return f"{m[1][:3].capitalize()} {m[2]}"
    return _title(t)


def _today(today=None):
    return today or datetime.now(IST).date()


def _parse_fee_rows(data):
    """getFeeDetails list[{"feedetails": "head##paid##total##date##year##trailing"}]
    -> row dicts. Short/junk rows padded and skipped when headless; never raises."""
    rows = []
    for item in data if isinstance(data, list) else []:
        raw = item.get("feedetails") if isinstance(item, dict) else None
        if not isinstance(raw, str) or not raw.strip():
            continue
        parts = (raw.split("##") + [""] * 6)[:6]
        head, paid, total, vdate, year, trailing = (p.strip() for p in parts)
        if not head:
            continue
        rows.append({"head": head, "paid": paid, "total": total,
                     "date": vdate, "year": year, "trailing": trailing})
    return rows


def _due_of(row):
    """One fee-row's outstanding amount from the ##-row alone: 0 while
    paid == total and trailing == 0; else trailing when trailing != 0, else
    total - paid.

    MEASURED 2026-11-04 against the live backend: this formula is NOT a
    reliable dues signal. Every row came back paid == total == trailing == 0
    (so 0.0) while getStudentExamFeesDetails reported 3150 still owed and due
    25-11-2026. Kept for the rows that do disagree — and a disagreeing row is
    now SURFACED as its own charge line, not folded into a silent total.
    """
    paid, total = _num(row["paid"]), _num(row["total"])
    trailing = _num(row["trailing"]) or 0.0
    if paid is None or total is None:
        return trailing if trailing > 0 else 0.0   # amounts unparsable: trailing is all we have
    if paid != total or trailing != 0:
        return trailing if trailing != 0 else total - paid
    return 0.0


def _level(days_left=None, overdue=False, penalised=False):
    """The charge's number colour, from its DEADLINE — not from its size.

    A 2,00,000 fee with 60 days left is not an error, and the old
    amount-magnitude rule (>= 100000 -> error) said it was. What earns colour
    is time: a penalty already applied or a passed deadline is `error`, a
    deadline inside 7 days is `warning`, anything else is uncoloured.

    Only the 22px number takes a status hue: the raw status tokens measure
    3.8:1 / 3.0:1 on `base-200` (DESIGN.md §4.14) and fail AA as 12px text, so
    the small print stays grayscale and the words carry the state.
    """
    if penalised or overdue or (days_left is not None and days_left < 0):
        return "text-error"
    if days_left is not None and days_left <= 7:
        return "text-warning"
    return ""


def _worst(levels):
    """The most severe of several charge levels (error > warning > none)."""
    if "text-error" in levels:
        return "text-error"
    return "text-warning" if "text-warning" in levels else ""


def _exam_dues(data, today=None):
    """getStudentExamFeesDetails rows -> (due total, itemised charge rows).

    Live shape (2026-11-04 / 2026-11-26):
      [{"academicyear": "NOVEMBER-2026", "feetype": "Exam Fees",
        "minamount": 3150, "amounttopay": 3150, "paidamount": 0,
        "concessionamount": 0, "amountwithoutpenalty": 3150,
        "penaltyamount": 1000, "feewithlatefee": 4150,
        "startdate": "21-09-2026", "enddate": "24-11-2026",
        "penaltydate": "24-11-2026",
        "lastdateforfeepaymentwithoutlatefee": "23-11-2026",
        "penaltystatus": 0, "sno": "2440869", "officeid": "20"}]

    Outstanding per row is amounttopay - paidamount (both are the real money
    fields; minamount is only the part-payment floor). An envelope-shaped
    response ({"Status": "Success", "Message": "No Details found", "Data": ""})
    means nothing is owed -> 0. Never raises: junk rows are skipped.

    The page shows the DEADLINE PAIR, which is the only urgent fact here:
    pay by `lastdateforfeepaymentwithoutlatefee` at `amt`, after `penaltydate`
    it becomes amt + the penalty delta (`feewithlatefee - amt`, falling back to
    `penaltyamount`). Older rows carry no cheap-deadline field; then the card
    states the penalty date alone instead of guessing a day earlier.
    """
    now = _today(today)
    rows, total = [], 0.0
    for it in data if isinstance(data, list) else []:
        if not isinstance(it, dict):
            continue
        owe = _num(it.get("amounttopay"))
        paid = _num(it.get("paidamount")) or 0.0
        if owe is None:
            continue
        due = owe - paid
        if due <= 0:
            continue
        total += due

        no_late = _date(it.get("lastdateforfeepaymentwithoutlatefee"))
        pen_on = _date(it.get("penaltydate")) or _date(it.get("enddate"))
        late_total = _num(it.get("feewithlatefee"))
        extra = None
        if late_total is not None and late_total > due:
            extra = late_total - due
        else:
            pen_amt = _num(it.get("penaltyamount"))
            extra = pen_amt if pen_amt and pen_amt > 0 else None

        deadline = no_late or pen_on           # when the cheap price ends
        days_left = (deadline - now).days if deadline else None
        min_amt = _num(it.get("minamount"))
        part_ok = str(it.get("partpaymentapplicable") or "0") not in ("0", "") \
            and min_amt is not None and 0 < min_amt < due

        penalised = str(it.get("penaltystatus") or "0") not in ("0", "")
        overdue = bool(days_left is not None and days_left < 0)
        rows.append({
            # no feetype on older rows -> the op's own name, never a bare "Fee"
            "head": _title(it.get("feetype")) or "Exam fee",
            "cycle": _cycle(it.get("academicyear")),
            "amt": _money(due),
            "level": _level(days_left, overdue, penalised),
            "deadline": _fmt(deadline) if deadline else "",
            "late_on": _fmt(pen_on) if pen_on and no_late else "",
            "late_extra": _money(extra) if extra else "",
            "days_left": days_left,
            "overdue": overdue,
            "penalised": penalised,
            "min": _money(min_amt) if part_ok else "",
        })
    rows.sort(key=lambda r: (r["days_left"] is None,
                             r["days_left"] if r["days_left"] is not None else 0,
                             r["head"]))
    return total, rows


def _first_clause(text):
    """Narration -> first clause (split on the first period/tab/CR/LF).
    Junk types and unicode garbage never raise; empty text -> ''."""
    if not isinstance(text, str):
        return ""
    return _CLAUSE.split(text, 1)[0].strip()


def _cap(text, n=_CAP):
    """Cut at the last word boundary at or before n; shorter text is untouched."""
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(":;-,. ")
    return cut or text[:n].rstrip(":;-,. ")


def _head_of(text):
    """Narration -> one-line receipt head (see _HEAD_END/_CHANNEL/_FEE_HEADS).

    Order: an explicit `Fee heads : X` token wins; else the first clause cut at
    a real sentence end / THRU / the bank-channel tail; else the capped clause.
    Never raises, never returns a multi-line string."""
    if not isinstance(text, str):
        return ""
    m = _FEE_HEADS.search(text)
    if m and m[1].strip():
        return _cap(m[1].strip().rstrip(":;-,. "))
    clause = _first_clause(text)
    head = _CHANNEL.split(_HEAD_END.split(clause, 1)[0], 1)[0].strip().rstrip(":;-,. ")
    # every narration opens with the same "Being …" filler; the label starts
    # at the noun ("Being Fee received from student for Exam Fees")
    head = re.sub(r"^being\s+", "", head, flags=re.I)
    return _cap(re.sub(r"\s+", " ", head))


def _fees_view(scope_json, features, today=None):
    """Fees tab view model, or None when the 'fees' feature is off or no fee /
    finance rows are stored (=> no navbar item, no panel — same self-hide
    rule as empty cards). `today` is the days-left clock, injectable so tests
    and screenshots pin it."""
    if "fees" not in features:
        return None
    scope_json = scope_json if isinstance(scope_json, dict) else {}

    def data_of(op):
        cell = scope_json.get(op)
        return cell.get("data") if isinstance(cell, dict) else None

    fee_rows = _parse_fee_rows(data_of("getFeeDetails"))
    fin_rows = data_of("getFinanceDetails")
    fin_rows = fin_rows if isinstance(fin_rows, list) else []
    exam_total, dues = _exam_dues(data_of("getStudentExamFeesDetails"), today)
    if not fee_rows and not fin_rows and not dues:
        return None

    # ── charges: exam dues are the authority; a fee head whose own row
    # disagrees is surfaced as its own named charge (no deadline exists for
    # it, which the card states rather than inventing one).
    due_total = exam_total
    for r in fee_rows:
        d = _due_of(r)
        if d <= 0:
            continue
        due_total += d
        dues.append({
            "head": _title(r["head"]), "cycle": _title(r["year"]),
            "amt": _money(d), "level": "",
            "deadline": "", "late_on": "", "late_extra": "",
            "days_left": None, "overdue": False, "penalised": False, "min": "",
        })
    # keep exam dues first (they own the deadline), then dateless charges
    dues.sort(key=lambda r: (r["days_left"] is None,
                             r["days_left"] if r["days_left"] is not None else 0,
                             r["head"]))

    # ── paid-by-year groups (newest year first), group + grand totals
    groups: dict = {}
    for r in fee_rows:
        groups.setdefault(r["year"] or "—", []).append(r)
    years, paid_total = [], 0.0
    for y in sorted(groups, reverse=True):
        gtot, rdisp = 0.0, []
        for r in groups[y]:
            amt = _num(r["paid"])
            rdisp.append({"head": r["head"],
                          "amt": _money(amt) if amt is not None else (r["paid"] or "?"),
                          "date": _fmt(r["date"]),
                          "_d": _date(r["date"]) or date.min})
            if amt is not None:
                gtot += amt
                paid_total += amt
        rdisp.sort(key=lambda x: x["_d"])
        for row in rdisp:
            row.pop("_d", None)
        years.append({"year": y, "rows": rdisp, "total": _money(gtot)})

    # ── receipt ledger, newest voucherdate first (parsed dates; the raw ISO
    # strings sort correctly today but the shape is not guaranteed)
    ledger = []
    for it in fin_rows:
        if not isinstance(it, dict):
            continue
        amt = _num(it.get("amount"))
        narr = it.get("narration")
        raw = str(it.get("voucherdate") or "")
        ledger.append({
            "_d": _date(raw) or date.min,
            "date": _fmt(raw),
            "amt": _money(amt) if amt is not None else str(it.get("amount") or ""),
            "vno": str(it.get("vouchernumber") or ""),
            "head": _head_of(narr),
            "full": re.sub(r"\s+", " ", narr).strip() if isinstance(narr, str) else "",
        })
    ledger.sort(key=lambda e: e["_d"], reverse=True)
    for e in ledger:
        e.pop("_d", None)

    # the sum line rides the worst state of the charges it sums
    level = _worst([r["level"] for r in dues])
    return {
        "due": due_total,
        "due_disp": _money(due_total) if due_total > 0 else "",
        "level": level,
        "dues": dues,
        # a single total line is only worth its ink when it SUMS something;
        # with one charge the card below already carries the number
        "due_sum": _money(due_total) if len(dues) > 1 else "",
        "years": years,
        "multi_year": len(years) > 1,
        "year_label": years[0]["year"] if len(years) == 1 else "",
        "paid_total": _money(paid_total) if fee_rows else "",
        "ledger": ledger,
    }
