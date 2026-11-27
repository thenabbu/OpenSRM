"""Marks view models: IE derivation, score/date formatting, tab + glance rows
(moved from app.app; re-exported from app.app)."""

import re
from datetime import date, datetime


def _fmt_score(v):
    """Minimal decimals: 11.7 -> '11.7', 5 -> '5' (trailing zeroes stripped —
    the '.' keeps whole-number zeros intact). Junk/None -> '?' — a stored
    null score used to TypeError into a 500 (audit B9)."""
    try:
        return f"{float(v):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "?"

def _fmt_pct(v):
    """Percent as one decimal: 94.0 -> '94.0', 78.6 -> '78.6'.

    The template printed the raw float and a JS Number drops the ".0", so the
    hydrated card said "94%" where the no-JS paint said "94.0%" (one page, two
    renderings). Formatting lives here, once, like every other display string.
    """
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "?"


def _fmt_max(v):
    """Maxima are whole marks on the portal: 15.0 -> '15' (never '15.00')."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "?"
    return str(int(f)) if f.is_integer() else f"{f:.2f}"

def _fmt_date(s):
    """Portal date '04/Sep/2026' -> muted display '04 Sep'; junk passes through."""
    try:
        return datetime.strptime(s, "%d/%b/%Y").strftime("%d %b")
    except (ValueError, TypeError):
        return s or ""

def _derive_ie(code, maximum):
    """DEPRECATED per-component guess — kept only so old callers import.

    The portal never labels IE-1/IE-2, and one max-based rule cannot tell a
    second internal exam from a fourth frequent test (it painted three
    "IE-1" rows on one subject). `_derive_ie_roles()` answers the question per
    SUBJECT instead. Do not call this.
    """
    if maximum == 15:
        return "IE-1"
    if maximum == 10 and str(code).endswith("P"):
        return "IE-1"
    return None


# Marks → letter grade for internal-only courses (a course whose internal
# total is already /100 has no end-semester paper to wait for). Bands come
# from the portal's own "marks to grade" conversion modal; high → low, first
# match wins. ponytail: one table, one place — swap the numbers here if SRM
# revises the scale, nothing else reads them.
GRADE_BANDS = ((91, "O"), (81, "A+"), (71, "A"), (61, "B"), (51, "C"), (41, "D"), (0, "F"))
INTERNAL_ONLY_TOTAL = 100.0   # a /100 internal total = grade, not a raw score


def _internal_grade(scored):
    """Letter grade for an internal-only subject's total, '' when unreadable."""
    try:
        s = float(scored)
    except (TypeError, ValueError):
        return ""
    for floor, grade in GRADE_BANDS:
        if s >= floor:
            return grade
    return ""


_IE_FAMILY = re.compile(r"^([A-Za-z]+)")


def _derive_ie_roles(components):
    """{component name: 'IE-1'|'IE-2'} for ONE subject — the portal labels no
    internal exam, so the pair is inferred from the subject's own repeats.

    A component can only be an internal exam if its name family repeats at the
    same max (FP-I/FP-II at /10; FT-II/FT-III/FT-IV at /15). Among those
    qualifying groups the smallest one wins (practical subjects carry a wider
    PBL/R21 group that is coursework, not an exam). Earliest by portal date is
    IE-1, latest is IE-2, and the middle repeats of a 3-member group stay
    unlabelled — two IEs is the ceiling, one is the floor.

    Every caller treats this as a guess: a stored tag always overrides it.
    """
    groups = {}
    for i, cpt in enumerate(components or []):
        m = _IE_FAMILY.match(str(cpt.get("name", "")).strip())
        if not m:
            continue
        try:
            maximum = float(cpt.get("max") or 0)
        except (TypeError, ValueError):
            continue
        if maximum <= 0:
            continue
        groups.setdefault((m.group(1).upper(), maximum), []).append((i, cpt))
    qual = [(len(v), k[1], v) for k, v in groups.items() if len(v) >= 2]
    if not qual:
        return {}
    qual.sort(key=lambda t: (t[0], t[1]))          # fewest members, then smallest max
    members = qual[0][2]

    def _when(pair):
        i, cpt = pair
        try:
            return (datetime.strptime(cpt.get("entered") or "", "%d/%b/%Y"), i)
        except (ValueError, TypeError):
            return (datetime.min, i)

    ordered = sorted(members, key=_when)
    roles = {ordered[-1][1].get("name", ""): "IE-2"}
    if len(ordered) >= 2:
        roles[ordered[0][1].get("name", "")] = "IE-1"
    return roles

