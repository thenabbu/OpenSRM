#!/usr/bin/env python3
"""Unit: the timetable NOW-hero must carry the slot's attendance join (_att) —
the renderer's 22px sig block reads hero_status['_att']; a dict-hop drop
rendered the hero statless. Regression guard, no server."""
import os
import sys
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="tth-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import app.app as A  # noqa: E402
from app.app import _now_next_from_slots  # noqa: E402
from datetime import datetime as _dt  # noqa: E402


class _Midday(_dt):
    """Pin the clock. This suite is about the attendance join surviving the
    dict hop, not about what time it is when CI runs: the slots below span
    00:00-23:59 and `end` is EXCLUSIVE, so the last minute of every day
    (now_mins == 1439) fell outside the slot and CI at 23:59:45 saw `done`
    instead of `current` — a one-minute-per-day red."""

    @classmethod
    def now(cls, tz=None):
        return _dt(2026, 11, 2, 12, 0, 0)


A.datetime = _Midday

fails = []

def check(name, cond, extra=""):
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        fails.append(name)

# slot spanning now -> kind=current; _att must survive the hop
h = _now_next_from_slots("Tuesday", [
    {"type": "class", "start": "00:00", "end": "23:59",
     "code": "21CSC102T", "name": "OBJECT ORIENTED PROGRAMMING", "location": "",
     "_att": {"code": "21CSC102T", "pct": 82, "cls": "ok", "num": 4}}])
check("kind is current", h and h.get("kind") == "current", str(h))
check("_att rides along", h.get("_att", {}).get("num") == 4, str(h.get("_att")))
# custom/never-joined slot: hero must still render without _att
h2 = _now_next_from_slots("Tuesday", [
    {"type": "class", "start": "00:00", "end": "23:59",
     "code": "X", "name": "N", "location": ""}])
check("missing _att tolerated", h2 and h2.get("kind") == "current" and "_att" not in h2, str(h2))

print("FAILED:", fails) if fails else print("hero sig passthrough: OK")
sys.exit(1 if fails else 0)
