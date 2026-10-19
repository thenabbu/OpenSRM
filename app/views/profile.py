"""SCOPE profile enrichment (feature slug `profile`) — three route-side joins
for the dashboard: avatar photo source, Settings personal-details fields, and
the profile widget's one-liner.

Contract rules baked in here:
  gate-first — feature off (or no stored scope data) every entry point hands
    back today's inputs untouched, so the templates render exactly what they
    rendered before;
  portal first — the portal's own values (personal_details_json, photo_b64)
    always win; scope only fills gaps, never overwrites, and scope-sourced
    rows are dropped when empty (advisors are empty on this campus);
  nothing new is stored — the foundation's users.scope_json already holds it.
"""
import base64
import binascii
import logging
import re

from app.scope.ops import enabled_features

log = logging.getLogger("opensrm.profile")

# ponytail: skip rendering a photo larger than this decoded (memory/display
# sanity, the fixture's photo is ~14KB); upgrade path = downscale on sync,
# then raise the cap.
MAX_PHOTO_BYTES = 300 * 1024

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

_PROGRAM_MAX = 30  # plain-string fallback when no degree token exists


def _program_part(program):
    """Degree-level token for the widget's one-liner: 'B.Tech.-Computer
    Science and Engineering...' -> 'B.Tech...' so program + semester +
    section ALL stay visible on one row at every widget width (the branch
    lives in Settings; the title attr keeps the full string). Bracketed
    portal form '... [B.Tech]' -> same token; no token -> capped string."""
    m = re.match(r"([BM]\.Tech)", program, re.I)
    if not m:
        m = re.search(r"\[([^\[\]]{1,24})\]", program)
    if m:
        token = m.group(1).strip()
        return token + ("…" if len(program) > len(token) else "")
    return program[:_PROGRAM_MAX].rstrip() + "…" if len(program) > _PROGRAM_MAX else program


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


def oneliner(fields, personal, enabled=None):
    """`<program> · <semester> · Section <x>` for the profile widget — scope
    fields first, portal's existing values as the fallback, "" when neither
    has anything (or the feature is off: the widget renders no line at all,
    exactly as today)."""
    if enabled is None:
        enabled = _on()
    if not enabled:
        return ""
    personal = personal or {}

    def first(*vals):
        for v in vals:
            if isinstance(v, str):
                v = v.strip()
                if v and v not in _EMPTY:
                    return v
        return ""

    program = _program_part(first(fields.get("program"), personal.get("Program")))
    semester = first(fields.get("semester"), personal.get("Semester"))
    section = first(fields.get("sectiondesc"), personal.get("Section"))
    parts = [p for p in (program, semester,
                         "Section " + section if section else "") if p]
    return " · ".join(parts)


def photo_uri(row, fields, enabled=None):
    """data:image/jpeg URI for the profile widget's avatar.

    Order: the portal's stored photo (users.photo_b64 on the row) first,
    then scope's inline getPersonalDetails.studentphoto - the blobatar SVG
    (today's rendering) stays the fallback whenever both are empty or
    unusable. A candidate must base64-decode (whitespace tolerated) to a
    JPEG (\\xff\\xd8 magic) within the size cap; anything else is skipped
    with a debug line, never raised. Feature off -> "" (no scope-sourced
    change to the widget at all).

    Takes the dashboard row (dict/Row/None), not a raw column, so the only
    mention of photo_b64 outside db.py stays inside this module."""
    if enabled is None:
        enabled = _on()
    if not enabled:
        return ""
    portal = ""
    if row is not None:
        try:
            portal = row["photo_b64"]
        except (IndexError, KeyError, TypeError):
            portal = ""
    uri = _jpeg_uri(portal)
    if uri:
        return uri
    return _jpeg_uri(fields.get("studentphoto"))


def _jpeg_uri(b64):
    if not isinstance(b64, str) or not b64.strip():
        return ""
    raw = b64.strip()
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    raw = "".join(raw.split())              # tolerate line-wrapped base64
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        log.debug("profile.photo: base64 decode failed, skipping render")
        return ""
    if not data.startswith(b"\xff\xd8"):
        log.debug("profile.photo: not a JPEG (magic bytes missing), skipping render")
        return ""
    if len(data) > MAX_PHOTO_BYTES:
        # ponytail: skip render >300KB decoded; upgrade path = resize on sync.
        log.debug("profile.photo: %d bytes exceeds %d cap, skipping render",
                  len(data), MAX_PHOTO_BYTES)
        return ""
    return "data:image/jpeg;base64," + raw
