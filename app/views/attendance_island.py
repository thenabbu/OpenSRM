"""Attendance meters as island props (P6.1) — server side.

The row markup in app/templates/attendance.html:220-253 carries three values
that today only exist as Jinja locals: the `nudge`/`pole` label-placement
classes, the role="img" aria-label prose, and the derived hatch geometry. A
Preact island cannot recompute them from the view model without re-typing the
template's rules a second time — the exact drift this module exists to prevent.

So the derivation lives HERE and the template calls it too (see attendance.html):
one implementation, two consumers. The island re-derives only pure arithmetic
(hatch band, connector midpoint) which is a `round(2)` away from the same thing.
"""
import json

from markupsafe import Markup


# Mirrors the template's {% if c.pct_disp is not none %} guard: a course with no
# held classes has no meter, so it has no row — and no island prop either.
def _rows(courses):
    return [c for c in courses if c.get("pct_disp") is not None]


def nudge(fill, gap):
    """Label-pair placement class — attendance.html:233 verbatim."""
    if gap < 3 and fill > 75:
        return "nud2R"
    if gap < 3:
        return "nud2L"
    if gap < 9 and fill > 75:
        return "nudR"
    if gap < 9:
        return "nudL"
    return ""


def pole(fill):
    """dpol < 9 -> ONE right-anchored cluster (attendance.html:237)."""
    return (100 - fill) < 9


def label(c):
    """The meter's aria-label — attendance.html:243 verbatim, prose included."""
    if c.get("attend_now") is not None:
        tail = "needs %s for 75 percent" % c["attend_now"]
    else:
        tail = "%s skippable for 75 percent" % c["skip_now"]
    return "%s, %s percent attended, %s" % (c["description"], c["pct_disp"], tail)


def props(courses):
    """The payload web/src/panels/attendance/contract.ts validates.

    Only what the template cannot hand over as markup: the geometry the island
    must paint. Rows are in template order (the view model already sorts), so a
    hydrated grid lists courses exactly like the no-JS one.
    """
    out = []
    for c in _rows(courses):
        fill = float(c["fill"])
        gap = abs(75 - fill)
        out.append({
            "code": c.get("code") or "",
            "description": c["description"],
            "attended": int(c["attended"]),
            "max_hours": int(c["max_hours"]),
            "pct_disp": c["pct_disp"],
            "fill": round(fill, 2),
            "t75": int(c["t75"]),
            "skip_now": c["skip_now"] if c["skip_now"] is not None else 0,
            "attend_now": c["attend_now"],
            "tint": c["tint"],
            "margin": c["margin"] if c["margin"] is not None else 0,
            "label": label(c),
            "nudge": nudge(fill, gap),
            "pole": pole(fill),
        })
    return out


def block(courses, element_id="island-attendance"):
    """The inert JSON block. Same escaping rule as sync_age.island_props:
    '<' is the only char that can unbalance the block."""
    payload = json.dumps({"courses": props(courses)}, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c")
    return Markup('<script type="application/json" id="%s">%s</script>' % (element_id, payload))
