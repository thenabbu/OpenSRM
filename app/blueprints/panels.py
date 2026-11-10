"""Read-only JSON for the four data-gated panels (P50).

Each rule serves the panel its page renders, from the SAME view model:
views.dashboard.panel_data() computes once, presentation() renders the page
from it, and these endpoints serialise the matching slice — so the page and the
offline store (Dexie) can never disagree about a number.

Contract, identical on all four:
  * auth — anonymous gets 401 JSON, never the page's 302 to /login HTML: an
    API consumer must be able to tell "logged out" from "no rows".
  * `{"ok": true, "data": {...}}` on success; `{"ok": false, "error": "..."}`
    with the status on failure.
  * a panel with no data is 404 — the SAME rule its page already applies
    (presentation()'s abort(404) on campus["show"] is False / academics is None
    / fees is None), so the gate has one definition, not a second one here.
  * Cache-Control: no-store — this is PII; the service worker refuses to cache
    the HTML for the same reason.
"""
from flask import jsonify

from ..app import get_current_user
from ..views import attendance_island, marks_island, timetable_island, tools_island
from ..views.dashboard import panel_data
from ..views.timetable import _day_slots, _tt_grid
from . import FlatBlueprint

bp = FlatBlueprint("panels", __name__)


def _panel(getter, error="no data yet — sync first"):
    """401/404/200 wrapper shared by the four endpoints. `getter` pulls the
    slice out of panel_data()'s model and returns None when the panel is
    gated — the one place the "no data" rule is spelled."""
    netid = get_current_user()
    if not netid:
        return jsonify(ok=False, error="not logged in"), 401
    data = getter(panel_data(netid))
    if data is None:
        return jsonify(ok=False, error=error), 404
    resp = jsonify(ok=True, data=data)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def api_attendance():
    """/attendance as data: subject rows with the SAME pct/display the meters
    print, the monthly bars with their absence chips, and — the one field that
    exists only here — the structured timetable grid the page renders as HTML
    (day -> period -> {code, name, location, attendance})."""
    def get(vm):
        return {
            "courses": [{**c, "stop": c["stop"].isoformat() if c["stop"] else None}
                        for c in vm["courses"]],
            "monthly": vm["monthly"],
            "hourwise": vm["hourwise"],     # set when the page shows the detailed
            "timetable": vm["schedule"],    # grid (then the page hides monthly)
            "period": vm["data"].get("period"),
            "has_budgets": vm["has_budgets"],
        }
    return _panel(get, "no attendance yet — sync first")


def api_fees():
    """/fees as data: the fees tab's own view model (due, dues, years, ledger),
    None when the page would 404."""
    return _panel(lambda vm: vm["fees"], "no fees data yet — sync first")


def api_campus():
    """/campus as data: {"show", "cards"}, 404 while show is False (the page's
    own gate)."""
    return _panel(lambda vm: vm["campus"] if vm["campus"]["show"] else None,
                  "no campus data yet — sync first")


def api_academics():
    """/academics as data: {"cgpa", "courses"}, None when the page would 404."""
    return _panel(lambda vm: vm["academics"], "no academics data yet — sync first")


def api_marks_island():
    """/api/marks/island as data: the payload the marks ISLAND validates —
    {"subjects": [...]}. marks_island.props() returns the bare row list; the
    island's zod schema wraps it under `subjects` (marks_island.block() wraps it
    the same way for the server paint), so this wraps too. Distinct from the
    legacy /api/marks (app.py:741) which serves raw stored JSON from before the
    island contract existed."""
    return _panel(lambda vm: {"subjects": marks_island.props(vm["marks_view"])},
                  "no marks data yet — sync first")


def api_timetable():
    """/timetable as data: timetable_island.props() for the current group."""
    def get(vm):
        gk = vm["group_key"]
        slots = _day_slots(gk)
        if slots is None:
            return None
        return timetable_island.props(slots, _tt_grid(gk), None)
    return _panel(get, "no timetable yet — sync first")


def api_tools():
    """/tools as data: tools_island.props() — {"rows": [...]}."""
    return _panel(lambda vm: tools_island.props(vm["tools"]),
                  "no tools available")


def api_attendance_island():
    """/api/attendance/island — exactly what the attendance ISLAND validates.

    Separate from /api/attendance on purpose. That one returns the panel slice
    with its extra fields (`monthly`, `hourwise`, `timetable`, `stop`, ...) and
    its schema is `.strict()`, so folding this payload into it would break every
    existing consumer. The offline cache needs the ISLAND shape (label, nudge,
    pole, tint — computed by attendance_island.props()), and that is all this
    route returns. One producer, no re-derivation in TypeScript.
    """
    # props() returns the bare course list; the island's zod schema wraps it
    # under `courses` (attendance_island.block() wraps it the same way for the
    # server paint), so this must wrap too — otherwise the client validates
    # `{courses: [...]}` against an array and rejects every cached row.
    return _panel(lambda vm: {"courses": attendance_island.props(vm["courses"])},
                  "no attendance yet — sync first")


bp.add_url_rule("/api/attendance", methods=["GET"], view_func=api_attendance)
bp.add_url_rule("/api/attendance/island", methods=["GET"], view_func=api_attendance_island)
bp.add_url_rule("/api/fees", methods=["GET"], view_func=api_fees)
bp.add_url_rule("/api/campus", methods=["GET"], view_func=api_campus)
bp.add_url_rule("/api/academics", methods=["GET"], view_func=api_academics)
bp.add_url_rule("/api/marks/island", methods=["GET"], view_func=api_marks_island)
bp.add_url_rule("/api/timetable/island", methods=["GET"], view_func=api_timetable)
bp.add_url_rule("/api/tools/island", methods=["GET"], view_func=api_tools)
