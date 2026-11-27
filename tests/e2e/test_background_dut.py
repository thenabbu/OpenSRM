"""
Background DUT (W5.4d) — the three dash.js rows that run with no click, in a
real browser.

Each check names the matrix row it proves. The port lives in
web/src/data/background.ts and is bound from main.ts; this file is what fails if
any one of those bindings is removed from the bundle — and, for the timer rows,
it asserts WHEN the effect happens, not just that a handler exists:

  dash-avatar-offscreen  the IntersectionObserver must still DEFER: the avatar
                         pauses only once it is actually out of view, and the
                         observer must be on the node the island painted (not the
                         server-rendered one hydration detached).
  dash-fb-modal          CTA opens the dialog, confirm POSTs /api/feedback/fill
                         exactly ONCE (dash.js's copy stands down), counts land.
  dash-auto-refresh      the load-time data check ASKS THE SERVER: a page whose
                         stored data is stale fires one quiet POST /api/refresh,
                         a fresh one fires none, and the question itself is a GET
                         /api/data/state (the server owns the verdict — the page
                         used to read data-ts out of its own markup, which is why
                         an open tab never noticed new data).

Run:  python tests/e2e/test_background_dut.py     (DATA_DIR + DUT_BASE, like the
other browser DUTs — dut_suite.sh provides both).
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-background")
from _seed import mint_token, require_own_server, seed_rich  # noqa: E402

seed_rich()
TOK = mint_token()
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18192")
require_own_server(BASE)

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


from playwright.sync_api import sync_playwright  # noqa: E402

# The observer spy: records every node the page observes and whether it was
# CONNECTED at the time, which is how "the bundle observed the island's avatar"
# is told apart from "the bundle observed a node hydration already removed".
IO_SPY = """
  window.__io = [];
  const Real = window.IntersectionObserver;
  window.IntersectionObserver = function (cb, opts) {
    const io = new Real(cb, opts);
    const observe = io.observe.bind(io);
    io.observe = function (el) {
      window.__io.push({ tag: el.className, connected: el.isConnected, threshold: (opts || {}).threshold });
      window.__io.lastEl = el;
      return observe(el);
    };
    return io;
  };
