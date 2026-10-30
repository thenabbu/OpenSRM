"""One runnable check: official portal timetable (formId 10) — parser,
offset grid, save/preserve contracts, editor stamp, push + render wiring.

Fixture: tests/fixtures/timetable_form10.html is the REAL portal response
(structure preserved), with every subject code/title swapped for fabricated
values — no netid, reg-no, or real section identity in the repo.

Offset contract: TIMETABLE_TIME_OFFSETS is derived so official+OFFSET == the
legacy SLOTS grid p1-6 exactly (the portal's clock is wrong by -60/-40 min
against real campus hours; see app.py near SLOTS). Set every offset to 0 in
ONE PR when the portal fixes its clock — test 07 is what proves it.
"""
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="osrm-official-tt-")
# editor POST cases below exercise the TIMETABLE_EDITOR=enabled escape hatch
# (default is archived — no user input on the portal-owned timetable)
os.environ["TIMETABLE_EDITOR"] = "enabled"

import app.app as A
from app.push_calc import blocks_for_day

FIXTURE = Path(__file__).parent.parent / "fixtures" / "timetable_form10.html"

fails = []
total = 0


def check(name, ok, detail=""):
    global total
    total += 1
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


# ── parser: real fixture structure ──────────────────────────────────────
html = FIXTURE.read_text()
tt = A.parse_timetable(html)
check("fixture parses to a dict", isinstance(tt, dict))
check("5 weekday rows", sorted(tt["grid"]) == ["Friday", "Monday", "Thursday", "Tuesday", "Wednesday"],
      str(sorted(tt["grid"])))
check("6 periods", sorted(tt["times"]) == [1, 2, 3, 4, 5, 6], str(sorted(tt["times"])))
check("p1 raw time", tt["times"][1] == "08:30-09:20", str(tt["times"][1]))
check("p5 raw time normalized to 24h", tt["times"][5] == "13:30-14:20", str(tt["times"][5]))
check("p6 raw time normalized to 24h", tt["times"][6] == "14:20-15:10", str(tt["times"][6]))
filled = sum(1 for d in tt["grid"] for p in tt["grid"][d] if tt["grid"][d][p])
check("all 30 day cells filled", filled == 30, str(filled))
check("legend has codes + CL", len(tt["legend"]) == 8 and "CL" in tt["legend"], str(len(tt["legend"])))
check("legend name swapped, not real", tt["legend"].get("21CSC101T") == "SOFTWARE DESIGN PATTERNS",
      str(tt["legend"].get("21CSC101T")))

# parser states: clean-empty vs preserve vs drift
check("no-tt marker -> clean empty []",
      A.parse_timetable('<div class="alert">No Time Table Found..!</div>') == [])
check("youLogin bounce -> None (preserve)", A.parse_timetable("please wait youLogin") is None)
check("empty html -> None (preserve)", A.parse_timetable("") is None)
bad = html.replace("08:30-09:20", "quarter past", 1)
check("bad time cell -> None", A.parse_timetable(bad) is None)
bad = html.replace("08:30-09:20", "10:20-09:20", 1)
check("inverted range -> None", A.parse_timetable(bad) is None)
# drop Friday's row entirely -> partial grid must preserve, not store a 4-day week
fri = [tr for tr in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S)
       if ">Friday</td>" in tr]
no_fri = html
for tr in fri:
    no_fri = no_fri.replace(tr, "", 1)
check("missing day row -> None (partial drift)", A.parse_timetable(no_fri) is None)
# a day row with one cell missing -> None
m = re.search(r"(<tr>\s*<td[^>]*>Monday</td>)(.*?)(</tr>)", html, re.S)
short = html[:m.start()] + m.group(1) + m.group(2).rsplit("<td", 1)[0] + m.group(3) + html[m.end():]
check("short day row -> None", A.parse_timetable(short) is None)
# all 5 day rows present but every cell blank: a published SHELL must not
# wipe stored rows (review #1: contentless grid -> 30 rows deleted)
blank = html
for _d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
    _m = re.search(r"(<tr>\s*<td[^>]*>" + _d + r"</td>)(.*?)(</tr>)", blank, re.S)
    blank = (blank[:_m.start()] + _m.group(1)
             + re.sub(r"<td[^>]*>.*?</td>", "<td></td>", _m.group(2), flags=re.S)
             + _m.group(3) + blank[_m.end():])
check("contentless grid (all cells blank) -> None (preserve)", A.parse_timetable(blank) is None)

