"""
Timetable-EDIT DUT (W5.4a).

HISTORY: `app/static/timetable.js` was the ONLY thing that could edit a
timetable, and `TimetablePanel.tsx` renders the read-only day panels only.
Nothing tested the editor, so the 9 matrix rows were STILL-LEGACY with no
coverage at all. This suite exercises EDIT, not render: it assigns a slot,
saves it, and proves it SURVIVED A RELOAD.

Two things make that possible, and both are the point of the suite:

  * the editor is ARCHIVED by default (TIMETABLE_EDITOR=archived): #tt-edit-btn
    does not render and POST /api/timetable answers 403. This suite boots its
    OWN gunicorn with TIMETABLE_EDITOR=enabled — the DUT asserts BOTH modes so
    the archive contract cannot silently regress either.
  * the bundle bound the editor BEFORE the classic script was deleted, and
    `timetable.js` skips init when `window.__osrmTimetableEditor` exists. The
    suite asserts the bundle bound it and that one Save is ONE POST.

Run:  python tests/e2e/test_timetable_edit_dut.py
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
os.environ["DATA_DIR"] = "/tmp/osrm-tt-edit-dut"
shutil.rmtree("/tmp/osrm-tt-edit-dut", ignore_errors=True)

import tests._seed as seed_mod

seed_mod.seed(with_payload=False)
TOK = seed_mod.mint_token()

GUNICORN = os.environ.get("GUNICORN") or os.path.join(os.path.dirname(sys.executable), "gunicorn")
if not os.path.isfile(GUNICORN):
    raise SystemExit(f"FAIL[guard]: missing {GUNICORN} (run with the repo .venv's python)")

fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def boot(port, editor):
    """gunicorn from THIS tree, with TIMETABLE_EDITOR pinned either way."""
    env = {**os.environ, "PYTHONPATH": str(REPO), "LOG_LEVEL": "ERROR",
           "TIMETABLE_EDITOR": editor,
           "SCOPE_FEATURES": "hourwise,academics,fees,profile,attendance,marks,campus"}
    p = subprocess.Popen(
        [GUNICORN, "-w", "1", "--threads", "4", "-b", f"127.0.0.1:{port}", "app.app:app"],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close()
            return p
        except OSError:
            time.sleep(0.5)
    p.kill()
    raise SystemExit("FAIL[guard]: server never came up")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


from playwright.sync_api import sync_playwright

port = free_port()
BASE = f"http://127.0.0.1:{port}"
srv = boot(port, "enabled")
seed_mod.require_own_server(BASE)

try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: fails.append(f"pageerror: {e}"))

        pg.goto(BASE + "/", wait_until="networkidle")
        pg.click("#tab-timetable-tab")
        pg.wait_for_selector("#tab-timetable", state="visible")
        pg.wait_for_timeout(400)

        # ── tt-open-editor ────────────────────────────────────────────────
        # The marker alone proves the MODULE is in the bundle, not that it BOUND.
        # With timetable.js still on the page, an unbound bundle is masked: the
        # classic script binds the same ids and every later assertion passes.
        # Verified by breaking it: deleting `bindTimetableEditor()` from main.ts
        # left this suite green until these two checks existed.
        check("bundle published the editor bridge",
              pg.evaluate("typeof window.__osrmTimetableEditor === 'function'"))
        check("bundle ACTUALLY bound the editor (timetable.js did NOT)",
              pg.evaluate("!!window.__osrmTimetableEditorBound"))
        check("edit entry point rendered when enabled",
              pg.locator("#tt-edit-btn").count() == 1)

        pg.click("#tt-edit-btn")
        pg.wait_for_selector("#tt-editor", state="visible")
        pg.wait_for_selector(".tt-grid-cell", state="visible")
        check("editor opens and the day panels hide",
              pg.locator("#tab-timetable-view").is_hidden())
        check("grid painted by the bundle (13-class header + cells)",
              pg.locator(".tt-grid-cell").count() == 35
              and pg.locator(".tt-grid-header .tt-grid-time").count() == 7)
        check("save/cancel/add actions un-hidden",
              all(not pg.locator(f"#{i}").is_hidden()
                  for i in ("tt-save-btn", "tt-cancel-btn", "tt-add-subject-btn")))

        # ── tt-add-subject ────────────────────────────────────────────────
        palette_before = pg.locator(".tt-subject-block").count()
        pg.click("#tt-add-subject-btn")
        pg.wait_for_selector("#add-subject-modal[open]")
        pg.fill("#subj-code", "zz9001")
        pg.fill("#subj-name", "Dut Subject")
        pg.click("#subj-confirm-btn")
        pg.wait_for_timeout(200)
        check("add-subject appends one palette block",
              pg.locator(".tt-subject-block").count() == palette_before + 1)
        check("add-subject uppercases the code",
              pg.locator('.tt-subject-block[data-code="ZZ9001"]').count() == 1)

        # ── selection + place (tt-open-editor / palette) ──────────────────
        TARGET = "Thursday-5"
        cell = pg.locator(f'.tt-grid-cell[data-key="{TARGET}"]')
        cell.click()
        check("cell selection is marked", cell.evaluate("n => n.classList.contains('tt-cell-sel')"))
        pg.locator('.tt-subject-block[data-code="ZZ9001"]').click()
        pg.wait_for_timeout(150)
        check("subject lands in the selected slot",
              cell.locator(".cell-code").inner_text() == "ZZ9001",
              cell.locator(".cell-code").inner_text() if cell.locator(".cell-code").count() else "empty")

        # ── tt-cell-remove ────────────────────────────────────────────────
        cell.locator(".cell-remove").click()
        pg.wait_for_timeout(120)
        check("remove button clears the cell", cell.locator(".cell-code").count() == 0)
        # put it back: this is what must be saved
        cell.click()
        pg.locator('.tt-subject-block[data-code="ZZ9001"]').click()
        pg.wait_for_timeout(120)

        # ── tt-save: exactly ONE POST, then it is on the server ───────────
        posts = []
        pg.on("request", lambda r: posts.append(r.url)
              if r.url.endswith("/api/timetable") and r.method == "POST" else None)
        with pg.expect_response(lambda r: r.url.endswith("/api/timetable") and r.request.method == "POST"):
            pg.click("#tt-save-btn")
        pg.wait_for_timeout(500)
        check("ONE POST per Save (bundle owns it, timetable.js stood down)",
              len(posts) == 1, f"posts={len(posts)}")
        check("editor closes after a successful save",
              pg.locator("#tt-editor").is_hidden())

        # ── persistence: the slot SURVIVES A RELOAD ───────────────────────
        pg.reload(wait_until="networkidle")
        pg.click("#tab-timetable-tab")
        pg.wait_for_selector("#tab-timetable", state="visible")
        pg.wait_for_timeout(400)

        api = ctx.request.get(BASE + "/api/timetable").json()
        check("server holds the saved slot after reload",
              (api.get("slots") or {}).get(TARGET, {}).get("code") == "ZZ9001",
              json.dumps((api.get("slots") or {}).get(TARGET)))

        pg.click("#tt-edit-btn")
        pg.wait_for_selector(".tt-grid-cell", state="visible")
        check("reopened editor shows the saved slot (round trip)",
              pg.locator(f'.tt-grid-cell[data-key="{TARGET}"] .cell-code').inner_text() == "ZZ9001")
        check("saved custom subject is in the palette",
              pg.locator('.tt-subject-block[data-code="ZZ9001"]').count() == 1)

        # ── tt-edit-history ───────────────────────────────────────────────
        hist = ctx.request.get(BASE + "/api/timetable/history").json()
        check("the save is in the edit log", bool(hist.get("entries")), str(len(hist.get("entries") or [])))
        check("history panel rendered an entry",
              pg.locator("#tt-history-list").inner_text().strip() != ""
              and "Could not load" not in pg.locator("#tt-history-list").inner_text())

        # ── tt-close-editor: cancel discards, it does not save ────────────
        cell2 = pg.locator('.tt-grid-cell[data-key="Friday-2"]')
        cell2.click()
        pg.locator('.tt-subject-block[data-code="ZZ9001"]').click()
        pg.wait_for_timeout(120)
        pg.click("#tt-cancel-btn")
        pg.wait_for_timeout(300)
        check("cancel closes the editor", pg.locator("#tt-editor").is_hidden())
        after = ctx.request.get(BASE + "/api/timetable").json()
        check("cancel did NOT save the pending change",
              not ((after.get("slots") or {}).get("Friday-2")),
              json.dumps((after.get("slots") or {}).get("Friday-2")))

        ctx.close()
        b.close()
finally:
    srv.send_signal(signal.SIGTERM)
    try:
        srv.wait(timeout=10)
    except subprocess.TimeoutExpired:
        srv.kill()

# ── archived default: the editor must stay gone ───────────────────────────
port2 = free_port()
BASE2 = f"http://127.0.0.1:{port2}"
srv2 = boot(port2, "archived")
seed_mod.require_own_server(BASE2)
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE2}])
        pg = ctx.new_page()
        pg.goto(BASE2 + "/", wait_until="networkidle")
        pg.click("#tab-timetable-tab")
        pg.wait_for_selector("#tab-timetable", state="visible")
        pg.wait_for_timeout(300)
        check("archived: no edit entry point", pg.locator("#tt-edit-btn").count() == 0)
        r = ctx.request.post(BASE2 + "/api/timetable",
                             data='{"slots": {}, "custom_subjects": []}',
                             headers={"Content-Type": "application/json"})
        check("archived: save API still 403", r.status == 403, str(r.status))
        ctx.close()
        b.close()
finally:
    srv2.send_signal(signal.SIGTERM)
    try:
        srv2.wait(timeout=10)
    except subprocess.TimeoutExpired:
        srv2.kill()

print()
print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)
