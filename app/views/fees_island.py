"""Fees rows as island props (P6.5) — server side.

The fees panel in app/templates/fees.html paints three row groups from
`fees` (app/views/fees.py): the named charge cards, the paid-by-year groups
and the receipt ledger. The island re-renders those three from data; the
threshold colour, every date string, the days-left count and every amount are
already decided server-side and travel on the wire untouched.

The page chrome (navbar, dock, modals) stays in the template — this module
only ships the row values, so a field added to the view model later cannot
silently reach the client.
"""
import json

from markupsafe import Markup


def props(fees):
    """The payload web/src/panels/fees/contract.ts validates.

    `fees` is _fees_view()'s dict. Amounts stay DISPLAY STRINGS (`_money`
    already formatted them, Indian grouping); the island prepends '₹' and
    nothing else. Dates are pre-formatted too, so the client never formats or
    parses — it cannot disagree with the no-JS paint. Nothing is sorted here:
    fees.py decided row, charge and ledger order.
    """
    return {
        "due_disp": fees["due_disp"],
        "due_sum": fees["due_sum"],
        "level": fees["level"],
        "dues": [
            {"head": d["head"], "cycle": d["cycle"], "amt": d["amt"],
             "level": d["level"], "deadline": d["deadline"], "late_on": d["late_on"],
             "late_extra": d["late_extra"], "days_left": d["days_left"],
             "overdue": bool(d["overdue"]), "penalised": bool(d["penalised"]),
             "min": d["min"]}
            for d in fees["dues"]
        ],
        "years": [
            {"year": y["year"], "total": y["total"],
             "rows": [{"head": r["head"], "amt": r["amt"], "date": r["date"]}
                      for r in y["rows"]]}
            for y in fees["years"]
        ],
        "multi_year": bool(fees["multi_year"]),
        "year_label": fees["year_label"],
        "paid_total": fees["paid_total"],
        "ledger": [
            {"date": e["date"], "amt": e["amt"], "vno": e["vno"],
             "head": e["head"], "full": e["full"]}
            for e in fees["ledger"]
        ],
    }


def block(payload, element_id="island-fees"):
    """The inert JSON block. Same escaping rule as timetable_island.block:
    '<' is the only char that can unbalance a <script> block."""
    out = json.dumps(payload, separators=(",", ":"))
    out = out.replace("<", "\\u003c")
    return Markup('<script type="application/json" id="%s">%s</script>' % (element_id, out))
