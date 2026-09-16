from datetime import datetime

TIMETABLE = {
    "Monday": [
        ("09:30", "10:20", "21CSC202J", "Operating Systems - Lab", "Lab C-6/7"),
        ("10:20", "11:10", "21CSC202J", "Operating Systems - Lab", "Lab C-6/7"),
        ("11:10", "11:20", "BREAK", "Break", ""),
        ("11:20", "12:10", "21CSC201J", "Data Structures and Algorithms", ""),
        ("12:10", "13:00", "21MAB206T", "Numerical Methods and Analysis", ""),
        ("13:00", "14:10", "LUNCH", "Lunch", ""),
        ("14:10", "15:00", "21CSC203P", "Advanced Programming Practice", ""),
        ("15:00", "15:50", "21CSS201T", "Computer Organization and Architecture", ""),
    ],
    "Tuesday": [
        ("09:30", "10:20", "21MAB206T", "Numerical Methods and Analysis", ""),
        ("10:20", "11:10", "21CSC202J", "Operating Systems", ""),
        ("11:10", "11:20", "BREAK", "Break", ""),
        ("11:20", "12:10", "21DCS201P", "Design Thinking and Methodology", ""),
        ("12:10", "13:00", "21CSS201T", "Computer Organization and Architecture", ""),
        ("13:00", "14:10", "LUNCH", "Lunch", ""),
        ("14:10", "15:00", "26CCT201E", "Career Catalyst Programme", ""),
        ("15:00", "15:50", "VA", "Value Added", ""),
    ],
    "Wednesday": [
        ("09:30", "10:20", "21CSC203P", "Advanced Programming Practice - Lab", "Lab C-8/9"),
        ("10:20", "11:10", "21CSC203P", "Advanced Programming Practice - Lab", "Lab C-8/9"),
        ("11:10", "11:20", "BREAK", "Break", ""),
        ("11:20", "12:10", "21CSC201J", "Data Structures and Algorithms", ""),
        ("12:10", "13:00", "21MAB206T", "Numerical Methods and Analysis", ""),
        ("13:00", "14:10", "LUNCH", "Lunch", ""),
        ("14:10", "15:00", "21CSS201T", "Computer Organization and Architecture", ""),
        ("15:00", "15:50", "21LEM201T", "Professional Ethics", ""),
    ],
    "Thursday": [
        ("09:30", "10:20", "21CSC201J", "Data Structures and Algorithms", ""),
        ("10:20", "11:10", "21CSC203P", "Advanced Programming Practice", ""),
        ("11:10", "11:20", "BREAK", "Break", ""),
        ("11:20", "12:10", "21MAB206T", "Numerical Methods and Analysis", ""),
        ("12:10", "13:00", "21DCS201P", "Design Thinking and Methodology", ""),
        ("13:00", "14:10", "LUNCH", "Lunch", ""),
        ("14:10", "15:00", "21CSC202J", "Operating Systems", ""),
        ("15:00", "15:50", "AWS", "AWS", ""),
    ],
    "Friday": [
        ("09:30", "10:20", "21DCS201P", "Design Thinking and Methodology", ""),
        ("10:20", "11:10", "21CSS201T", "Computer Organization and Architecture", ""),
        ("11:10", "11:20", "BREAK", "Break", ""),
        ("11:20", "12:10", "21CSC202J", "Operating Systems", ""),
        ("12:10", "13:00", "21CSC203P", "Advanced Programming Practice", ""),
        ("13:00", "14:10", "LUNCH", "Lunch", ""),
        ("14:10", "15:00", "21CSC201J", "Data Structures and Algorithms - Lab", "Lab C-4/5"),
        ("15:00", "15:50", "21CSC201J", "Data Structures and Algorithms - Lab", "Lab C-4/5"),
    ],
}

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _slot_highlight(day, start, end, code):
    """Row-level highlight for a single scheduled slot. Only ever fires for
    today's own rows -- 'current' if we're inside the slot right now, 'upcoming'
    if it starts within the next two hours."""
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


def _fmt_mins(m):
    if m < 60:
        return "{0}m".format(m)
    h, mm = divmod(m, 60)
    return "{0}h {1}m".format(h, mm) if mm else "{0}h".format(h)


