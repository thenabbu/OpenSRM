"""P10.1 / W9.2 rollback flag — PREACT_ISLANDS, proven in BOTH directions.

Contract: the boot flag (AppConfig.preact_islands, env PREACT_ISLANDS) gates
ONLY the island module tag. Default is ON — PREACT_ISLANDS unset must still
hydrate, or the whole migration silently dies in prod. Off = stop hydrating;
the server-rendered panels are the app (no 500, no blank page).

Why this file is a MATRIX and not one route: the flag is read in exactly one
place (`{% if preact_islands %}` in app/templates/partials/theme.html), so a
single-route proof of `/attendance` says nothing about the other eight panels
— a panel whose rollback path quietly kept a second island alive, or one that
stopped including the shared partial, would still pass. Every authenticated
route is rendered in BOTH positions and the two bodies are compared directly:
they must differ ONLY by the module tag.

Self-contained: temp DATA_DIR, seeded user, minted session. No server, no
network, no portal. Runner style: check(name, ok, detail).
"""
import atexit
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

TMP = tempfile.mkdtemp(prefix="osrm-rollback-")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
os.environ["DATA_DIR"] = TMP
os.environ["OCR_PREWARM"] = "0"
os.environ.pop("PREACT_ISLANDS", None)   # unset IS the default case
os.environ.pop("SCOPE_FEATURES", None)   # each boot owns its own gates

import app.app as A                        # noqa: E402
from app.config import AppConfig           # noqa: E402

FAILS = []
TOTAL = [0]


def check(name, ok, detail=""):
    TOTAL[0] += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


# fabricated netid only — the repo is public (AGENTS.md)
NETID = "zz9999"
TOKEN = "rollback-test-token"     # raw cookie; the DB stores its sha256 (migration 17)
ISLAND = 'type="module"'          # the island module tag; no other module tag exists

# Every authenticated route that renders a panel. `/campus`, `/academics`,
# `/fees` and `/tools` 404 when their feature has no rows, so seed_features()
# turns those on with synthetic rows (marked as such in its own docstring).
ROUTES = ["/", "/attendance", "/timetable", "/marks", "/campus",
          "/academics", "/fees", "/tools", "/settings"]


def make_config(dirpath, **kw):
    return AppConfig(data_dir=dirpath, db_path=os.path.join(dirpath, "srm.db"),
                     secret_path=os.path.join(dirpath, "secret"), prewarm_ocr=False, **kw)


def seed_features(app_obj):
    """Populate scope_json so the four row-gated tabs render real rows.

    MARKED SYNTHETIC — no live SCOPE data exists here. Values are wrapped the
    way the sync writes them ({data, ts}); the shapes are the ones
    tests/unit/test_scope_campus.py already drives through the real parsers.
    Without this, /campus, /academics, /fees and /tools answer 404 and this
    matrix would silently shrink back to five routes.
    """
    # Payload shapes follow the suites that already own each parser
    # (test_scope_campus / test_scope_academics / test_scope_fees), so a shape
    # drift upstream breaks those files first and this one second.
    scope = {
        # ── campus ──
        "getHostelDetails": {"roomNo": "412", "blockName": "C"},
        "getViewNotificationListJson": [{"notificationId": "N1",
                                         "notificationtitle": "Synthetic notice",
                                         "notificationdate": "01-10-2026",
                                         "notificationtime": "09:00"}],
        # ── placement (the /campus placement card) ──
        "getStudentAllOfferedJobs": [{"jobTitle": "SDE Intern", "companyName": "Acme Corp",
                                      "status": "Open", "appliedDate": "12-10-2026",
                                      "jobId": "J1"}],
        # ── /fees: the ##-joined rows the parser splits ──
        "getFeeDetails": [{"feedetails": "Tuition Fees##200000.00##200000.00"
                                         "##13-Aug-2025##2025-2026##0"},
                          {"feedetails": "Exam Fees##3150.00##3150.00"
                                         "##24-Sep-2026##2026-2027##0"}],
        # ── /academics: one released exam row registers the tab ──
        "getExamDetails": [{"result": "Pass", "grade": "O", "semester": "3",
                            "monthyear": "NOV 2026", "subjectcode": "21CSC201J",
                            "credit": "4", "subjectdesc": "DATA STRUCTURES"}],
    }
    now = int(time.time())
    with app_obj.app_context():
        c = A.db()
        c.execute("UPDATE users SET scope_json=?, scope_fetched_at=? WHERE netid=?",
                  (json.dumps({k: {"data": v, "ts": now} for k, v in scope.items()}),
                   now, NETID))
        c.commit()
        c.close()


