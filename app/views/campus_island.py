"""Campus cards as island props (P6.7) — server side.

app/templates/campus.html paints `campus.cards` (app/views/campus.py): the
placement board, the library, one hostel+transport card and the notifications.
A card is one of two shapes and campus_view() decides which:
  * {title, rows} — line_row()'s {title, sub, badge, meta, extras}, every
    string already formatted;
  * {title, kv}   — [{label, pairs: [[key, value], ...]}] for hostel/transport.
The island re-renders both; ordering, labels and formatting all arrive decided.
"""
import json

from markupsafe import Markup


def _line(r):
    return {"title": r["title"], "sub": r["sub"], "badge": r["badge"],
            "meta": r["meta"],
            "extras": [[str(k), str(v)] for k, v in r["extras"]]}


def props(campus):
    """The payload web/src/panels/campus/contract.ts validates.

    `campus` is campus_view()'s {show, cards}; cards is [] when the tab hides,
    which the route 404s before rendering — so the island sees what the
    template sees, card for card.
    """
    cards = []
    for c in campus.get("cards") or ():
        if c.get("kv"):
            cards.append({"title": c["title"],
                          "kv": [{"label": g["label"],
                                  "pairs": [[str(k), str(v)] for k, v in g["pairs"]]}
                                 for g in c["kv"]]})
        else:
            cards.append({"title": c["title"], "rows": [_line(r) for r in c.get("rows") or ()]})
    return {"cards": cards}


def block(payload, element_id="island-campus"):
    """The inert JSON block. Same escaping rule as fees_island.block:
    '<' is the only char that can unbalance a <script> block."""
    out = json.dumps(payload, separators=(",", ":"))
    out = out.replace("<", "\\u003c")
    return Markup('<script type="application/json" id="%s">%s</script>' % (element_id, out))