def _now_next(day):
    """What's happening right now on `day`, if `day` is today. Returns None for
    a day with no timetable entry (weekends)."""
    if day not in TIMETABLE:
        return None
    now_mins = datetime.now().hour * 60 + datetime.now().minute
    slots = TIMETABLE[day]

    for s, e, code, name, loc in slots:
        sm, em = _minutes(s), _minutes(e)
        if sm <= now_mins < em:
            if code in ("BREAK", "LUNCH"):
                return {"kind": "break", "label": name, "until": e}
            return {"kind": "current", "code": code, "name": name, "loc": loc, "until": e}

    upcoming = [s for s in slots if _minutes(s[0]) > now_mins and s[2] not in ("BREAK", "LUNCH")]
    if upcoming:
        s, e, code, name, loc = upcoming[0]
        return {"kind": "next", "code": code, "name": name, "loc": loc, "at": s, "in_mins": _minutes(s) - now_mins}

    return {"kind": "done"}


def _hero_html(status, today):
    if status is None:
        return (
            '<div class="tt-hero tt-hero--off"><span class="tt-hero-dot tt-hero-dot--off"></span>'
            '<div><strong>No classes today</strong>'
            '<div class="tt-hero-sub">Nothing scheduled for {0}</div></div></div>'
        ).format(today)

    kind = status["kind"]
    if kind == "current":
        loc_html = '<div class="tt-hero-loc">{0}</div>'.format(status["loc"]) if status["loc"] else ""
        return (
            '<div class="tt-hero tt-hero--now"><span class="tt-hero-dot tt-hero-dot--now"></span>'
            '<div><strong>{0} — {1}</strong><div class="tt-hero-sub">Ends {2}</div>{3}</div></div>'
        ).format(status["code"], status["name"], status["until"], loc_html)

    if kind == "break":
        return (
            '<div class="tt-hero tt-hero--break"><span class="tt-hero-dot tt-hero-dot--break"></span>'
            '<div><strong>{0}</strong><div class="tt-hero-sub">Until {1}</div></div></div>'
        ).format(status["label"], status["until"])

    if kind == "next":
        loc_html = '<div class="tt-hero-loc">{0}</div>'.format(status["loc"]) if status["loc"] else ""
        return (
            '<div class="tt-hero tt-hero--next"><span class="tt-hero-dot tt-hero-dot--next"></span>'
            '<div><strong>Next: {0} — {1}</strong>'
            '<div class="tt-hero-sub">{2}, in {3}</div>{4}</div></div>'
        ).format(status["code"], status["name"], status["at"], _fmt_mins(status["in_mins"]), loc_html)

    return (
        '<div class="tt-hero tt-hero--done"><span class="tt-hero-dot tt-hero-dot--off"></span>'
        '<div><strong>Done for today</strong><div class="tt-hero-sub">No more classes</div></div></div>'
    )


def _day_rows_html(day):
    rows = []
    for s, e, code, name, loc in TIMETABLE[day]:
        if code in ("BREAK", "LUNCH"):
            rows.append('<div class="tt-divider">{0}</div>'.format(name))
            continue
        hl = _slot_highlight(day, s, e, code)
        cls = " tt-row--{0}".format(hl) if hl else ""
        badge = ""
        if hl == "current":
            badge = '<span class="tt-badge tt-badge--now">Now</span>'
        elif hl == "upcoming":
            badge = '<span class="tt-badge tt-badge--soon">Soon</span>'
        loc_html = '<span class="tt-loc">{0}</span>'.format(loc) if loc else ""
        rows.append(
            '<div class="tt-row{cls}">'
            '<div class="tt-time">{s}<small>{e}</small></div>'
            '<div class="tt-info"><strong>{code}</strong><span class="tt-name">{name}</span>{loc}</div>'
            '{badge}'
            '</div>'.format(cls=cls, s=s, e=e, code=code, name=name, loc=loc_html, badge=badge)
        )
    return "".join(rows)


def timetable_html():
    today = datetime.now().strftime("%A")
    default_day = today if today in DAY_ORDER else "Monday"
    hero = _hero_html(_now_next(today), today)

    radios = "".join(
        '<input type="radio" name="ttday" id="day-{0}" class="tt-radio"{1}>'.format(
            d, " checked" if d == default_day else ""
        )
        for d in DAY_ORDER
    )
    tabs = "".join(
        '<label for="day-{0}"{1}>{2}</label>'.format(
            d, ' class="tt-today"' if d == today else "", d[:3]
        )
        for d in DAY_ORDER
    )
    panels = "".join(
        '<div class="day-panel" id="panel-{0}">{1}</div>'.format(d, _day_rows_html(d))
        for d in DAY_ORDER
    )

    return (
        '<div class="tt-wrap"><h2>Timetable</h2>'
        + hero
        + '<div class="tt-tabs">'
        + radios
        + '<div class="tt-tabbar">' + tabs + '</div>'
        + '<div class="panels">' + panels + '</div>'
        + '</div></div>'
    )
