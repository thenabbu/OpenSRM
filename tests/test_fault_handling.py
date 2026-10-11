"""Fault-handling regression suite — guards the fixes from the Oct 2026
reliability audit (error-audit.md: B1-B6, B9-B11, S25; prod-forensics S1-S3).

Every check here failed (or could crash prod) on origin/main:
  * _semester_int("") raised IndexError -> 500 on / and timetable APIs (B5)
  * index()/api_marks json.loads were unguarded -> one corrupt stored row
    500'd the dashboard on every load (B1-B4)
  * marks_json had no preserve-if-empty -> a parse failure wiped stored
    marks silently (B6)
  * http_scraper parsed the STALE body after a mid-scrape relogin (S25)
  * no @app.errorhandler existed -> unhandled exceptions left no opensrm line

Offline: fetch_attendance is stubbed where a route needs it; no portal calls.
"""
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="osrm-fault-")  # verify76: no test DBs in-tree

from app import app as A          # noqa: E402
from _seed import mint_token, seed  # noqa: E402

FAILS = []


def check(name, fn):
    try:
        fn()
        print(f"  ok  {name}")
    except AssertionError as e:
        FAILS.append(name)
        print(f"FAIL  {name}: {e}")
    except Exception as e:
        FAILS.append(name)
        print(f"FAIL  {name}: raised {type(e).__name__}: {e}")


# ── helpers: pure functions ──────────────────────────────────────────
def t_semester():
    assert A._semester_int("III SEMESTER") == 3
    assert A._semester_int("") == 0, "empty semester must be 0, not IndexError"
    assert A._semester_int(None) == 0, "None semester must be 0"
    assert A._semester_int("  ") == 0
    assert A._semester_int("ZZ") == 0


def t_jload():
    assert A._jload('{"a": 1}', {}) == {"a": 1}
    assert A._jload("{not json", []) == [], "corrupt stored row must degrade to default"
    assert A._jload("[1, 2]", {}) == {}, "wrong shape must degrade to default"
    assert A._jload(None, {"x": 1}) == {"x": 1}
    assert A._jload("", []) == []
    assert A._jload('{"a": 1}', []) == [], "dict-for-list shape mismatch must degrade"


def t_fmt():
    assert A._fmt_score(11.7) == "11.7"
    assert A._fmt_max(15.0) == "15"
    assert A._fmt_score(None) == "?", "null score must not TypeError into a 500"
    assert A._fmt_max(None) == "?"
    assert A._fmt_score("junk") == "?"


# ── S25: content_html re-derived after mid-scrape relogin ────────────
def t_s25():
    src = (REPO / "app" / "http_scraper.py").read_text()
    n = src.count('content_html = parallel_html.get("9", "")')
    assert n == 2, (
        "S25: content_html must be re-derived after the relogin refetch "
        f"(found {n} assignment(s), expected 2) — without it a successful "
        "refetch parses the dead session's body and 503s with a false "
        "'Attendance page did not load'")


# ── unhandled exceptions: 500 JSON + one opensrm ERROR line ─────────
def t_errorhandler():
    records = []

    class Cap(logging.Handler):
        def emit(self, r):
            records.append(r)

    cap = Cap(level=logging.ERROR)
    logging.getLogger().addHandler(cap)
    try:
        @A.app.route("/__fault_boom")
        def _boom():
            raise RuntimeError("kaboom")

        r = A.app.test_client().get("/__fault_boom")
        assert r.status_code == 500, f"expected 500, got {r.status_code}"
        body = r.get_json(silent=True)
        assert body and body.get("ok") is False, f"expected JSON error body, got {r.data[:120]!r}"
    finally:
        logging.getLogger().removeHandler(cap)
    hits = [x for x in records if "unhandled error" in x.getMessage()]
    assert hits, "errorhandler must emit an opensrm ERROR line with the path"


# ── B1-B4: corrupt stored rows must not 500 the dashboard ───────────
def t_corrupt_rows():
    seed()
    c = A.db()
    c.execute("UPDATE users SET attendance_json='not json', "
              "personal_details_json='{broken', marks_json='[1,' "
              "WHERE netid='ng2776'")
    c.commit(); c.close()
    cl = A.app.test_client()
    cl.set_cookie("srm_session", mint_token())
    r = cl.get("/")
    assert r.status_code == 200, f"corrupt stored rows must degrade, not 500 (got {r.status_code})"
    r2 = cl.get("/api/marks")
    assert r2.status_code == 200, f"/api/marks must degrade (got {r2.status_code})"
    assert r2.get_json()["marks"] == [], r2.get_json()


