"""P10.1 rollback flag — PREACT_ISLANDS.

Contract: the boot flag (AppConfig.preact_islands, env PREACT_ISLANDS) gates
ONLY the island module tag. Default is ON — PREACT_ISLANDS unset must still
hydrate, or the whole migration silently dies in prod. Off = stop hydrating;
the server-rendered panels are the app (no 500, no blank page).

Self-contained: temp DATA_DIR, seeded user, minted session. No server, no
network, no portal. Runner style: check(name, ok, detail).
"""
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import atexit

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

TMP = tempfile.mkdtemp(prefix="osrm-rollback-")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
os.environ["DATA_DIR"] = TMP
os.environ["OCR_PREWARM"] = "0"
os.environ.pop("PREACT_ISLANDS", None)   # unset IS the default case

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


def make_config(dirpath, **kw):
    return AppConfig(data_dir=dirpath, db_path=os.path.join(dirpath, "srm.db"),
                     secret_path=os.path.join(dirpath, "secret"), prewarm_ocr=False, **kw)


def seed_user(app_obj):
    """users row for NETID so /attendance renders real server-side rows."""
    att = {"courses": [
        {"code": "21CSC201J", "description": "DATA STRUCTURES",
         "max_hours": "40", "attended": "30", "absent": "10"},
        {"code": "21CSC202J", "description": "DBMS",
         "max_hours": "40", "attended": "20", "absent": "20"}],
        "period": {"from": "20/Jul/2026", "to": "13/Oct/2026"}, "monthly": []}
    personal = {"name": "Fabricated Student", "program": "CSE Cloud Computing",
                "batch": 2025, "semester": 3, "section": "A"}
    with app_obj.app_context():
        c = sqlite3.connect(app_obj.config["DB_PATH"])
        c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
                     attendance_json, last_fetch) VALUES(?,?,?,?,?)""",
                  (NETID, "pw", json.dumps(personal), json.dumps(att), int(time.time())))
        c.execute("DELETE FROM cookies WHERE token=?",
                  (hashlib.sha256(TOKEN.encode()).hexdigest(),))
        c.execute("INSERT INTO cookies(token,netid,created) VALUES(?,?,?)",
                  (hashlib.sha256(TOKEN.encode()).hexdigest(), NETID, int(time.time())))
        c.commit()
        c.close()


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


# 1) the default: unset env -> True (the flag must never default off)
cfg_default = AppConfig.from_env()
check("PREACT_ISLANDS unset -> config True", cfg_default.preact_islands is True)

os.environ["PREACT_ISLANDS"] = "0"
check("PREACT_ISLANDS=0 -> config False", AppConfig.from_env().preact_islands is False)
os.environ["PREACT_ISLANDS"] = ""
check("PREACT_ISLANDS='' -> config True (empty = unset)", AppConfig.from_env().preact_islands is True)
os.environ.pop("PREACT_ISLANDS", None)

# 2) flag ON (default): the island hydrates
code_on, html_on = render(boot("on"))
check("flag ON: /attendance 200", code_on == 200, str(code_on))
check("flag ON: island module tag present", ISLAND in html_on,
      f'{html_on.count(ISLAND)} module tag(s)')
check("flag ON: asset_dist('app') entry emitted", "/static/dist/assets/" in html_on)

# 3) flag OFF: no island tag, still a real page with server-rendered rows
code_off, html_off = render(boot("off", preact_islands=False))
check("flag OFF: /attendance 200 (no 500)", code_off == 200, str(code_off))
check("flag OFF: no island module tag", ISLAND not in html_off,
      f'{html_off.count(ISLAND)} module tag(s)')
check("flag OFF: not a blank page", len(html_off) > 2000, f"{len(html_off)} bytes")
# rows the panels render SERVER-side: one <td class="att-subj"> per seeded course
rows = html_off.count('class="att-subj"')
check("flag OFF: 2 server-rendered course rows in HTML", rows == 2, f"{rows} att-subj cells")
check("flag OFF: seeded course names title-cased in the rows",
      "Data Structures" in html_off and "Dbms" in html_off)
check("flag OFF: legacy dash.js still shipped", "dash.js" in html_off)
check("flag OFF: page still an HTML document", "<html" in html_off.lower() and "</html>" in html_off.lower())

# 4) structure: differ by the island tag only-ish — ON must be a superset
check("ON html is strictly longer than OFF (only the tag is skipped)",
      len(html_on) > len(html_off), f"{len(html_on)} vs {len(html_off)}")

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} passed")
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    sys.exit(1)
