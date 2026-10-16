"""Official timetable (formId 10) parser + the day grid it validates against
(moved from app.app; re-exported from app.app)."""

import re

from .common import log

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

def _tt_norm_clock(h, m):
    """Portal clock -> 24h minutes. The published time row mixes bands: morning
    is 24h (08:30) but the afternoon is 12h-style WITHOUT meridiem (01:30 ==
    13:30). No campus period starts before 08:00, so single-digit hours are
    always the PM band. Verified live 2026-10-12 (6 periods, 08:30-15:10)."""
    h = int(h)
    if h < 8:
        h += 12
    return h * 60 + int(m)


def parse_timetable(html):
    """studentTimeTableDetails.jsp (iden=10, official 'Timetable' page)
    -> weekly grid. LIVE since Oct 2026 (verified 2026-10-12; the endpoint was
    a hard server-side gap before — 'No Time Table Found..!' for every section).

    Page = two static tables: a grid (row 0 = `Hour/Day order` header with
    rowspan + period numbers 1..N, row 1 = N time cells — the rowspan keeps
    them aligned under the periods, there is NO label cell — then one row per
    weekday) and a Legends table (Code | Description). Breaks are NOT rows:
    they exist only as gaps between consecutive times.

    Returns:
      {"times": {period: "HH:MM-HH:MM"}  # RAW as published, 24h-normalized,
                                          # pre-offset (offsets apply at render)
       "grid":  {day: {period: code}},
       "legend":{code: name}}            # may be empty; caller falls back
                                          # stored name -> code
      []  — explicit empty marker ('No Time Table Found..!'): section not
            published, a clean empty callers MAY overwrite.
      None — preserve-signal (never wipe stored rows): missing/blank html,
            youLogin bounce (auth state, not data), or a table present that
            yields 0 day rows / unparseable times (shape drift — the Oct-4
            exam-parser rule)."""
    if not html:
        return None
    if "No Time Table Found" in html:
        return []
    if "youLogin" in html:
        return None
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)

    def _tcells(row_html):
        # _cells() is <td>-only; this page's header + time rows are <th>
        return [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
                for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row_html, re.S)]

    period_labels, times, grid, legend = None, None, {}, {}
    for i, row in enumerate(rows):
        cells = _tcells(row)
        if period_labels is None and cells and "Hour/Day" in cells[0]:
            # header row: label + one <th> per period; row i+1 = the time row
            period_labels = [c.strip() for c in cells[1:]]
            if i + 1 < len(rows):
                tcells = _tcells(rows[i + 1])
                if len(tcells) != len(period_labels):
                    return None
                times = {}
                for p, t in enumerate(tcells, 1):
                    tm = re.fullmatch(r"\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*", t)
                    if not tm:
                        return None
                    s = _tt_norm_clock(*tm.group(1).split(":"))
                    e = _tt_norm_clock(*tm.group(2).split(":"))
                    if e <= s:
                        return None  # band-normalization went wrong: preserve
                    times[p] = "%02d:%02d-%02d:%02d" % (s // 60, s % 60, e // 60, e % 60)
            continue
        if period_labels and cells and cells[0] in DAY_ORDER:
            if len(cells) != len(period_labels) + 1:
                return None  # day row drifted off the period axis: preserve
            grid[cells[0]] = {p: cells[p].strip() for p in range(1, len(period_labels) + 1)}
        elif len(cells) == 2 and cells[0].strip() and cells[0].strip().lower() != "code":
            legend[cells[0].strip()] = cells[1].strip()
    if not period_labels or times is None or not grid or not times \
            or not any(str(v).strip(" -\u2013\u2014\xa0") for d in grid.values() for v in d.values()):
        # table present but the grid never resolved (structure drift), zero
        # day rows, or every cell blank/dash (structurally valid but
        # contentless — a published shell): NOT a clean empty — preserve
        # stored rows (Oct-4 rule; review #1: a blank grid used to wipe 30 rows)
        log.debug("timetable: unparseable shape (labels=%s times=%s day_rows=%d)",
                  bool(period_labels), times is not None, len(grid))
        return None
    missing = [d for d in DAY_ORDER if d not in grid]
    if missing:
        # a dropped day row is partial drift, not a published 4-day week —
        # storing it would silently thin every stored weekday slot
        log.debug("timetable: day rows missing %s (shape drift?)", missing)
        return None
    return {"times": times, "grid": grid, "legend": legend}
