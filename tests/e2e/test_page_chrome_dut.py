"""
Page-chrome DUT (W5.4b) — the five dash.js page-chrome rows, in a real browser.

Each check names the matrix row it proves. The port lives in
web/src/data/pageChrome.ts and is bound from main.ts; this file is what fails if
any one of those bindings is removed from the bundle.

Run:  python tests/e2e/test_page_chrome_dut.py
Needs a seeded server on DUT_BASE like the other browser DUTs (or let
_scope_fixture/seed_rich boot one). The scroll-indicator row is NOT here: it is
already asserted by tests/e2e/test_dash_fit.py ("bar shows on use" /
"retracts when idle"), so this file does not duplicate it.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-pagechrome")
from _seed import seed_rich, mint_token, require_own_server

seed_rich()

# The page-chrome rows include the four personal-details groups, and the shared
# rich seed only fills ONE of them — with one group, "all open at 1280 px" and
# "only the first opens at 375 px" are the same observation and can never tell
# the two rules apart. Fill the Academic/Personal/Family/Contact groups here so
# the settings checks are non-vacuous. (Deliberately local: _seed.py is shared
# by capture/perf tooling and a richer default would drift those baselines.)
def seed_settings_groups():
    from app import app as A
    from app.views.settings_island import GROUPS
    import json
    c = A.db()
    row = c.execute("SELECT personal_details_json FROM users WHERE netid='zz9999'").fetchone()
    personal = json.loads(row[0]) if row and row[0] else {}
    for title, keys in GROUPS:
        for k in keys:
            personal.setdefault(k, "seed-" + k)
    personal["Student Name"] = personal.get("Student Name", "Test Student")
    c.execute("UPDATE users SET personal_details_json=? WHERE netid='zz9999'",
              (json.dumps(personal),))
    c.commit(); c.close()

seed_settings_groups()
TOK = mint_token()
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18191")
require_own_server(BASE)
results = []

def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()

    # ── dash-sw-register ─────────────────────────────────────────────────
    # A panel route (not /login) must register /static/sw.js at scope '/'.
    # Spy on register BEFORE any page script runs, so the count is the bundle's.
    ctx = b.new_context()
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    ctx.add_init_script("""
      window.__swCalls = [];
      const real = navigator.serviceWorker && navigator.serviceWorker.register;
      if (real) navigator.serviceWorker.register = function (url, opts) {
        window.__swCalls.push([url, opts && opts.scope]);
        return real.apply(this, arguments);
      };
    """)
    pg = ctx.new_page()
    pg.goto(BASE + "/attendance", wait_until="load")
    pg.wait_for_timeout(2000)
    calls = pg.evaluate("() => window.__swCalls")
    check("dash-sw-register: panel route registers /static/sw.js at scope /",
          any(c[0] == "/static/sw.js" and c[1] == "/" for c in calls), str(calls))
    # And it really installed/active — a register() call that rejects is not proof.
    reg = pg.evaluate("""async () => {
        const r = await navigator.serviceWorker.getRegistration();
        return r ? {scope: r.scope, active: !!r.active, installing: !!r.installing} : null;
    }""")
    check("dash-sw-register: registration is live (not just an attempted call)",
          reg is not None and (reg["active"] or reg["installing"]), str(reg))
    ctx.close()

    # ── dash-item-beacon + dash-offline-banner + dash-settings-groups ─────
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    ctx.add_init_script("""
      window.__beacons = [];
      const real = window.fetch;
      window.fetch = function (url, init) {
        try {
          if (String(url).indexOf('/api/track/tab') !== -1) {
            window.__beacons.push({url: String(url), init: {method: init && init.method,
              keepalive: !!(init && init.keepalive), body: init && init.body}});
          }
        } catch (e) {}
        return real.apply(this, arguments);
      };
    """)
    pg = ctx.new_page()

    # dash-item-beacon on /marks: the marks island emits data-track-item.
    pg.goto(BASE + "/marks", wait_until="load")
    pg.wait_for_timeout(1800)
    n_tracked = pg.evaluate("() => document.querySelectorAll('[data-track-item]').length")
    check("dash-item-beacon: /marks ships tracked elements to click",
          n_tracked > 0, f"{n_tracked} target(s)")
    # Click a data-track-item that BELONGS to marks. The nav's sync button also
    # carries data-track-item (tab 'dashboard'), so picking the first match on
    # the page measures the navbar, not the panel. Prefer the marks item.
    clicked_item = pg.evaluate("""() => {
        const els = [...document.querySelectorAll('[data-track-item]')];
        const el = els.find(e => (e.getAttribute('data-track-item') || '').startsWith('marks-')) || els[0];
        el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        return el.getAttribute('data-track-item');
    }""")
    pg.wait_for_timeout(700)
    beacons = pg.evaluate("() => window.__beacons")
    check("dash-item-beacon: a tracked click POSTs /api/track/tab with keepalive",
          len(beacons) >= 1 and beacons[0]["init"]["method"] == "POST"
          and beacons[0]["init"]["keepalive"], str(beacons)[:220])
    if beacons:
        import json as _j
        body = _j.loads(beacons[0]["init"]["body"])
        # The tab must be the one the clicked item's row belongs to; for a
        # marks-* item that is 'marks'.
        check("dash-item-beacon: the body carries {tab, item} for the clicked item",
              set(body) == {"tab", "item"}
              and body["item"] == clicked_item
              and (body["tab"] == "marks" if str(clicked_item).startswith("marks-")
                   else body["tab"] == "dashboard"),
              f"clicked={clicked_item} body={body}")

    # dash-offline-pill: a navbar badge, not the old full-width bar. Both
    # navbars ship one; the desktop bar is the visible one at this viewport.
    pg.goto(BASE + "/marks", wait_until="load")
    pg.wait_for_timeout(1200)
    pilled = ("() => [...document.querySelectorAll('[data-offline-pill]')]"
              ".map(e => ({hidden: e.hasAttribute('hidden'), "
              "visible: !!(e.offsetWidth || e.offsetHeight)}))")
    pg.evaluate("() => window.dispatchEvent(new Event('offline'))")
    pg.wait_for_timeout(250)
    off = pg.evaluate(pilled)
    check("dash-offline-pill: offline shows a padded, non-bar icon in the navbar",
          bool(off) and all(not p["hidden"] for p in off) and any(p["visible"] for p in off),
          str(off))
    bar = pg.evaluate("""() => {
        const e = document.querySelector('[data-offline-pill]');
        if (!e) return null;
        const r = e.getBoundingClientRect();
        return {w: Math.round(r.width), vw: window.innerWidth, bottom: Math.round(r.bottom)};
    }""")
    check("dash-offline-pill: it is small, not a full-width bottom bar",
          bool(bar) and bar["w"] < bar["vw"] / 3 and bar["bottom"] < 120, str(bar))
    pg.evaluate("() => window.dispatchEvent(new Event('online'))")
    pg.wait_for_timeout(250)
    on = pg.evaluate(pilled)
    check("dash-offline-pill: online hides it again",
          bool(on) and all(p["hidden"] for p in on), str(on))

    # dash-settings-groups at 1280 px: every group checked. The row's own toggle
    # must stay collapsed — that is the selector bug the port keeps fixed.
    pg.goto(BASE + "/settings", wait_until="load")
    pg.wait_for_timeout(1800)
    wide = pg.evaluate("""() => {
        const wrap = document.querySelector('#personal-details .collapse-content > .flex.flex-col');
        if (!wrap) return null;
        const gs = [...wrap.querySelectorAll('.collapse > input')];
        const row = document.querySelector('#personal-details > input');
        return {n: gs.length, checked: gs.filter(g => g.checked).length,
                rowChecked: row ? row.checked : null};
    }""")
    check("dash-settings-groups: all groups open at 1280 px",
          wide is not None and wide["n"] > 1 and wide["checked"] == wide["n"], str(wide))
    check("dash-settings-groups: the personal-details ROW stays collapsed",
          wide is not None and wide["rowChecked"] is False, str(wide))
    ctx.close()

    # ── dash-settings-groups, phone width ────────────────────────────────
    ctx = b.new_context(viewport={"width": 375, "height": 800})
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg = ctx.new_page()
    pg.goto(BASE + "/settings", wait_until="load")
    pg.wait_for_timeout(1800)
    narrow = pg.evaluate("""() => {
        const wrap = document.querySelector('#personal-details .collapse-content > .flex.flex-col');
        if (!wrap) return null;
        const gs = [...wrap.querySelectorAll('.collapse > input')];
        return {n: gs.length, checked: gs.filter(g => g.checked).length};
    }""")
    check("dash-settings-groups: only the first group opens at 375 px",
          narrow is not None and narrow["n"] > 1 and narrow["checked"] == 1, str(narrow))
    ctx.close()
    b.close()

passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} passed")
if passed != len(results):
    print("FAILED:", [n for n, ok in results if not ok])
    sys.exit(1)
