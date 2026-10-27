"""SCOPE profile enrichment (feature slug `profile`) — one route-side join for
the dashboard: Settings -> Personal details.

Contract rules baked in here:
  gate-first — feature off (or no stored scope data) hands back today's inputs
    untouched, so the template renders exactly what it rendered before;
  portal first — the portal's own values (personal_details_json) always win;
    scope only fills gaps, never overwrites, and scope-sourced rows are
    dropped when empty (advisors are empty on this campus);
  nothing new is stored — the foundation's users.scope_json already holds it.
"""
from app.scope.ops import enabled_features

# Scope field -> personal-details display label (the template's group keys).
# Program/Section/Batch intentionally map onto the portal's own labels so the
# portal value wins and scope only fills the gap — the timetable group key is
# derived from the portal's Program format and must never see a scope string.
FIELDS = {
    "father": "Father Name",
    "mother": "Mother Name",
    "dob": "Date of Birth",
    "admitteddate": "Admitted On",
    "address": "Address",
    "program": "Program (Full)",
    "universityname": "University",
    "sectiondesc": "Section",
    "batch": "Batch",
    "facultyadvisor": "Faculty Advisor",
    "academicadvisor": "Academic Advisor",
}
# render-if-present: "" and the API's "-" placeholder never render a row.
_EMPTY = ("", "-")


def _on():
    return "profile" in enabled_features()


def scope_profile(scope_json, enabled=None):
    """The getPersonalDetails payload as a plain dict.

    Accepts every shape the sync can hold: the fixture's bare top-level dict,
    the per-op {"data": ..., "ts": ...} wrapper, and a {Status, Message, Data}
    envelope inside either of them (same defensive unwrap as the campus
    contract). Anything else (feature off, corrupt, wrong type) -> {}."""
    if enabled is None:
        enabled = _on()
    if not enabled or not isinstance(scope_json, dict):
        return {}
    payload = scope_json.get("getPersonalDetails")
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]           # sync stores {"data": ..., "ts": ...}
    if isinstance(payload, dict) and "Data" in payload:
        payload = payload["Data"]           # {Status, Message, Data} envelope
    return payload if isinstance(payload, dict) else {}


def merge_personal(personal, fields):
    """personal_details_json + scope fields: portal value wins, scope fills
    only gaps, empty/placeholder scope values dropped (a missing advisor is
    an absent row, never an empty one). Returns a new dict."""
    out = dict(personal or {})
    for key, label in FIELDS.items():
        v = fields.get(key)
        if not isinstance(v, str):
            continue
        v = v.strip()
        if v in _EMPTY:
            continue
        current = out.get(label)
        if not (isinstance(current, str) and current.strip()):
            out[label] = v
    return out