def _marks_view(marks, tags=None):
    """Marks tab view model: title-cased subjects, components sorted by NAME
    (the portal's order is by entry, dates jump around), '04 Sep' dates,
    integer maxima with 2-decimal scores, and IE rows converted back to their
    raw /50 (IE-1) or /60 (IE-2) marks. `tags` = confirmed overrides.

    The card headline is the subject's own `scored/max`. An internal-only
    course (total already /100) shows its GRADE there instead, with
    `scored/max` demoted to the sub-line — a /100 internal total is a result,
    not a running score. `pct`/`pct_disp` survive only as the ordering key for
    the single outlier accent; nothing renders them any more.
    """
    tags = tags or {}
    out = []
    for s in marks:
        code = s.get("code", "")
        roles = _derive_ie_roles(s.get("components"))
        comps = []
        for cpt in sorted(s.get("components", []), key=lambda c: str(c.get("name", ""))):
            maximum, scored = cpt.get("max", 0.0), cpt.get("scored", 0.0)
            name = cpt.get("name", "")
            tag = tags.get((code, name))
            derived = roles.get(name)
            role = tag["role"] if tag else derived   # confirmed wins, incl. 'none'
            ie = None
            if role in ("IE-1", "IE-2"):
                raw = (tag.get("raw_max") if tag and tag.get("raw_max")
                       else (50.0 if role == "IE-1" else 60.0))
                ie = {"role": role, "confirmed": bool(tag), "max_disp": _fmt_max(raw),
                      "score_disp": _fmt_score(scored * raw / maximum) if maximum else _fmt_score(0)}
            comps.append({"name": name, "date_disp": _fmt_date(cpt.get("entered", "")),
                          "score_disp": _fmt_score(scored), "max_disp": _fmt_max(maximum),
                          "derived": derived or "", "confirmed": tag["role"] if tag else None,
                          "ie": ie})
        st, mt = s.get("scored_total", 0.0), s.get("max_total", 0.0)
        total_disp = f"{_fmt_score(st)}/{_fmt_max(mt)}"
        internal = abs(float(mt or 0) - INTERNAL_ONLY_TOTAL) < 0.005
        grade = _internal_grade(st) if internal else ""
        out.append({"code": code, "title": (s.get("title") or "").title(),
                    "scored_disp": _fmt_score(st), "max_disp": _fmt_max(mt),
                    "head_disp": grade or total_disp,      # card headline
                    "sub_disp": total_disp if grade else "",   # sub-line, /100 only
                    "grade": grade, "internal": internal,
                    "pct": round(st / mt * 100, 1) if mt else 0.0, "outlier": False,
                    "pct_disp": _fmt_pct(round(st / mt * 100, 1) if mt else 0.0),
                    "components": comps})
    # One muted accent per screen (DESIGN.md §2.7): the UNIQUE lowest subject,
    # and only below the 75% target — everything else on this page is neutral.
    ranked = sorted(out, key=lambda x: x["pct"])
    if len(ranked) > 1 and ranked[0]["pct"] < ranked[1]["pct"] and ranked[0]["pct"] < 75:
        ranked[0]["outlier"] = True
    return out

def _marks_summary(marks):
    """Dashboard glance: EVERY subject as code scored/max chips in risk-first
    order (weakest first) — no %, no aggregate/overall number. `stale=True`
    marks a row preserved from an earlier sync (the widget renders those chips
    faint). `recent` = some component's portal "Entered on" is today — the
    portal writes a date only (no time), so "changed in the last 24 hrs"
    resolves to entered-today at day granularity; `entered` carries that date
    for the chip's tooltip. None when empty."""
    if not marks:
        return None
    low = sorted(marks, key=lambda m: (m.get("scored_total", 0) / m["max_total"])
                 if m.get("max_total") else 1)
    today = date.today()
    out = []
    for m in low:
        recent, entered = False, ""
        for cpt in m.get("components", []):
            try:
                d = datetime.strptime(cpt.get("entered", "") or "", "%d/%b/%Y").date()
            except (ValueError, TypeError):
                continue
            if d == today:
                recent, entered = True, _fmt_date(cpt.get("entered", ""))
        out.append({"code": m.get("code", ""),
                    "scored": _fmt_score(m.get("scored_total", 0)),
                    "max": _fmt_max(m.get("max_total", 0)),
                    "stale": bool(m.get("stale")),
                    "recent": recent,
                    "entered": entered})
    # stale wins the chip: a preserved row has no fresh entry to show
    for r in out:
        if r["stale"]:
            r["recent"], r["entered"] = False, ""
    return out
