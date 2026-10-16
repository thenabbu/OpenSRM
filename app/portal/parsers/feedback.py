"""Feedback fill-plan builder (moved from app.app; re-exported from app.app)."""

def _fb_plan(faculty_map):
    """Stored map -> [{subject, teacher, staff_id, comment}] — the exact rows the
    fill endpoint submits. EVERY listed teacher gets their own row: the portal
    takes one form per teacher within a subject, so a subject with 2 staff
    becomes 2 rows.

    SINGLE builder: the modal preview AND POST /api/feedback/fill both call
    this, so what the student saw IS what gets sent. {} / unknown-only -> [].
    """
    from app.app import _faculty_view  # deferred: app.app imports this module (same cycle rule as push_calc)
    plan = []
    for r in _faculty_view(faculty_map, []):
        for sid, tname, kind in r["staff"]:
            plan.append({"subject": r["name"],
                         "teacher": f"{tname} ({kind})" if kind else tname,
                         "staff_id": sid,
                         "comment": "none"})
    return plan
