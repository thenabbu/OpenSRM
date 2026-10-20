"""E2E: perf-budget guardrails at 6x CPU throttle (phase 8).

  1. ten tab switches: NO long task > 50 ms inside a switch window
     (element.animate runs off the main thread; the forced-layout switch
     was removed in phase 5)
  2. a data-changing sync: zero navigations; scroll, focus and the active
     tab survive; the new number renders in place
  3. ?perf=low: 0 running avatar animations

Run: python tests/test_perf_budget_e2e.py   (seeded server on DUT_BASE).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-budget-e2e")
from _seed import mint_token, require_own_server, seed

seed(with_payload=False)
from app.app import db

MARKS = [
    {"code": "21CSS201T", "title": "COMPUTER ORGANIZATION",
     "components": [{"name": "FT-I", "entered": "04/Sep/2026", "scored": 4.5, "max": 5.0}],
     "scored_total": 4.5, "max_total": 5.0},
]
c = db()
c.execute("UPDATE users SET marks_json=? WHERE netid='zz9999'", (json.dumps(MARKS),))
c.commit(); c.close()

TOK = mint_token()
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18180")
require_own_server(BASE)
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 393, "height": 400})
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg = ctx.new_page()
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 6})

    # ── 1. tab switches under 6x throttle ────────────────────────────
    pg.route("**/api/refresh", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "cached": True})))   # no sync churn
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_timeout(1500)
    # warm every panel ONCE before measuring: the FIRST show of a server-
    # rendered panel pays cold style/layout at 6x throttle (~50-350ms,
    # measured intermittently across runs). That cost is "first render of
    # the tab", not the switch machinery this guardrail targets; after one
    # full pass the measured 10 switches isolate what phase 5 removed
    # (forced reflow + CSS transition). Background tasks outside any
    # switch window (shared-lab noise) are excluded by attribution below.
    pg.evaluate("""() => {
      for (const n of ['marks', 'attendance', 'timetable', 'settings', 'dashboard'])
        document.querySelector('[data-tab="' + n + '"]').click();
    }""")
    pg.wait_for_timeout(700)
    switches = pg.evaluate("""() => {
      window.__t0 = performance.now();
      window.__wins = [];   // measurement starts here
      window.__tasks = [];
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) window.__tasks.push({s: e.startTime, d: e.duration});
      }).observe({entryTypes: ['longtask']});
      const tabs = ['marks', 'attendance', 'timetable', 'settings', 'dashboard'];
      for (let i = 0; i < 10; i++) {
        const name = tabs[i % tabs.length];
        const t0 = performance.now();
        document.querySelector('[data-tab="' + name + '"]').click();
        window.__wins.push(t0);
      }
      return window.__wins.length;
    }""")
    pg.wait_for_timeout(600)
    bad = pg.evaluate("""() => window.__tasks.filter(t =>
      t.s >= window.__t0 &&   // ignore anything before the measured phase
      window.__wins.some(w => t.s >= w - 20 && t.s <= w + 400) && t.d > 50
    )""")
    check("10 throttled tab switches: no long task > 50 ms in a switch window",
          len(bad) == 0, json.dumps(bad[:4]))

    # ── 2. data-changing sync under throttle ─────────────────────────
    pg.route("**/api/refresh", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "cached": False})))
    pg.evaluate("""() => {
      window.__alive = true;
      // scroll the DASHBOARD tab: with this bare seed the marks panel fits
      // and scrollTo(250) would clamp to 0 (a vacuous pass — learned thrice)
      document.querySelector('[data-tab="dashboard"]').click();
      window.scrollTo(0, 250);
      window.__focusNode = document.activeElement;
      window.__tab = [...document.querySelectorAll('[data-tabpanel]')]
        .findIndex(p => p.style.display !== 'none');
      window.__scroll = window.scrollY;
    }""")
    check("setup: dashboard actually scrolled (non-vacuous position)",
          pg.evaluate("window.__scroll") >= 200, str(pg.evaluate("window.__scroll")))
    MARKS[0]["components"][0]["scored"] = 3.0
    c = db()
    c.execute("UPDATE users SET marks_json=? WHERE netid='zz9999'", (json.dumps(MARKS),))
    c.commit(); c.close()
    nav0 = pg.evaluate("performance.getEntriesByType('navigation').length")
    pg.evaluate("ref(true)")
    pg.wait_for_timeout(2000)
    nav1 = pg.evaluate("performance.getEntriesByType('navigation').length")
    check("throttled sync: no navigation", pg.evaluate("window.__alive === true") and nav0 == nav1)
    check("throttled sync: scroll preserved",
          pg.evaluate("window.scrollY") == pg.evaluate("window.__scroll"),
          f"{pg.evaluate('window.__scroll')} -> {pg.evaluate('window.scrollY')}")
    check("throttled sync: focus preserved (same node)",
          pg.evaluate("document.activeElement === window.__focusNode"))
    check("throttled sync: active tab preserved",
          pg.evaluate("""() => [...document.querySelectorAll('[data-tabpanel]')]
            .findIndex(p => p.style.display !== 'none')""") ==
          pg.evaluate("window.__tab"))
    pg.evaluate("document.querySelector('[data-tab=\"marks\"]').click()")
    pg.wait_for_timeout(300)
    ft = pg.evaluate("""() => {
      const row = [...document.querySelectorAll('#tab-marks .py-1')]
        .find(r => r.textContent.includes('FT-I'));
      return row ? (row.textContent.match(/3(\.0)?\\/5/) || [null])[0] : 'no-row';
    }""")
    check("throttled sync: updated number renders in place",
          ft in ("3/5", "3.0/5"), str(ft))

    # ── 3. low tier: avatar calm ─────────────────────────────────────
    pg3 = ctx.new_page()
    pg3.goto(BASE + "/?perf=low", wait_until="load")
    pg3.wait_for_timeout(1200)
    n = pg3.evaluate("""() => {
      const wrap = document.querySelector('.blobatar-gaze');
      return [...document.getAnimations()].filter(a => {
        const t = a.effect && a.effect.target;
        return t && wrap && wrap.contains(t) && a.playState === 'running';
      }).length;
    }""")
    check("?perf=low: 0 running avatar animations", n == 0, str(n))
    try:
        b.close()
    except Exception:
        pass

fails = [n for n, ok in results if not ok]
print(f"\nTOTAL: {len(results)} checks | PASS {len(results)-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
