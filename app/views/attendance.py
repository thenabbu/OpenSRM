"""Attendance view models: skip budgets, absences card, display helpers
(moved from app.app; re-exported from app.app)."""

import math
from datetime import date, datetime, timedelta

ATTENDANCE_TARGET = 0.75
ATTENDANCE_WARN = 0.65
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


def hourwise_view(rows, slots, custom=frozenset(), limit=14):
    """SCOPE getHourwiseAttendance rows + the user's timetable slots
    ({day: {period: {"code", "name", ...}}}) -> the two views the hourwise
    feature earns (join spec: validate, don't redesign):

      chips: {"16 Oct": [{"label", "title"}]} — A hours only, contiguous
        same-subject runs grouped ("14 Oct · h1,h2 COA"). A missing hour
        key = no class scheduled = never an absence; any slot miss (weekend,
        no row, NULL code, "CL" class-in-charge, custom subject) and any
        h7+ hour (SCOPE only sends h1..h6 -> period 7 is UNKNOWN) falls back
        to a bare hN chip. NEVER invents a subject.
      strip: last `limit` school days, newest first — 6 period slots per
        column (state P|A|OD, None = no class, kept for period alignment)
        plus the joined subject for labels.

    O(days×6) dict lookups, per-request, nothing cached (contract)."""
    chips, strip = {}, []
    parsed = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        try:
            parsed.append((datetime.strptime(str(r.get("attendancedate", "")), _HW_FMT).date(), r))
        except ValueError:
            continue  # junk row: no date, no view — never a crash
    parsed.sort(key=lambda t: t[0], reverse=True)

    def _subject(day, n, r):
        """The joined subject for hour n, or None = bare hN fallback.
        period 7+ is deliberately None: SCOPE has no h7, so it can never be
        named (and never be called an absence from the timetable side)."""
        if n > 6:
            return None, None
        slot = (slots.get(day) or {}).get(n)
        if not slot:
            return None, None
        code = str(slot.get("code") or "")
        name = str(slot.get("name") or "")
        if not code or not name or code == "CL" or code in custom:
            return None, None  # NULL code / class-in-charge / custom slot
        return name, code

    for d, r in parsed:
        day = d.strftime("%A")
        disp = d.strftime("%d %b")
        # chips: contiguous same-subject runs across h1..h6 (+ defensive h7)
        runs = []
        for n in range(1, 8):
            v = r.get("h%d" % n)
            if v is None:
                continue  # missing key = no class scheduled, never an absence
            if str(v).strip().upper() != "A":
                continue  # P / OD / junk: not an absence hour
            subj, code = _subject(day, n, r)
            if runs and runs[-1]["subj"] == subj and runs[-1]["last"] == n - 1:
                runs[-1]["last"] = n
            else:
                runs.append({"first": n, "last": n, "subj": subj, "code": code})
        if runs:
            out = []
            for run in runs:
                hrs = ",".join("h%d" % n for n in range(run["first"], run["last"] + 1))
                if run["subj"]:
                    out.append({"label": "%s · %s %s" % (disp, hrs, run["subj"]),
                                "title": "Absent %s — %s (%s)" % (hrs, run["subj"], run["code"])})
                else:
                    out.append({"label": "%s · %s" % (disp, hrs),
                                "title": "Absent %s — no subject on the timetable" % hrs})
            chips[disp] = out
        # day strip: newest `limit` rows, 6 fixed period slots each
        if len(strip) < limit:
            cells = []
            for n in range(1, 7):
                v = r.get("h%d" % n)
                st = str(v).strip().upper() if v is not None else None
                if st not in ("P", "A", "OD"):
                    st = None  # no key / junk value = no class slot
                subj, _ = _subject(day, n, r)
                cells.append({"n": n, "state": st, "subject": subj})
            strip.append({"date": disp, "dow": day[:3], "cells": cells})
    return {"chips": chips, "strip": strip}
