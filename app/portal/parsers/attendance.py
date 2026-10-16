"""Attendance page parser (moved from app.app; re-exported from app.app)."""

import re

from .common import _cells, log


def parse_attendance(html):
    out = {"courses": [], "monthly": [], "period": None}
    m = re.search(r"During the Period.*?<b>([^<]+)</b>\s*To\s*<b>([^<]+)</b>", html, re.S)
    if m:
        out["period"] = {"from": m.group(1).strip(), "to": m.group(2).strip()}
    tbody = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    if tbody:
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody.group(1), re.S):
            cells = _cells(row)
            if not cells or len(cells) < 5:
                continue
            if cells[0].lower() == "total" or len(cells) == 7:
                continue
            # audit: numeric columns must look numeric — a portal column change
            # would shift text into them and silently poison attendance.
            # audit run-1: "" and "-" no longer pass (a non-attendance tbody
            # with blank trailing columns used to substitute junk courses);
            # a rejected row -> empty courses -> sync fails closed, stored
            # attendance_json is never touched.
            if not all(re.fullmatch(r"-?\d+(?:\.\d+)?", n)
                       for n in (cells[2], cells[3], cells[4])):
                log.warning("attendance row layout shifted, skipped: %r", cells[:5])
                continue
            out["courses"].append({
                "code": cells[0], "description": cells[1],
                "max_hours": cells[2], "attended": cells[3], "absent": cells[4],
            })
    cum = re.search(r"Cumulative Attendance.*?<table[^>]*>.*?<tbody>(.*?)</tbody>", html, re.S)
    if cum:
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", cum.group(1), re.S):
            cells = _cells(row)
            # audit run-1: present/absent must parse as integers — column drift
            # otherwise poisons the monthly bars; a rejected row leaves monthly
            # empty and the merge preserves stored history instead of wiping it.
            # od/ml are display-only passthrough (portal may blank them).
            if len(cells) >= 6 and all(re.fullmatch(r"-?\d+", c) for c in cells[1:3]):
                out["monthly"].append({
                    "month": cells[0], "present": cells[1], "absent": cells[2],
                    "od_present": cells[3], "od_absent": cells[4], "ml": cells[5],
                })
    return out
