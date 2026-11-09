"""Settings panel as island props (P6.8) — server side.

app/templates/settings.html:189-236 paints the `personal` details collapse: the
identity header (Student Name / Program) plus the four key groups, each key
listed only when the portal actually returned it. The island re-renders that
block 1:1; every string arrives already formatted and ordered, and the count
badge is the number the server counted (not a recount the client could skew).
"""
import json

from markupsafe import Markup

# settings.html:180 — the four groups and their keys, in render order.
GROUPS = [
    ("Academic", ["Register No.", "Institution", "Batch", "Semester", "Section", "ABC NUMBER",
                  "University", "Program (Full)", "Faculty Advisor", "Academic Advisor"]),
    ("Personal", ["Date of Birth", "Gender", "Religion", "Nationality", "Blood Group",
                  "Admitted On"]),
    ("Family", ["Father Name", "Mother Name", "Parent Contact No.", "Parent Email ID"]),
    ("Contact", ["Address", "Pincode", "District", "State", "Personal Email ID",
                 "Student Mobile No.", "Alternative Student Mobile No."]),
]
WIDE = ("Institution", "Address")   # sm:col-span-2 (settings.html:229)


def props(personal):
    """The payload web/src/panels/settings/contract.ts validates.

    `personal` is the template's `personal` (merge_personal(vm["personal_data"],
    vm["scope_fields"])): a dict, or falsy when the portal returned nothing —
    in which case the template paints the "No personal details available."
    alert and so does the island.
    """
    if not personal:
        return {"personal": None, "count": 0}
    groups, count = [], 0
    for title, keys in GROUPS:
        items = [{"key": k, "value": str(personal[k]), "wide": k in WIDE, "mono": k != "Address"}
                 for k in keys if k in personal]
        count += len(items)
        if items:
            groups.append({"title": title, "items": items})
    count += 1 if personal.get("Student Name") else 0
    count += 1 if personal.get("Program") else 0
    return {"personal": {"name": str(personal.get("Student Name") or ""),
                         "program": str(personal.get("Program") or ""),
                         "groups": groups},
            "count": count}


def block(payload, element_id="island-settings"):
    """The inert JSON block. Same escaping rule as fees_island.block:
    '<' is the only char that can unbalance a <script> block."""
    out = json.dumps(payload, separators=(",", ":"))
    out = out.replace("<", "\\u003c")
    return Markup('<script type="application/json" id="%s">%s</script>' % (element_id, out))
