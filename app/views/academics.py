"""Academics tab view model — the CGPA hero (which owns the semester
results), and one combined credits + subjects card (SCOPE ops read from
users.scope_json).

Reads the stored cold blob only: no network, no new columns, no new
endpoints. Every section builds independently so the template can self-hide
each card (DESIGN.md §4.12 empty = hidden), and academics_view() returns
None when the feature is off, the row holds none of the academics ops, or
every section is empty — the tab then has ZERO footprint (no navbar item,
per the SCOPE toggle contract).

CGPA honesty contract (mission): credit-weighted over RELEASED results,
2 decimals with ROUND_HALF_UP (Python round() is banker's). The figure is
labelled plainly "CGPA" — it is a calculation, not an estimate — and the
grade -> point scale note lives in a code comment + the PR body, never in
the UI.
"""
import html
import json
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from ..scope.ops import FEATURES
from .attendance import _title_case

# ponytail: SRM grade->point scale unconfirmed from official docs; upgrade
# path = swap this map when a published SRM scale or portal-displayed CGPA
# appears for cross-check.
GRADE_POINTS = {"O": 10, "A+": 9, "A": 8, "B": 7, "C": 6, "D": 5, "F": 0}


def _int(v, default=0):
    """Portal counts arrive as strings ("-"/""/None are routine)."""
    try:
        return int(Decimal(str(v).strip()))
    except Exception:
        return default


def _monthkey(label):
    """'MAY 2026' -> datetime for newest-first ordering; junk sorts oldest."""
    try:
        return datetime.strptime(str(label).strip(), "%b %Y")
    except ValueError:
        return datetime.min


