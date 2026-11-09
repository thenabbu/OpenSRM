"""Dashboard widgets as island props (P6.2) — server side.

The six home widgets (today, week, attendance budgets, marks, exams, teachers)
are pure renderings of dicts the view model already computed. So unlike the
attendance meters there is NOTHING to re-derive here: the props are the very
same objects the partials read, serialised. One shape, two consumers — a
hydration that disagrees with the no-JS paint is impossible by construction.

`None`/empty is preserved as `null`/`[]` because the widget must self-hide
exactly as the partial's `{% if %}` does (DESIGN §4.12, empty=hidden).
"""
import json

from markupsafe import Markup


def props(*, ticker, week, budgets, marks_summary, exams, teach_groups, fb_plan):
    """The payload web/src/panels/dashboard/contract.ts validates.

    `week` is dash["week"] — `today_absent` rides along because today.html:6
    reads dash.week.today_absent, so it is part of the today widget's inputs.
    `budgets` stays the template's tuple list -> [[name, value, risk], ...]
    (the partial unpacks `{% for name, val, risk in budgets %}`, teachers.py:17).
    """
    return {
        "ticker": ticker or None,
        "week": week,
        "budgets": [[n, v, r] for (n, v, r) in budgets or []],
        "marks": marks_summary or [],
        "exams": exams or None,
        "teachers": teach_groups or [],
        "fb_plan": bool(fb_plan),     # only the CTA's presence is markup
    }


def block(payload, element_id="island-dashboard"):
    """The inert JSON block. Same escaping rule as sync_age.island_props:
    '<' is the only char that can unbalance the block."""
    raw = json.dumps(payload, separators=(",", ":"))
    raw = raw.replace("<", "\\u003c")
    return Markup('<script type="application/json" id="%s">%s</script>' % (element_id, raw))
