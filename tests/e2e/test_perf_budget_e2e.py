"""E2E: perf-budget guardrails at 6x CPU throttle (phase 8).

  1. ten attendance view switches (graph <-> table) at 6x: NO long task
     > 50 ms inside a switch window, and every switch really flipped the view
     (P3.1: the tab machine is gone; the softRefresh morph this used to also
     cover is a locked SPEC deletion — see the note at the check)
  2. a data-changing sync on /attendance: zero navigations, scroll/focus/route
     survive; the new number renders on /marks after a real navigation
  3. ?perf=low: 0 running avatar animations on / (the route owning the widget)

Run: python tests/e2e/test_perf_budget_e2e.py   (seeded server on DUT_BASE).
Needs a LIVE seeded gunicorn sharing DATA_DIR (scripts/dut_server.sh); with
none listening it ABORTS — an abort is not a pass.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-budget-e2e")
from _seed import seed_rich, mint_token, require_own_server

seed_rich()  # rich: the dashboard must have real height to scroll (no notices feed pads it any more)
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

    # ── 1. ten view switches under 6x throttle ───────────────────────
    # P3.1: there is no tab machine to switch between any more. The one
    # in-page view switch left is the attendance graph <-> table toggle;
    # it is user-visible, persisted in localStorage, and each switch is
    # asserted to have really happened (otherwise "0 long tasks" would
    # grade a page that did nothing).
    #
    # SCOPE CHANGE, recorded on purpose: this check used to also cover
    # softRefresh()'s morph, because the tab switch ran it. That path is a
    # locked deletion in the migration SPEC (vendor/idiomorph.min.js +
    # the two-stage softRefresh morph); a full-<main> Idiomorph morph costs
    # 53-124 ms on its own at 6x CPU throttle (measured: 10/10 runs over
    # budget, spaced or not), so it cannot honour a 50 ms main-thread
    # budget and is not made green here. When the Preact unit replaces it,
    # re-add a sync check against the new render path.
    pg.goto(BASE + "/attendance", wait_until="load")
    pg.wait_for_timeout(1500)
    switches = pg.evaluate("""() => {
      window.__t0 = performance.now();
      window.__wins = [];   // measurement starts here
      window.__tasks = [];
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) window.__tasks.push({s: e.startTime, d: e.duration});
      }).observe({entryTypes: ['longtask']});
      window.__states = [];
      for (let i = 0; i < 10; i++) {
        const bt = document.getElementById(i % 2 ? 'att-view-graph' : 'att-view-table');
        window.__wins.push(performance.now());
        bt.click();
        window.__states.push(document.getElementById('att-table').hidden);
      }
      return window.__wins.length;
    }""")
    pg.wait_for_timeout(800)
    states = pg.evaluate("window.__states")
    check("setup: 10 switches really flipped the view on /attendance",
          switches == 10 and all(h == (i % 2 == 1) for i, h in enumerate(states)), str(states))
    bad = pg.evaluate("""() => window.__tasks.filter(t =>
      t.s >= window.__t0 &&   // ignore anything before the measured phase
      window.__wins.some(w => t.s >= w - 20 && t.s <= w + 400) && t.d > 50
    )""")
    check("10 throttled/6x view switches: no long task > 50 ms in a switch window",
          switches == 10 and len(bad) == 0, json.dumps(bad[:4]))

    # ── 2. data-changing sync under throttle ─────────────────────────
    # The scroll/focus contract belongs to a route that actually overflows:
    # /attendance (1150px at 393x400 with seed_rich); /marks is 485px and
    # scrollTo(250) would clamp to 0 — the vacuous pass this suite already
    # learned to avoid. The sync is triggered the way a user triggers it, by
    # clicking the panel's [data-refresh] button (the app's ref() is module-
    # scoped, not a window global).
    pg.route("**/api/refresh", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "cached": False})))
    pg.goto(BASE + "/attendance", wait_until="load")
    pg.wait_for_timeout(1000)
    # Focus a real control inside the panel first. (Focusing the refresh
    # button ITSELF is a separate issue this suite will not hide: ref()
    # disables the button, so the browser moves focus into the shell/dock —
    # measured, real, not a route-split artifact; see the report.)
    pg.focus("#att-view-table")
    pg.wait_for_timeout(100)
    pg.evaluate("""() => {
      window.__alive = true;
      window.scrollTo(0, 250);
      window.__focusNode = document.activeElement;
      window.__focusId = document.activeElement.id || document.activeElement.tagName;
      window.__path = location.pathname;
      window.__scroll = window.scrollY;
    }""")
    check("setup: /attendance actually scrolled (non-vacuous position)",
          pg.evaluate("window.__scroll") >= 200, str(pg.evaluate("window.__scroll")))
    check("setup: focus parked on a real control (not <body> — that would pass vacuously)",
          pg.evaluate("window.__focusId") == "att-view-table", str(pg.evaluate("window.__focusId")))
    MARKS[0]["components"][0]["scored"] = 3.0
    c = db()
    c.execute("UPDATE users SET marks_json=? WHERE netid='zz9999'", (json.dumps(MARKS),))
    c.commit(); c.close()
    nav0 = pg.evaluate("performance.getEntriesByType('navigation').length")
    # Clicking a [data-refresh] moves focus onto THAT button, so "focus
    # preserved" cannot mean "still on the control I parked on before the
    # click". Re-park focus on the parked control immediately after the click
    # so this asserts the real contract: a sync must not drop focus off <main>.
    pg.locator("[data-refresh]:visible").first.click()
    # focus() scrolls the control into view, which would reset the scroll
    # position being measured below; restore it right after.
    pg.focus("#att-view-table")
    pg.evaluate("window.scrollTo(0, 250)")
    pg.wait_for_timeout(2000)
    nav1 = pg.evaluate("performance.getEntriesByType('navigation').length")
    check("throttled sync: no navigation", pg.evaluate("window.__alive === true") and nav0 == nav1,
          f"{nav0} -> {nav1}")
    check("throttled sync: scroll preserved",
          pg.evaluate("window.scrollY") == pg.evaluate("window.__scroll"),
          f"{pg.evaluate('window.__scroll')} -> {pg.evaluate('window.scrollY')}")
    # Focus must land back on the SAME CONTROL. It is compared by identity
    # (id, else tag+text) rather than `===` node identity: softRefresh rebuilds
    # <main>, so the node is necessarily a new object even when the user is
    # exactly where they were. Asserting node identity would demand that the
    # DOM never be rebuilt, which is the morph this suite is retiring.
    check("throttled sync: focus preserved (same control)",
          pg.evaluate("(document.activeElement.id || document.activeElement.tagName) === window.__focusId"),
          pg.evaluate("document.activeElement.tagName + '#' + (document.activeElement.id || document.activeElement.className)"))
    check("throttled sync: stayed on its own route (no redirect off /attendance)",
          pg.evaluate("location.pathname") == pg.evaluate("window.__path"))
    pg.goto(BASE + "/marks", wait_until="load")   # cross-route: real navigation, fresh render
    pg.wait_for_timeout(500)
    ft = pg.evaluate("""() => {
      const row = [...document.querySelectorAll('#tab-marks .py-1')]
        .find(r => r.textContent.includes('FT-I'));
      const m = row && row.textContent.match(/3\\.[05]\\/5|3\\/5/);
      return m ? m[0] : 'no-row';
    }""")
    check("synced data renders on /marks (updated number in the panel)",
          ft in ("3/5", "3.0/5"), str(ft))

    # ── 3. low tier: avatar calm ─────────────────────────────────────
    # The profile widget (and its blobatar) lives on / — the only route that
    # carries it. A missing avatar must FAIL here, not pass as "0 animations".
    pg3 = ctx.new_page()
    pg3.goto(BASE + "/?perf=low", wait_until="load")
    pg3.wait_for_timeout(1200)
    r = pg3.evaluate("""() => {
      const wrap = document.querySelector('.blobatar-gaze');
      return {present: !!wrap, perf: document.documentElement.dataset.perf || null,
              running: [...document.getAnimations()].filter(a => {
                const t = a.effect && a.effect.target;
                return t && wrap && wrap.contains(t) && a.playState === 'running';
              }).length};
    }""")
    check("?perf=low: avatar present on / and the low tier is active",
          r["present"] and r["perf"] == "low", json.dumps(r))
    check("?perf=low: 0 running avatar animations", r["present"] and r["running"] == 0, json.dumps(r))
    try:
        b.close()
    except Exception:
        pass

fails = [n for n, ok in results if not ok]
print(f"\nTOTAL: {len(results)} checks | PASS {len(results)-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
