"""Marks view models: IE derivation, score/date formatting, tab + glance rows
(moved from app.app; re-exported from app.app)."""

from datetime import date, datetime


def _fmt_score(v):
    """Minimal decimals: 11.7 -> '11.7', 5 -> '5' (trailing zeroes stripped —
    the '.' keeps whole-number zeros intact). Junk/None -> '?' — a stored
    null score used to TypeError into a 500 (audit B9)."""
    try:
        return f"{float(v):.2f}".rstrip("0").rstrip(".")
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
    """IE-1/IE-2 are never labelled by the portal — guess IE-1 from the
    component's scaled max (the /15 component; /10 for practicals like
    21CSC203P). A confirmed tag always wins; this is the 'derived' state."""
    if maximum == 15:
        return "IE-1"
    if maximum == 10 and str(code).endswith("P"):
        return "IE-1"
    return None

def _marks_view(marks, tags=None):
    """Marks tab view model: title-cased subjects, components sorted by NAME
    (the portal's order is by entry, dates jump around), '04 Sep' dates,
    integer maxima with 2-decimal scores, and IE rows converted back to their
    raw /50 (IE-1) or /60 (IE-2) marks. `tags` = confirmed overrides."""
    tags = tags or {}
    out = []
    for s in marks:
        code = s.get("code", "")
        comps = []
        for cpt in sorted(s.get("components", []), key=lambda c: str(c.get("name", ""))):
            maximum, scored = cpt.get("max", 0.0), cpt.get("scored", 0.0)
            tag = tags.get((code, cpt.get("name", "")))
            derived = _derive_ie(code, maximum)
            role = tag["role"] if tag else derived   # confirmed wins, incl. 'none'
            ie = None
            if role in ("IE-1", "IE-2"):
                raw = (tag.get("raw_max") if tag and tag.get("raw_max")
                       else (50.0 if role == "IE-1" else 60.0))
                ie = {"role": role, "confirmed": bool(tag), "max_disp": _fmt_max(raw),
                      "score_disp": _fmt_score(scored * raw / maximum) if maximum else _fmt_score(0)}
            comps.append({"name": cpt.get("name", ""), "date_disp": _fmt_date(cpt.get("entered", "")),
                          "score_disp": _fmt_score(scored), "max_disp": _fmt_max(maximum),
                          "derived": derived or "", "confirmed": tag["role"] if tag else None,
                          "ie": ie})
        st, mt = s.get("scored_total", 0.0), s.get("max_total", 0.0)
        out.append({"code": code, "title": (s.get("title") or "").title(),
                    "scored_disp": _fmt_score(st), "max_disp": _fmt_max(mt),
                    "pct": round(st / mt * 100, 1) if mt else 0.0, "outlier": False,
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
