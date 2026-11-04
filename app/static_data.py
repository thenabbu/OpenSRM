"""Declarative app data: timetable slots and the Tools panel.

Extracted from app/app.py (facade pump, cycle A). Nothing here executes — these
are literal tables the views read. Pure data means zero import risk: this module
imports nothing, so it cannot participate in a cycle, and every constant is
re-exported from app.app so existing readers are untouched.

Editing a constant here is the whole change — no logic lives alongside them.
"""
# ── Timetable (SQLite-backed, per-group) ─────────────────────────
SLOTS = [
    {"period": 1, "start": "09:30", "end": "10:20", "type": "class"},
    {"period": 2, "start": "10:20", "end": "11:10", "type": "class"},
    {"period": 0, "start": "11:10", "end": "11:20", "type": "break", "name": "Break"},
    {"period": 3, "start": "11:20", "end": "12:10", "type": "class"},
    {"period": 4, "start": "12:10", "end": "13:00", "type": "class"},
    {"period": 0, "start": "13:00", "end": "14:10", "type": "break", "name": "Lunch"},
    {"period": 5, "start": "14:10", "end": "15:00", "type": "class"},
    {"period": 6, "start": "15:00", "end": "15:50", "type": "class"},
    {"period": 0, "start": "15:50", "end": "16:00", "type": "break", "name": "Break"},
    {"period": 7, "start": "16:00", "end": "16:50", "type": "class"},
]


TIMETABLE_TIME_OFFSETS = {1: 60, 2: 60, 3: 60, 4: 60, 5: 40, 6: 40}

# Where the rendered grid comes from: "official" = portal timetable when the
# group has one (legacy SLOTS as per-group fallback); "manual" = always the
# legacy SLOTS/manual rows — the ops escape hatch if a published official
# timetable is ever wrong beyond a clock offset.
TIMETABLE_SOURCE = "official"


# ── Tools tab (SCOPE-sourced surfaces) ──────────────────────────────
# One entry per SCOPE surface. A row renders ONLY when its feature slug is
# enabled AND its representative op landed a non-empty answer; nothing
# qualifying = empty list = no entry, no tab (zero footprint — the mission
# toggle contract, and the same self-hiding rule the dashboard widgets obey).
# `tab` is the panel that surface's own PR mounts: the row navigates there
# when that panel exists today and renders inert otherwise, so this stays a
# landing surface for the SCOPE rotation instead of a duplicate of it.
TOOLS = [
    # (slug, label, hint, gate op, tab). The tab is where the row sends you: a
    # surface with its own panel names it, one that lives inside an existing
    # tab points there. dash.js marks a row inert when that panel is absent, so
    # a not-yet-mounted surface degrades to a disabled row, never a dead link.
    ("fees", "Fees", "Dues, payments and receipts", "getFeeDetails", "fees"),
    # gates on the RELEASED-results op: the provisional/revaluation endpoints
    # are empty outside their window, so keying the entry on them left Academics
    # hidden even with a full grade history (caught in review).
    ("academics", "Academics", "Results, grades and credits",
     "getExamDetails", "academics"),
    # hourwise renders inside the Attendance tab, not a panel of its own, and
    # its gate op is what the detailed grid needs (rows, not the summary list).
    ("hourwise", "Attendance by hour", "Every period, joined to your timetable",
     "getHourwiseAttendance", "attendance"),
    # profile fills the Personal details section inside Settings.
    ("profile", "Personal details", "Parents, date of birth, address",
     "getStudentPersonalDetails", "settings"),
    ("library", "Library", "Issued books, due dates, fines",
     "getLibraryTransaction", "campus"),
    ("campus", "Hostel & transport", "Room, mess and bus route",
     "getHostelDetails", "campus"),
    ("campus", "Notifications", "Campus notices and circulars",
     "getViewNotificationListJson", "campus"),
    ("placement", "Placement", "Offers, eligibility, registration",
     "getStudentAllOfferedJobs", "campus"),
]
