"""Fees view models: ##-row parser, dues logic, paid-by-year groups and the
receipt ledger for the Fees tab (SCOPE getFeeDetails + getFinanceDetails
from users.scope_json — the marks-tab pattern: server-rendered in
dashboard(), no new DB columns). Feature gate + empty data -> None, which
the template guards the navbar item and panel on (empty=hidden)."""

import re

# the first narration clause ends at the first tab, CR or LF —
# SCOPE narrations carry bank-ref / payer / PayU-Razorpay garbage after it
_CLAUSE = re.compile(r"[\t\r\n]")
# ...and the receipt's head cuts at the first real sentence end ("recd." and
# "yr.2025" are abbreviations, so a ".""+space before a lowercase word is not
# one), at THRU (the amount after it duplicates the amount column), and at
# the bank-channel tail a PayU/Razorpay narration always carries.
_HEAD_END = re.compile(r"\.\s+(?=[A-Z])|\s+THRU\s+|\s+Accounted\s")
_CHANNEL = re.compile(r"\s+(?:fee\s+paid\s+)?through\s+online\b.*$", re.I)


def _num(v):
    """Amount string -> float; junk/None -> None. Never raises: a bad amount
    renders its raw string, never a 500 (contract)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _money(v):
    """2-decimal display: 200000.00 -> '200,000.00'.

    ponytail: Western ',' grouping (the repo has no Indian-grouping helper;
    grep formatIndian/lakh found none) — acceptable per contract. Upgrade
    path when rupee totals get big: split lakhs/crores -> '2,00,000.00'.
    """
    return f"{v:,.2f}"


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
    25-11-2026. Kept for the rows that do disagree; the fees view no longer
    treats this as the authority — _exam_dues() does.
    """
    paid, total = _num(row["paid"]), _num(row["total"])
    trailing = _num(row["trailing"]) or 0.0
    if paid is None or total is None:
        return trailing if trailing > 0 else 0.0   # amounts unparsable: trailing is all we have
    if paid != total or trailing != 0:
        return trailing if trailing != 0 else total - paid
    return 0.0


def _exam_dues(data):
    """getStudentExamFeesDetails rows -> (due total, itemised rows).

    Live shape (2026-11-04):
      [{"amounttopay": 3150, "paidamount": 0, "minamount": 3150,
        "startdate": "21-09-2026", "enddate": "25-11-2026",
        "penaltydate": "24-11-2026", "penaltystatus": 0, "sno": "2440869",
        "studentname": ..., "officeid": "20", "appln_category_id": "1"}]

    Outstanding per row is amounttopay - paidamount (both are the real money
    fields; minamount is only the part-payment floor). An envelope-shaped
    response ({"Status": "Success", "Message": "No Details found", "Data": ""})
    means nothing is owed -> 0. Never raises: junk rows are skipped.
    """
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
        rows.append({"amt": _money(due),
                     "due": str(it.get("enddate") or ""),
                     "penalty": str(it.get("penaltydate") or ""),
                     "penalised": str(it.get("penaltystatus") or "0") not in ("0", "")})
    rows.sort(key=lambda r: r["due"])
    return total, rows


def _first_clause(text):
    """Narration -> first clause (split on the first period/tab/CR/LF).
    Junk types and unicode garbage never raise; empty text -> ''."""
    if not isinstance(text, str):
        return ""
    return _CLAUSE.split(text, 1)[0].strip()


def _head_of(text):
    """Narration -> one-line receipt head (see _HEAD_END/_CHANNEL). Never raises."""
    clause = _first_clause(text)
    return _CHANNEL.split(_HEAD_END.split(clause, 1)[0], 1)[0].strip().rstrip(":;-,. ")


def _fees_view(scope_json, features):
    """Fees tab view model, or None when the 'fees' feature is off or no fee /
    finance rows are stored (=> no navbar item, no panel — same self-hide
    rule as empty cards)."""
    if "fees" not in features:
        return None
    scope_json = scope_json if isinstance(scope_json, dict) else {}

    def data_of(op):
        cell = scope_json.get(op)
        return cell.get("data") if isinstance(cell, dict) else None

    fee_rows = _parse_fee_rows(data_of("getFeeDetails"))
    fin_rows = data_of("getFinanceDetails")
    fin_rows = fin_rows if isinstance(fin_rows, list) else []
    exam_total, exam_rows = _exam_dues(data_of("getStudentExamFeesDetails"))
    if not fee_rows and not fin_rows and not exam_rows:
        return None

    # ── hero: total outstanding. getStudentExamFeesDetails is the authority
    # when it reports anything; the ##-row formula is the fallback for
    # deployments that have not fetched it yet (see _due_of). Threshold
    # documented: any rupee owed (>= 1) is a warning; >= 100000 (a
    # semester-fee scale) escalates to error. Zero dues is never colored.
    due = exam_total
    if not exam_rows:
        for r in fee_rows:
            d = _due_of(r)
            if d > 0:
                due += d
    level = ""
    if due >= 1:
        level = "text-warning"
    if due >= 100000:
        level = "text-error"

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
                          "date": r["date"]})
            if amt is not None:
                gtot += amt
                paid_total += amt
        years.append({"year": y, "rows": rdisp, "total": _money(gtot)})

    # ── receipt ledger, newest voucherdate first (ISO yyyy-mm-dd sorts
    # lexicographically; junk dates sort wherever, never raise)
    ledger = []
    for it in fin_rows:
        if not isinstance(it, dict):
            continue
        amt = _num(it.get("amount"))
        narr = it.get("narration")
        ledger.append({
            "date": str(it.get("voucherdate") or ""),
            "amt": _money(amt) if amt is not None else str(it.get("amount") or ""),
            "vno": str(it.get("vouchernumber") or ""),
            "head": _head_of(narr),
            "full": re.sub(r"\s+", " ", narr).strip() if isinstance(narr, str) else "",
        })
    ledger.sort(key=lambda e: e["date"], reverse=True)

    return {
        "due": due,
        "due_disp": _money(due) if due > 0 else "",
        "level": level,
        "dues": exam_rows,
        "years": years,
        "paid_total": _money(paid_total) if fee_rows else "",
        "ledger": ledger,
    }