# ── grid resolver: official + offset == SLOTS p1-6 (the offset contract) ─
PERSONAL = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
            "Batch": "2025", "Semester": "III SEMESTER", "Section": "A",
            "Student Name": "Test Student"}
GK = A._group_key(PERSONAL)
c = A.db()
c.execute("INSERT OR REPLACE INTO users(netid,password,attendance_json,last_fetch,personal_details_json) "
          "VALUES('tt0001','unused-by-tests','{}',?,?)", (int(time.time()), json.dumps(PERSONAL)))
c.commit(); c.close()

res = {"personal": PERSONAL,
       "courses": [{"code": "21CSC101T", "name": "SOFTWARE DESIGN PATTERNS", "credits": 4}],
       "timetable": tt}

# no official data yet -> legacy grid identity
check("never-published group -> SLOTS", A._tt_grid(GK) is A.SLOTS)
check("unknown group -> SLOTS", A._tt_grid("nope") is A.SLOTS)

A._save_timetable_group("tt0001", res)
c = A.db()
row = c.execute("SELECT official_times, tt_fetched_at FROM timetable_groups WHERE group_key=?", (GK,)).fetchone()
n, n_off = c.execute("SELECT COUNT(*), SUM(source='official') FROM timetable_slots").fetchone()
c.close()
check("group row + official stamp written", row is not None and row[1] > 0, str(row and row[1]))
check("30 official rows", n == 30 and n_off == 30, f"{n}/{n_off}")
check("RAW portal times stored (offsets applied at read only)",
      json.loads(row[0])["1"] == "08:30-09:20" and json.loads(row[0])["6"] == "14:20-15:10",
      row[0][:60])

grid = A._tt_grid(GK)
classes = [s for s in grid if s["type"] == "class"]
breaks = [s for s in grid if s["type"] == "break"]
exp = [(s["period"], s["start"], s["end"]) for s in A.SLOTS if s["type"] == "class" and s["period"] <= 6]
got = [(s["period"], s["start"], s["end"]) for s in classes]
check("07 offset contract: official grid == SLOTS p1-6 exactly", got == exp, str(got))
check("dividers derived: 10m Break + 70m Lunch",
      [(b["start"], b["end"], b["name"]) for b in breaks]
      == [("11:10", "11:20", "Break"), ("13:00", "14:10", "Lunch")],
      str([(b["start"], b["end"], b["name"]) for b in breaks]))

# fallbacks: corrupt / overlapping official_times degrade to SLOTS, never raise
c = A.db()
c.execute("UPDATE timetable_groups SET official_times=? WHERE group_key=?", ("{not json", GK))
c.commit(); c.close()
check("corrupt official_times -> SLOTS fallback", A._tt_grid(GK) is A.SLOTS)
c = A.db()
c.execute("UPDATE timetable_groups SET official_times=? WHERE group_key=?",
          (json.dumps({"1": "08:30-09:20", "2": "09:00-10:10"}), GK))
c.commit(); c.close()
check("overlapping corrected periods -> SLOTS fallback", A._tt_grid(GK) is A.SLOTS)
c = A.db()
c.execute("UPDATE timetable_groups SET official_times=? WHERE group_key=?",
          (json.dumps({str(k): v for k, v in tt["times"].items()}), GK))
c.commit(); c.close()
check("grid restored after repair", len(A._tt_grid(GK)) > 0)

# ops escape hatch
saved_mode = A.TIMETABLE_SOURCE
A.TIMETABLE_SOURCE = "manual"
check("TIMETABLE_SOURCE=manual forces SLOTS", A._tt_grid(GK) is A.SLOTS)
A.TIMETABLE_SOURCE = saved_mode

# ── save contract: preserve + location carry-forward + hot-shape group ──
A._save_timetable_group("tt0001", {"personal": {}, "courses": []})   # hot sync: no personal, no grid
c = A.db()
n2 = c.execute("SELECT COUNT(*) FROM timetable_slots").fetchone()[0]
c.close()
check("no timetable key -> rows preserved (30)", n2 == 30, str(n2))
A._save_timetable_group("tt0001", {"personal": {}, "timetable": []})  # section unpublished
c = A.db()
n3 = c.execute("SELECT COUNT(*) FROM timetable_slots").fetchone()[0]
c.close()
check("[] (unpublished) -> rows preserved", n3 == 30, str(n3))

