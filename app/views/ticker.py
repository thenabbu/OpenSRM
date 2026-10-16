"""Today/ticker view models (moved from app.app; re-exported from app.app).

The clock and the db-backed grid resolve from app.app at CALL time via deferred
imports — same module-global semantics app.app had, so the test-pinned clock
(A.datetime = FakeDT in test_layout / test_official_tt / test_tt_history) and
the A.LAYOUT-era patch seams keep working untouched.
"""

from datetime import timedelta


def _today_ticker(group_key):
    """Today widget: prev/now/next class rows from the REAL slot grid.

    None = no timetable / no classes today -> widget hidden (empty=hidden).
    state: "now" (a class is running), "up" (none running, one upcoming —
    breaks land here naturally), "done" (all classes finished). v1 renders
    statically; event-driven promotion is a later rung.
    """
    from app.app import _day_slots, _tt_grid, datetime  # deferred: app.app imports this module; tests pin A.datetime
    day_slots = _day_slots(group_key)
    if not day_slots:
        return None
    todays = day_slots.get(datetime.now().strftime("%A"), {})
    rows = [{"start": s["start"], "end": s["end"],
             "code": todays[s["period"]]["code"],
             "name": todays[s["period"]].get("name") or ""}
            for s in _tt_grid(group_key) if s["type"] != "break" and s["period"] in todays]
    if not rows:
        return None
    now = datetime.now().hour * 60 + datetime.now().minute

    def _m(t):
        return int(t[:2]) * 60 + int(t[3:5])
    for i, r in enumerate(rows):
        if now < _m(r["end"]):
            state = "now" if now >= _m(r["start"]) else "up"
            return {"state": state, "prev": rows[i - 1] if i else None,
                    "now": r, "next": rows[i + 1] if i + 1 < len(rows) else None}
    return {"state": "done", "prev": rows[-1], "now": None, "next": None}

def _now_next_from_slots(day, slots):
    from app.app import datetime  # deferred: tests pin the clock via A.datetime (test_official_tt / test_tt_history)
    now_mins = datetime.now().hour * 60 + datetime.now().minute
    for s in slots:
        sm = int(s["start"].split(":")[0]) * 60 + int(s["start"].split(":")[1])
        em = int(s["end"].split(":")[0]) * 60 + int(s["end"].split(":")[1])
        if sm <= now_mins < em:
            if s.get("type") == "break":
                return {"kind": "break", "label": s.get("name","Break"), "until": s["end"]}
            # _att must ride along: the hero's 22px sig block reads it (spec §1.B);
            # dropping it here silently rendered hero without the stat
            return {"kind": "current", "code": s["code"], "name": s["name"],
                    "loc": s.get("location",""), "until": s["end"],
                    **({"_att": s["_att"]} if "_att" in s else {})}
    upcoming = [s for s in slots if s.get("type") != "break" and
                int(s["start"].split(":")[0])*60 + int(s["start"].split(":")[1]) > now_mins]
    if upcoming:
        s = upcoming[0]
        sm = int(s["start"].split(":")[0])*60 + int(s["start"].split(":")[1])
        return {"kind": "next", "code": s["code"], "name": s["name"],
                "loc": s.get("location",""), "at": s["start"],
                "in_mins": sm - now_mins}
    return {"kind": "done"} if slots else None

def _today_brief(group_key):
    """Dashboard: today's class count + next class from the timetable."""
    from app.app import _day_slots, _tt_grid, datetime  # deferred: app.app imports this module; tests pin A.datetime
    day_slots = _day_slots(group_key)
    out = {"count": 0, "next": None, "day_done": False}
    if not day_slots:
        return out
    today = datetime.now().strftime("%A")
    todays = day_slots.get(today, {})
    out["count"] = len(todays)
    for s in _tt_grid(group_key):
        if s["type"] == "break" or s["period"] not in todays:
            continue
        sm = int(s["start"].split(":")[0]) * 60 + int(s["start"].split(":")[1])
        em = int(s["end"].split(":")[0]) * 60 + int(s["end"].split(":")[1])
        now_mins = datetime.now().hour * 60 + datetime.now().minute
        if sm <= now_mins < em:
            sl = todays[s["period"]]
            out["next"] = {"kind": "now", "code": sl["code"], "at": s["end"]}
            return out
        if now_mins < sm:
            sl = todays[s["period"]]
            out["next"] = {"kind": "next", "code": sl["code"], "at": s["start"]}
            return out
    out["day_done"] = True
    return out

def _week_updates(daily_absent):
    """Dashboard: absences in the current Mon–Sun week (IST server time)."""
    from app.app import datetime  # deferred: tests pin the clock via A.datetime
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    hits, hours = [], 0.0
    for _month, rows in (daily_absent or {}).items():
        for r in rows:
            try:
                d = datetime.strptime(r.get("date", ""), "%d-%m-%Y").date()
            except ValueError:
                continue
            if monday <= d <= sunday:
                hits.append({"date": r["date"], "hours": r.get("hours", "")})
                try:
                    hours += float(str(r.get("hours", "0")).split("-")[0])
                except ValueError:
                    pass
    hits.sort(key=lambda x: x["date"])
    return {"days": len(hits), "hours": hours, "dates": hits,
            "today_absent": any(h["date"] == today.strftime("%d-%m-%Y") for h in hits)}
