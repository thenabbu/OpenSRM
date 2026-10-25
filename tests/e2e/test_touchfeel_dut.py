"""
Touch-feel DUT — smoothness campaign phase 5.

Asserts the phase-5 contracts: press feedback tokens compiled in, the tab
transition runs via element.animate (present under normal motion, ABSENT
under prefers-reduced-motion), per-tab scroll memoization, keyboard-only
focus, and the bottom-sheet dialog classes.

Run:  python tests/e2e/test_touchfeel_dut.py   (needs a seeded server on
DUT_BASE like the other browser DUTs).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-touchfeel")
from _seed import seed, mint_token, require_own_server

seed(with_payload=False)
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

    # sample animations at the end of the click dispatch (inside the 200ms
    # window, no race with evaluate round-trips)
    pg.evaluate("""() => {
      // CSSOM, not attribute substring: server renders style="display:none"
      // (no space) on some panels — [style*="display: none"] would pick one
      const active = () => [...document.querySelectorAll('[data-tabpanel]')]
        .find(p => p.style.display !== 'none');
      document.addEventListener('click', () => setTimeout(() => {
        const el = active();
        window.__animSeen = el ? el.getAnimations().length : -1;
      }, 0), true);
    }""")

    # press feedback exists on the settings rows
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

    # tab switch animation runs under normal motion
    pg.click('[data-tab="marks"]:visible')
    pg.wait_for_timeout(120)
    seen = pg.evaluate("window.__animSeen || 0")
    check("tab switch runs an element.animate() on the panel", seen >= 1, str(seen))

    # scroll memo: dashboard scroll survives a round trip to marks and back
    pg.click('[data-tab="dashboard"]:visible')
    pg.wait_for_timeout(300)
    pg.evaluate("window.scrollTo(0, 300)")
    pg.click('[data-tab="marks"]:visible')
    pg.wait_for_timeout(300)
    pg.click('[data-tab="dashboard"]:visible')
    pg.wait_for_timeout(300)
    check("per-tab scroll memo restores the reading position",
          abs(pg.evaluate("window.scrollY") - 300) <= 4,
          str(pg.evaluate("window.scrollY")))
    check("exactly one panel visible after a switch round-trip",
          pg.evaluate("""() => [...document.querySelectorAll('[data-tabpanel]')]
            .filter(p => p.style.display !== 'none').length""") == 1)

    # keyboard navigation moves focus (byKeyboard flag); mouse click does not
    # force focus away (switchTab only focuses on the keyboard path)
    pg.evaluate("""() => {
      const vis = [...document.querySelectorAll('[data-tab]')]
        .filter(x => x.offsetParent);
      vis[0].focus();
      window.__kbdFrom = document.activeElement.dataset.tab;
      window.__visCount = vis.length;
    }""")
    pg.keyboard.press("ArrowRight")
    pg.wait_for_timeout(300)
    check("keyboard arrow moves focus to the next tab",
          pg.evaluate("document.activeElement.dataset.tab") !=
          pg.evaluate("window.__kbdFrom"),
          pg.evaluate("document.activeElement.dataset.tab || document.activeElement.tagName"))

    # reduced motion: press + tab motion must be off
    pg2 = ctx.new_page()
    pg2.emulate_media(reduced_motion="reduce")
    pg2.goto(BASE + "/", wait_until="load")
    pg2.wait_for_timeout(1200)
    tr = pg2.evaluate("""() => getComputedStyle(document.querySelector('.pressable')).transition""")
    check("prefers-reduced-motion: .pressable transition is off",
          tr == "none" or tr.startswith("none"), str(tr))
    pg2.evaluate("""() => {
      const active = () => [...document.querySelectorAll('[data-tabpanel]')]
        .find(p => p.style.display !== 'none');
      document.addEventListener('click', () => setTimeout(() => {
        const el = active();
        window.__animRM = el ? el.getAnimations().length : -1;
      }, 0), true);
    }""")
    pg2.click('[data-tab="marks"]:visible')
    pg2.wait_for_timeout(120)
    rm = pg2.evaluate("window.__animRM")
    check("prefers-reduced-motion: no tab animation runs",
          rm == 0, str(rm))
try:
    b.close()
except Exception:
    pass

fails = [n for n, ok in results if not ok]
print(f"\nTOTAL: {len(results)} checks | PASS {len(results)-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
