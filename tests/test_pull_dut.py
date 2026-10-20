"""
Pull-to-refresh DUT — smoothness campaign phase 7.

On an emulated coarse-pointer device, pulling down at the top must run the
existing refresh IN PLACE (no navigation) after ~80px; on a mouse device,
or when scrolled away from the top, the gesture must do nothing; under
prefers-reduced-motion there is no rotation and no spring.

Run:  python tests/test_pull_dut.py   (needs seeded server on DUT_BASE).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-pull")
from _seed import seed, mint_token, require_own_server

seed(with_payload=False)
TOK = mint_token()
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18180")
require_own_server(BASE)
results = []

def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

here = os.path.dirname(os.path.abspath(__file__))
css = open(os.path.join(here, "..", "app", "static", "app.css")).read()
check("overscroll containment compiled (phase-5 pairing)",
      "overscroll-behavior-y:contain" in css)

# synthetic touch helper — real TouchEvent objects on the document
TOUCH = """(y0) => {
  window.__pullTap = (y1, type) => {
    const mk = (cy) => new Touch({identifier: 1, target: document.body,
                                  clientX: 200, clientY: cy});
    const t = type === 'touchend' ? mk(y1) : mk(y1);
    document.dispatchEvent(new TouchEvent(type, {
      touches: type === 'touchend' ? [] : [t],
      targetTouches: type === 'touchend' ? [] : [t],
      changedTouches: [t], bubbles: true, cancelable: true}));
  };
  window.__pullTap(y0, 'touchstart');
  return true;
}"""

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()

    # ── coarse pointer device: the gesture works ─────────────────────
    ctx = b.new_context(viewport={"width": 393, "height": 700},
                        is_mobile=True, has_touch=True)
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg = ctx.new_page()
    refresh_hits = {"n": 0}
    def on_refresh(route):
        import json, time
        refresh_hits["n"] += 1
        time.sleep(0.2)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": True, "cached": False}))
    pg.route("**/api/refresh", on_refresh)
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_timeout(1500)
    pg.evaluate("window.__alive = true")
    check("coarse pointer detected on the mobile context",
          pg.evaluate("matchMedia('(pointer: coarse)').matches"))

    pg.evaluate(TOUCH, 100)
    pg.evaluate("window.__pullTap(300, 'touchmove')")   # raw dy=200 -> eff ~162
    tr = pg.evaluate("document.body.style.transform")
    check("pull moves the content via transform", "translateY(" in tr, tr[:60])
    ind = pg.evaluate("""() => {
      const i = [...document.body.children].find(e => e.getAttribute && e.getAttribute('aria-hidden') === 'true' && e.style.borderRadius === '50%');
      return i ? {op: i.style.opacity, rot: i.style.transform} : null;
    }""")
    check("indicator tracks the pull (opacity + rotation)",
          ind is not None and ind["op"] not in ("", "0") and "rotate(" in ind["rot"],
          str(ind))

    pg.evaluate("window.__pullTap(300, 'touchend')")
    pg.wait_for_timeout(800)
    check("release past 80px fires the existing refresh", refresh_hits["n"] == 1,
          str(refresh_hits["n"]))
    check("the refresh never navigates (sentinel alive)",
          pg.evaluate("window.__alive === true"))
    check("body transform cleared after the gesture settles",
          pg.evaluate("document.body.style.transform") in ("", "translateY(0px)"),
          repr(pg.evaluate("document.body.style.transform")))

    # scrolled away from the top: the gesture must not start
    pg.evaluate("window.scrollTo(0, 600)")
    pg.wait_for_timeout(200)
    pg.evaluate("window.__pullTap(700, 'touchstart')")
    pg.evaluate("window.__pullTap(400, 'touchmove')")
    tr2 = pg.evaluate("document.body.style.transform")
    check("gesture ignored when not at the top", tr2 in ("", "translateY(0px)"), repr(tr2))
    pg.evaluate("window.__pullTap(400, 'touchend')")
    pg.evaluate("window.scrollTo(0, 0)")

    # ── mouse device: pull.js never activates ────────────────────────
    ctx2 = b.new_context(viewport={"width": 1366, "height": 768})
    ctx2.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg2 = ctx2.new_page()
    pg2.goto(BASE + "/", wait_until="load")
    pg2.wait_for_timeout(1200)
    check("mouse device: pointer is fine (not coarse)",
          not pg2.evaluate("matchMedia('(pointer: coarse)').matches"))
    pg2.evaluate(TOUCH, 100)
    pg2.evaluate("window.__pullTap(300, 'touchmove')")
    tr3 = pg2.evaluate("document.body.style.transform")
    check("mouse device: synthetic pull does nothing", tr3 in ("", None, "translateY(0px)"),
          repr(tr3))

    # ── reduced motion: no rotation, instant snap ────────────────────
    ctx3 = b.new_context(viewport={"width": 393, "height": 700},
                         is_mobile=True, has_touch=True)
    ctx3.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg3 = ctx3.new_page()
    pg3.emulate_media(reduced_motion="reduce")
    pg3.goto(BASE + "/", wait_until="load")
    pg3.wait_for_timeout(1200)
    pg3.evaluate(TOUCH, 100)
    pg3.evaluate("window.__pullTap(300, 'touchmove')")
    ind3 = pg3.evaluate("""() => {
      const i = [...document.body.children].find(e => e.getAttribute && e.getAttribute('aria-hidden') === 'true' && e.style.borderRadius === '50%');
      return i ? i.style.transform : null;
    }""")
    check("reduced motion: indicator translates without rotation",
          ind3 and "translateY(" in ind3 and "rotate" not in ind3, str(ind3))
    pg3.evaluate("window.__pullTap(300, 'touchend')")
    check("reduced motion: spring skipped (instant clear, no transition)",
          pg3.evaluate("document.body.style.transition") in ("", "none"),
          repr(pg3.evaluate("document.body.style.transition")))
    try:
        b.close()
    except Exception:
        pass

fails = [n for n, ok in results if not ok]
print(f"\nTOTAL: {len(results)} checks | PASS {len(results)-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
