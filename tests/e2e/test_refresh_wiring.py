"""W5.2a: does the BUNDLE own the refresh click, and only once?

The refresh primitive moved out of dash.js into web/src/data/refresh.ts, and
dash.js keeps a PREACT_ISLANDS=0 fallback for the same buttons. That is exactly
the shape that fails silently: two binders = two syncs per click, or a fallback
that wins and a port nobody exercises. So assert the wiring itself, in a browser.

Asserts, in a real browser on a seeded server:
  * the bundle published __osrmRevalidate + __osrmShowError (so dash.js's binder
    stands down and the fallback body is dead code on this page);
  * ONE click on [data-refresh] issues EXACTLY ONE POST /api/refresh (one binder);
  * no navigation, busy state cleared, and the caption obeys the answer: a
    landed sync resets the age, a cached or FAILED one leaves it alone (a failed
    one now also shows the server's own message in #error-toast, which is the
    errorToast.ts port doing its job).

Run: python tests/e2e/test_refresh_wiring.py   (seeded server on DUT_BASE)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-w52a-probe")
from _seed import seed_rich, mint_token, require_own_server
from playwright.sync_api import sync_playwright

seed_rich()
BASE = os.environ["DUT_BASE"]
require_own_server(BASE)
TOK = mint_token()
res = []


def check(name, ok, detail=""):
    res.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 393, "height": 851})
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg = ctx.new_page()
    posts = []
    nav = []
    replies = []

    def _resp(r):
        if r.request.method == "POST" and "/api/refresh" in r.url:
            try:
                replies.append(r.json())
            except Exception:
                replies.append({"ok": False, "cached": None})

    pg.on("request", lambda r: posts.append(r.url) if r.method == "POST" and "/api/refresh" in r.url else None)
    pg.on("response", _resp)
    pg.on("framenavigated", lambda f: nav.append(f.url))
    pg.goto(BASE + "/", wait_until="networkidle")

    check("dashboard loaded (not /login)", pg.url.rstrip("/") == BASE.rstrip("/"), pg.url)
    check("bundle published __osrmRevalidate",
          pg.evaluate("() => typeof window.__osrmRevalidate === 'function'"))
    check("bundle published __osrmShowError",
          pg.evaluate("() => typeof window.__osrmShowError === 'function'"))
    check("bundle published __osrmRefreshData",
          pg.evaluate("() => typeof window.__osrmRefreshData === 'function'"))

    before = pg.evaluate("""() => {
      const el = document.querySelector('.sync-line');
      return el ? el.dataset.ts || '0' : null;
    }""")
    nav.clear()
    posts.clear()
    pg.locator("[data-refresh]:visible").first.click()
    pg.wait_for_timeout(2500)
    reply = replies[0] if replies else {}
    check("the POST answered with the server's own JSON", isinstance(reply.get("ok"), bool), str(reply)[:90])
    check("exactly ONE POST /api/refresh for one click", len(posts) == 1, f"{len(posts)} POST(s)")
    check("click caused no navigation", not nav, ",".join(nav[:2]))
    check("busy state released",
          pg.evaluate("() => ![...document.querySelectorAll('[data-refresh]')].some(b => b.getAttribute('aria-disabled') === 'true')"))
    after = pg.evaluate("""() => {
      const el = document.querySelector('.sync-line');
      return el ? el.dataset.ts || '0' : null;
    }""")
    # The caption contract, both branches: a sync that LANDED resets the age;
    # a CACHED answer (SYNC_MIN_INTERVAL_S) must not claim a fresh one.
    toast = pg.evaluate("() => { const t = document.getElementById('error-toast'); return t ? [t.textContent, t.classList.contains('hidden')] : null; }")
    if not reply.get("ok"):
        # A seeded user has no readable portal password, so /api/refresh answers
        # {ok:false}. The contract then: age untouched (nothing was synced) and
        # the server's own message on the toast — which is the errorToast.ts
        # port doing its job in a real browser.
        check("a FAILED sync left the caption age alone", after == before, f"{before} -> {after}")
        check("the server's error reached #error-toast (errorToast.ts port live)",
              bool(toast) and toast[1] is False and reply.get("error", "x") in (toast[0] or ""),
              str(toast)[:90])
    elif reply.get("cached"):
        check("cached answer left the age alone (claims nothing it did not do)",
              after == before, f"{before} -> {after} (cached)")
    else:
        check("a landed sync reset the caption age", after != before, f"{before} -> {after}")
    b.close()

bad = [n for n, ok in res if not ok]
print(f"W5.2A PROBE: {len(res) - len(bad)} passed, {len(bad)} failed")
sys.exit(1 if bad else 0)
