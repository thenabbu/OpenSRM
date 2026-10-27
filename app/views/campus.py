"""Campus tab view model — shape-driven parsers for the SCOPE campus ops.

All four campus cards (placement board, library, hostel+transport,
notifications) read {Status, Message, Data} envelopes that are ALIVE-EMPTY
today (fixtures: Status Error/Success + Data "" + "No data found" message).
Alive-empty is data, never an error: _rows() yields [] and the card renders
nothing — the tab itself hides when every card is empty or disabled.

Payload field sets are unknown until the placement season / first real
sync, so row rendering is a detection heuristic over key names, and every
key it does not consume collapses into the row's <details> — no key is
ever dropped, no KeyError is possible.
"""
import json
import logging
import re
from datetime import datetime

log = logging.getLogger("opensrm.campus")

# ponytail: placement payload unknown until season — field detection
# heuristic; upgrade path = concrete renderer once first real payload lands

# date formats the SCOPE payloads have been seen to use; first that parses wins
_DATE_FMTS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y",
              "%d %b %Y", "%d %B %Y", "%d-%m-%Y %H:%M:%S", "%Y/%m/%d")


def _val(v):
    """A scalar worth showing (empty string / None never reach the UI)."""
    return v is not None and not isinstance(v, (dict, list)) and str(v).strip() != ""


def _fmt(v):
    """Display text for any value; nested payloads land in <details> as JSON."""
    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v, ensure_ascii=False)
        except (TypeError, ValueError):  # pragma: no cover - non-serialisable
            return str(v)
    return str(v).strip()


def rows(payload):
    """Whatever an op stored -> list[dict]; NEVER raises.

    Handles: bare list[dict] · {Status,Message,Data} envelope (Data may be
    "", a JSON string, a list, or a dict) · a lone dict · a JSON string ·
    anything else -> []. The alive-empty envelopes all land on [].
    """
    try:
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if isinstance(payload, dict):
            if any(k in payload for k in ("Status", "Message", "Data")):
                return rows(payload.get("Data"))
            return [payload]
        if isinstance(payload, str):
            text = payload.strip()
            if not text:
                return []
            return rows(json.loads(text))
    except (ValueError, TypeError, RecursionError) as e:
        log.debug("scope.campus unparseable payload type=%s err=%r", type(payload).__name__, e)
    return []


def _take(d, used, pred):
    """First not-yet-used key matching pred -> its value (None when none).
    Predicates see the key LOWER-cased (portal keys arrive camelCase); the
    stored key keeps its original spelling for the extras dump."""
    for k, v in d.items():
        if k not in used and pred(k.lower()) and _val(v):
            used.add(k)
            return v
    return None


def line_row(payload_row, meta_pred=None):
    """One placement / library / notification row: {title, sub, badge, meta,
    extras}. Detection is keyword-ranked over the key names; whatever it
    does not consume goes to `extras`, so every value stays reachable."""
    d = {str(k): v for k, v in dict(payload_row).items()}
    used: set = set()
    # title: ranked keywords — 'title' beats 'job' beats 'book' beats 'name'
    title = None
    for kw in ("title", "job", "book", "name"):
        title = _take(d, used,
                      lambda k, kw=kw: kw in k and not (kw == "job" and ("id" in k or "count" in k)))
        if title is not None:
            break
    if title is None:  # no keyword at all: lead with the first value so the row reads
        title = _take(d, used, lambda k: True)
    sub = _take(d, used, lambda k: "company" in k or "organis" in k or "organiz" in k)
    badge = _take(d, used, lambda k: "status" in k)
    if meta_pred is None:  # date-ish / id-ish / money-ish -> the mono meta line
        meta_pred = lambda k: "date" in k or "time" in k or "stipend" in k or k.endswith("id")
    metas = [k for k in d if k not in used and meta_pred(k.lower()) and _val(d[k])]
    used.update(metas)
    return {
        "title": _fmt(title) if title is not None else "",
        "sub": _fmt(sub) if sub is not None else "",
        "badge": _fmt(badge) if badge is not None else "",
        "meta": " \xb7 ".join(_fmt(d[k]) for k in metas),
        "extras": [(k, _fmt(v)) for k, v in d.items() if k not in used and _val(v)],
    }


def _label(key):
    """`roomNo` / `route_number` -> `Room no` (group labels stay sentence case)."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key)).replace("_", " ").replace("-", " ").strip()
    return s[:1].upper() + s[1:] if s else s


def kv_rows(payload):
    """{label, value} pairs from an envelope, humanised keys, order kept."""
    out = []
    for r in rows(payload):
        for k, v in r.items():
            if _val(v):
                out.append((_label(k), _fmt(v)))
    return out


def _sort_newest(items, raw_rows):
    """Newest-first by the row's date key (unparseable dates keep their
    source order at the end); stability keeps undated payloads untouched."""
    def key(item):
        r = item[1]
        date = next((str(v) for k, v in r.items() if "date" in str(k).lower() and _val(v)), "")
        time_ = next((str(v) for k, v in r.items() if "time" in str(k).lower() and _val(v)), "")
        for fmt in _DATE_FMTS:
            try:
                return (datetime.strptime(date.strip(), fmt), time_.strip())
            except ValueError:
                continue
        return (datetime.min, time_.strip())
    return [it[0] for it in sorted(zip(items, raw_rows), key=key, reverse=True)]


def campus_view(scope, features):
    """{show, cards} for the Campus tab.

    `scope` = the user's scope_json blob ({"<op>": {"data":..., "ts":...}}).
    A card is built ONLY when its feature slug is enabled AND it has rows,
    so every card self-hides and `show` (the tab) hides with the last one.
    """
    scope = scope if isinstance(scope, dict) else {}
    feats = set(features or ())

    def op(name):
        entry = scope.get(name)
        if isinstance(entry, dict) and "data" in entry:  # sync writes {data, ts}
            return entry.get("data")
        return entry

    cards = []
    if "placement" in feats:
        # job board first; resumes fill the card when the board is still empty
        jobs = rows(op("getStudentAllOfferedJobs")) or rows(op("getResumeUploads"))
        if jobs:
            cards.append({"title": "Placement", "rows": [line_row(r) for r in jobs]})
    if "library" in feats:
        books = rows(op("getLibraryTransaction"))
        if books:
            cards.append({"title": "Library", "rows": [line_row(r) for r in books]})
    if "campus" in feats:
        room_groups = []
        for label, name in (("Hostel", "getHostelDetails"), ("Transport", "getTransportDetails")):
            pairs = kv_rows(op(name))
            if pairs:
                room_groups.append({"label": label, "pairs": pairs})
        if room_groups:
            cards.append({"title": "Hostel & transport", "kv": room_groups})
        notes = rows(op("getViewNotificationListJson"))
        if notes:
            # documented field names (MASTER_DOCUMENT §10) ride the default
            # detection: notificationtitle -> title, date+time -> mono meta
            items = [line_row(r, meta_pred=lambda k: "date" in k or "time" in k) for r in notes]
            cards.append({"title": "Notifications", "rows": _sort_newest(items, notes)})
    return {"show": bool(cards), "cards": cards}
