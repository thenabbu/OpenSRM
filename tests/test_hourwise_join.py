"""Hourwise join — Phase 2 suite (self-contained: temp DATA_DIR, seeded in-test).

Covers the join spec (agents/hourwise.md): weekday match against the user's
group slots, missing hour key = no class = never an absence, OD never absent,
slot-miss fallback (NULL code / CL / custom / no row) = bare hN, period 7
unknown (SCOPE has no h7 -> bare, never named), weekend rows unnamed, the
per-subject cross-check vs fixtures/attendance-subject.txt (tolerance ±1 —
documented in t_cross_check_subject_totals), the day strip shape, and the
feature gate: OFF / empty scope / no group all render the chip list exactly
as today (chip text asserted verbatim) with the day strip hidden.

Fixture rows = tests/fixtures/scope-attendance-hour.txt (byte-copy of the
mission's LIVE getHourwiseAttendance output); slots = the seeded group's
timetable (GRID fit, shared with scripts/seed_hourwise.py).
Run: .venv/bin/python tests/test_hourwise_join.py  (offline, no server)
"""
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# verify76 forbids test-DB files in the repo root / tests dir; mkdtemp so the
# DB dir outlives this module-level test body
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="osrm-hourwise-")

from app.app import _hourwise_ctx, hourwise_view  # noqa: E402  (DATA_DIR first)
from app import app as A  # noqa: E402
from app.db import day_slots, group_id, group_subjects  # noqa: E402

# the seed module is the single source of GRID + fixture wiring (dev server too)
_spec = importlib.util.spec_from_file_location(
    "seed_hourwise", REPO / "scripts" / "seed_hourwise.py")
seedmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seedmod)

NETID = "zzhw01"
FIX_ROWS = seedmod.load_hourwise_rows()          # 61 fixture rows + 3 probes
PORTAL = {s["subjectcode"]: int(s["absent"]) for s in seedmod.load_subjects()}
CLIENT = A.app.test_client()

seedmod.seed(NETID)
GK = A._group_key(seedmod.PERSONAL)
TOK = A.make_session_token(NETID)
CLIENT.set_cookie("srm_session", TOK)
SLOTS = day_slots(GK)                            # the seeded group's slots
CUSTOM = {r[0] for r in group_subjects(group_id(GK)) if r[3] and r[0]}
JOIN = hourwise_view(FIX_ROWS, SLOTS, CUSTOM)    # pure join over fixture rows


def _chip(date):
    return [c["label"] for c in JOIN["chips"].get(date, [])]


def _titles(date):
    return [c["title"] for c in JOIN["chips"].get(date, [])]


def _get(env=None):
    prev = os.environ.get("SCOPE_FEATURES")
    if env is None:
        os.environ.pop("SCOPE_FEATURES", None)
    else:
        os.environ["SCOPE_FEATURES"] = env
    try:
        return CLIENT.get("/").get_data(as_text=True)
    finally:
        if prev is None:
            os.environ.pop("SCOPE_FEATURES", None)
        else:
            os.environ["SCOPE_FEATURES"] = prev


# ── join rules ──────────────────────────────────────────────────────────────
def t_fixture_weekday_match():
    """Fixture A-hours join the group's slot for that weekday+period."""
    # 15-Oct-2026 = Thursday, Thu p1 = 21CSC201J
    assert _chip("15 Oct") == ["15 Oct · h1 DATA STRUCTURES AND ALGORITHMS"], _chip("15 Oct")
    # 14-Oct-2026 = Wednesday: h1 = Wed p1 (OS), h2 = Wed p2 (MATH) -> two chips
    assert _chip("14 Oct") == ["14 Oct · h1 OPERATING SYSTEMS",
                               "14 Oct · h2 NUMERICAL METHODS AND ANALYSIS"], _chip("14 Oct")
    # contiguous same-subject run groups: 01-Oct h4,h5 are both Thu p4/p5 = APP
    assert "01 Oct · h4,h5 ADVANCED PROGRAMMING PRACTICE" in _chip("01 Oct"), _chip("01 Oct")
    # every chip hour is an hour the scope row literally says "A"
    by_date = {r["attendancedate"]: r for r in FIX_ROWS if "attendancedate" in r}
    from datetime import datetime
    for disp, chips in JOIN["chips"].items():
        row = next(r for d, r in by_date.items()
                   if datetime.strptime(d, "%d-%b-%Y").strftime("%d %b") == disp)
        for label in chips:
            for h in re.findall(r"h(\d)", label["label"].split("· ", 1)[1].split(" ")[0]):
                assert row.get("h" + h) == "A", (label, row)


