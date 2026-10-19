"""Academics tab view model — released results, derived CGPA/SGPA, credit
progress, subject completion grid (SCOPE ops read from users.scope_json).

Reads the stored cold blob only: no network, no new columns, no new
endpoints. Every section builds independently so the template can self-hide
each card (DESIGN.md §4.12 empty = hidden), and academics_view() returns
None when the feature is off, the row holds none of the academics ops, or
every section is empty — the tab then has ZERO footprint (no navbar item,
per the SCOPE toggle contract).

CGPA honesty contract (mission): credit-weighted over RELEASED results,
2 decimals with ROUND_HALF_UP (Python round() is banker's), labelled
"CGPA (est.)" — the grade -> point scale is not officially published by
SRM, so it is never rendered as an official figure.
"""
import html
import json
import time
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


def _sgpa_rows(rows):
    """Per-semester SGPA: same math bucketed by monthyear, newest first."""
    buckets = {}
    for r in rows or []:
        if isinstance(r, dict):
            buckets.setdefault(str(r.get("monthyear") or "").strip() or "-", []).append(r)
    out = []
    for label, rs in buckets.items():
        val, _credits = _gpa(rs)
        if val:
            out.append({"label": label, "value": val})
    out.sort(key=lambda s: _monthkey(s["label"]), reverse=True)
    return out


def _results_view(rows):
    """Released results grouped by monthyear (semester-grouped rows),
    newest semester first. Rows: mono code, title-cased name, grade chip,
    failed flag (F / non-Pass renders as error TEXT, never a colored chip)."""
    groups, order = {}, []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        label = str(r.get("monthyear") or "").strip() or "-"
        g = groups.get(label)
        if g is None:
            g = {"label": label,
                 "semester": str(r.get("semester") or "").strip(),
                 "rows": []}
            groups[label] = g
            order.append(g)
        g["rows"].append({
            "code": str(r.get("subjectcode") or "").strip(),
            "title": _title_case(r.get("subjectdesc") or ""),
            "grade": str(r.get("grade") or "").strip(),
            "failed": str(r.get("result") or "").strip().lower() != "pass",
        })
    order.sort(key=lambda g: _monthkey(g["label"]), reverse=True)
    return order


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


def _credits_view(status_rows, sem_rows):
    """8 category meters + overall + the latest-semester summary line.

    Fill/labels are derived HERE (route-side, never in the template):
    NEUTRAL progress fill always, success fill ONLY at >=100% complete —
    deliberately no attendance-threshold semantics (DESIGN §2.6 stays on the
    attendance tab; a completed credit category is a fact, not a health
    state). Every number sits next to its bar, so the hue is never the cue.
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
    by_sem = {}
    for r in sem_rows or []:
        if not isinstance(r, dict):
            continue
        sid = _int(r.get("semesterid"))
        if sid <= 0:
            continue
        acc = by_sem.setdefault(sid, {"id": sid, "req": 0, "acq": 0})
        acc["req"] += _int(r.get("requiredcredits"))
        acc["acq"] += _int(r.get("acquiredcredits"))
    # latest semester = the newest one that actually EARNED credits;
    # course-status-sem also lists future semesters at 0/N, and reporting
    # the newest-planned as "latest" would print a meaningless 0/15.
    latest = None
    if by_sem:
        latest = max((s for s in by_sem.values() if s["acq"] > 0) or by_sem.values(),
                     key=lambda s: s["id"])
    return {"cats": cats,
            "overall": {"req": sum(c["req"] for c in cats),
                        "acq": sum(c["acq"] for c in cats)},
            "latest": latest}


def _subjects_view(rows):
    """63-row completion grid grouped by category (portal order preserved,
    inside one internal scroll like the teachers list). Completed rows carry
    grade + month (+ a quiet 'N attempts' note when attempts > 1); pending
    rows keep the portal's dim '-' grade (grade '-' = not yet completed)."""
    groups, idx = [], {}
    done = total = 0
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        total += 1
        cat = html.unescape(str(r.get("subjectcategory") or "")).strip() or "Other"
        g = idx.get(cat)
        if g is None:
            g = {"name": cat, "rows": []}
            idx[cat] = g
            groups.append(g)
        grade = str(r.get("grade") or "").strip()
        completed = grade in GRADE_POINTS
        done += completed
        month = str(r.get("completedmonthandyear") or "").strip()
        attempts = _int(r.get("noofattempts"))
        g["rows"].append({
            "code": str(r.get("subjectcode") or "").strip(),
            "title": _title_case(r.get("description") or ""),
            "grade": grade, "completed": completed, "failed": completed and grade == "F",
            "month": "" if month == "-" else month,
            "attempts": attempts if attempts > 1 else 0,
        })
    if not groups:
        return None
    return {"groups": groups, "done": done, "total": total}


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
    results = _results_view(exam)
    cgpa_val, cgpa_cr = _gpa(exam)
    credits = _credits_view(data("getSubCategoryWiseStatus"),
                            data("getSubCategorySemesterWiseStatus"))
    view = {
        "results": results,
        "n_results": sum(len(g["rows"]) for g in results),
        "cgpa": None,
        "credits": credits,
        "subjects": _subjects_view(data("getProgramSubCategoryWiseSubjects")),
        "provisional": _envelope_rows(data("getStudentExamProvisionalResult")),
        "revaluation": _envelope_rows(data("getStudentExamRevaluationResult")),
        "fetched_at": _int(scope_row["scope_fetched_at"] if scope_row else 0),
        "fetched_disp": "",
    }
    if cgpa_val:
        # the hero's credit line comes from course-status (earned/required);
        # with only exam-details on hand we say what was actually released.
        disp = (f"{credits['overall']['acq']}/{credits['overall']['req']} credits earned"
                if credits else f"{cgpa_cr} credits released")
        view["cgpa"] = {"value": cgpa_val, "credits_disp": disp,
                        "sems": _sgpa_rows(exam)}
    if view["fetched_at"]:
        view["fetched_disp"] = time.strftime("%d %b %Y %H:%M",
                                             time.localtime(view["fetched_at"]))
    if not any([view["results"], view["cgpa"], view["credits"], view["subjects"],
                view["provisional"], view["revaluation"]]):
        return None   # op keys present but all empty -> still no tab
    return view
