"""DUT for the official-timetable UI: seed official rows, boot, drive the
browser, DOM-assert the contract, screenshot desktop+mobile for vision QA."""
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ["DATA_DIR"] = "/tmp/osrm-tt-dut"

import shutil

shutil.rmtree("/tmp/osrm-tt-dut", ignore_errors=True)

import tests._seed as seed_mod

seed_mod.seed(with_payload=False)

# official grid for the seeded group (real fixture, sanitized)
import app.app as A

tt = A.parse_timetable((REPO / "tests/fixtures/timetable_form10.html").read_text())
A._save_timetable_group("ng2776", {"personal": seed_mod.PERSONAL, "courses": [], "timetable": tt})
token = seed_mod.mint_token()

GUNICORN = "/opt/data/opensrm-repo/.venv/bin/gunicorn"
if not os.path.isfile(GUNICORN):
    raise SystemExit(f"FAIL[guard]: missing {GUNICORN} (an OpenSRM checkout .venv)")
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
srv = subprocess.Popen(
    [GUNICORN, "-w", "1", "--threads", "4", "-b", f"127.0.0.1:{port}",
     "app.app:app"], cwd=REPO, env={**os.environ, "PYTHONPATH": str(REPO)},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    try:
        socket.create_connection(("127.0.0.1", port), 0.5).close(); break
    except OSError:
        time.sleep(0.5)
else:
    raise SystemExit("FAIL[guard]: own server never came up")
seed_mod.require_own_server(f"http://127.0.0.1:{port}")

from playwright.sync_api import sync_playwright

OUT = Path("/opt/data/cache/scratch/tt-dut"); OUT.mkdir(exist_ok=True)
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


try:
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--font-render-hinting=none", "--force-color-profile=srgb"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900},
                            device_scale_factor=2)
        ctx.add_cookies([{"name": "srm_session", "value": token, "url": f"http://127.0.0.1:{port}"}])
        pg = ctx.new_page()
        pg.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
        pg.click("#tab-timetable-tab")
        pg.wait_for_selector("#tab-timetable", state="visible")
        pg.wait_for_timeout(400)

        body = pg.inner_text("#tab-timetable")
        check("synced badge removed (obsolete)", "Synced from portal" not in body)
        check("edit history archived (absent)", "Edit history" not in body)
        check("corrected 09:30 rendered", "09:30" in body)
        check("no raw 08:30 anywhere", "08:30" not in body)
        check("legacy 16:00 gone", "16:00" not in body)
        check("lunch divider present", "Lunch" in body)

        # archive contract (default TIMETABLE_EDITOR=archived): no edit entry
        check("edit button archived (absent)", pg.locator("#tt-edit-btn").count() == 0)
        resp = ctx.request.post(f"http://127.0.0.1:{port}/api/timetable",
                                data='{"slots": {}, "custom_subjects": []}',
                                headers={"Content-Type": "application/json"})
        check("save API 403 while archived", resp.status == 403, str(resp.status))
        pg.screenshot(path=str(OUT / "1-desktop-timetable.png"))
        ctx.close()

        # mobile 393px (DUT convention)
        ctx2 = b.new_context(viewport={"width": 393, "height": 852}, device_scale_factor=2,
                             is_mobile=True, has_touch=True)
        ctx2.add_cookies([{"name": "srm_session", "value": token, "url": f"http://127.0.0.1:{port}"}])
        pg2 = ctx2.new_page()
        pg2.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
        pg2.click("button[aria-label='Timetable tab']")
        pg2.wait_for_timeout(500)
        mbody = pg2.inner_text("#tab-timetable")
        check("mobile: synced badge absent", "Synced from portal" not in mbody)
        sw = pg2.evaluate("document.documentElement.scrollWidth")
        check("no horizontal overflow @393", sw <= 393, f"scrollWidth={sw}")
        pg2.screenshot(path=str(OUT / "3-mobile-timetable.png"), full_page=False)
        ctx2.close()
        b.close()
finally:
    srv.send_signal(signal.SIGTERM)
    try:
        srv.wait(timeout=10)
    except subprocess.TimeoutExpired:
        srv.kill()

print()
print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)
