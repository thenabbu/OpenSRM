"""P3.5 — dash.js on the routed model (F1/F2/F3/F8).

Four regressions, each red on the pre-split tab machine:

  F1  softRefresh() fetched '/' and morphed the DASHBOARD into <main> on every
      route — a refresh on /marks left dashboard content under a /marks URL.
  F2  a [data-tab] click handler called switchTab() with no preventDefault:
      the JS switch AND the navigation both ran, then replaceState wrote a
      stale '#dashboard' onto the new URL.
  F3  switchTab() set tabIndex 0/-1, so only the current nav link was
      Tab-reachable.
  F8  every Tools row was stripped to inert because its '#panel' anchor did
      not exist on /tools any more (fees/academics are routes now).

Runs against a live server with a FULL seed (seed_rich + the scope blob) so
the gated Tools panel exists. DATA_DIR must be shared with the server under
test; BASE_URL defaults to the port scripts/ci_e2e_http.sh assigns.
"""
import json
import os
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

BASE = os.environ.get("DUT_BASE", os.environ.get("BASE_URL", "http://127.0.0.1:18181")).rstrip("/")
os.environ.setdefault("DATA_DIR", "/tmp/osrm-navroutes")

from _seed import seed_rich, mint_token, require_own_server  # noqa: E402


def seed_full():
    seed_rich(with_payload=True)
    data_dir = os.environ["DATA_DIR"]
    cap_path = "/opt/data/missions/opensrm-preact/scripts/capture.py"
    if os.path.exists(cap_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cap", cap_path)
        cap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cap)
        cap.inject_scope(data_dir)


seed_full()
TOK = mint_token()
require_own_server(BASE)

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── static contract: the tab machine and the stale-hash write are gone ──
src = open(os.path.join(REPO, "app", "static", "dash.js"), encoding="utf-8").read()
check("dash.js: no tab-switching engine left (switchTab/replaceState)",
      "switchTab" not in src and "replaceState" not in src
      and "b.tabIndex" not in src)
check("dash.js: softRefresh fetches this route, not '/'",
      "fetch(location.pathname + location.search" in src)

from playwright.sync_api import sync_playwright  # noqa: E402


def _get(path):
    req = urllib.request.Request(BASE + path, headers={"Cookie": f"srm_session={TOK}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


try:
    tools_html = _get("/tools")
except urllib.error.HTTPError:
    tools_html = ""
check("seed precondition: /tools renders Tools rows",
      'data-tool-tab="fees"' in tools_html and 'data-tool-tab="academics"' in tools_html,
      f"rows={tools_html.count('data-tool-tab')}")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])

    # ── F1: a refresh on /marks re-renders /marks ────────────────────────
    pg = ctx.new_page()
    seen = []
    pg.on("request", lambda r: seen.append(r.url) if r.resource_type == "fetch" else None)
    pg.route("**/api/refresh", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "cached": False})))
    pg.goto(BASE + "/marks", wait_until="load")
    pg.wait_for_timeout(2500)          # let the boot auto-sync settle
    seen.clear()
    pg.evaluate("async () => { await softRefresh(); }")
    pg.wait_for_timeout(300)
    f1 = pg.evaluate("""() => ({
        path: location.pathname,
        marks: !!document.getElementById('tab-marks'),
        dash: !!document.getElementById('tab-dashboard'),
        mainHeading: (document.querySelector('main h1, main h2') || {}).textContent || ''})""")
    check("F1: softRefresh on /marks fetched /marks, not /",
          any(u.rstrip("/").endswith("/marks") for u in seen) and not any(
              u.replace(BASE, "").rstrip("/") == "" for u in seen), str(seen))
    check("F1: after the refresh the page still shows the marks panel (no dashboard swap)",
          f1["marks"] and not f1["dash"] and f1["path"] == "/marks", json.dumps(f1))
    pg.close()

    # ── F2 / F3: nav is real navigation, links are Tab-reachable ─────────
    pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(400)
    links = pg.evaluate("""() => [...document.querySelectorAll('.navbar.hidden nav a[data-tab]')]
        .map(a => ({tab: a.dataset.tab, ti: a.getAttribute('tabindex'),
                    href: a.getAttribute('href'),
                    focusable: (a.focus(), document.activeElement === a)}))""")
    check("F3: every desktop nav link is keyboard reachable (no negative tabindex)",
          bool(links) and all(l["ti"] in (None, "0") and l["focusable"] for l in links),
          json.dumps(links))
    pg.evaluate("window.__alive = true")
    nav = pg.evaluate("() => ({hashAtRest: location.hash})")
    pg.click('.navbar.hidden nav a[data-tab="marks"]')
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(300)
    nav |= pg.evaluate("""() => ({path: location.pathname, hash: location.hash,
                                 alive: window.__alive === true,
                                 marks: !!document.getElementById('tab-marks'),
                                 dash: !!document.getElementById('tab-dashboard'),
                                 current: (document.querySelector('.navbar.hidden nav a[aria-current="page"]') || {}).dataset?.tab})""")
    check("F2: no stale '#dashboard' hash written by JS (at rest or on the route)",
          nav["hashAtRest"] == "" and nav["path"] == "/marks" and nav["hash"] == "",
          json.dumps(nav))
    check("F2: the click was a real page load (switched DOM, one panel)",
          not nav["alive"] and nav["marks"] and not nav["dash"] and nav["current"] == "marks",
          json.dumps(nav))

    pg.close()

    # the dock is the phone's nav: measure reachability where it is visible
    ctx2 = b.new_context(viewport={"width": 393, "height": 851})
    ctx2.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg = ctx2.new_page()
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(300)
    dock = pg.evaluate("""() => [...document.querySelectorAll('.dock a[data-tab]')]
        .filter(a => a.offsetParent !== null)
        .map(a => ({tab: a.dataset.tab, ti: a.getAttribute('tabindex'),
                    focusable: (a.focus(), document.activeElement === a)}))""")
    check("F3: every dock link is keyboard reachable too",
          bool(dock) and all(l["ti"] in (None, "0") and l["focusable"] for l in dock),
          json.dumps(dock))
    pg.close()
    ctx2.close()

    # ── F8: a Tools row whose panel is now a route stays a working link ──
    pg = ctx.new_page()
    pg.goto(BASE + "/tools", wait_until="networkidle")
    pg.wait_for_timeout(400)
    rows = pg.evaluate("""() => [...document.querySelectorAll('[data-tool-tab]')]
        .map(a => ({tab: a.dataset.toolTab, href: a.getAttribute('href'),
                    disabled: a.getAttribute('aria-disabled')}))""")
    fees = next((r for r in rows if r["tab"] == "fees"), None)
    check("F8: Tools row for a routed panel keeps a live link (not inert)",
          fees is not None and fees["href"] == "/fees" and fees["disabled"] is None,
          json.dumps(rows))
    pg.click('[data-tool-tab="fees"]')
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(300)
    dest = pg.evaluate("""() => ({path: location.pathname, hash: location.hash,
                                   fees: !!document.getElementById('tab-fees')})""")
    check("F8: clicking that row lands on the route, not a dead hash",
          dest["path"] == "/fees" and dest["hash"] == "", json.dumps(dest))
    b.close()

fails = [n for n, ok in results if not ok]
print(f"\nTOTAL: {len(results)} checks | PASS {len(results) - len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
