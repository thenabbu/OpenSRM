"""Shared portal-HTML/key helpers (moved from app.app, PR #refactor-extract-parsers).

MONTHS, _cells, ROMAN and the group/class key derivations are consumed by the
parsers below AND by app.app / http_scraper — every name is re-exported from
app.app so existing imports keep working.
"""

import logging

log = logging.getLogger("opensrm")  # app.app's own logger object (setup_logging configures it)

import re

MONTHS = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}

# ── HTML parsing ───────────────────────────────────────────────────
def _cells(row_html):
    return [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]

ROMAN = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10}

def _semester_int(semester_str):
    """Convert 'III SEMESTER' -> 3. Empty/None -> 0: split()[0] raised
    IndexError (probe-verified) and 500'd every page calling _group_key."""
    parts = (semester_str or "").split()
    return ROMAN.get(parts[0].strip(), 0) if parts else 0

def _program_short(program):
    """Portal Program -> stable branch id: drop the bracketed suffix and the
    'B.Tech.-'/'with specialization in' boilerplate, so the same programme
    always maps to one string ('...Cloud Computing[UG - FT - ACADEMIC]' ->
    'Computer Science and Engineering Cloud Computing')."""
    short = re.sub(r"\[.*?\]", "", program).strip()
    short = re.sub(r"B\.Tech\.\s*-\s*", "", short).strip()
    short = re.sub(r"with specialization in\s*", "", short).strip()
    return short.replace(",", "")

def _group_key(personal):
    """Extract timetable group from personal details dict."""
    program = re.sub(r"\[.*?\]", "", personal.get("Program", "")).strip()
    batch = personal.get("Batch", "")
    semester = _semester_int(personal.get("Semester", ""))
    section = personal.get("Section", "")
    if not all([program, batch, semester, section]):
        return None
    return f"{_program_short(program)}_{batch}_{semester}_{section}"

def _class_key(personal, netid):
    """Class context for component tags: year|branch|section — deliberately no
    semester, because a teacher's components belong to the whole class every
    term (one student's confirmation then applies to the whole class).
    ponytail: a profile missing any field falls back to a per-student key
    instead of a shared '?' bucket, so an incomplete profile can never leak a
    tag into another class."""
    ctx = [personal.get("Batch", ""), _program_short(personal.get("Program", "")),
           personal.get("Section", "")]
    return "|".join(ctx if all(ctx) else [f"net:{netid}"])
