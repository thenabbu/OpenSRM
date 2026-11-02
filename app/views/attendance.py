"""Attendance view models: skip budgets, absences card, display helpers
(moved from app.app; re-exported from app.app)."""

import math
from datetime import date, datetime, timedelta

from flask import g

from ..db import weekly_slot_counts

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

# ── moved from app/app.py (facade pump, cycle B) ─────────────────────
# Attendance row shaping: budget sentences, the subject join, exact truncated
# percentages and the per-course/per-month view dicts. Same family as the
# helpers above, so they live together instead of in the facade.


def _bunk_counts(attended, total, threshold=ATTENDANCE_TARGET):
    """(skip_now, attend_now) — the numbers behind _bunk_line's prose (spec §3).
    Exactly one side is non-None when total > 0; (None, None) when nothing was held.
    The ±1e-9 epsilon and max(1, …) are the original _bunk_line's semantics [F10] —
    _bunk_line renders these; the meter connector + timetable glance need the NUMBER."""
    if total <= 0:
        return (None, None)
    room = attended / threshold - total
    if room >= -1e-9:
        return (max(0, math.floor(room + 1e-9)), None)
    return (None, max(1, math.ceil((threshold * total - attended) / (1 - threshold) - 1e-9)))

def _bunk_line(attended, max_hours, threshold=ATTENDANCE_TARGET):
    if max_hours <= 0: return None
    pct_target = threshold * 100
    skip, attend = _bunk_counts(attended, max_hours, threshold)
    if skip is not None:
        if skip == 0:
            return "One more miss drops you below %.0f%%" % pct_target
        return "Can miss %d more class%s and stay above %.0f%%" % (skip, "" if skip == 1 else "es", pct_target)
    return "Attend the next %d class%s in a row to reach %.0f%%" % (attend, "" if attend == 1 else "es", pct_target)


def _weekly_slots(group_key):
    """w = weekly slot count per subject_code, scoped to THIS user's group [F4].
    Precedent: _day_slots / timetable_html / /api/timetable all scope by group_id."""
    return weekly_slot_counts(group_key)


def _norm_subject(s):
    """Join key: upper / strip / squash whitespace (spec §4.3)."""
    return " ".join(str(s or "").upper().split())


def _attendance_index(courses):
    """spec §4 join index built in index(): code-exact map + normalized-name fallback map."""
    by_code = {c["code"]: c for c in courses if c.get("code")}
    by_name = {}
    for c in courses:
        key = _norm_subject(c.get("description"))
        if key:
            by_name.setdefault(key, c)
    return {"by_code": by_code, "by_name": by_name}

def _join_attendance(index, custom_codes, code, name):
    """spec §4 order is load-bearing: custom (is_custom=1) → code-exact → normalized name
    → None. None means neutral "no data" — an unmatched slot must NEVER render as 0% [F9]."""
    if not index:
        return None
    if code in custom_codes:
        return None  # a custom subject typed with a portal-matching name must never join
    return index["by_code"].get(code) or index["by_name"].get(_norm_subject(name))

def _pct_trunc(part, whole, dec=ATTENDANCE_DECIMALS):
    """Attendance % as an EXACT truncated value, never rounded, in integer space.

    SRM detains below 75, so 74.9847% must read 74.9 — `round()`/`%.1f` would print
    75.0 and the row would also flip to the comfortable tint. Integer math because
    float is lossy here: 7499/10000*100 == 7498.999…, so math.floor(x*100) and
    string-slicing both shave a digit. Returns (float, "dd.d" string) or (None, None)
    when `whole` is 0 (nothing held -> the template renders `--`).
    """
    if whole <= 0:
        return (None, None)
    scale = 10 ** dec
    e = part * 100 * scale // whole          # the % scaled to `dec` places, truncated
    return (e / scale, "%d.%0*d" % (e // scale, dec, e % scale))

def _course_view(c):
    attended = _safe_int(c.get("attended"))
    max_hours = _safe_int(c.get("max_hours"))
    # ONE number feeds display, tint and the sort key — see _pct_trunc.
    pct, pct_disp = _pct_trunc(attended, max_hours)
    if pct is None:
        pct = 0.0
    skip, attend = _bunk_counts(attended, max_hours)
    # status/absent outputs dropped: grep showed no template/route consumer —
    # the monthly bar's band lives on the MONTH dict now (_month_view)
    return {"code": c.get("code", ""), "description": _title_case(c.get("description", "")),
            "max_hours": max_hours, "attended": attended,
            "pct": pct, "bunk_line": _bunk_line(attended, max_hours),
            # meter-row fields (spec §1.1): display per ATTENDANCE_DECIMALS, fill EXACT A/C [F12],
            # pct_disp None = `--` (C = 0 holds nothing → no fill, no pinned numbers)
            "pct_disp": pct_disp,
            "fill": (100.0 * attended / max_hours) if max_hours > 0 else None,
            "t75": math.ceil(ATTENDANCE_TARGET * max_hours),
            "skip_now": skip, "attend_now": attend,
            # fill tint: red = pct < 75 · orange(warn) = pct ≥ 75 AND skip-now == 0 · gray = comfortable
            "tint": "red" if pct < ATTENDANCE_TARGET * 100 else ("warn" if skip == 0 else "gray"),
            # table view: the SAME signed _bunk_counts pair the dashboard widget shows
            # (+skip / 0 / -attend) — one sign language, one threshold source. None =
            # no classes held -> template renders `--`, never a fake 0.
            "margin": (skip if skip is not None else -attend) if max_hours > 0 else None}

_BAND_BAR = {"ok": "success", "warn": "warning", "danger": "error"}

def _month_view(m):
    present = _safe_int(m.get("present"))
    absent = _safe_int(m.get("absent"))
    total = present + absent
    out = dict(m)
    # same truncated figure as the subject meters — a rounded one can turn a sub-75%
    # month into "75.0%" and read as safe.
    out["pct"], out["pct_disp"] = _pct_trunc(present, total)
    # bar class derived in Python from the ONE threshold source — the old
    # template ternary re-typed >=75/>=65 as a second copy of _status_for_pct
    out["bar"] = _BAND_BAR[_status_for_pct(out["pct"])] if out["pct"] is not None else None
    return out


# ── Request logging ─────────────────────────────────────────────────
def _bare(code, reason):
    """Deliberately bare response body (nothing for a prober to read — used
    by the internal endpoints' auth); the reason still lands on the status
    line via _log_request's g._log_reason fallback, so every >=400 line in
    opensrm.log carries an error= (the logging-gap rule)."""
    g._log_reason = reason
    return "", code