# ── B6: login/refresh preserve stored marks when the fetch returns [] ─
FAKE_EMPTY = {"ok": True, "data": {"courses": [], "monthly": [], "period": None},
              "personal": {}, "photo": "", "courses": [], "marks": [],
              "subjects": {}, "fetched": int(time.time())}
FAKE_NEW = dict(FAKE_EMPTY, marks=[{"code": "1CSC999", "name": "Fresh"}])
STORED = [{"code": "1CSC301", "name": "Stored"}]


def _set_stored_marks():
    seed()
    c = A.db()
    c.execute("UPDATE users SET marks_json=? WHERE netid='ng2776'",
              (json.dumps(STORED),))
    c.commit(); c.close()


def _stored_marks():
    c = A.db()
    row = c.execute("SELECT marks_json FROM users WHERE netid='ng2776'").fetchone()
    c.close()
    return json.loads(row[0])


def t_login_preserves_marks():
    _set_stored_marks()
    orig = A.fetch_attendance
    A.fetch_attendance = lambda n, p: dict(FAKE_EMPTY)
    try:
        r = A.app.test_client().post("/api/login",
                                     json={"netid": "ng2776", "password": "pw"},
                                     content_type="application/json")
    finally:
        A.fetch_attendance = orig
    assert r.status_code == 200, r.data[:200]
    # preserved rows stay AND carry stale=True (widget's faint-highlight flag)
    assert _stored_marks() == [dict(STORED[0], stale=True)], (
        f"empty-marks login must preserve stored marks flagged stale: {_stored_marks()}")


def t_login_empty_overwrites_with_data():
    # preserve must not stick: a real fetch still overwrites
    _set_stored_marks()
    orig = A.fetch_attendance
    A.fetch_attendance = lambda n, p: dict(FAKE_NEW)
    try:
        r = A.app.test_client().post("/api/login",
                                     json={"netid": "ng2776", "password": "pw"},
                                     content_type="application/json")
    finally:
        A.fetch_attendance = orig
    assert r.status_code == 200, r.data[:200]
    assert _stored_marks() == FAKE_NEW["marks"], (
        f"non-empty fetch must overwrite: {_stored_marks()}")


def t_refresh_preserves_marks():
    _set_stored_marks()
    c = A.db()
    c.execute("UPDATE users SET password=? WHERE netid='ng2776'",
              (A.encrypt_pw("pw"),))
    c.commit(); c.close()
    orig = A.fetch_attendance
    A.fetch_attendance = lambda n, p: dict(FAKE_EMPTY)
    cl = A.app.test_client()
    cl.set_cookie("srm_session", mint_token())
    try:
        r = cl.post("/api/refresh")
    finally:
        A.fetch_attendance = orig
    assert r.status_code == 200, r.data[:200]
    assert r.get_json().get("ok") is True, r.data[:200]
    assert _stored_marks() == [dict(STORED[0], stale=True)], (
        f"empty-marks refresh must preserve stored marks flagged stale: {_stored_marks()}")


for name, fn in [
    ("_semester_int guards empty/None (B5)", t_semester),
    ("_jload degrades corrupt/shape-mismatched rows (B1-B4,B10)", t_jload),
    ("_fmt_score/_fmt_max tolerate junk (B9)", t_fmt),
    ("S25 content_html re-derived after relogin refetch", t_s25),
    ("errorhandler: 500 JSON + opensrm ERROR line", t_errorhandler),
    ("corrupt stored rows: / and /api/marks stay 200 (B1-B4)", t_corrupt_rows),
    ("login preserves stored marks on empty fetch (B6)", t_login_preserves_marks),
    ("login overwrites stored marks on real data (B6)", t_login_empty_overwrites_with_data),
    ("refresh preserves stored marks on empty fetch (B6)", t_refresh_preserves_marks),
]:
    check(name, fn)

total = 9
print(f"\n{total - len(FAILS)}/{total} passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("ok  fault handling suite")
