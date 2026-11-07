"""
Touch-feel DUT — smoothness campaign phase 5.

Asserts the phase-5 contracts that survive P3.1's route split: press
feedback tokens compiled in (off only under prefers-reduced-motion), no
client-side tab animation, a nav click is a real navigation to exactly one
panel, and the bottom-sheet dialog classes.

Run:  python tests/e2e/test_touchfeel_dut.py   (needs a seeded server on
DUT_BASE like the other browser DUTs).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-touchfeel")
from _seed import seed_rich, mint_token, require_own_server

seed_rich()  # rich: the dashboard must have real height to scroll (no notices feed pads it any more)
TOK = mint_token()
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18180")
require_own_server(BASE)
results = []

def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

# static: the phase-5 rules compiled into app.css
here = os.path.dirname(os.path.abspath(__file__))
css = open(os.path.join(here, "..", "..", "app", "static", "app.css")).read()
check("app.css carries the pressable rule + spring easing",
      ".pressable" in css and "--ease-spring" in css)
check("app.css carries bottom-sheet classes for phones",
      ".modal-bottom" in css and "sm\\:modal-middle" in css)
check("old CSS-driven tab transition is gone (JS animate owns it)",
      "[data-tabpanel]{transition" not in css and ".tab-enter" not in css)

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 393, "height": 400})
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_timeout(1500)

    # press feedback exists on the rows that carry it (settings log-out/danger rows)
    pg.goto(BASE + "/settings", wait_until="load")
    pg.wait_for_timeout(600)
    check("settings rows carry .pressable",
          pg.evaluate("document.querySelectorAll('.pressable').length >= 2"),
          str(pg.evaluate("document.querySelectorAll('.pressable').length")))

    # dialogs are bottom sheets on phones
    check("dialogs carry modal-bottom sm:modal-middle (3 of 3)",
          pg.evaluate("""() => {
            const ds = [document.getElementById('delete-account-modal'),
                        document.getElementById('add-subject-modal')];
            const fb = document.getElementById('fb-modal');
            if (fb) ds.push(fb);
            return ds.every(d => d && d.classList.contains('modal-bottom') &&
                                 d.classList.contains('sm:modal-middle'));
          }"""))

    # P3.1: nav is real navigation now — no client-side tab switch, so no
    # panel animation and no per-tab scroll memo. What must still hold: a nav
    # click loads exactly one panel and lands on that route.
    pg.click('.dock a[data-tab="marks"]:visible, .navbar [data-tab="marks"]:visible')
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(300)
    nav = pg.evaluate("""() => ({path: location.pathname, hash: location.hash,
        panels: [...document.querySelectorAll('[data-tabpanel]')].map(p => p.id),
        anims: [...document.querySelectorAll('[data-tabpanel]')]
                 .reduce((n, p) => n + p.getAnimations().length, 0)})""")
    check("nav click loads the target route, one panel, no JS tab animation",
          nav["path"] == "/marks" and nav["hash"] == ""
          and nav["panels"] == ["tab-marks"] and nav["anims"] == 0, str(nav))

    # reduced motion: press motion must be off
    pg2 = ctx.new_page()
    pg2.emulate_media(reduced_motion="reduce")
    pg2.goto(BASE + "/settings", wait_until="load")
    pg2.wait_for_timeout(1200)
    tr = pg2.evaluate("""() => getComputedStyle(document.querySelector('.pressable')).transition""")
    check("prefers-reduced-motion: .pressable transition is off",
          tr == "none" or tr.startswith("none"), str(tr))
try:
    b.close()
except Exception:
    pass

fails = [n for n, ok in results if not ok]
print(f"\nTOTAL: {len(results)} checks | PASS {len(results)-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
