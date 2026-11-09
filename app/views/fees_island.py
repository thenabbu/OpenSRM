"""Fees rows as island props (P6.5) — server side.

The fees panel in app/templates/fees.html paints three row groups from
`fees` (app/views/fees.py): the outstanding-dues lines, the paid-by-year
groups and the receipt ledger. The island re-renders those three from data;
the hero's threshold colour, the year/row ordering and every amount already
decided server-side travel on the wire untouched.

The page chrome (navbar, dock, modals) and the "Paid"/"Receipts" headings'
structure stay in the template — this module only ships the row values, so a
field added to the view model later cannot silently reach the client.
"""
import json

from markupsafe import Markup


def props(fees):
    """The payload web/src/panels/fees/contract.ts validates.

    `fees` is _fees_view()'s dict. Amounts stay DISPLAY STRINGS (`_money`
    already formatted them); the island prepends '₹' and nothing else. Nothing
    is sorted here — fees.py decided row and ledger order.
    """
    return {
        "due_disp": fees["due_disp"],
        "level": fees["level"],
        "dues": [
            {"amt": d["amt"], "due": d["due"], "penalty": d["penalty"],
             "penalised": bool(d["penalised"])}
            for d in fees["dues"]
        ],
        "years": [
            {"year": y["year"], "total": y["total"],
             "rows": [{"head": r["head"], "amt": r["amt"], "date": r["date"]}
                      for r in y["rows"]]}
            for y in fees["years"]
        ],
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
