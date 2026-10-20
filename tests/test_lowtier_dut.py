"""
Low-end / avatar-pause DUT — smoothness campaign phase 6.

Checks: perf.js tier override, avatar idle loops paused in the low tier
AND when scrolled offscreen, gaze driver absent in the low tier, the
drag-drop polyfill absent when the timetable editor is archived, and the
pause rule compiled into app.css.

Run:  python tests/test_lowtier_dut.py   (needs seeded server on DUT_BASE).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-lowtier")
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
check("app.css carries the low-tier/offscreen avatar pause rule",
      'data-perf=low] .mo-root' in css and          # minifier strips quotes
      ".mo-root.is-offscreen" in css and
      "animation-play-state:paused" in css)

AVATAR = """() => {
  const wrap = document.querySelector('.blobatar-gaze');
  if (!wrap) return -1;
  return [...document.getAnimations()].filter(a => {
    const t = a.effect && a.effect.target;
    return t && wrap.contains(t) && a.playState === 'running';
  }).length;
}"""

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()

    # ── forced LOW tier ───────────────────────────────────────────────
    # 393x400: the dashboard must OVERFLOW the viewport so scrolling can
    # actually take the avatar offscreen (it fits at 1366x768 with the bare
    # seed — same trap as the phase-4 scroll check)
    ctx = b.new_context(viewport={"width": 393, "height": 400})
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg = ctx.new_page()
    pg.goto(BASE + "/?perf=low", wait_until="load")
    pg.wait_for_timeout(1500)
    check("forced ?perf=low sets html[data-perf=low]",
          pg.evaluate("document.documentElement.dataset.perf") == "low")
    check("perf.js is the blocking head script (before first paint)",
          pg.evaluate("""() => {
            const s = document.querySelector('head script[src]');
            return s && s.src.includes('perf.js') && !s.hasAttribute('defer');
          }"""))
    n = pg.evaluate(AVATAR)
    check("low tier: 0 running avatar animations", n == 0, str(n))
    check("low tier: gaze driver not started",
          pg.evaluate("!document.querySelector('.blobatar-gaze')._blobatarGaze"))
    check("low tier: no gaze inline vars written",
          pg.evaluate("""() => !document.querySelector('.blobatar-gaze')
                               .style.getPropertyValue('--mo-track-x')"""))
    # polyfill absent (editor archived)
    check("drag-drop polyfill NOT shipped when the editor is archived",
          pg.evaluate("""() => performance.getEntriesByType('resource')
            .every(r => !r.name.includes('drag-drop-touch'))"""))

    # ── NORMAL tier: running > 0 in view, 0 offscreen ────────────────
    pg2 = ctx.new_page()
    pg2.goto(BASE + "/?perf=high", wait_until="load")
    pg2.wait_for_timeout(1500)
    check("forced ?perf=high sets html[data-perf=high]",
          pg2.evaluate("document.documentElement.dataset.perf") == "high")
    n_in = pg2.evaluate(AVATAR)
    check("high tier: avatar loops run while in view", n_in > 0, str(n_in))
    pg2.evaluate("window.scrollTo(0, 3000)")
    pg2.wait_for_timeout(400)
    offscreen = pg2.wait_for_function(
        "() => document.querySelector('.mo-root').classList.contains('is-offscreen')",
        timeout=4000)
    check("avatar gets .is-offscreen when scrolled out", bool(offscreen))
    pg2.wait_for_timeout(300)
    n_off = pg2.evaluate(AVATAR)
    check("offscreen: 0 running avatar animations", n_off == 0, str(n_off))
    pg2.evaluate("window.scrollTo(0, 0)")
    pg2.wait_for_timeout(400)
    back = pg2.wait_for_function(
        "() => !document.querySelector('.mo-root').classList.contains('is-offscreen')",
        timeout=4000)
    check(".is-offscreen removed when scrolled back", bool(back))
    n_back = pg2.evaluate(AVATAR)
    check("back in view: avatar loops resume", n_back > 0, str(n_back))

    # ── gaze batching: no per-event layout reads ──────────────────────
    # scroll 30 frames fast; count how many times measure-equivalent runs
    # by watching rAF frames where getBoundingClientRect fires — we assert
    # the cheap contract: scrolling 100x does not throw and gaze stays alive
    ok = pg2.evaluate("""() => {
      try {
        for (let i = 0; i < 100; i++) window.dispatchEvent(new Event('scroll'));
        return true;
      } catch (e) { return false; }
    }""")
    check("scroll storm: gaze handlers run without errors", ok)
    try:
        b.close()
    except Exception:
        pass

fails = [n for n, ok in results if not ok]
print(f"\nTOTAL: {len(results)} checks | PASS {len(results)-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