c = A.db()
gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (GK,)).fetchone()[0]
c.execute("UPDATE timetable_slots SET location='LT-3' WHERE group_id=? AND day='Monday' AND period=1", (gid,))
c.commit(); c.close()
A._save_timetable_group("tt0001", res)
c = A.db()
loc = c.execute("SELECT location FROM timetable_slots WHERE day='Monday' AND period=1").fetchone()[0]
c.close()
check("editor-typed location survives official resync", loc == "LT-3", loc)

# ── archive contract: no user input unless ops re-enables it ────────────
os.environ.pop("TIMETABLE_EDITOR", None)  # unset = the shipped default
cl = A.app.test_client()
cl.set_cookie("srm_session", A.make_session_token("tt0001"))
check("editor archived by default (env unset)", A._tt_editor_enabled() is False)
r = cl.post("/api/timetable", json={"slots": {}, "custom_subjects": []})
check("save API 403 while archived", r.status_code == 403, str(r.status_code))
os.environ["TIMETABLE_EDITOR"] = "enabled"
check("TIMETABLE_EDITOR=enabled re-opens save", A._tt_editor_enabled() is True)

# ── editor contract: manual stamp + official times cleared (same tx) ────
cl = A.app.test_client()
cl.set_cookie("srm_session", A.make_session_token("tt0001"))
r = cl.post("/api/timetable", json={
    "slots": {"Monday-1": {"code": "21CSC101T", "name": "SOFTWARE DESIGN PATTERNS"}},
    "custom_subjects": []})
check("editor save ok", r.get_json().get("ok") is True, str(r.get_json()))
c = A.db()
src = c.execute("SELECT source FROM timetable_slots WHERE group_id=? AND day='Monday' AND period=1",
                (gid,)).fetchone()
times = c.execute("SELECT official_times, tt_fetched_at FROM timetable_groups WHERE id=?", (gid,)).fetchone()
c.close()
check("editor rows stamped manual", src and src[0] == "manual", str(src))
check("editor save clears official stamp", times == ("", 0) or times == (None, 0) or times[0] in ("", None),
      str(times))
check("editor save -> _tt_grid back to SLOTS (rows/times agree)", A._tt_grid(GK) is A.SLOTS)

# next official sync re-stamps (round trip)
A._save_timetable_group("tt0001", res)
c = A.db()
src = c.execute("SELECT source FROM timetable_slots WHERE group_id=? AND day='Monday' AND period=1",
                (gid,)).fetchone()
c.close()
check("sync after editor re-stamps official", src and src[0] == "official", str(src))
check("sync after editor restores official grid", [s for s in A._tt_grid(GK) if s["type"] == "class"][0]["start"]
      == "09:30")

# ── push: blocks_for_day uses the official-corrected clock ──────────────
c = A.db()
day_slots = {r[0]: {"code": r[1], "name": r[2], "location": r[3] or ""}
             for r in c.execute("SELECT period,subject_code,subject_name,location "
                                "FROM timetable_slots WHERE group_id=? AND day='Monday'", (gid,))}
c.close()
blocks = blocks_for_day("Monday", day_slots, datetime.now().date(), GK)
check("push block starts at corrected 09:30 (not raw 08:30)",
      blocks and blocks[0].start.strftime("%H:%M") == "09:30",
      str(blocks and blocks[0].start.strftime("%H:%M")))
check("legacy blocks_for_day (no group_key) unchanged shape",
      isinstance(blocks_for_day("Monday", day_slots, datetime.now().date()), list))

# ── render: panels use the corrected grid, legacy p7 is gone ────────────
html_out = A.timetable_html(GK, attendance={})
check("render shows corrected 09:30", "09:30" in html_out)
check("render never shows raw 08:30", "08:30" not in html_out)
check("render drops legacy p7 (16:00)", "16:00" not in html_out)

# ── attendance tiers (reference redesign 2026-10-30): the left rim became an
#    inline tag in the row tail — neutral comfortable / warn zero-margin / red below 75.
#    Same three tiers, same mapping, different node. ──
_c = A.db()
_codes = [r[0] for r in _c.execute(
    "SELECT DISTINCT subject_code FROM timetable_slots WHERE subject_code!='' ORDER BY subject_code")]
