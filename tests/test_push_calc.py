"""Pure due-calculation spec (no I/O): window edges, block collapsing,
rooms, timezone, idempotency/catch-up, TTL, message text."""
import os, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="osrm-push-calc-"))

from app.push_calc import IST, MAX_ATTEMPTS, Sub, blocks_for_day, due_reminders

fails = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)

MON = datetime(2026, 10, 5).date()          # a Monday
def at(h, m, s=0, tz=IST):
    return datetime(2026, 10, 5, h, m, s, tzinfo=tz)

OS = {"code": "21CSC202J", "name": "Operating Systems", "location": ""}
LAB = {"code": "21CSC202J", "name": "Operating Systems - Lab", "location": "Lab C-6/7"}
DSA = {"code": "21CSC201J", "name": "Data Structures and Algorithms", "location": ""}
NMA = {"code": "21MAB206T", "name": "Numerical Methods and Analysis", "location": ""}

# ── block collapsing ──────────────────────────────────────────────────
day = {1: dict(OS), 2: dict(OS), 3: dict(DSA), 4: dict(NMA), 5: dict(NMA)}
# P4→P5 crosses lunch, P2→P3 crosses break; P4+P5 same code+name
b = blocks_for_day("Monday", day, MON)
check("P1+P2 merge into one block", len(b) == 4 and b[0].periods == (1, 2), str([(x.code, x.periods) for x in b]))
check("block start/end span the run", b[0].start.strftime("%H:%M") == "09:30" and b[0].end.strftime("%H:%M") == "11:10", f"{b[0].start}-{b[0].end}")
check("lunch never merged (P4,P5 -> two blocks)", [x.periods for x in b[1:]] == [(3,), (4,), (5,)], str([x.periods for x in b]))

day2 = {2: dict(OS), 3: dict(OS)}           # same code+name across the 11:10 break
b2 = blocks_for_day("Monday", day2, MON)
check("break never merged (P2,P3 -> two blocks)", len(b2) == 2, str([x.periods for x in b2]))

day3 = {1: dict(OS), 2: dict(LAB)}          # same code, lecture then lab
b3 = blocks_for_day("Monday", day3, MON)
check("same code different name not merged", len(b3) == 2, str([x.name for x in b3]))

day4 = {1: dict(LAB), 2: dict(LAB)}         # the real live lab shape
b4 = blocks_for_day("Monday", day4, MON)
check("lab run merged with room", len(b4) == 1 and b4[0].location == "Lab C-6/7", str(b4[0].location if b4 else None))
day5 = {1: dict(OS), 2: dict(OS, location="TP-401")}
b5 = blocks_for_day("Monday", day5, MON)
check("room taken from run even if on 2nd period", b5[0].location == "TP-401", b5[0].location)
day6 = {1: dict(OS), 3: dict(OS)}           # gap (P2 empty)
check("gap not merged", len(blocks_for_day("Monday", day6, MON)) == 2, "")

# ── due window edges ──────────────────────────────────────────────────
TT = {"G": {"Monday": day}}
sub = Sub(id=1, netid="aa1111", group_key="G", lead_minutes=10)
def due(now, sent=None, subs=(sub,), tt=TT):
    return due_reminders(now, subs, tt, sent or {})

d = due(at(9, 20))
check("due exactly at start-lead", len(d) == 1 and d[0].block.start.strftime("%H:%M") == "09:30", str(len(d)))
check("not due 1s before start-lead", len(due(at(9, 19, 59))) == 0, "")
check("due 1s before start", len(due(at(9, 29, 59))) == 1, "")
check("never due at/after start", len(due(at(9, 30))) == 0 and len(due(at(9, 30, 1))) == 0, "")
check("catch-up: 75s past the lead mark still due", len(due(at(9, 21, 15))) == 1, "")
check("TTL = real seconds to start", d[0].ttl == 600, str(d[0].ttl))

