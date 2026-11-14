"""Timetable panels as island props (P6.4) — server side.

The panel markup in timetable_html (timetable.py:419-475) is painted from
day_slots + _tt_grid; the island re-renders those rows from data instead of
re-reading the source. Two rules are reproduced here verbatim, because a
hydration that disagrees with the no-JS paint is a bug:

  * a break divider only renders BETWEEN two present classes
    (timetable.py:425-431) — never trailing, never leading;
  * a class row renders only when its slot exists, and a day with no rows gets
    the "No classes" line (timetable.py:468-469).

Only the PANELS ship. The hero and the day-selector pills are time-dependent
and pure CSS (radios), so they stay server-painted markup.
"""
import json

from markupsafe import Markup


def props(day_slots, grid, today):
    """The payload web/src/panels/timetable/contract.ts validates.

    `day_slots` is timetable_html's escaped-but-same-shape mapping
    ({day: {period: {code, name, location}}}); `grid` is _tt_grid(group_key).
    Nothing is sorted here — grid order IS the display order.
    """
    # Imported here, not at module top: timetable.py imports this module, so a
    # top-level import of that module from here is circular.
    from ..portal.parsers.timetable import DAY_ORDER
    from .timetable import _title_case, _tt_att_sig

    days = []
    for d in DAY_ORDER:
        slots = day_slots.get(d, {})
        present = [s["type"] == "class" and s["period"] in slots for s in grid]
        day_last = max((i for i, p in enumerate(present) if p), default=-1)
        rows = []
        for i, s in enumerate(grid):
            if s["type"] == "break":
                if any(present[:i]) and i < day_last:
                    rows.append({"kind": "break", "label": s["name"]})
                continue
            sl = slots.get(s["period"])
            if not sl:
                continue
            sig = _tt_att_sig((sl.get("_att") or None))
            rows.append({
                "kind": "class",
                "start": s["start"],
                "end": s["end"],
                "code": sl["code"],
                "name": _title_case(sl["name"]),
                "location": sl.get("location", ""),
                "live": d == today,
                "sig": None if not sig else {"cls": sig["cls"], "num": sig["num"]},
            })
        days.append({"day": d, "short": d[:3], "rows": rows, "empty": not rows})
    return {"days": days, "default_day": today if today in DAY_ORDER else "Monday"}


def block(payload, element_id="island-timetable"):
    """The inert JSON block. Same escaping rule as marks_island.block: '<' is
    the only char that can unbalance a <script> block."""
    out = json.dumps(payload, separators=(",", ":"))
    out = out.replace("<", "\\u003c")
    return Markup('<script type="application/json" id="%s">%s</script>' % (element_id, out))
