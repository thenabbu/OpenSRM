"""Instrumented scroll trace for the [data-refresh] sync on /attendance.

MEASUREMENT ONLY — no product code, no test assertions are touched here.
Mirrors tests/e2e/test_perf_budget_e2e.py's sync phase (scroll to 250, click
[data-refresh], focus the parked control, restore scroll) and samples
window.scrollY + "<main>'s first child node is still the same object" every
100 ms for ~3 s, so a scrollY drop can be lined up against a DOM rebuild.

Run against a live seeded DUT server (scripts/dut_server.sh):

    DATA_DIR=/tmp/dut-x DUT_BASE=http://127.0.0.1:18180 \
      /opt/data/opensrm-repo/.venv/bin/python scripts/scroll_trace.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-budget-e2e")

from _seed import mint_token, require_own_server, seed_rich  # noqa: E402

seed_rich()
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18180")
require_own_server(BASE)

from playwright.sync_api import sync_playwright  # noqa: E402

TICKS = 31  # t=0 .. 3000 ms at 100 ms

SAMPLER = """(n) => {
  window.scrollTo(0, 250);
  window.__trace = [];
  let first = document.querySelector('main').firstChild;
  const t0 = performance.now();
  const tick = () => {
    const f = document.querySelector('main').firstChild;
    window.__trace.push({t: Math.round(performance.now() - t0),
                         y: window.scrollY, same: f === first});
    first = f;
    if (window.__trace.length <= n) setTimeout(tick, 100);
  };
  tick();
}"""

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 393, "height": 400})
    ctx.add_cookies([{"name": "srm_session", "value": mint_token(), "url": BASE}])
    pg = ctx.new_page()
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 6})
    pg.route("**/api/refresh", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "cached": False})))
    pg.goto(BASE + "/attendance", wait_until="load")
    pg.wait_for_timeout(1000)
    pg.focus("#att-view-table")
    pg.wait_for_timeout(100)
    # start sampling BEFORE the click so the click + focus + restore all land
    # inside the series instead of before it
    pg.evaluate(SAMPLER, TICKS)
    pg.locator("[data-refresh]:visible").first.click()
    pg.focus("#att-view-table")
    pg.evaluate("window.scrollTo(0, 250)")
    pg.wait_for_timeout(3400)
    trace = pg.evaluate("window.__trace")
    alive = pg.evaluate("window.__trace.length")
    b.close()

print(f"samples={len(trace)} (expected {alive}) base={BASE}")
for s in trace:
    print(f"t={s['t']}ms scrollY={s['y']} mainSame={'true' if s['same'] else 'FALSE'}")
below = [s for s in trace if s["y"] < 250]
rebuilt = [s for s in trace if not s["same"]]
print("\nSUMMARY")
print(f"  samples={len(trace)} below250={len(below)} rebuildSamples={len(rebuilt)}")
if below:
    first = below[0]
    print(f"  first drop: t={first['t']}ms scrollY={first['y']} mainSame={'true' if first['same'] else 'FALSE'}")
if rebuilt:
    first = rebuilt[0]
    print(f"  first rebuild: t={first['t']}ms scrollY={first['y']}")
print(f"  final scrollY={trace[-1]['y']}")
print(f"  verdict={'PRESERVED' if trace[-1]['y'] == 250 else 'LOST'}")
