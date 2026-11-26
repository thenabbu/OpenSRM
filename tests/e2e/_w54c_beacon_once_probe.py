"""One tracked click => exactly ONE /api/track/tab beacon.

dash.js binds its beacon listener at PARSE time and stands down on
`window.__osrmItemBeacon`; the bundle binds its own. If both ever bound, every
tracked click would beacon twice and the analytics would double-count. W5.4c
measured it while checking whether its own stand-downs could race load order:
1 POST, so the bundle's marker is in place before dash.js parses.

  DATA_DIR=... DUT_BASE=... python tests/e2e/_w54c_beacon_once_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DATA_DIR', '/tmp/osrm-w54c2')
from _seed import seed, mint_token, require_own_server  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

seed()
TOK = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:18177')
require_own_server(BASE)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1280, 'height': 900})
    ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
    page = ctx.new_page()
    hits = []
    page.on('request', lambda r: hits.append(r.url) if '/api/track/tab' in r.url else None)
    page.goto(f'{BASE}/marks', wait_until='networkidle')
    page.wait_for_timeout(1200)
    markers = page.evaluate("() => ({beacon: typeof window.__osrmItemBeacon, "
                            "scroll: typeof window.__osrmScrollIndicator})")
    # A tracked, non-refresh element so a sync cannot add its own click noise.
    page.evaluate("""() => {
      const el = document.createElement('button');
      el.id = 'probe-track'; el.setAttribute('data-track-item', 'probe');
      document.body.appendChild(el);
    }""")
    # Not page.click(): the dock overlay intercepts hit-testing. A bubbling
    # MouseEvent is what the delegated document listener sees either way.
    page.evaluate("() => document.getElementById('probe-track')"
                  ".dispatchEvent(new MouseEvent('click', {bubbles: true}))")
    page.wait_for_timeout(1200)
    print('markers:', markers, '| /api/track/tab POSTs for one click:', len(hits))
    b.close()
