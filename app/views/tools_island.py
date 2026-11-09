"""Tools rows as island props (P6.9) — server side.

app/templates/tools.html paints one row per entry of `tools`
(app/views/timetable.py:_tools_entries): a destination link, a label and a
hint. Nothing here is user data — the rows are app-owned URLs gated server-side
by SCOPE_FEATURES, and the route already 404s when the list is empty.

The island re-renders the <ul> only; the card, the heading and the footnote
stay template markup.
"""
import json

from markupsafe import Markup


def props(tools):
    """The payload web/src/panels/tools/contract.ts validates.

    `tools` is _tools_entries()'s list of {slug, label, hint, op, tab}. Only
    the three fields the row prints cross the wire; ordering is the server's.
    """
    return {"rows": [{"slug": t["slug"], "label": t["label"], "hint": t["hint"],
                      "tab": t["tab"]} for t in tools]}


def block(payload, element_id="island-tools"):
    """The inert JSON block. Same escaping rule as fees_island.block:
    '<' is the only char that can unbalance a <script> block."""
    out = json.dumps(payload, separators=(",", ":"))
    out = out.replace("<", "\\u003c")
    return Markup('<script type="application/json" id="%s">%s</script>' % (element_id, out))