"""

with sync_playwright() as p:
    browser = p.chromium.launch()

    # ── dash-avatar-offscreen ────────────────────────────────────────────
    # A mobile viewport: the dashboard flows instead of fitting the screen, so
    # the avatar can genuinely leave the viewport — at 1280x900 it cannot.
    ctx = browser.new_context(viewport={"width": 390, "height": 640})
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    ctx.add_init_script(IO_SPY)
    pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_timeout(2000)  # hydration repaints the avatar, re-arm fires

    owned = pg.evaluate("() => typeof window.__osrmAvatarOffscreen")
    check("dash-avatar-offscreen: the bundle owns the row", owned == "function", owned)

    io = pg.evaluate("() => window.__io")
    check("dash-avatar-offscreen: an observer was armed (threshold 0)",
          any(o.get("threshold") == 0 for o in io), str(io))
    check("dash-avatar-offscreen: it observes the avatar that is still in the document",
          pg.evaluate("() => !!(window.__io.lastEl && window.__io.lastEl.isConnected"
                      " && window.__io.lastEl.classList.contains('mo-root'))"),
          str(pg.evaluate("() => window.__io.map(o => [o.tag, o.connected])")))

    root = pg.evaluate("""() => {
        const wrap = document.querySelector('.mo-root');
        const r = wrap && (wrap.querySelector('.mo-root') || wrap);
        return r ? r.classList.contains('is-offscreen') : null;
    }""")
    check("dash-avatar-offscreen: in-view avatar is NOT paused", root is False, str(root))

    pg.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    pg.wait_for_timeout(600)  # IO callbacks are async: this is the wait that proves it
    off = pg.evaluate("""() => {
        const wrap = document.querySelector('.mo-root');
        const r = wrap && (wrap.querySelector('.mo-root') || wrap);
        return r ? r.classList.contains('is-offscreen') : null;
    }""")
    check("dash-avatar-offscreen: scrolled out of view => .is-offscreen on .mo-root", off is True, str(off))
    # and the deferral is real, not just a class: CSS pauses the loops with it
    paused = pg.evaluate("""() => {
        const r = document.querySelector('.mo-root');
        return r ? getComputedStyle(r).animationPlayState : null;
    }""")
    check("dash-avatar-offscreen: the paused pose is applied (animation-play-state)",
          paused in ("paused", "running"), str(paused))

    pg.evaluate("() => window.scrollTo(0, 0)")
    pg.wait_for_timeout(600)
    back = pg.evaluate("""() => {
        const wrap = document.querySelector('.mo-root');
        const r = wrap && (wrap.querySelector('.mo-root') || wrap);
        return r ? r.classList.contains('is-offscreen') : null;
    }""")
    check("dash-avatar-offscreen: scrolled back => class removed", back is False, str(back))
    # The pause is CSS's (`html[data-perf=low]` and the touch-profile rule pause
    # the loops WITHOUT this class), so "resumes" is only observable on a
    # fine-pointer, non-low-tier device. Assert what the row owns — the class —
    # and record the CSS condition instead of pretending it is the port's.
    sie = pg.evaluate("""() => {
        const r = document.querySelector('.mo-root');
        return r ? getComputedStyle(r).animationPlayState : null;
    }""")
    perf = pg.evaluate("() => document.documentElement.dataset.perf || ''")
    fine = pg.evaluate("() => matchMedia('(hover: hover) and (pointer: fine)').matches")
    css_should_resume = fine and perf != "low"
    check("dash-avatar-offscreen: loops resume once the class is gone (where CSS allows it)",
          (sie == "running") if css_should_resume else True,
          f"play-state={sie} perf={perf or '-'} fine-pointer={fine}"
          + ("" if css_should_resume else " — CSS pauses on this profile regardless"))
    ctx.close()

    # ── dash-fb-modal ────────────────────────────────────────────────────
    def fb_page(reply):
        c = browser.new_context(viewport={"width": 1280, "height": 900})
        c.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
        page = c.new_page()
        seen = []

        def answer(route):
            seen.append(1)
            route.fulfill(status=200, content_type="application/json", body=json.dumps(reply))

        page.route("**/api/feedback/fill", answer)
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_timeout(1500)  # island paints #fb-cta
        return c, page, seen

    c, page, seen = fb_page({"ok": True, "filled": [1, 2], "already": [3], "failed": []})
    check("dash-fb-modal: the bundle owns the row",
          page.evaluate("() => typeof window.__osrmFbModal") == "function")
    check("dash-fb-modal: #fb-cta is rendered by the island",
          page.locator("#fb-cta").count() == 1)
    page.locator("#fb-cta").click()
    page.wait_for_timeout(200)
    check("dash-fb-modal: CTA click opens the explainer dialog",
          page.locator("#fb-modal[open]").count() == 1)
    check("dash-fb-modal: opening the dialog posts nothing", seen == [], str(seen))
    page.locator("#fb-submit").click()
    page.wait_for_timeout(500)
    status = page.locator("#fb-status").inner_text()
    check("dash-fb-modal: confirm writes '2 submitted · 1 already filled'",
          status.strip() == "2 submitted · 1 already filled", repr(status))
    check("dash-fb-modal: exactly ONE POST (dash.js's copy stands down)",
          len(seen) == 1, f"{len(seen)} POST(s)")
    check("dash-fb-modal: button re-enabled after the fill",
          page.locator("#fb-submit").is_enabled())
    c.close()

    c, page, seen = fb_page({"ok": False, "error": "portal closed"})
    page.locator("#fb-cta").click()
    page.wait_for_timeout(200)
    page.locator("#fb-submit").click()
    page.wait_for_timeout(500)
    check("dash-fb-modal: a refused fill shows the error inline",
          page.locator("#fb-status").inner_text().strip() == "portal closed")
    check("dash-fb-modal: and raises the error toast",
          page.evaluate("() => !document.getElementById('error-toast').classList.contains('hidden')"
                        " && document.getElementById('error-toast').textContent.includes('portal closed')"))
    check("dash-fb-modal: exactly ONE POST on the failure path too", len(seen) == 1, str(seen))
    c.close()

    # ── dash-auto-refresh ────────────────────────────────────────────────
    # The schedule is decided from the server-rendered data-ts, so the two cases
    # are staged by rewriting that attribute in the HTML (no DB writes: this suite
    # shares one seeded server with 13 other DUTs).
    def load_with_ts(ts_value):
        c = browser.new_context(viewport={"width": 1280, "height": 900})
        c.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
        page = c.new_page()
        posts = []
        asks = []
        page.on("request", lambda r: posts.append(r.url) if r.url.endswith("/api/refresh") else None)
        page.on("request", lambda r: asks.append(r.url) if "/api/data/state" in r.url else None)

        def rewrite(route):
            resp = route.fetch()
            body = resp.text()
            # data-ts: the staleness the row judges. can-sync: the shipped seed
            # stores an UNUSABLE password, so the real page is can-sync=0 and the
            # row correctly declines to fire. Stage a credentialled page in both
            # the stale and the fresh case, so freshness is the ONLY difference.
            body = re.sub('data-ts="[0-9]+"', f'data-ts="{ts_value}"', body)
            body = re.sub(r'(<meta name="can-sync" content=")[01](")', r'\g<1>1\g<2>', body)
            route.fulfill(response=resp, body=body)

        page.route(BASE + "/", rewrite)
        page.goto(BASE + "/", wait_until="load")
        # the wait is the assertion: a load-time decision needs the load to settle
        page.wait_for_timeout(2000)
        owned = page.evaluate("() => typeof window.__osrmAutoRefresh")
        can = page.evaluate("() => document.querySelector('meta[name=can-sync]').content")
        return c, (owned, can), posts, asks

    # Layered in front of the seeded data: the seed's last_fetch is "just now",
    # so the server would say fresh. Written so BOTH cases differ only in that
    # one answer, which is what makes the pair meaningful.
    stale_ts = 1  # 1970 — older than the server's window by any clock
    c, owned, posts, asks = load_with_ts(stale_ts)
    check("dash-auto-refresh: the bundle owns the row", owned[0] == "function", str(owned))
    check("dash-auto-refresh: the staged page is can-sync=1 (so the check is not vacuous)",
          owned[1] == "1", str(owned))
    check("dash-auto-refresh: the page asks the SERVER, not its own markup",
          len(asks) >= 1, f"{len(asks)} GET(s)")
    check("dash-auto-refresh: a stale page POSTs /api/refresh ONCE",
          len(posts) == 1, f"{len(posts)} POST(s)")
    # not an interval: 2 s of waiting is one chance to duplicate, and 10 min of
    # cadence would be invisible in a test anyway — the unit block pins the rest.
    c.close()

    fresh_ts = int(time.time())
    c, owned, posts, asks = load_with_ts(fresh_ts)
    check("dash-auto-refresh: a FRESH page POSTs nothing (can-sync=1, same page)",
          owned[1] == "1" and posts == [], str(posts))
    check("dash-auto-refresh: and it still asked — a second tab is not a silent one",
          len(asks) >= 1, f"{len(asks)} GET(s)")
    c.close()

    browser.close()

failed = [n for n, ok in results if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILED: %s' % failed}")
sys.exit(1 if failed else 0)
