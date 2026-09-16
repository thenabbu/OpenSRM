from datetime import datetime
import json, os

_TIMETABLE_PATH = os.path.join(os.path.dirname(__file__), "data", "timetable.json")
TIMETABLE = json.load(open(_TIMETABLE_PATH)) if os.path.exists(_TIMETABLE_PATH) else {}
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _slot_highlight(day, start, end, code):
    if code in ("BREAK", "LUNCH"):
        return ""
    if day != datetime.now().strftime("%A"):
        return ""
    now_mins = datetime.now().hour * 60 + datetime.now().minute
    s, e = _minutes(start), _minutes(end)
    if s <= now_mins < e:
        return "current"
    if now_mins < s and (s - now_mins) <= 120:
        return "upcoming"
    return ""


def _now_next(day):
    if day not in TIMETABLE:
        return None
    now_mins = datetime.now().hour * 60 + datetime.now().minute
    slots = TIMETABLE[day]
    for s in slots:
        sm, em = _minutes(s["start"]), _minutes(s["end"])
        if sm <= now_mins < em:
            if s["code"] in ("BREAK", "LUNCH"):
                return {"kind": "break", "label": s["name"], "until": s["end"]}
            return {"kind": "current", "code": s["code"], "name": s["name"],
                    "loc": s["location"], "until": s["end"]}
    upcoming = [s for s in slots if _minutes(s["start"]) > now_mins and s["code"] not in ("BREAK", "LUNCH")]
    if upcoming:
        s = upcoming[0]
        return {"kind": "next", "code": s["code"], "name": s["name"],
                "loc": s["location"], "at": s["start"],
                "in_mins": _minutes(s["start"]) - now_mins}
    return {"kind": "done"}


def _hero_html(status, today):
    if status is None:
        return ("<div class=tt-hero tt-hero--off><span class=tt-hero-dot tt-hero-dot--off></span>"
                "<div><strong>No classes today</strong>"
                "<div class=tt-hero-sub>Nothing scheduled for {0}</div></div></div>").format(today)
    kind = status["kind"]
    if kind == "current":
        return ("<div class=tt-hero tt-hero--now><span class=tt-hero-dot tt-hero-dot--now></span>"
                "<div><strong>{code} \u2014 {name}</strong>"
                "<div class=tt-hero-sub>Ends {until}</div>"
                "<div class=tt-hero-loc>{loc}</div></div></div>").format(**status)
    if kind == "next":
        return ("<div class=tt-hero tt-hero--next><span class=tt-hero-dot tt-hero-dot--next></span>"
                "<div><strong>{code} \u2014 {name}</strong>"
                "<div class=tt-hero-sub>Starts at {at} (in {in_mins}m)</div>"
                "<div class=tt-hero-loc>{loc}</div></div></div>").format(**status)
    if kind == "break":
        return ("<div class=tt-hero tt-hero--break><span class=tt-hero-dot tt-hero-dot--break></span>"
                "<div><strong>{label}</strong>"
                "<div class=tt-hero-sub>Until {until}</div></div></div>").format(**status)
    return ("<div class=tt-hero tt-hero--done><span class=tt-hero-dot tt-hero-dot--off></span>"
            "<div><strong>Done for today</strong><div class=tt-hero-sub>No more classes</div></div></div>")


def _day_rows_html(day):
    rows = []
    for s in TIMETABLE[day]:
        if s["code"] in ("BREAK", "LUNCH"):
            rows.append("<div class=tt-divider>{0}</div>".format(s["name"]))
            continue
        hl = _slot_highlight(day, s["start"], s["end"], s["code"])
        cls = " tt-row--{0}".format(hl) if hl else ""
        badge = ""
        if hl == "current":
            badge = "<span class=tt-badge tt-badge--now>Now</span>"
        elif hl == "upcoming":
            badge = "<span class=tt-badge tt-badge--soon>Soon</span>"
        loc_html = "<span class=tt-loc>{0}</span>".format(s["location"]) if s["location"] else ""
        rows.append(
            "<div class=tt-row{cls}>"
            "<div class=tt-time>{start}<small>{end}</small></div>"
            "<div class=tt-info><strong>{code}</strong><span class=tt-name>{name}</span>{loc}</div>"
            "{badge}</div>".format(cls=cls, start=s["start"], end=s["end"], code=s["code"],
                                   name=s["name"], loc=loc_html, badge=badge))
    return "".join(rows)


def timetable_html():
    today = datetime.now().strftime("%A")
    default_day = today if today in DAY_ORDER else "Monday"
    hero = _hero_html(_now_next(today), today)
    radios = "".join(
        "<input type=radio name=ttday id=day-{0} class=tt-radio{1}>".format(
            d, " checked" if d == default_day else "") for d in DAY_ORDER)
    tabs = "".join(
        "<label for=day-{0}{1}>{2}</label>".format(
            d, " class=tt-today" if d == today else "", d[:3]) for d in DAY_ORDER)
    panels = "".join(
        "<div class=day-panel id=panel-{0}>{1}</div>".format(d, _day_rows_html(d))
        for d in DAY_ORDER)
    return ("<div class=tt-wrap>" + hero
            + "<div class=tt-tabs>" + radios
            + "<div class=tt-tabbar>" + tabs + "</div>"
            + "<div class=panels>" + panels + "</div>"
            + "</div></div>")
