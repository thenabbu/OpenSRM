"""Exam schedule/timetable parsers (moved from app.app; re-exported from app.app)."""

import re
from html import unescape as _hescu

from .common import MONTHS, _cells, log


def parse_exam_schedule(html):
    """ScribeInner.jsp (iden=1, ANY hdnExamMonth/Year — portal doesn't
    validate against the official dropdown) -> end-sem exam rows.

    Structure verified live Sep 27 2026: checkbox td (strips to '') then
    code / description / date / session / type / amount. Empty sessions
    return 'No subject found'.
    """
    if not html or "No subject found" in html:
        return []
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = _cells(row)
        # td[0] is the checkbox cell -> ''; real columns shift by 1
        if len(cells) >= 6 and re.fullmatch(r"\d{2}-\d{2}-\d{4}", cells[3] or ""):
            out.append({"code": cells[1], "name": cells[2], "date": cells[3],
                        "session": cells[4], "type": cells[5]})
    return out


def parse_exam_timetable(html):
    """StudentExamTimeTable.jsp (iden=126, official 'Exam Time Table' page)
    -> end-sem exam rows. Verified live Oct 7 2026 (the ONLY published source
    with exact clock times).

    Columns: Sem/Year/Trim | Subject Code | Subject Description | Date & Session
    | Hall No. | Seat No. (+ a month banner) — cells at the Date & Session
    position hold `DD-MMM-YYYY AN  (02:00-05:00)`; subjects without a slot yet
    render `- -`. Empty page = 'No subjects found'.

    Column positions are resolved from the header row so the portal can
    REORDER or INSERT columns (hall allotment day may add fields) without
    breaking known fields; unknown labels are ignored. Falls back to the
    positional shape above when no header row exists.

    Returns rows, [] (clean empty — 'No subjects found'), or None (table
    present but unparseable: label/column drift or blanked rows — callers
    MUST preserve stored rows, never treat as empty).
    """
    if not html or "No subjects found" in html:
        return []
    # header-driven indexes: label -> column position (known fields only)
    labels = {"subject code": "code", "subject description": "name",
              "date & session": "date", "hall no.": "hall", "seat no.": "seat"}
    idx = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        ths = re.findall(r"<th[^>]*>(.*?)</th>", tr, re.S)
        if len(ths) >= 4:
            for i, th in enumerate(ths):
                lbl = _hescu(re.sub(r"<[^>]+>", "", th)).replace("\xa0", " ").strip().lower()
                if lbl in labels:
                    idx.setdefault(labels[lbl], i)
            break
    got_header = bool(idx)
    pos = {"code": 1, "name": 2, "date": 3, "hall": 4, "seat": 5}  # positional fallback
    # header found but a known label missing -> the column is GONE (do not
    # guess positionally — that would read a neighbour cell as the field)
    def _i(field):
        if field in idx:
            return idx[field]
        return None if got_header else pos[field]

    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = _cells(row)
        i_date, i_code = _i("date"), _i("code")
        need = [i for i in (i_date, i_code, _i("hall"), _i("seat")) if i is not None]
        if not need or len(cells) <= max(need) or i_date is None or i_code is None:
            continue
        ds = cells[i_date] or ""
        dm = re.match(r"(\d{2})-([A-Z]{3})-(\d{4})", ds)
        if not dm or not cells[i_code]:
            continue  # header/banner rows, pending `- -`, blanked cells
        mon = MONTHS.get(dm.group(2), "00")
        tm = re.search(r"\((\d{2}:\d{2})-(\d{2}:\d{2})\)", ds)
        out.append({
            "code": cells[i_code], "name": (cells[_i("name")] or "") if _i("name") is not None else "",
            "date": f"{dm.group(1)}-{mon}-{dm.group(3)}",
            "session": (re.search(r"\b(AN|FN)\b", ds) or [None, ""])[1],
            "slot": f"{tm.group(1)}-{tm.group(2)}" if tm else "",
            "hall": (cells[_i("hall")] or "") if _i("hall") is not None else "",
            "seat": (cells[_i("seat")] or "") if _i("seat") is not None else "",
        })
    if not out and "<table" in html:
        # table present but nothing parsed: label/column drift or blanked rows.
        # NOT a clean empty — callers must preserve stored rows (Oct 4 2026 rule).
        log.debug("exam timetable: table present but 0 dated rows parsed (shape drift?)")
        return None
    return out
