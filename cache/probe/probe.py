import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath("tests/e2e/")))
os.environ["DATA_DIR"] = os.environ.get("PROBE_DATA", "/tmp/osrm-probe")
sys.path.insert(0, "tests")
from _seed import mint_token, require_own_server, seed_rich
seed_rich(); TOK = mint_token()
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18177")
require_own_server(BASE)
from playwright.sync_api import sync_playwright
SPY = """
  window.__ev = [];
  document.addEventListener('submit', () => window.__ev.push('form-submit'), true);
  const rf = window.fetch;
  window.fetch = function (i, n) {
    const u = typeof i === 'string' ? i : (i && i.url) || '';
    window.__ev.push('fetch ' + (((n&&n.method)||'GET')) + ' ' + u.slice(-40));
    return rf.apply(this, arguments);
  };
"""
with sync_playwright() as p:
    b = p.chromium.launch()
    c = b.new_context(viewport={"width": 1280, "height": 900})
    c.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    page = c.new_page(); page.add_init_script(SPY)
    reqs = []
    page.on("request", lambda r: reqs.append((r.method, r.url.split('/')[-2:] , r.frame.url.split('/')[-1] if r.frame else None)) if '/api/refresh' in r.url else None)
    def st(route): route.fulfill(status=200, content_type='application/json', body=json.dumps({"ok":True,"age_s":1,"window_s":300,"stale":False}))
    def pg(route):
        r = route.fetch(); route.fulfill(response=r, body=re.sub(r'(<meta name="can-sync" content=")[01](")', r'\g<1>1\g<2>', r.text()))
    page.route(BASE + "/api/data/state", st); page.route(BASE + "/", pg)
    page.goto(BASE + "/", wait_until="load"); page.wait_for_timeout(2500)
    print("refresh requests:", reqs)
    print("events:", page.evaluate("() => window.__ev.filter(e => /refresh|submit/.test(e))"))
    b.close()
