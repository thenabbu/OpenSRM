"""Attendance view models: skip budgets, absences card, display helpers
(moved from app.app; re-exported from app.app)."""

import math
from datetime import date, datetime, timedelta

ATTENDANCE_TARGET = 0.75
ATTENDANCE_WARN = 0.65
# Decimals shown for every attendance percentage. 1 is deliberate: SRM detains below
# 75, and one decimal is the least that keeps 74.98 distinguishable from 75 — rounded
# to 0dp (or shown as 2dp, which reads as noise at a glance) it loses that job.
ATTENDANCE_DECIMALS = 1
WORKING_DAYS = 90  # 90-working-day skip-budget horizon (spec §3); no academic calendar exists (see _attendance_budgets)

def _safe_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0

def _status_for_pct(pct):
    if pct >= ATTENDANCE_TARGET * 100: return "ok"
    if pct >= ATTENDANCE_WARN * 100: return "warn"
    return "danger"

def _weekdays(a, b):
    """Mon–Fri count with BOTH ends inclusive (0 when b < a) [F13]."""
    if not a or not b or b < a:
        return 0
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n

def _exam_stop(exams):
    """One global attendance horizon for every subject: first parseable endsem date − 1 day
    (spec §0/R6 — portal marking stops at the FIRST exam of ANY subject). None when
    exam_schedule is empty/junk: callers degrade, never guess a date."""
    dates = []
    for r in exams or []:
        try:
            dates.append(datetime.strptime(str(r.get("date", "")), "%d-%m-%Y").date())
        except ValueError:
            continue  # junk rows fall back in _exams_view; they must not anchor the horizon
    return (min(dates) - timedelta(days=1)) if dates else None

def _attendance_budgets(attended, max_hours, w, period=None, exams=None, today=None):
    """Semester skip budgets (spec §3): 90-working-day model + endsem-date model.
    Every value degrades to None (template renders `--` / hides) — never a fake zero:
    no exams → m_end/days_left_exam None; w = 0 → both budgets None; period absent or
    elapsed ≤ 0 → days_left_90 dropped (column keeps its budgets) [F9].
    ponytail: period.from may be a rolling window; if days-left ever looks wrong, add
    academic_calendar_json (migration v11 is free) — ceiling disclosed in the PR [R7]."""
    today = today or date.today()
    stop = _exam_stop(exams)
    out = {"m90": None, "m_end": None, "days_left_90": None, "days_left_exam": None, "stop": stop}
    if w > 0:
        T = math.ceil(WORKING_DAYS * w / 5)
        N = T - max_hours
        out["m90"] = max(0, math.floor(attended + N - ATTENDANCE_TARGET * T))
        if stop is not None:
            # ceil REQUIRED here: floor/raw gives DBMS 4 where the frozen table says 5 [F1]
            N_e = math.ceil(w * _weekdays(today + timedelta(days=1), stop) / 5)
            T_e = max_hours + N_e
            out["m_end"] = max(0, math.floor(attended + N_e - ATTENDANCE_TARGET * T_e))
    if stop is not None:
        out["days_left_exam"] = (stop - today).days
    frm = period.get("from") if isinstance(period, dict) else None
    if frm:
        try:
            elapsed = _weekdays(datetime.strptime(str(frm), "%d/%b/%Y").date(), today)
        except ValueError:
            elapsed = 0
        if elapsed > 0:
            out["days_left_90"] = WORKING_DAYS - min(elapsed, WORKING_DAYS)
    return out

def _absences_view(daily):
    """Absences card (review R4): month-grouped; each row is `date · hours` ONLY —
    no subject column [R5] (daily_absent rows carry none; deriving one would be a lie)."""
    out = []
    for label, rows in (daily or {}).items():
        disp_rows = []
        for r in rows or []:
            raw = str(r.get("date", ""))
            try:
                disp = datetime.strptime(raw, "%d-%m-%Y").strftime("%d %b")
            except ValueError:
                disp = raw  # unknown shape: show it raw rather than hide the absence
            disp_rows.append({"date": disp, "hours": r.get("hours", "")})
        if disp_rows:
            out.append({"label": _title_case(str(label).replace(" / ", " ")), "rows": disp_rows})
    return out

def _title_case(s):
    """Display only (review R2): portal names arrive ALL CAPS -> Title Case.
    No-op on mixed-case strings (custom timetable names keep their casing);
    join keys still go through _norm_subject, so casing is render-time only."""
    s = str(s or "")
    return s.title() if s.isupper() else s

