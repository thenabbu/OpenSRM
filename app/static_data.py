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
