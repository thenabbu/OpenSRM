"""
Sync-carries-DATA DUT (W5.1b).

HISTORY: a sync used to re-fetch THIS route's HTML and swap <main> out
(idiomorph, plus three hand-carried compensations: re-focus the old id,
re-open the open <details>, re-show the attendance table view). That destroyed
the nodes the user was looking at, so the browser clamped scrollY — observed
250 -> 0 on a phone — and it cost ~60 KB of re-downloaded, re-parsed markup to
change one number.

THE CONTRACT NOW: `/api/refresh` answering `{ok:true, cached:false}` makes every
mounted island refetch its OWN `/api` slice and Preact patches the text nodes
that changed. This suite asserts the consequence directly, because a
"scroll preserved" number alone can be true for a sync that did nothing:

  1. a tagged node is the SAME object after a quiet sync (node identity);
  2. the changed number IS updated in place (identity alone proves nothing);
  3. no page markup is fetched on the sync path — only /api/* slices;
  4. scroll, focus, the open <details>, the attendance view and the avatar's
     inline gaze vars survive BY CONSTRUCTION;
  5. delegated listeners (click-to-copy, marks tag save) still work afterwards.

Run:  python tests/e2e/test_sync_data_dut.py   (needs a seeded server on
DUT_BASE whose DATA_DIR this test also writes to, like test_marks_dut).
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-sync-data")
from _seed import seed_rich, mint_token, require_own_server

seed_rich(with_payload=True)
from app.app import db

# seed_rich gives the tall real dashboard (personal details with data-copy
# values, multiple subjects); graft an FT-II component onto subject 1 so the
# tag round-trip has a second component to confirm.
c = db()
MARKS = json.loads(c.execute(
    "SELECT marks_json FROM users WHERE netid='zz9999'").fetchone()[0])
MARKS[0]["components"].append(
    {"name": "FT-II", "entered": "09/Sep/2026", "scored": 11.7, "max": 15.0})
c.execute("UPDATE users SET marks_json=? WHERE netid='zz9999'",
          (json.dumps(MARKS),))
c.execute("DELETE FROM component_tags")
c.commit(); c.close()

TOK = mint_token()
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18180")
require_own_server(BASE)
results = []

def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

# ── static contract (the deletion actually happened) ─────────────────
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "..", "..", "app", "static", "dash.js"), encoding="utf-8").read()
code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))
check("dash.js: the sync never re-fetches the route's markup",
      "location.pathname + location.search" not in code)
check("dash.js: no morph library / markup swap left",
      not any(t in code for t in ("Idiomorph", "DOMParser", "outerHTML", "replaceChild")))
check("dash.js: no hard reload on the sync path", "location.reload(" not in code)
check("vendored morph library is deleted",
      not os.path.exists(os.path.join(here, "..", "..", "app", "static", "vendor",
                                      "idiomorph.min.js")))

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    # 393x400: /marks overflows the window at this height, so the scroll check
    # works with zero clicks between setup and the quiet sync (a click would
    # light-dismiss the open tag panel).
    ctx = b.new_context(viewport={"width": 393, "height": 400},
                        permissions=["clipboard-read", "clipboard-write"])
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg = ctx.new_page()

    # the sync API is intercepted: no portal contact, deterministic answer
    pg.route("**/api/refresh", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "cached": False})))

    pg.goto(BASE + "/marks", wait_until="load")
    pg.wait_for_timeout(2500)      # let the boot auto-sync settle first
    pg.evaluate("window.__alive = true")

    # ── LEG A: a quiet sync repaints DATA over the SAME nodes ─────────
    pg.click("#tab-marks .py-1 summary >> nth=0")   # open the first tag panel
    pg.wait_for_timeout(250)
    pg.evaluate("""() => {
      window.__detNode = document.querySelector('#tab-marks details[id]');
      window.__focusNode = document.activeElement;     // the summary just clicked
      // an island-rendered row: the node a full-page swap used to replace
      window.__rowNode = [...document.querySelectorAll('#tab-marks .py-1')][0];
    }""")
    check("setup: first marks panel is open (real click set the attribute)",
          pg.evaluate("window.__detNode.open === true && window.__detNode.hasAttribute('open')"))
    pg.evaluate("window.scrollTo(0, 300)")   # marks tab overflows at 400px height
    state_before = pg.evaluate("""() => ({
      scrollY: window.scrollY,   // may clamp below 300 — compare like for like
      focusTag: document.activeElement.tagName,
    })""")

    # change the data the refreshed page must show: FT-I scored 4.5 -> 3.0
    for cp in MARKS[0]["components"]:
        if cp["name"] == "FT-I":
            cp["scored"] = 3.0
    c = db()
    c.execute("UPDATE users SET marks_json=? WHERE netid='zz9999'",
              (json.dumps(MARKS),))
    c.commit(); c.close()

    seen = []
    pg.on("request", lambda r: seen.append(r.url))
    # quiet sync — exactly what the 10-minute auto-sync runs; no click, no dismiss
    pg.evaluate("ref(true)")
    pg.wait_for_timeout(2500)

    check("quiet sync caused NO navigation (still /marks, dashboard never swapped in)",
          pg.evaluate("window.__alive === true && location.pathname === '/marks'"
                      " && !document.getElementById('tab-dashboard')"))
    # THE ACCEPTANCE ASSERTION (W8 owns the 10-run contract test; this is the
    # one-run proof it exists).
    check("node identity: the island's row is the SAME object after the sync",
          pg.evaluate("window.__rowNode === [...document.querySelectorAll('#tab-marks .py-1')][0]"))
    check("node identity: the open <details> is the SAME object (not re-opened by hand)",
          pg.evaluate("window.__detNode.isConnected && window.__detNode.open === true"
                      " && window.__detNode === document.querySelector('#tab-marks details[id]')"))
    ft_row = pg.evaluate("""() => {
      const rows = [...document.querySelectorAll('#tab-marks .py-1')];
      const row = rows.find(r => r.textContent.includes('FT-I'));
      return row ? (row.textContent.match(/3(\\.0)?\\/5/) || [null])[0] : 'no-row';
    }""")
    check("updated data rendered in place (FT-I now 3/5)", ft_row in ("3/5", "3.0/5"), str(ft_row))
    check("scroll position survived (window scroll unchanged)",
          pg.evaluate("window.scrollY") == state_before["scrollY"],
          f"before {state_before['scrollY']} after {pg.evaluate('window.scrollY')}")
    check("focus preserved (same node or body)",
          pg.evaluate("""() => document.activeElement === window.__focusNode ||
                               document.activeElement === document.body"""),
          pg.evaluate("document.activeElement.tagName"))
    api_calls = [u for u in seen if "/api/" in u]
    page_fetches = [u for u in seen if "/api/" not in u and not u.endswith((".js", ".css"))]
    check("the sync fetched /api slices, not this route's HTML",
          bool(api_calls) and not page_fetches,
          f"api={len(api_calls)} other={page_fetches[:3]}")
    check("the marks island's own feed fed the update (/api/marks/island)",
          any("/api/marks/island" in u for u in seen), str(api_calls[:4]))

    # ── LEG B: a CLICKED sync — no navigation, no focus theft ─────────
    pg.evaluate("window.__alive = true")
    pg.click('[data-refresh]:visible')
    pg.wait_for_timeout(1800)
    check("clicked sync caused NO navigation", pg.evaluate("window.__alive === true"))
    check("no focus theft after the clicked sync",
          pg.evaluate("""() => document.activeElement === document.body ||
                               document.activeElement.matches('[data-refresh]')"""),
          pg.evaluate("document.activeElement.tagName"))
    check("overlay modal no longer exists in the DOM",
          pg.evaluate("document.getElementById('overlay') === null"))

    # ── LEG C: the page-level handlers still work on repainted nodes ──
    pg.click('.navbar [data-tab="dashboard"]:visible, .dock [data-tab="dashboard"]:visible')
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(400)
    tgt = pg.query_selector("#tab-dashboard [data-copy]")
    if tgt:
        tgt.click()
        pg.wait_for_timeout(150)
        flashed = pg.evaluate(
            "() => document.querySelector('#tab-dashboard [data-copy]').textContent")
        check("click-to-copy works after a repaint", flashed == "Copied!", str(flashed))
    else:
        check("click-to-copy works after a repaint", False, "no data-copy target")
    # the dashboard repaints from /api/dashboard, and must keep the avatar's
    # inline gaze vars (they are the reason the old code hand-carried this node)
    dash = pg.evaluate("""() => {
        const el = document.querySelector('.blobatar-gaze');
        el.style.setProperty('--mo-test-marker', 'kept');
        return el.style.getPropertyValue('--mo-test-marker'); }""")
    pg.evaluate("async () => { await window.__osrmRefreshData(); }")
    pg.wait_for_timeout(600)
    check("dashboard repaint kept the avatar node and its inline gaze vars",
          pg.evaluate("document.querySelector('.blobatar-gaze')"
                      ".style.getPropertyValue('--mo-test-marker')") == dash,
          str(dash))

    # ── LEG D: the tag form (a write through the same island) ─────────
    pg.click('.navbar [data-tab="marks"]:visible, .dock [data-tab="marks"]:visible')
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(400)
    pg.evaluate("window.__alive = true")   # fresh document after the real navigation
    pg.click("#tab-marks .py-1 summary >> nth=0")
    pg.wait_for_timeout(250)
    pg.select_option("#tab-marks details[open] select[name=role]", "IE-1")
    pg.click("#tab-marks details[open] button:has-text('Save')")
    pg.wait_for_timeout(1500)
    check("tag save: no navigation, still the same page",
          pg.evaluate("window.__alive === true"))
    check("tag save: still on the /marks route, no hash",
          pg.evaluate("location.pathname + location.hash") == "/marks")
    c = db()
    row = c.execute("SELECT role FROM component_tags").fetchall()
    c.close()
    check("tag persisted through the fetch path", [r[0] for r in row] == ["IE-1"], str(row))
    c = db(); c.execute("DELETE FROM component_tags"); c.commit(); c.close()
try:
    b.close()   # route handlers can leave the sync loop closed — teardown only
except Exception:
    pass

fails = [n for n, ok in results if not ok]
print(f"\nTOTAL: {len(results)} checks | PASS {len(results)-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