_c.close()
check("rim fixtures: >=3 seeded codes", len(_codes) >= 3, str(_codes[:5]))
if len(_codes) >= 3:
    att3 = A._attendance_index([A._course_view(c) for c in [   # views carry skip_now/attend_now
        {"code": _codes[0], "description": "", "attended": 40, "max_hours": 40},  # 100% → skip>0 → grey
        {"code": _codes[1], "description": "", "attended": 3, "max_hours": 4},    #  75% → skip==0 → warn
        {"code": _codes[2], "description": "", "attended": 1, "max_hours": 4},    #  25% → attend  → danger
    ]])
    html_r = A.timetable_html(GK, attendance=att3)
    _rows = html_r.split('<div class="tt-row')[1:]

    def _tier_for(code):
        # the NAME leads the row and the code rides the subline, so match the
        # code anywhere in the segment rather than in the <b>
        for seg in _rows:
            if code in seg:
                return ("danger" if "tt-tag--danger" in seg
                        else "warn" if "tt-tag--warn" in seg
                        else "ok" if "tt-tag--ok" in seg else "none")
        return "absent"

    check("tag tier: comfortable ≥75", _tier_for(_codes[0]) == "ok", _tier_for(_codes[0]))
    check("tag tier: at 75, zero margin", _tier_for(_codes[1]) == "warn", _tier_for(_codes[1]))
    check("tag tier: below 75, must attend", _tier_for(_codes[2]) == "danger", _tier_for(_codes[2]))
else:
    check("attendance tiers (need 3 codes)", False, "skipped")

class _FixedDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 14, 10, 5)  # Wednesday 10:05 → inside period 1 (corrected 09:30–10:20)

_orig_dt = A.datetime
A.datetime = _FixedDT
try:
    html_now = A.timetable_html(GK, attendance={})
finally:
    A.datetime = _orig_dt
# the "Now" badge was retired with the redesign: the live class is marked by the
# row modifier + the hero saying "Now · ends HH:MM" (no badge, no dot — review R2)
check("live class marked by row modifier (faked clock)", "tt-row--now" in html_now)
check("hero says the live class ends", "now &middot; ends" in html_now)
check("Soon badge retired — absent everywhere",
      "Soon" not in html_now and "tt-badge--soon" not in html_out)

# ── room chip renders (the stock seed carries NO locations, so this branch was
#    never exercised): a room shows as a chip, a long one stays whole, and a
#    slot with no room renders no chip rather than an empty pill ──
c = A.db()
_gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (GK,)).fetchone()[0]
_LONG = "Computer Lab-3 (Block C, 2nd Floor)"
c.execute("UPDATE timetable_slots SET location=? WHERE group_id=? AND day='Monday' AND period=1",
          (_LONG, _gid))
c.execute("UPDATE timetable_slots SET location='' WHERE group_id=? AND day='Monday' AND period=2",
          (_gid,))
c.commit(); c.close()
_html_room = A.timetable_html(GK)
check("room with text renders a chip", 'class=tt-chip' in _html_room)
check("long room name is emitted whole (no truncation in markup)", _LONG in _html_room, _LONG)
check("a slot with no room renders no empty chip", 'class=tt-chip></span>' not in _html_room)

# location carry (same rule as the editor path): unchanged code keeps the
# room, swapped subject drops it (review #3)
c = A.db()
gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (GK,)).fetchone()[0]
c.execute("UPDATE timetable_slots SET location='Room 101' "
          "WHERE group_id=? AND day='Monday' AND period=1", (gid,))
c.commit(); c.close()
A._save_timetable_group("tt0001", res)   # same codes -> room survives
c = A.db()
loc_same = c.execute("SELECT location FROM timetable_slots WHERE group_id=? "
                     "AND day='Monday' AND period=1", (gid,)).fetchone()[0]
c.execute("UPDATE timetable_slots SET location='Room 101' "
          "WHERE group_id=? AND day='Monday' AND period=1", (gid,))
c.commit(); c.close()
tt_swap = {**tt, "grid": {**tt["grid"], "Monday": {**tt["grid"]["Monday"], 1: "99ZZZ99T"}}}
A._save_timetable_group("tt0001", {**res, "timetable": tt_swap})  # swapped code -> room dropped
c = A.db()
loc_swap = c.execute("SELECT location FROM timetable_slots WHERE group_id=? "
                     "AND day='Monday' AND period=1", (gid,)).fetchone()[0]
c.close()
check("room carried when the code is unchanged", loc_same == "Room 101", str(loc_same))
check("room dropped when the subject swaps", loc_swap == "", str(loc_swap))

print()
print("%d/%d passed" % (total - len(fails), total))
sys.exit(1 if fails else 0)