def seed_user(app_obj):
    """users row for NETID so every panel renders real server-side rows."""
    att = {"courses": [
        {"code": "21CSC201J", "description": "DATA STRUCTURES",
         "max_hours": "40", "attended": "30", "absent": "10"},
        {"code": "21CSC202J", "description": "DBMS",
         "max_hours": "40", "attended": "20", "absent": "20"}],
        "period": {"from": "20/Jul/2026", "to": "13/Oct/2026"}, "monthly": []}
    personal = {"name": "Fabricated Student", "program": "CSE Cloud Computing",
                "batch": 2025, "semester": 3, "section": "A"}
    with app_obj.app_context():
        c = A.db()
        c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
                     attendance_json, last_fetch) VALUES(?,?,?,?,?)""",
                  (NETID, "pw", json.dumps(personal), json.dumps(att), int(time.time())))
        c.execute("DELETE FROM cookies WHERE token=?",
                  (hashlib.sha256(TOKEN.encode()).hexdigest(),))
        c.execute("INSERT INTO cookies(token,netid,created) VALUES(?,?,?)",
                  (hashlib.sha256(TOKEN.encode()).hexdigest(), NETID, int(time.time())))
        c.commit()
        c.close()
    seed_features(app_obj)


def render(app_obj, path="/attendance"):
    cl = app_obj.test_client()
    cl.set_cookie("srm_session", TOKEN)
    r = cl.get(path)
    return r.status_code, r.get_data(as_text=True)


def boot(tag, **kw):
    d = tempfile.mkdtemp(prefix=f"osrm-{tag}-")
    atexit.register(shutil.rmtree, d, ignore_errors=True)
    a = A.create_app(make_config(d, **kw))
    seed_user(a)
    return a


# ── 1) config parsing: the default can never be OFF ──────────────────────
cfg_default = AppConfig.from_env()
check("PREACT_ISLANDS unset -> config True", cfg_default.preact_islands is True)

os.environ["PREACT_ISLANDS"] = "0"
check("PREACT_ISLANDS=0 -> config False", AppConfig.from_env().preact_islands is False)
os.environ["PREACT_ISLANDS"] = "1"
check("PREACT_ISLANDS=1 -> config True", AppConfig.from_env().preact_islands is True)
os.environ["PREACT_ISLANDS"] = "off"
check("PREACT_ISLANDS=off -> config False", AppConfig.from_env().preact_islands is False)
os.environ["PREACT_ISLANDS"] = ""
check("PREACT_ISLANDS='' -> config True (empty = unset)", AppConfig.from_env().preact_islands is True)
os.environ.pop("PREACT_ISLANDS", None)

# ── 2) every route, BOTH directions ──────────────────────────────────────
# feature gates on, so the four row-gated tabs are reachable at all
os.environ["SCOPE_FEATURES"] = "all"
app_on = boot("on")                       # default: unset -> island hydrates
app_off = boot("off", preact_islands=False)

bodies = {}
for route in ROUTES:
    code_on, html_on = render(app_on, route)
    code_off, html_off = render(app_off, route)
    bodies[route] = (html_on, html_off)

    # ON must be the full app, not a broken one
    check(f"flag ON: {route} 200", code_on == 200, str(code_on))
    check(f"flag ON: {route} island module tag present", ISLAND in html_on,
          f'{html_on.count(ISLAND)} module tag(s)')
    check(f"flag ON: {route} asset_dist('app') entry emitted",
          "/static/dist/assets/" in html_on)

    # OFF must still be a real page with zero client layer
    check(f"flag OFF: {route} 200 (no 500)", code_off == 200, str(code_off))
    check(f"flag OFF: {route} no island module tag", ISLAND not in html_off,
          f'{html_off.count(ISLAND)} module tag(s)')
    check(f"flag OFF: {route} not a blank page", len(html_off) > 2000,
          f"{len(html_off)} bytes")
    check(f"flag OFF: {route} still an HTML document",
          "<html" in html_off.lower() and "</html>" in html_off.lower())
    check(f"flag OFF: {route} no legacy script tags (dash/timetable/pull/drag-drop-touch)",
          not any(n in html_off for n in ("dash.js", "timetable.js", "pull.js",
                                          "drag-drop-touch.js")))
    # gaze.js was a standalone served script from the house port; the gaze driver
    # is now blobatar/gaze inside the module bundle, so push.js is the only KEEP
    # script left with its own <script src>. Its continued presence is what proves
    # the rollback did not gut the client layer wholesale.
    check(f"flag OFF: {route} the surviving KEEP scripts still load (push)",
          "push.js" in html_off and "gaze.js" not in html_off)

    # The two positions must differ by the module tag and NOTHING else. A route
    # whose OFF branch quietly dropped a section would render a shorter page in
    # BOTH directions and still pass every check above; this is the one that
    # catches it. Two clocks are legitimately allowed to vary (the two boots are
    # seconds apart) and are normalised away: the epoch, and the rendered
    # "YYYY-MM-DD HH:MM:SS" the sync caption and its JSON block print. Blank lines
    # the removed tag leaves behind are dropped too.
    norm = lambda h: re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", "DT",
                            re.sub(r"\d{9,}", "TS", re.sub(
                                r'<script type="module"[^>]*></script>', "", h,
                            ))).replace("\n", "")
    check(f"both directions: {route} identical once the module tag is removed",
          norm(html_on) == norm(html_off),
          f"{len(html_on)} vs {len(html_off)} bytes")

# ── 3) /attendance detail: server-rendered rows in BOTH directions ───────
html_on, html_off = bodies["/attendance"]
rows = html_off.count('class="att-subj"')
check("flag OFF: 2 server-rendered course rows in HTML", rows == 2,
      f"{rows} att-subj cells")
check("flag OFF: seeded course names title-cased in the rows",
      "Data Structures" in html_off and "Dbms" in html_off)
check("flag ON: the same 2 rows are painted server-side too (no blank flash)",
      html_on.count('class="att-subj"') == 2,
      f'{html_on.count(chr(34) + "att-subj" + chr(34))} att-subj cells')

# ── 4) mount points survive OFF; only the loader is gated ────────────────
# A `data-island` div is inert markup the server paints. Dropping it under OFF
# would change the page itself — the "silently degrades" failure A2 forbids.
mounts_off = sum(h.count('data-island="') for _, h in bodies.values())
mounts_on = sum(h.count('data-island="') for h, _ in bodies.values())
check("flag OFF: island mount points still painted server-side",
      mounts_off > 0 and mounts_off == mounts_on,
      f"{mounts_off} off vs {mounts_on} on over {len(ROUTES)} routes")

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} passed")
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    sys.exit(1)
