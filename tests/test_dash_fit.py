"""DUT: the dashboard must FIT the desktop viewport (no page scrollbar) while
mobile keeps normal page flow, plus the feedback-CTA archive toggle (fb_open).

Covers two shipped behaviours (v1.19.0):
  1. lg grid = 100dvh - 94px (navbar 64 + uniform 15px edge top/bottom) with content-
     hugging row 1 + 1fr row 2: document scrollHeight == clientHeight at
     1280x900, cards stretch to fill, residue (if any) scrolls inside the card.
     The 94px constant is PINNED: grid height must equal innerH - navH -
     mainPadTop - mainPadBottom, so a navbar-height change fails here first.
     Plus the v1.20 layout contract: uniform 15px card-column edge on both
     sides (scrollbar-strip compensated) and ZERO card-body residue at the
     squeeze viewports 1920x944 / 1366x768 (widgets absorb their cell).
  2. fb_open=0 (portal's feedback service closed) -> #fb-cta AND #fb-modal
     archived from the render, Teachers list kept; fb_open=1 -> both return.
     Auto-unarchive is the flip itself: no code path, just the stored flag.

Self-booting (dut_official_tt.py pattern): fresh DATA_DIR, rich fabricated
seed, gunicorn on a free port, require_own_server guard. Run:
  PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers \
  .venv/bin/python tests/test_dash_fit.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DATA = "/tmp/osrm-dashfit-dut"
os.environ["DATA_DIR"] = DATA
shutil.rmtree(DATA, ignore_errors=True)

import tests._seed as seed_mod  # noqa: E402

seed_mod.seed()  # group + base user FIRST (its INSERT OR REPLACE nulls other cols)

import app.app as A  # noqa: E402

# ---- rich fabricated payload so the grid is exercised at real load --------
PERSONAL = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
            "Batch": "2025", "Semester": "III SEMESTER", "Section": "A",
            "Student Name": "Test Student", "Register No.": "RA2500000000"}
ATT = {"courses": [
    {"code": "21CSC201J", "description": "DATA STRUCTURES AND ALGORITHMS", "max_hours": "46", "attended": "45", "absent": "1"},
    {"code": "21CSC202J", "description": "OPERATING SYSTEMS", "max_hours": "44", "attended": "30", "absent": "14"},
    {"code": "21CSC203P", "description": "ADVANCED PROGRAMMING PRACTICE", "max_hours": "55", "attended": "30", "absent": "25"},
    {"code": "21CSS201T", "description": "COMPUTER ORGANIZATION AND ARCHITECTURE", "max_hours": "45", "attended": "43", "absent": "2"},
    {"code": "21DCS201P", "description": "DESIGN THINKING AND METHODOLOGY", "max_hours": "30", "attended": "26", "absent": "4"},
    {"code": "21LEM201T", "description": "PROFESSIONAL ETHICS", "max_hours": "11", "attended": "10", "absent": "1"},
    {"code": "21MAB206T", "description": "NUMERICAL METHODS AND ANALYSIS", "max_hours": "44", "attended": "38", "absent": "6"},
    {"code": "CL", "description": "CLASS IN CHARGE", "max_hours": "4", "attended": "2", "absent": "2"}],
    "period": {"from": "20/Jul/2026", "to": "13/Oct/2026"},
    "monthly": [{"month": "OCT / 2026", "present": "19", "absent": "5",
                 "od_present": "0", "od_absent": "0", "ml": "0"}],
    "daily_absent": {"OCT / 2026": [{"date": "01-10-2026", "hours": "1"},
                                    {"date": "06-10-2026", "hours": "2"}]}}
MARKS = [{"code": "21CSS201T", "title": "COMPUTER ORGANIZATION AND ARCHITECTURE",
          "components": [{"name": "FT-I", "entered": "04/Sep/2026", "scored": 4.5, "max": 5.0}],
          "scored_total": 4.5, "max_total": 5.0},
         {"code": "21MAB206T", "title": "NUMERICAL METHODS AND ANALYSIS",
          "components": [{"name": "FT-I", "entered": "21/Sep/2026", "scored": 5.0, "max": 5.0}],
          "scored_total": 5.0, "max_total": 5.0}]
EXAMS = [{"code": "21CSC201J", "name": "DATA STRUCTURES AND ALGORITHMS", "date": "25-11-2026", "session": "FN", "month": "11", "year": "2026"},
         {"code": "21CSC202J", "name": "OPERATING SYSTEMS", "date": "28-11-2026", "session": "AN", "month": "11", "year": "2026"}]
FACULTY = {"DATA STRUCTURES AND ALGORITHMS": {"subject_id": "90001", "staff": [["50001", "Dr.Test Alpha-Theory"], ["50002", "Dr.Test Beta-Theory"]]},
           "OPERATING SYSTEMS": {"subject_id": "90004", "staff": [["50004", "Dr.Test Delta-Theory"]]},
           "ADVANCED PROGRAMMING PRACTICE": {"subject_id": "90005", "staff": [["50005", "Dr.Test Epsilon-Practical"]]},
           "COMPUTER ORGANIZATION AND ARCHITECTURE": {"subject_id": "90006", "staff": [["50006", "Dr.Test Zeta-Theory"]]},
           "DESIGN THINKING AND METHODOLOGY": {"subject_id": "90007", "staff": [["50007", "Dr.Test Eta-Practical"]]},
           "PROFESSIONAL ETHICS": {"subject_id": "90002", "staff": [["50003", "Dr.Test Gamma-Practical"]]},
           "NUMERICAL METHODS AND ANALYSIS": {"subject_id": "90008", "staff": [["50008", "Dr.Test Theta-Theory"]]}}

_c = A.db()
_c.execute("""UPDATE users SET personal_details_json=?, attendance_json=?, marks_json=?,
              exam_schedule_json=?, faculty_map_json=?, fb_open=?, last_fetch=?
              WHERE netid='zz9999'""",
           (json.dumps(PERSONAL), json.dumps(ATT), json.dumps(MARKS),
            json.dumps(EXAMS), json.dumps(FACULTY), 1, int(time.time())))
_c.commit(); _c.close()
token = seed_mod.mint_token()

GUNICORN = "/opt/data/opensrm-repo/.venv/bin/gunicorn"
if not os.path.isfile(GUNICORN):
    raise SystemExit(f"FAIL[guard]: missing {GUNICORN} (an OpenSRM checkout .venv)")
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); port = _s.getsockname()[1]; _s.close()
srv = subprocess.Popen(
    [GUNICORN, "-w", "1", "--threads", "4", "-b", f"127.0.0.1:{port}",
     "app.app:app"], cwd=REPO, env={**os.environ, "PYTHONPATH": str(REPO)},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close(); break
        except OSError:
            time.sleep(0.5)
    else:
        raise SystemExit("FAIL[guard]: own server never came up")
    seed_mod.require_own_server(f"http://127.0.0.1:{port}")

    from playwright.sync_api import sync_playwright

    BASE = f"http://127.0.0.1:{port}"
    fails = []
    total = [0]


    def check(name, ok, detail=""):
        total[0] += 1
        print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
        if not ok:
            fails.append(name)


    def set_fb_open(v):
        import sqlite3
        con = sqlite3.connect(os.path.join(DATA, "srm.db"))
        con.execute("UPDATE users SET fb_open=? WHERE netid='zz9999'", (v,))
        con.commit(); con.close()


    with sync_playwright() as p:
        b = p.chromium.launch()

        # ---------------- desktop 1280x900: the dashboard must FIT ----------
        ctx = b.new_context(viewport={"width": 1280, "height": 900},
                            device_scale_factor=2, service_workers="block")
        ctx.add_cookies([{"name": "srm_session", "value": token, "url": BASE}])
        pg = ctx.new_page()
        pg.goto(BASE + "/", wait_until="networkidle")
        check("auth (netid in title)", "zz9999" in pg.title(), pg.title())

        m = pg.evaluate("""() => {
          const de = document.documentElement;
          const nav = [...document.querySelectorAll('.navbar')]
            .find(n => getComputedStyle(n).display !== 'none');
          const main = document.querySelector('main');
          const ms = getComputedStyle(main);
          const g = document.querySelector('#tab-dashboard > .grid');
          const gr = g.getBoundingClientRect();
          const cards = [...g.querySelectorAll(':scope > .card')].map(c => {
            const body = c.querySelector('.card-body');
            return {h: Math.round(c.getBoundingClientRect().height),
                    bottom: Math.round(c.getBoundingClientRect().bottom),
                    scroll: body.scrollHeight - body.clientHeight,
                    span4: c.className.includes('col-span-4')};
          });
          return {innerH: window.innerHeight, docSH: de.scrollHeight, docCH: de.clientHeight,
                  navH: Math.round(nav.getBoundingClientRect().height),
                  padT: parseFloat(ms.paddingTop), padB: parseFloat(ms.paddingBottom),
                  gridTop: Math.round(gr.top), gridBottom: Math.round(gr.bottom),
                  gridH: Math.round(gr.height), cards};
        }""")
        check("no page scrollbar on desktop (scrollHeight <= clientHeight)",
              m["docSH"] <= m["docCH"], json.dumps(m))
        # pins the 94px CSS constant: grid must equal innerH - navH - pads
        expected = m["innerH"] - m["navH"] - m["padT"] - m["padB"]
        check("grid height == innerH - navH - padTop - padBottom (94px chrome)",
              abs(m["gridH"] - expected) <= 2,
              f"gridH={m['gridH']} expected={expected} navH={m['navH']} "
              f"padT={m['padT']} padB={m['padB']}")
        check("grid bottom leaves exactly the main bottom padding",
              abs((m["innerH"] - m["gridBottom"]) - m["padB"]) <= 2,
              f"bottom gap={m['innerH'] - m['gridBottom']} padB={m['padB']}")
        check("grid starts below navbar + top padding",
              abs(m["gridTop"] - (m["navH"] + m["padT"])) <= 2,
              f"gridTop={m['gridTop']} navH+padT={m['navH'] + m['padT']}")
        day = next((c for c in m["cards"] if c["span4"]), None)
        people = max((c for c in m["cards"] if not c["span4"]),
                     key=lambda c: c["h"], default=None)
        check("day column card fills the grid (bottom == grid bottom)",
              day is not None and abs(day["bottom"] - m["gridBottom"]) <= 2,
              f"day bottom={day and day['bottom']} gridBottom={m['gridBottom']}")
        check("bottom-row card fills the grid (uniform row bottom)",
              people is not None and abs(people["bottom"] - m["gridBottom"]) <= 2,
              f"card bottom={people and people['bottom']}")
        check("zero card-body residue scroll at standard desktop data",
              all(c["scroll"] == 0 for c in m["cards"]),
              str([(c["h"], c["scroll"]) for c in m["cards"]]))

        # notices widget caps instead of stretching the day column
        nw = pg.evaluate("""() => {
          const ws = [...document.querySelectorAll('.widget-scroll')];
          const n = ws.find(e => (e.closest('.wbox')?.querySelector('.wlabel')||{}).textContent === 'Notices');
          return n ? {ch: n.clientHeight, sh: n.scrollHeight} : null; }""")
        check("notices widget inside widget-scroll (capped, scrollable)",
              nw is not None and nw["ch"] <= 320 and nw["sh"] >= nw["ch"],
              str(nw))

        # ---- uniform edge (v1.20): the shell compensates the reserved
        # scrollbar strip so BOTH card-column edges land on 15px (red on the
        # pre-fix layout: left 16 / right 31 measured at 1920x1039) ----
        edge = pg.evaluate("""() => {
          const g = document.querySelector('#tab-dashboard > .grid');
          const r = g.getBoundingClientRect();
          const main = document.querySelector('main');
          const nav = document.querySelector('.navbar.hidden');
          return {left: Math.round(r.x), right: Math.round(window.innerWidth - r.right),
                  gap: getComputedStyle(g).gap,
                  padL: parseFloat(getComputedStyle(main).paddingLeft),
                  navPadL: parseFloat(getComputedStyle(nav).paddingLeft)}; }""")
        check("desktop: card column 15px on BOTH sides, gap 15, navbar aligned",
              edge["left"] == edge["right"] == 15 and edge["gap"] == "15px"
              and edge["padL"] == edge["navPadL"] == edge["left"],
              json.dumps(edge))

        # ---- widgets auto-adjust to the cell (v1.20): the two squeeze
        # viewports where the old fixed-height widgets made cards scroll while
        # their lists already scrolled internally (people card resid +26px @
        # 1920x944, +228px @ 1366x768 — this check is red without the flex
        # chain) ----
        for vw, vh in [(1920, 944), (1366, 768)]:
            pg.set_viewport_size({"width": vw, "height": vh})
            pg.wait_for_timeout(300)
            res = pg.evaluate("""() => [...document.querySelectorAll('#tab-dashboard .card-body')]
                .map(b => b.scrollHeight - b.clientHeight)""")
            check(f"zero card-body residue at {vw}x{vh} (widgets absorb the cell)",
                  all(x == 0 for x in res), str(res))
        pg.set_viewport_size({"width": 1280, "height": 900})
        pg.wait_for_timeout(300)

        # ---- task 1: feedback CTA follows fb_open (render-level) ----------
        check("fb_open=1: Auto-fill CTA rendered",
              pg.locator("#fb-cta").count() == 1)
        check("fb_open=1: explainer modal rendered",
              pg.locator("#fb-modal").count() == 1)
        set_fb_open(0)
        pg.reload(wait_until="networkidle")
        check("fb_open=0: CTA archived (absent)",
              pg.locator("#fb-cta").count() == 0)
        check("fb_open=0: modal archived (absent)",
              pg.locator("#fb-modal").count() == 0)
        check("fb_open=0: Teachers list itself stays (historical data)",
              pg.locator('#tab-dashboard .wbox:has(.wlabel:text-is("Teachers"))').count() == 1)
        check("fb_open=0: no page-level fit regression",
              pg.evaluate("document.documentElement.scrollHeight <= document.documentElement.clientHeight"))
        set_fb_open(1)
        pg.reload(wait_until="networkidle")
        check("auto-unarchive: next render brings CTA + modal back",
              pg.locator("#fb-cta").count() == 1 and pg.locator("#fb-modal").count() == 1)
        ctx.close()

        # ---------------- mobile 393x851: scrolling is FINE -----------------
        ctx2 = b.new_context(viewport={"width": 393, "height": 851},
                             device_scale_factor=2.75, service_workers="block")
        ctx2.add_cookies([{"name": "srm_session", "value": token, "url": BASE}])
        pg2 = ctx2.new_page()
        pg2.goto(BASE + "/", wait_until="networkidle")
        mm = pg2.evaluate("""() => {
          const de = document.documentElement;
          const g = document.querySelector('#tab-dashboard > .grid');
          return {docSH: de.scrollHeight, docCH: de.clientHeight,
                  sw: de.scrollWidth, cw: de.clientWidth,
                  gridH: Math.round(g.getBoundingClientRect().height),
                  innerH: window.innerHeight}; }""")
        check("mobile keeps page flow (scrollHeight > clientHeight)",
              mm["docSH"] > mm["docCH"], json.dumps(mm))
        check("mobile grid not viewport-locked (natural stacked height)",
              mm["gridH"] > mm["innerH"], f"gridH={mm['gridH']}")
        check("mobile no horizontal overflow",
              mm["sw"] <= mm["cw"], f"sw={mm['sw']} cw={mm['cw']}")
        check("mobile still renders the CTA", pg2.locator("#fb-cta").count() == 1)
        ctx2.close()
        b.close()
finally:
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except subprocess.TimeoutExpired:
        srv.kill()

print(f"\n{total[0] - len(fails)}/{total[0]} passed" if not fails else f"\nFAILED ({len(fails)}/{total[0]}): {fails}")
sys.exit(1 if fails else 0)
