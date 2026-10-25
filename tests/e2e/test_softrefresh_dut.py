"""
Soft-refresh DUT — smoothness campaign phase 4.

Two sync legs:
  A) a QUIET sync (ref(true), what the 10-minute auto-sync runs) morphs in
     place and must preserve every piece of user state: scroll, the open
     marks panel (same node), the attendance view choice, avatar gaze vars,
     push-card client state, focus, and it must render the new data.
  B) a CLICKED sync must not navigate, must not dump focus on a random
     element, and the delegated listeners (click-to-copy, marks tag form)
     must work on freshly morphed nodes.

Note: clicking refresh is itself an outside-click — the tag panel's
light-dismiss closing on a click-triggered sync is by design (test_marks_dut
pins that dismiss), so state survival is measured on the quiet path.

Run:  python tests/e2e/test_softrefresh_dut.py   (needs a seeded server on
DUT_BASE whose DATA_DIR this test also writes to, like test_marks_dut).
"""
import hashlib, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-softrefresh")
from _seed import seed_rich, mint_token, require_own_server

seed_rich(with_payload=True)
from app.app import db

# seed_rich gives the tall real dashboard (personal details with
# data-copy values, multiple subjects); graft an FT-II component onto
# subject 1 so the tag round-trip has a second component to confirm.
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

# ── static contract asserts (phase-4 done-when, grep-level) ──────────
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "..", "..", "app", "static", "dash.js")).read()
code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("//")]
code = "\n".join(code_lines)
start = code.index("function softRefresh")
end = code.index("function ref(quiet)", start)
reloads = [m for m in range(len(code)) if code.startswith("location.reload()", m)]
inside = [m for m in reloads if start < m < end]
check("dash.js: location.reload exists ONLY inside softRefresh (catch net)",
      len(reloads) == 2 and len(inside) == 2,
      f"{len(reloads)} total, {len(inside)} inside softRefresh")
