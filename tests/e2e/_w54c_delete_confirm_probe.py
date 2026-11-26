"""W5.4c break-proof + confirmation proof for dash-delete-account.

Three checks that nothing else in the suite makes:
  1. clicking the settings ROW opens the explainer and issues ZERO requests to
     /api/account/delete — the destructive POST is reachable only from the
     confirm button inside the open dialog;
  2. a keyboard/accidental second click on the row still issues zero;
  3. the confirm does the one POST and lands on /login.

Run against a live seeded server:
  DATA_DIR=... DUT_BASE=... python tests/e2e/_w54c_delete_confirm_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DATA_DIR', '/tmp/osrm-w54c')
from _seed import seed, mint_token, require_own_server  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

seed(with_payload=False)
TOK = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:18177')
require_own_server(BASE)
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1280, 'height': 900})
    ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
    page = ctx.new_page()

    hits = []
    page.on('request', lambda r: hits.append(r.url) if '/api/account/delete' in r.url else None)

    page.goto(f'{BASE}/settings', wait_until='networkidle')
    page.reload(wait_until='networkidle')
    page.wait_for_timeout(700)

    # The bundle must own the flow, or this proves the fallback and not the port.
    owns = page.evaluate("() => typeof window.__osrmDeleteAccount")
    check('bundle owns the delete row (window.__osrmDeleteAccount is a function)',
          owns == 'function', owns)

    page.click('#delete-account-btn')
    page.wait_for_timeout(400)
    opened = page.evaluate("() => document.getElementById('delete-account-modal').open")
    check('row click opens the explainer dialog', opened, str(opened))
    check('ROW CLICK SENDS NO DELETE — 0 POSTs so far', len(hits) == 0, f"hits={hits}")

    # The dialog is MODAL, so the row behind it cannot even be hit — a second
    # real click is refused by hit-testing (Playwright proved it: the dialog
    # subtree intercepts pointer events). Then the pathological case: a
    # PROGRAMMATIC click on the row node, which bypasses hit-testing entirely.
    # It may only re-showModal(); it must never reach the fetch.
    modal_blocks = page.evaluate("""() => {
      const r = document.getElementById('delete-account-btn').getBoundingClientRect();
      const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return !!el && !document.getElementById('delete-account-btn').contains(el)
             && !!el.closest('#delete-account-modal');
    }""")
    check('the open modal masks the row (a second real click cannot land)',
          modal_blocks, str(modal_blocks))

    page.evaluate("""() => {
      for (let i = 0; i < 3; i++) {
        document.getElementById('delete-account-btn')
          .dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
      }
    }""")
    page.wait_for_timeout(400)
    check('row re-click (3x, programmatic) still sends no DELETE', len(hits) == 0, f"hits={hits}")

    still = page.evaluate("() => document.getElementById('del-confirm').disabled")
    check('confirm button is still enabled (nothing ran)', still is False, str(still))

    # Now the one path that deletes.
    page.click('#del-confirm')
    try:
        page.wait_for_url('**/login', timeout=10000)
    except Exception:
        pass
    check('CONFIRM sends exactly one DELETE and lands on /login',
          len(hits) == 1 and page.url.rstrip('/').endswith('/login'),
          f"post={len(hits)} url={page.url}")
    b.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} PASS")
sys.exit(1 if fails else 0)
