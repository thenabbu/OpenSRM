"""Marks cards as island props (P6.3) — server side.

The card markup in app/templates/marks.html:205-262 is painted from the
`_marks_view` dicts; nothing on it is derived only inside Jinja except the
tag-form's `confirmed` prose and the `selected` fallback, and both are
reproduced in the island from the same fields. So this module ships the view
model with ONE normalisation: `confirmed == 'none'` (a real, meaningful value —
"the student said this is neither exam") is passed through as `'none'` and the
island renders "confirmed neither" for it, while `None` means "never confirmed".
Both stay distinct on the wire, exactly as marks.py:56-58 keeps them distinct.
"""
import json

from markupsafe import Markup


def props(marks):
    """The payload web/src/panels/marks/contract.ts validates.

    Rows arrive in view-model order (subjects sorted by pct in marks.py for the
    outlier pick; components already sorted by name) — passed through untouched
    so a hydrated page lists them exactly like the no-JS one.
    """
    out = []
    for s in marks or []:
        comps = []
        for c in s.get("components") or []:
            ie = c.get("ie")
            comps.append({
                "name": c.get("name", ""),
                "date_disp": c.get("date_disp") or "",
                "score_disp": c.get("score_disp", "?"),
                "max_disp": c.get("max_disp", "?"),
                "derived": c.get("derived") or "",
                "confirmed": c.get("confirmed"),
                "ie": None if not ie else {
                    "role": ie["role"],
                    "confirmed": bool(ie.get("confirmed")),
                    "max_disp": ie["max_disp"],
                    "score_disp": ie["score_disp"],
                },
            })
        out.append({
            "code": s.get("code", ""),
            "title": s.get("title") or "",
            "scored_disp": s.get("scored_disp", "?"),
            "max_disp": s.get("max_disp", "?"),
            "pct": float(s.get("pct") or 0),
            "outlier": bool(s.get("outlier")),
            "components": comps,
        })
    return out


def block(marks, element_id="island-marks"):
    """The inert JSON block. Same escaping rule as sync_age.island_props:
    '<' is the only char that can unbalance the block."""
    payload = json.dumps({"subjects": props(marks)}, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c")
    return Markup('<script type="application/json" id="%s">%s</script>' % (element_id, payload))