# ── Hourwise join (SCOPE getHourwiseAttendance × the user's timetable) ──────
_HW_FMT = "%d-%b-%Y"  # SCOPE attendancedate: "16-Oct-2026"
_HW_STATES = ("P", "A", "OD")


def _hw_subject(day, n, slots, custom):
    """The timetable's subject for hour n of `day`, or None = no name.
    period 7+ is deliberately None: SCOPE only sends h1..h6, so it can never
    be named from timetable data. Any slot miss (weekend, no row, NULL code,
    "CL" class-in-charge, custom subject) is None too — never invent one."""
    if n > 6:
        return None, None
    slot = (slots.get(day) or {}).get(n)
    if not slot:
        return None, None
    code = str(slot.get("code") or "")
    name = str(slot.get("name") or "")
    if not code or not name or code == "CL" or code in custom:
        return None, None
    return name, code


def hourwise_view(rows, slots, custom=frozenset(), portal_months=None):
    """SCOPE getHourwiseAttendance rows + the user's timetable slots
    ({day: {period: {"code", "name", ...}}}) -> the Detailed attendance grid.

    Returns {"hours": [1..N], "months": [{"label", "p", "a", "od", "days":
    [{"date", "dow", "cells"}]}], "ts"} where each cell is
    {"n", "state": "P"|"A"|"OD"|None, "subject", "code", "title"}.

    Join contract (unchanged from the foundations PR): hN -> timetable period
    N of that row's weekday; a missing hour key = no class delivered = never
    an absence (state None, rendered as an empty placeholder); unmatched slot
    (CL / custom / weekend) keeps the state but drops the name (bare hN).
    `portal_months` = the portal's monthly rows ({"label": "Oct / 2026", ...}),
    consumed among others to order the grid months and carry their own
    labels/percentages through; a month only SCOPE knows about lands last.
    O(days×6) dict lookups, per request, nothing cached.
    """
    parsed = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        try:
            parsed.append((datetime.strptime(str(r.get("attendancedate", "")), _HW_FMT).date(), r))
        except ValueError:
            continue  # junk row: no date, no view — never a crash
    parsed.sort(key=lambda t: t[0], reverse=True)

    # hours SCOPE actually reported; a column no row ever carries is noise
    hours = [n for n in range(1, 8) if any(r.get("h%d" % n) is not None for _, r in parsed)]
    # period 7 has no SCOPE hour: a reported h7 gets a column but can never
    # hold a state or a name (see _hw_subject) — the PR body states this.
    if not hours:
        hours = [1, 2, 3, 4, 5, 6]

    portal_months = portal_months or {}
    order = {lab.replace(" / ", " "): lab for lab in portal_months}
    by_label, extra = {}, {}
    for d, r in parsed:
        day = d.strftime("%A")
        label = d.strftime("%b %Y")
        cells = []
        for n in hours:
            v = r.get("h%d" % n)
            st = str(v).strip().upper() if v is not None else None
            if st not in _HW_STATES or n > 6:
                st = None  # missing key / junk value / period 7 = no state
            subj, code = _hw_subject(day, n, slots, custom)
            if st:
                bits = [day, d.strftime("%d %b %Y"), "h%d" % n,
                        {"P": "present", "A": "absent", "OD": "on duty"}[st]]
                bits.append("%s (%s)" % (subj, code) if subj
                            else "no subject on the timetable")
                title = " · ".join(bits)
            else:
                title = "No class scheduled · h%d" % n
            cells.append({"n": n, "state": st, "subject": subj, "code": code,
                          "title": title})
        rec = {"date": d.strftime("%d %b"), "full": d.strftime("%d %b %Y"),
               "dow": day, "cells": cells}
        (by_label if label in order else extra).setdefault(label, []).append(rec)

    out = []
    for label in list(order) + sorted(extra):
        days = by_label.get(label) or extra.get(label)
        if not days:
            continue
        p = portal_months.get(order.get(label, "")) or {}
        out.append({"label": label,
                    "side": p.get("label") or label,   # the portal's own wording
                    "pct": p.get("pct"),
                    "p": sum(1 for x in days for c in x["cells"] if c["state"] == "P"),
                    "a": sum(1 for x in days for c in x["cells"] if c["state"] == "A"),
                    "od": sum(1 for x in days for c in x["cells"] if c["state"] == "OD"),
                    "days": days})
    return {"hours": hours, "months": out}