sat = datetime(2026, 10, 10, 9, 25, tzinfo=IST)   # Saturday
check("weekend: no reminders", len(due(sat)) == 0, str(sat))
check("no timetable -> no reminders", len(due(at(9, 25), tt={})) == 0, "")
check("unknown group_key -> no reminders", len(due(at(9, 25), tt={"OTHER": TT["G"]})) == 0, "")

# ── timezone: same instant expressed in UTC ──────────────────────────
d_utc = due(datetime(2026, 10, 5, 5, 45, tzinfo=timezone.utc))   # = 11:15 IST
check("UTC 'now' computes IST windows", any(r.block.start.strftime("%H:%M") == "11:20" for r in d_utc), str([r.block.start.strftime("%H:%M") for r in d_utc]))
d_naive = due(datetime(2026, 10, 5, 9, 25))       # naive == read as IST
check("naive now read as IST", len(d_naive) >= 1 and d_naive[0].block.start.strftime("%H:%M") == "09:30", str(len(d_naive)))

# ── lead time per subscription ───────────────────────────────────────
sub5 = Sub(id=2, netid="bb2222", group_key="G", lead_minutes=5)
d_lead = due(at(9, 20), subs=(sub, sub5))
check("lead applies per subscription (10-min due, 5-min not)", sorted(r.sub.id for r in d_lead) == [1], str([(r.sub.id, r.block.start.strftime('%H:%M')) for r in d_lead]))

# ── idempotency / sent log / retries ─────────────────────────────────
KEY = (1, "2026-10-05", at(9, 30).timestamp().__int__(), "21CSC202J")
check("logged as sent -> no reminder", len(due(at(9, 25), sent={KEY: ("sent", 1, 7)})) == 0, "")
check("orphaned -> no retry (at-most-once)", len(due(at(9, 25), sent={KEY: ("orphaned", 1, 7)})) == 0, "")
check("skipped -> no retry", len(due(at(9, 25), sent={KEY: ("skipped", 1, 7)})) == 0, "")
r_fail = due(at(9, 25), sent={KEY: ("failed", 1, 7)})
check("failed under cap -> retry with row id", len(r_fail) == 1 and r_fail[0].retry and r_fail[0].row_id == 7, str(r_fail[:1]))
check("attempts exhausted -> no retry", len(due(at(9, 25), sent={KEY: ("failed", MAX_ATTEMPTS, 7)})) == 0, "")
check("retry still never after start", len(due(at(9, 30), sent={KEY: ("failed", 1, 7)})) == 0, "")
day_swap = {1: dict(OS, code="21CSC301T"), 2: dict(OS, code="21CSC301T")}   # slot swapped OS -> DBMS
r_swap = due(at(9, 25), sent={KEY: ("sent", 1, 7)}, tt={"G": {"Monday": day_swap}})
check("subject change -> new key -> due again", len(r_swap) == 1 and r_swap[0].block.code == "21CSC301T", str([r.block.code for r in r_swap]))

# ── message text ──────────────────────────────────────────────────────
m = d[0].message(at(9, 25))
check("title format", m["title"] == "Operating Systems · starts 09:30", m["title"])
check("body has real 'in N min' (not the lead)", m["body"].startswith("in 5 min · 09:30–11:10"), m["body"])
check("no room -> no room line, no placeholder", "Lab" not in m["body"] and "Room not set" not in m["body"], m["body"])
m2 = due(at(11, 15))[0].message(at(11, 15)) if due(at(11, 15)) else None
day_lab = {1: dict(LAB), 2: dict(LAB)}
m3 = due(at(9, 25), tt={"G": {"Monday": day_lab}})[0].message(at(9, 25))
check("room printed when known", m3["body"].endswith(" · Lab C-6/7") and m3["title"].startswith("Operating Systems - Lab"), m3["body"])
check("tag is per block", m["tag"] == "cls-2026-10-05-" + str(int(at(9, 30).timestamp())) + "-21CSC202J", m["tag"])

print("ok  push calc" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
