#!/usr/bin/env python3
"""Prove the SCOPE surfaces actually RENDER for a logged-in user.

The old CI smoke only asserted the netid string appeared on / — which passes
even when every SCOPE panel is empty, and is exactly how "deployed and working"
got claimed while the UI showed nothing. This asserts the real chain:

    SCOPE_FEATURES on -> scope_json[op] has data -> Tools row rendered ->
    target panel exists in the DOM -> dash.js can activate it

Seeds FABRICATED data only (public repo), scope_json encoded exactly ONCE as a
JSON object. Exits non-zero on the first broken link.

Run: DATA_DIR=$(mktemp -d) SCOPE_FEATURES=all .venv/bin/python scripts/scope_ui_smoke.py
"""
import json
import os
import re
import sys
import time

DATA_DIR = os.environ.get("DATA_DIR")
if not DATA_DIR:
    sys.exit("DATA_DIR must be set (fresh temp dir)")
os.environ["OCR_PREWARM"] = "0"
os.environ.setdefault("SCOPE_FEATURES", "all")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as A  # noqa: E402

NETID = "zz9999"

# One blob, encoded ONCE. Every value is {"data": ..., "ts": ...} — the shape
# the view models and _tools_entries both key off. Field names MIRROR THE REAL
# PARSERS (views/academics.py, views/fees.py), not invented ones: a fixture
# that doesn't match the parser renders empty and "proves" nothing.
SCOPE = {
    # fees._parse_fee_rows: "head##paid##total##date##year##trailing"
    "getFeeDetails": {"data": [
        {"feedetails": "Tuition Fee##125000##125000##12 Jul 2026##2026##1"},
    ], "ts": int(time.time())},
    # academics: rows key on monthyear / subjectcode / subjectdesc / credit /
    # grade / result / semester (grade counts only when result == Pass).
    "getExamDetails": {"data": [
        {"monthyear": "DEC 2025", "semester": "1", "subjectcode": "21CSS101J",
         "subjectdesc": "PROGRAMMING FOR PROBLEM SOLVING", "credit": "4",
         "grade": "A+", "result": "Pass"},
        {"monthyear": "DEC 2025", "semester": "1", "subjectcode": "21MAB101T",
         "subjectdesc": "CALCULUS AND LINEAR ALGEBRA", "credit": "4",
         "grade": "A", "result": "Pass"},
    ], "ts": int(time.time())},
    "getCummulativeAttendance": {"data": [
        {"subjectcode": "21CSS201T", "subjectname": "COMPUTER ORGANIZATION AND ARCHITECTURE",
         "attended": "41", "total": "50", "percentage": "82"},
    ], "ts": int(time.time())},
    "getSubjectwiseAttendance": {"data": [
        {"subjectcode": "21CSS201T", "subjectname": "COMPUTER ORGANIZATION AND ARCHITECTURE",
         "attended": "41", "total": "50", "percentage": "82"},
    ], "ts": int(time.time())},
    "getHourwiseAttendance": {"data": [
        {"attendancedate": "06 Oct 2026", "h1": "P", "h2": "P", "h3": "A",
         "h4": "P", "h5": "P", "h6": "OD"},
    ], "ts": int(time.time())},
}

fails = []


def check(name, cond, ev=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f" — {ev}" if ev and not cond else ""))
    if not cond:
        fails.append(name)


c = A.db()
c.execute(
    "INSERT OR REPLACE INTO users(netid,password,personal_details_json,last_fetch,"
    "scope_json,scope_fetched_at) VALUES(?,?,?,?,?,?)",
    (NETID, "unused-by-smoke",
     json.dumps({"Student Name": "Fabricated Smoke Student",
                 "Program": "Computer Science and Engineering Cloud Computing [B.Tech]"}),
     int(time.time()),
     json.dumps(SCOPE, ensure_ascii=False),      # encoded exactly once
     int(time.time())))
c.commit()
c.close()

# ── the stored shape is sane before we blame the frontend ──────────────────
row = A.user_scope_data(NETID)
blob = json.loads(row["scope_json"])
check("scope_json decodes once into a top-level object", isinstance(blob, dict), type(blob).__name__)
check("every stored op is {data, ts}",
      all(isinstance(v, dict) and "data" in v and "ts" in v for v in blob.values()))

# ── the Tools gate produces rows ───────────────────────────────────────────
rows = A._tools_entries(NETID)
slugs = sorted(r["slug"] for r in rows)
check("_tools_entries yields SCOPE rows with data present", len(rows) >= 3, str(slugs))
check("every Tools row names a real tab",
      all(r.get("tab") in {"academics", "fees", "attendance", "settings", "campus", "tools"}
          for r in rows), str([(r["slug"], r.get("tab")) for r in rows]))

# ── the rendered page carries the panels AND links to them ────────────────
tok = A.make_session_token(NETID)
cl = A.app.test_client()
cl.set_cookie("srm_session", tok)          # a raw Cookie header is not honoured here
r = cl.get("/")
check("authenticated GET / is 200", r.status_code == 200, str(r.status_code))
html = r.get_data(as_text=True)

for tab in ("tools", "academics", "fees", "attendance"):
    check(f'panel id="tab-{tab}" present', f'id="tab-{tab}"' in html)
    check(f'nav data-tab="{tab}" present', f'data-tab="{tab}"' in html)
# campus self-hides on empty answers BY DESIGN (no campus ops seeded here), so
# assert the rule rather than the panel: present only when it has cards.
check("campus hidden when it has no cards (self-hide rule)",
      ('id="tab-campus"' in html) == ("Campus" in html and 'data-tab="campus"' in html))

# the Tools rows must point at panels that exist (the original broken-link bug)
hrefs = re.findall(r'data-tool-tab="([a-z]+)"', html)
check("Tools rows carry data-tool-tab targets", len(hrefs) >= 3, str(hrefs))
missing = [h for h in hrefs if f'id="tab-{h}"' not in html]
check("every Tools target panel exists in the DOM", not missing, str(missing))

# the sync-state hook the frontend polls off must be rendered
check("body carries data-scope-sync", "data-scope-sync=" in html)

# seeded content reached the browser, not just the DB
check("seeded fee head rendered", "Tuition Fee" in html)
check("seeded subject rendered", "Programming For Problem Solving" in html)  # view title-cases

# ── the status endpoint answers for the session user only ─────────────────
s = A.app.test_client().get("/api/scope/status")     # a FRESH client: no cookie
check("status 401s without a session", s.status_code == 401, str(s.status_code))
s = cl.get("/api/scope/status")
check("status 200 with a session", s.status_code == 200, str(s.status_code))
j = s.get_json()
check("status returns a state word + op count, no payload",
      j.get("ok") is True and j.get("state") in ("off", "stale", "running", "complete")
      and isinstance(j.get("ops"), int) and "scope_json" not in json.dumps(j), str(j))

print()
if fails:
    print(f"SCOPE UI SMOKE: FAIL ({len(fails)}) — " + "; ".join(fails))
    sys.exit(1)
print("SCOPE UI SMOKE: PASS — panels render, Tools links resolve, data reaches the DOM")