def _gpa(rows):
    """(value:str|None, credits:int) — credit-weighted grade points over the
    released rows, 2dp ROUND_HALF_UP.

    A row counts when its grade is on GRADE_POINTS AND the portal released
    it as `result=Pass` — except F, which always counts (dropping failed
    credits would inflate the average, the one dishonest direction). Grade
    "-", "" and unknown grades are not released results: skipped, never 0.
    0-credit rows cannot weight anything, so they are skipped too.
    """
    num = den = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        grade = str(r.get("grade") or "").strip()
        pt = GRADE_POINTS.get(grade)
        if pt is None:
            continue
        if grade != "F" and str(r.get("result") or "").strip().lower() != "pass":
            continue
        cr = _int(r.get("credit"))
        if cr <= 0:
            continue
        num += pt * cr
        den += cr
    if not den:
        return None, 0
    val = (Decimal(num) / Decimal(den)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{val:.2f}", den


def _envelope_rows(data):
    """{Status, Message, Data} wrapper -> generic rows. Alive-empty
    (Data "" / "No data found") -> [] so the subsection self-hides; a season
    payload renders SHAPE-DRIVEN (no field hardcoding — the non-empty shape
    is unconfirmed until a season publishes one, and the section must not
    break when it does)."""
    payload = data.get("Data") if isinstance(data, dict) else data
    if not payload:
        return []
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return [{"title": _title_case(payload), "code": "", "grade": "", "meta": []}]
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return [{"title": _title_case(str(payload)), "code": "", "grade": "", "meta": []}]
    titles = ("subjectdesc", "description", "subjectname", "examname", "name")
    row_keys = set(titles) | {"subjectcode", "code", "grade"}
    out = []
    for item in payload[:100]:
        if not isinstance(item, dict):
            out.append({"title": _title_case(str(item)), "code": "", "grade": "", "meta": []})
            continue
        title = next((str(item[k]) for k in titles if item.get(k)), "")
        code = next((str(item[k]) for k in ("subjectcode", "code") if item.get(k)), "")
        meta = [(k, str(v)) for k, v in item.items()
                if k not in row_keys and v not in (None, "", "-")][:4]
        if not (title or code or item.get("grade") or meta):
            continue   # nothing renderable (alive-empty row shape) -> skip
        out.append({"title": _title_case(title), "code": code,
                    "grade": str(item.get("grade") or "").strip(), "meta": meta})
    return out


def _subject_row(code, name, grade):
    """One line per subject: `CODE | NAME`, grade on the right.

    `tint_f` = a fail (F, or any grade the portal released as non-Pass) gets
    the approved faint red; `tint_o` = O gets the soft blue. Pending rows
    carry grade "-" and no hue at all — the grade letter itself always renders,
    so neither tint is ever the only cue.
    """
    g = str(grade or "").strip()
    return {
        "code": str(code or "").strip(),
        "title": _title_case(name or ""),
        "grade": g,
        "completed": g in GRADE_POINTS,
        "tint_o": g == "O",
        "tint_f": g == "F",
    }


def _semesters_view(exam):
    """Per-semester dropdown rows for the CGPA hero, newest first.

    Each row: `Semester N` left, `DEC 2025` right, SGPA + released credits in
    the summary line; expanded shows that semester's subject rows, then the
    provisional / revaluation envelopes when their payload is non-empty.
    The semester number comes from the portal; rows that carry none fall
    back to their chronological rank (1 = oldest).
    """
    buckets, order = {}, []
    for r in exam or []:
        if not isinstance(r, dict):
            continue
        label = str(r.get("monthyear") or "").strip() or "-"
        b = buckets.get(label)
        if b is None:
            b = buckets[label] = {"label": label, "rows": []}
            order.append(b)
        b["rows"].append(r)
    order.sort(key=lambda b: _monthkey(b["label"]))       # oldest first
    ranked = []
    for i, b in enumerate(order, 1):
        sid = max((_int(r.get("semester")) for r in b["rows"]
                   if isinstance(r, dict)), default=0)
        val, credits = _gpa(b["rows"])
        ranked.append({
            "sem": sid or i,
            "label": b["label"],
            "sgpa": val or "-",
            "credits": credits,
            "rows": [_subject_row(r.get("subjectcode"), r.get("subjectdesc"), r.get("grade"))
                     for r in b["rows"]],
            "provisional": [], "revaluation": [],
        })
    ranked.reverse()                                      # newest first
    return ranked


def _credits_view(status_rows):
    """Per-category meters: `acq/req` + the §4.15 bar.

    Fill is derived HERE (route-side, never in the template): neutral
    progress always, success fill ONLY at >=100% complete — deliberately no
    attendance-threshold semantics (DESIGN §2.6 stays on the attendance tab;
    a completed credit category is a fact, not a health state).
    """
    cats = []
    for r in status_rows or []:
        if not isinstance(r, dict):
            continue
        req, acq = _int(r.get("requiredcredits")), _int(r.get("acquiredcredits"))
        pct = min(100.0, (100.0 * acq / req) if req > 0 else (100.0 if acq else 0.0))
        done = req > 0 and acq >= req
        cats.append({
            "name": html.unescape(str(r.get("subjectcategory") or "")).strip(),
            "req": req, "acq": acq, "pct": round(pct, 1), "done": done,
            "fill": f"width:{pct:.1f}%" + (";background:var(--color-success)" if done else ""),
        })
    if not cats:
        return None
    return {"cats": cats,
            "overall": {"req": sum(c["req"] for c in cats),
                        "acq": sum(c["acq"] for c in cats)}}


def _courses_view(status, subject_rows):
    """ONE combined card: a dropdown per degree category, summary = the
    category's `acq/req` credits + its §4.15 meter, expanded = that
    category's subjects — pending FIRST, completed LAST (navya's ordering).

    Categories and their credit figures come from course-status; subjects
    are matched to a category by name (both ops key on subjectcategory).
    """
    if not status:
        return None
    by_cat = {}
    for r in subject_rows or []:
        if not isinstance(r, dict):
            continue
        cat = html.unescape(str(r.get("subjectcategory") or "")).strip() or "Other"
        month = str(r.get("completedmonthandyear") or "").strip()
        row = _subject_row(r.get("subjectcode"), r.get("description"), r.get("grade"))
        row["month"] = "" if month == "-" else month
        row["attempts"] = _int(r.get("noofattempts")) if row["completed"] else 0
        by_cat.setdefault(cat, []).append(row)
    cats = []
    for c in status["cats"]:
        rows = by_cat.pop(c["name"], [])
        pending = [r for r in rows if not r["completed"]]
        done = [r for r in rows if r["completed"]]
        cats.append({**c, "pending": pending, "completed": done,
                     "n": len(rows), "n_pending": len(pending)})
    for cat, rows in by_cat.items():        # subjects with no credit row
        pending = [r for r in rows if not r["completed"]]
        done = [r for r in rows if r["completed"]]
        cats.append({"name": cat, "req": 0, "acq": 0, "pct": 0.0, "done": False,
                     "fill": "width:0%", "pending": pending, "completed": done,
                     "n": len(rows), "n_pending": len(pending)})
    if not cats:
        return None
    pending = sum(c["n_pending"] for c in cats)
    total = sum(c["n"] for c in cats)
    return {"cats": cats, "overall": status["overall"],
            "pending": pending, "total": total}


def academics_view(scope_row, features):
    """The whole tab or None (zero footprint). `scope_row` = the
    users.scope_json row from db.user_scope_data(); `features` = the enabled
    SCOPE feature slugs."""
    if "academics" not in features:
        return None
    blob = {}
    if scope_row is not None:
        try:
            blob = json.loads(scope_row["scope_json"] or "{}")
        except (TypeError, ValueError):
            blob = {}
    if not isinstance(blob, dict) or not any(op in blob for op in FEATURES["academics"]):
        return None

    def data(op):
        cell = blob.get(op)
        return cell.get("data") if isinstance(cell, dict) else None

    exam = data("getExamDetails") or []
    cgpa_val, cgpa_cr = _gpa(exam)
    credits = _credits_view(data("getSubCategoryWiseStatus"))
    sems = _semesters_view(exam)
    prov = _envelope_rows(data("getStudentExamProvisionalResult"))
    reval = _envelope_rows(data("getStudentExamRevaluationResult"))
    if sems and (prov or reval):
        # season payloads carry the newest semester's monthyear most often;
        # attach them there and let the template render them only when set.
        sems[0]["provisional"], sems[0]["revaluation"] = prov, reval
    combined = _courses_view(credits, data("getProgramSubCategoryWiseSubjects"))
    view = {
        "cgpa": None,
        "courses": combined,
    }
    if cgpa_val:
        view["cgpa"] = {
            "value": cgpa_val,
            "credits_disp": (f"{credits['overall']['acq']}/{credits['overall']['req']} credits earned"
                             if credits else f"{cgpa_cr} credits released"),
            "sems": sems,
        }
    if not any([view["cgpa"], view["courses"]]):
        return None   # op keys present but all empty -> still no tab
    return view
