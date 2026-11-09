"""Academics rows as island props (P6.6) — server side.

app/templates/academics.html paints two cards from `academics`
(app/views/academics.py): the CGPA hero with one dropdown per semester, and the
combined credits + subjects card with one dropdown per degree category. The
island re-renders both from data; the CGPA figure, every `acq/req` pair, the
meter fill and the row ordering all arrive already decided.

`provisional` / `revaluation` are NOT shipped: _semesters_view() hardcodes them
to [], so there is no shape to type. The template keeps painting them if a
non-empty list ever appears — add the field here and in
web/src/panels/academics/contract.ts together when that happens.
"""
import json

from markupsafe import Markup


def _row(r):
    return {"code": r["code"], "title": r["title"], "grade": r["grade"],
            "completed": bool(r["completed"]), "tint_o": bool(r["tint_o"]),
            "tint_f": bool(r["tint_f"])}


def _course(r):
    return {**_row(r), "month": r.get("month") or "", "attempts": int(r.get("attempts") or 0)}


def props(academics):
    """The payload web/src/panels/academics/contract.ts validates.

    `academics` is academics_view()'s dict; each section is None when empty
    (DESIGN.md §4.12 empty = hidden), which the schema models as nullable.
    """
    cgpa = academics.get("cgpa")
    courses = academics.get("courses")
    return {
        "cgpa": None if not cgpa else {
            "value": cgpa["value"],
            "credits_disp": cgpa["credits_disp"],
            "sems": [{"sem": s["sem"], "label": s["label"], "credits": s["credits"],
                      "sgpa": s["sgpa"], "rows": [_row(r) for r in s["rows"]]}
                     for s in cgpa["sems"]],
        },
        "courses": None if not courses else {
            "overall": {"acq": courses["overall"]["acq"], "req": courses["overall"]["req"]},
            "pending": courses["pending"],
            "total": courses["total"],
            "cats": [{"name": c["name"], "req": c["req"], "acq": c["acq"],
                      "pct": c["pct"], "done": bool(c["done"]), "fill": c["fill"],
                      "n": c["n"], "n_pending": c["n_pending"],
                      "pending": [_course(r) for r in c["pending"]],
                      "completed": [_course(r) for r in c["completed"]]}
                     for c in courses["cats"]],
        },
    }


def block(payload, element_id="island-academics"):
    """The inert JSON block. Same escaping rule as fees_island.block:
    '<' is the only char that can unbalance a <script> block."""
    out = json.dumps(payload, separators=(",", ":"))
    out = out.replace("<", "\\u003c")
    return Markup('<script type="application/json" id="%s">%s</script>' % (element_id, out))