def t_missing_key_no_class():
    """Missing hour key = no class scheduled: no chip, no cell."""
    out = hourwise_view([{"attendancedate": "09-Nov-2026", "h1": "A"}], SLOTS, CUSTOM)
    # 09-Nov-2026 = Monday: h1 joins Mon p1, and ONLY h1 (h2..h6 keys absent)
    assert [c["label"] for c in out["chips"]["09 Nov"]] == [
        "09 Nov · h1 COMPUTER ORGANIZATION AND ARCHITECTURE"], out["chips"]
    cells = out["strip"][0]["cells"]
    assert len(cells) == 6 and cells[1]["state"] is None and all(
        c["state"] is None for c in cells[1:]), cells
    # fixture 10-Oct has NO h4 key: h4 never appears in any chip for it
    assert all("h4" not in c["label"] for c in JOIN["chips"].get("10 Oct", []))


def t_od_never_absent():
    """OD is not an absence: only the A hour chips; OD keeps its strip cell."""
    assert _chip("05 Nov") == ["05 Nov · h2 ADVANCED PROGRAMMING PRACTICE"], _chip("05 Nov")
    assert not any(re.search(r"\bh1\b", c) for c in _chip("05 Nov"))
    col = next(d for d in JOIN["strip"] if d["date"] == "05 Nov")
    assert col["cells"][0]["state"] == "OD" and col["cells"][1]["state"] == "A", col


def t_slot_miss_bare_fallback():
    """NULL code / CL / custom / no slot row -> bare hN, never a subject."""
    slots = {"Monday": {1: {"code": "", "name": "JUNK"},
                        2: {"code": "CL", "name": "CLASS IN CHARGE"},
                        3: {"code": "CCLAB99", "name": "CLOUD COMPUTING LAB"}}}
    row = [{"attendancedate": "12-Oct-2026", "h1": "A", "h2": "A",
            "h3": "A", "h4": "A"}]  # 12-Oct-2026 = Monday; h4 has no slot row
    out = hourwise_view(row, slots, custom={"CCLAB99"})
    assert [c["label"] for c in out["chips"]["12 Oct"]] == ["12 Oct · h1,h2,h3,h4"], out
    assert out["chips"]["12 Oct"][0]["title"].endswith("no subject on the timetable")


def t_period7_unknown():
    """SCOPE has no h7: period 7 renders bare h7, never a subject; strip = 6."""
    assert _chip("06 Nov") == ["06 Nov · h7"], _chip("06 Nov")
    assert _titles("06 Nov")[0].endswith("no subject on the timetable")
    assert all(len(d["cells"]) == 6 for d in JOIN["strip"])
    # no chip anywhere ever names a subject for h7
    all_labels = [c["label"] for cs in JOIN["chips"].values() for c in cs]
    assert not [l for l in all_labels if "h7" in l and not l.endswith("h7")], all_labels


def t_weekend_row_unnamed():
    """Saturday row: A-hours chip bare (no weekday slots), subjects None."""
    assert _chip("10 Oct") == ["10 Oct · h1,h2,h3", "10 Oct · h5,h6"], _chip("10 Oct")
    col = next(d for d in JOIN["strip"] if d["date"] == "10 Oct")
    assert all(c["subject"] is None for c in col["cells"]), col


def t_cross_check_subject_totals():
    """Joined A-count per subjectcode within ±1 of attendance-subject totals.

    Tolerance ±1 because the portal counts may include hours outside timetable
    scope (Saturday classes + CL have no Mon-Fri slot: the fixture's 34 A
    hours minus 6 Saturday hours = 28 joinable vs the portal's 35 total).
    CL is deliberately excluded from the ±1 loop and asserted joined==0:
    class-in-charge is never on a timetable (join spec: bare-hN fallback),
    so its portal count (2) can never be joined — the >1 delta is explained,
    not investigated away. Any OTHER >1 delta fails the suite.
    """
    with open(REPO / "tests" / "fixtures" / "scope-attendance-hour.txt") as f:
        fixture_only = json.load(f)  # 61 LIVE rows — probes excluded
    fx = hourwise_view(fixture_only, SLOTS, CUSTOM)
    joined = Counter()
    for chips in fx["chips"].values():
        for c in chips:
            m = re.search(r"Absent ([\dh,]+) — .* \((\w+)\)$", c["title"])
            if m:
                joined[m.group(2)] += len(m.group(1).split(","))
    assert set(joined) <= set(PORTAL), f"invented codes: {set(joined) - set(PORTAL)}"
    lines = []
    for code, portal_n in sorted(PORTAL.items()):
        got = joined.get(code, 0)
        delta = got - portal_n
        lines.append(f"  cross-check {code}: joined={got} portal={portal_n} delta={delta:+d}")
        if code == "CL":
            assert got == 0, "CL must never join (never on a timetable)"
        else:
            assert abs(delta) <= 1, f"{code} delta {delta:+d} > ±1\n" + "\n".join(lines)
    print("    " + "\n    ".join(lines))