vh = os.path.join(here, "..", "..", "app", "static", "vendor", "idiomorph.min.js")
check("vendored idiomorph sha256 matches the pinned 0.8.0 build",
      hashlib.sha256(open(vh, "rb").read()).hexdigest() ==
      "4cbd535caf7663a51eda9bce6595371c384fc430d54b8d414e29a61167f19f96")

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    # 393x400: the marks tab overflows the window at this height, so the
    # scroll-survival check works on the marks tab with zero clicks between
    # setup and the quiet sync (a click would light-dismiss the open panel)
    ctx = b.new_context(viewport={"width": 393, "height": 400},
                         permissions=["clipboard-read", "clipboard-write"])
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg = ctx.new_page()

    # the sync API is intercepted: no portal contact, deterministic answer
    pg.route("**/api/refresh", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "cached": False})))

    pg.goto(BASE + "/#marks", wait_until="load")
    pg.wait_for_timeout(2500)      # let the boot auto-sync settle first
    pg.evaluate("window.__alive = true")

    # ── LEG A: quiet sync must preserve all user state ────────────────
    pg.click('[data-tab="marks"]:visible')
    pg.wait_for_timeout(300)
    pg.click("#tab-marks .py-1 summary >> nth=0")   # open the first tag panel
    pg.wait_for_timeout(250)
    pg.evaluate("""() => {
      window.__detNode = document.querySelector('#tab-marks details[id]');
      window.__focusNode = document.activeElement;   // the summary just clicked
    }""")
    check("setup: first marks panel is open (real click set the attribute)",
          pg.evaluate("window.__detNode.open === true && window.__detNode.hasAttribute('open')"))
    pg.evaluate("""() => {  // attendance view choice = table
      document.getElementById('att-table').hidden = false;
      document.getElementById('att-graph').hidden = true;
    }""")
    pg.evaluate("window.scrollTo(0, 300)")   # marks tab overflows at 400px height
    state_before = pg.evaluate("""() => ({
      scrollY: window.scrollY,   // may clamp below 300 — compare like for like
      pushText: document.getElementById('push-state').textContent,
      pushHidden: document.getElementById('push-controls').hidden,
      avatarVar: document.querySelector('.blobatar-gaze')
                   .style.getPropertyValue('--mo-track-x'),
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

    # quiet sync — exactly what the auto-sync runs; no click, no dismiss
    pg.evaluate("ref(true)")
    pg.wait_for_timeout(2000)

    check("quiet sync caused NO navigation", pg.evaluate("window.__alive === true"))
    check("scroll position survived (window scroll unchanged)",
          pg.evaluate("window.scrollY") == state_before["scrollY"],
          f"before {state_before['scrollY']} after {pg.evaluate('window.scrollY')}")
    check("open marks panel: SAME details node, still open",
          pg.evaluate("""() => window.__detNode.isConnected &&
                               window.__detNode.open === true &&
                               window.__detNode ===
                                 document.querySelector('#tab-marks details[id]')"""))
    check("focus preserved by the quiet sync (same node or body)",
          pg.evaluate("""() => document.activeElement === window.__focusNode ||
                               document.activeElement === document.body"""),
          pg.evaluate("document.activeElement.tagName"))
    check("attendance view choice survived (#att-table visible)",
          pg.evaluate("document.getElementById('att-table').hidden === false"))
    check("push card untouched by morph (state + hidden flag)",
          pg.evaluate("""() => ({
            t: document.getElementById('push-state').textContent,
            h: document.getElementById('push-controls').hidden })""")
          == {"t": state_before["pushText"], "h": state_before["pushHidden"]})
    check("avatar inline gaze vars survived (data-morph=ignore)",
          pg.evaluate("""() => document.querySelector('.blobatar-gaze')
                           .style.getPropertyValue('--mo-track-x')""")
          == state_before["avatarVar"])
    ft_row = pg.evaluate("""() => {
      const rows = [...document.querySelectorAll('#tab-marks .py-1')];
      const row = rows.find(r => r.textContent.includes('FT-I'));
      return row ? (row.textContent.match(/3(\\.0)?\\/5/) || [null])[0] : 'no-row';
    }""")
    check("updated data rendered in place (FT-I now 3/5)",
          ft_row in ("3/5", "3.0/5"), str(ft_row))

    # ── LEG B: clicked sync — no navigation, no focus theft, listeners ──
    pg.click('[data-refresh]:visible')
    pg.wait_for_timeout(1500)
    check("clicked sync caused NO navigation", pg.evaluate("window.__alive === true"))
    check("no focus theft after the clicked sync",
          pg.evaluate("""() => document.activeElement === document.body ||
                               document.activeElement.matches('[data-refresh]')"""),
          pg.evaluate("document.activeElement.tagName"))
    check("overlay modal no longer exists in the DOM",
          pg.evaluate("document.getElementById('overlay') === null"))

    # post-morph listeners on morphed nodes ------------------------------
    pg.click('[data-tab="dashboard"]:visible')
    pg.wait_for_timeout(300)
    tgt = pg.query_selector("#tab-dashboard [data-copy]")
    if tgt:
        tgt.click()
        pg.wait_for_timeout(150)
        flashed = pg.evaluate("""() => document
            .querySelector('#tab-dashboard [data-copy]').textContent""")
        check("click-to-copy works on a post-morph node",
              flashed == "Copied!", str(flashed))
    else:
        check("click-to-copy works on a post-morph node", False,
              "no data-copy target on dashboard tab")

    # tag form on the morphed tree: fetch path, no navigation ------------
    pg.click('[data-tab="marks"]:visible')
    pg.wait_for_timeout(300)
    pg.click("#tab-marks .py-1 summary >> nth=0")
    pg.wait_for_timeout(250)
    pg.select_option("#tab-marks details[open] select[name=role]", "IE-1")
    pg.click("#tab-marks details[open] button:has-text('Save')")
    pg.wait_for_timeout(1200)
    check("tag save: no navigation, still the same page",
          pg.evaluate("window.__alive === true"))
    check("tag save: hash still #marks", pg.evaluate("location.hash") == "#marks")
    c = db()
    row = c.execute("SELECT role FROM component_tags").fetchall()
    c.close()
    check("tag persisted through the fetch path",
          [r[0] for r in row] == ["IE-1"], str(row))
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
