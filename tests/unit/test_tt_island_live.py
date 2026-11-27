#!/usr/bin/env python3
"""Unit: the timetable's live marker is ONE running period, on today.

The panels hydrate from props(), so `live` is what the student sees after the
island takes over. api_timetable used to hand props() today=None, so `d ==
today` could only be false and NOTHING was marked live while the server markup
had its own idea — a page whose two paints disagree reads as "every period is
highlighted". This pins the two hosts to the same clock.
"""
import os
import sys
import tempfile
from datetime import datetime as _dt

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ttil-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import app.app as A  # noqa: E402
from app.static_data import SLOTS  # noqa: E402
from app.views.timetable_island import props  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        fails.append(name)


DAY = "Monday"   # 2026-11-02 is a Monday
slots = {DAY: {s["period"]: {"code": "21CSS201T", "name": "Comp Org", "location": ""}
               for s in SLOTS if s["type"] == "class"}}


def slow_clock(hh, mm):
    """Pin app.datetime to Monday 2026-11-02 HH:MM. The facade holds the real
    class, so an instance would leave `.now()` on the wall clock — override
    now() (same shape as test_tt_hero's _Midday)."""
    class _Fixed(_dt):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 2, hh, mm)
    A.datetime = _Fixed
    return _dt


def lives(payload):
    return [r for d in payload["days"] for r in d["rows"]
            if r["kind"] == "class" and r["live"]]


# the bug in one line: today=None must mark NOTHING live (it used to be handed
# to every row, and a prop that is always equal is a highlight on every row)
check("today=None marks nothing live", lives(props(slots, SLOTS, None)) == [])

real = slow_clock(12, 30)                     # inside period 4, 12:10-13:00
try:
    p = props(slots, SLOTS, A.datetime.now().strftime("%A"))
finally:
    A.datetime = real
check("today marks today's rows", len(lives(p)) == len(slots[DAY]), lives(p))
check("nothing live off today",
      not [r for d in p["days"] if d["day"] != DAY
           for r in d["rows"] if r["kind"] == "class" and r["live"]])
check("default_day is today", p["default_day"] == DAY)

if fails:
    print(f"\nFAILED: {len(fails)}")
    sys.exit(1)
print("\nALL PASS")
