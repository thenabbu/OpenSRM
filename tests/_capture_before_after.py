"""Before/after capture for PR #44 body: SAME seeded timetable, two code bases.
before = origin/main checkout (no feature), after = this worktree."""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

WORKTREE = Path("/opt/data/cache/scratch/tt-official/wt")
MAIN = Path("/opt/data/opensrm-repo")
OUT = Path("/opt/data/cache/scratch/tt-dut")
DB_DIR = Path("/tmp/osrm-tt-pair")
shutil.rmtree(DB_DIR, ignore_errors=True)
OUT.mkdir(exist_ok=True)

# ── phase 1: seed a schema-13 DB with a full legacy grid via MAIN code ──
sys.path.insert(0, str(MAIN))
os.environ["DATA_DIR"] = str(DB_DIR)
import app.app as A  # main checkout: no parse_timetable / no feature

PERSONAL = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
            "Batch": "2025", "Semester": "III SEMESTER", "Section": "A"}
c = A.db()
c.execute("INSERT INTO users(netid,password,attendance_json,last_fetch,personal_details_json) "
          "VALUES('ng2776','unused-by-tests','{}',?,?)", (int(time.time()), json.dumps(PERSONAL)))
gk = A._group_key(PERSONAL)
c.execute("INSERT INTO timetable_groups(group_key,program,batch,semester,section) VALUES(?,?,?,?,?)",
          (gk, "CSE Cloud Computing", 2025, 3, "A"))
gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()[0]
# read the fixture's grid through the worktree parser in a child process
proc = subprocess.run(
    ["/opt/data/opensrm-repo/.venv/bin/python", "-c",
     f"import sys,os;sys.path.insert(0,'{WORKTREE}');os.environ['DATA_DIR']='{DB_DIR}-parse';"
     "import logging;logging.disable(logging.CRITICAL);import app.app as A;"
     f"tt=A.parse_timetable(open('{WORKTREE}/tests/fixtures/timetable_form10.html').read());"
     "print(__import__('json').dumps(tt['grid']))"],
    capture_output=True, text=True)
grid = json.loads(proc.stdout.strip().splitlines()[-1])
for day, slots in grid.items():
    for p, code in slots.items():
        name = "SOFTWARE DESIGN PATTERNS" if code == "21CSC101T" else code
        c.execute("INSERT INTO timetable_slots(group_id,day,period,subject_code,subject_name,location) "
                  "VALUES(?,?,?,?,?,?)", (gid, day, int(p), code, name, ""))
# three attendance tiers round-robined over the codes → rim colours (grey/
# faded yellow/faded red) render in BOTH phases' shots (the rim exists on main)
TIER = [(40, 40), (3, 4), (1, 4)]
_codes = sorted({s for slots in grid.values() for s in slots.values()})
c.execute("UPDATE users SET attendance_json=? WHERE netid='ng2776'",
          (json.dumps({"courses": [
              {"code": cd, "description": cd, "attended": TIER[i % 3][0], "max_hours": TIER[i % 3][1]}
              for i, cd in enumerate(_codes)]}),))
c.commit(); c.close()
from app.app import make_session_token

token = make_session_token("ng2776")
print("seeded:", len(grid), "days; schema:", end=" ")
import sqlite3

print(sqlite3.connect(DB_DIR / "srm.db").execute("SELECT MAX(version) FROM schema_version").fetchone())

# drop the feature's offline-parse temp dir if created
shutil.rmtree(f"{DB_DIR}-parse", ignore_errors=True)


def serve(cwd, extra_env=None):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    p = subprocess.Popen(
        ["/opt/data/opensrm-repo/.venv/bin/gunicorn", "-w", "1", "--threads", "4",
         "-b", f"127.0.0.1:{port}", "app.app:app"], cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(cwd), **(extra_env or {})},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close()
            return p, port
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


from playwright.sync_api import sync_playwright


def shots(port, prefix, editor_prefix):
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--font-render-hinting=none", "--force-color-profile=srgb"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        ctx.add_cookies([{"name": "srm_session", "value": token, "url": f"http://127.0.0.1:{port}"}])
        pg = ctx.new_page()
        pg.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
        pg.click("#tab-timetable-tab")
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(OUT / prefix))
        ctx.close(); b.close()


# ── before: main checkout (feature absent) ──────────────────────────────
srv, port = serve(str(MAIN))
shots(port, "0-before-desktop.png", "0b-before-editor.png")
srv.send_signal(signal.SIGTERM); srv.wait(timeout=10)
print("before captured")

# ── promote the same DB to official state via the WORKTREE code ─────────
sys.path.insert(0, str(WORKTREE))
proc = subprocess.run(
    ["/opt/data/opensrm-repo/.venv/bin/python", "-c",
     f"import sys,os,json;sys.path.insert(0,'{WORKTREE}');os.environ['DATA_DIR']='{DB_DIR}';"
     "import logging;logging.disable(logging.CRITICAL);import app.app as A;"
     f"tt=A.parse_timetable(open('{WORKTREE}/tests/fixtures/timetable_form10.html').read());"
     "A._save_timetable_group('ng2776',{'personal':" + json.dumps(PERSONAL) +
     ",'courses':[],'timetable':tt});print('official rows written')"],
    capture_output=True, text=True)
print(proc.stdout.strip().splitlines()[-1], proc.stderr[-200:] if proc.returncode else "")

# ── after: worktree (feature present) ───────────────────────────────────
srv, port = serve(str(WORKTREE))
shots(port, "1-desktop-timetable.png", "2-desktop-editor.png")
# mobile after
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 393, "height": 852}, device_scale_factor=2,
                        is_mobile=True, has_touch=True)
    ctx.add_cookies([{"name": "srm_session", "value": token, "url": f"http://127.0.0.1:{port}"}])
    pg = ctx.new_page()
    pg.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
    pg.click("button[aria-label='Timetable tab']")
    pg.wait_for_timeout(400)
    body = pg.inner_text("#tab-timetable")
    print("after mobile: synced badge absent:", "Synced from portal" not in body)
    pg.screenshot(path=str(OUT / "3-mobile-timetable.png"))
    ctx.close(); b.close()
srv.send_signal(signal.SIGTERM); srv.wait(timeout=10)
print("after captured")