def t_strip_shape():
    """Last 14 school days newest-first, 6 period slots, closed state set."""
    strip = JOIN["strip"]
    assert len(strip) == 14, len(strip)
    assert strip[0]["date"] == "06 Nov", strip[0]["date"]  # newest first
    from datetime import datetime as _dt
    ds = [_dt.strptime(d["date"], "%d %b").replace(year=2026) for d in strip]
    assert ds == sorted(ds, reverse=True), "strip must be newest-first"
    assert all(len(d["cells"]) == 6 for d in strip)
    assert all(c["state"] in (None, "P", "A", "OD") for d in strip for c in d["cells"])
    assert all(len(d["dow"]) == 3 for d in strip)


# ── feature gate + render (view context, chip text verbatim) ────────────────
def t_feature_off_no_join():
    prev = os.environ.get("SCOPE_FEATURES")
    os.environ["SCOPE_FEATURES"] = "off"
    try:
        assert _hourwise_ctx(NETID, GK) is None, "feature off -> no join context"
        html = CLIENT.get("/").get_data(as_text=True)
    finally:
        if prev is None:
            os.environ.pop("SCOPE_FEATURES", None)
        else:
            os.environ["SCOPE_FEATURES"] = prev
    assert "Last 14 school days" not in html, "day strip must be hidden"
    assert "15 Oct · 1h" in html, "old count chip must render verbatim"
    assert "15 Oct · h1 DATA STRUCTURES" not in html, "no subject chips when off"


def t_feature_on_joined_render():
    html = _get(env="hourwise")
    ctx = _hourwise_ctx(NETID, GK)
    assert ctx and ctx["ts"] > 0, ctx
    assert "Last 14 school days" in html, "day strip hidden although all legs present"
    for want in (
        "15 Oct · h1 DATA STRUCTURES AND ALGORITHMS",     # weekday match chip
        "01 Oct · h4,h5 ADVANCED PROGRAMMING PRACTICE",   # same-subject run grouped
        "10 Oct · h1,h2,h3",                              # Saturday bare run
        "23 Oct · h6",                                    # custom slot bare
        "06 Nov · h7",                                    # period 7 bare
        "04 Sep · 2h",                                    # per-row degrade (no scope A)
        "15 Oct · h1 · absent · DATA STRUCTURES AND ALGORITHMS",  # cell title
    ):
        assert want in html, f"missing from render: {want}"


def t_scope_empty_renders_as_today():
    row = A.db()
    saved = row.execute("SELECT scope_json FROM users WHERE netid=?", (NETID,)).fetchone()[0]
    row.execute("UPDATE users SET scope_json='{}' WHERE netid=?", (NETID,))
    row.commit()
    row.close()
    try:
        assert _hourwise_ctx(NETID, GK) is None, "empty scope -> no join"
        html = _get(env="hourwise")
        assert "Last 14 school days" not in html and "15 Oct · 1h" in html, \
            "empty scope must render today's chip list unchanged"
    finally:
        row = A.db()
        row.execute("UPDATE users SET scope_json=? WHERE netid=?", (saved, NETID))
        row.commit()
        row.close()


def t_no_group_renders_as_today():
    row = A.db()
    gid = group_id(GK)
    saved = row.execute("SELECT day, period, subject_code, subject_name, location "
                        "FROM timetable_slots WHERE group_id=?", (gid,)).fetchall()
    row.execute("DELETE FROM timetable_slots WHERE group_id=?", (gid,))
    row.commit()
    row.close()
    try:
        assert _hourwise_ctx(NETID, GK) is None, "no slots -> no join"
        html = _get(env="hourwise")
        assert "Last 14 school days" not in html and "15 Oct · 1h" in html, \
            "no timetable group must render today's chip list unchanged"
    finally:
        row = A.db()
        row.executemany("INSERT INTO timetable_slots(group_id, day, period, subject_code,"
                        " subject_name, location, source) VALUES(?,?,?,?,?,?,'manual')",
                        [(gid, *r) for r in saved])
        row.commit()
        row.close()


TESTS = [
    ("weekday match + every chip hour is an A", t_fixture_weekday_match),
    ("missing hour key = no class, never an absence", t_missing_key_no_class),
    ("OD is never an absence hour", t_od_never_absent),
    ("slot miss (NULL/CL/custom/no row) -> bare hN", t_slot_miss_bare_fallback),
    ("period 7 unknown: bare h7, strip stays 6", t_period7_unknown),
    ("weekend row never gets a subject name", t_weekend_row_unnamed),
    ("cross-check vs attendance-subject within ±1", t_cross_check_subject_totals),
    ("day strip: 14 newest days x 6 period slots", t_strip_shape),
    ("feature off -> no join ctx, chip text unchanged", t_feature_off_no_join),
    ("feature on -> subject chips + day strip render", t_feature_on_joined_render),
    ("empty scope_json -> renders exactly as today", t_scope_empty_renders_as_today),
    ("no timetable group -> renders exactly as today", t_no_group_renders_as_today),
]

if __name__ == "__main__":
    failed = 0
    t0 = time.monotonic()
    for name, fn in TESTS:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed ({time.monotonic() - t0:.1f}s)")
    sys.exit(1 if failed else 0)
