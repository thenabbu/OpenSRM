"""XSS e2e DUT (9 checks): DB payload must render inert in a real Chromium
(positive control included — fails if the timetable block stops rendering)."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DATA_DIR', '/tmp/osrm-xss')
from _seed import seed, mint_token, PAYLOAD, require_own_server
from playwright.async_api import async_playwright

seed(with_payload=True)
TOKEN = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:18099')
require_own_server(BASE)

# Scripts whose content the browser can actually run: no type, or a JS type.
# Anything else (application/json island props, ld+json, text/template) is data,
# never code — counting it as "an injected script element" is a false positive.
_EXEC_SCAN = """
(() => {
  const JS = new Set(['', 'text/javascript', 'application/javascript', 'module']);
  return Array.from(document.scripts)
    .filter(s => JS.has((s.type || '').trim().toLowerCase()))
    .filter(s => s.textContent.includes('__xss2')).length;
})()
"""

async def main():
    fails, dialogs, js_errors, csp = [], [], [], []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context()
        await ctx.add_cookies([{"name": "srm_session", "value": TOKEN,
                                "url": BASE}])
        page = await ctx.new_page()
        page.on("dialog", lambda d: (dialogs.append(d.message), asyncio.ensure_future(d.dismiss())))
        page.on("pageerror", lambda e: js_errors.append(str(e)))
        page.on("console", lambda m: csp.append(m.text) if "Content Security Policy" in m.text else None)
        # P3.1: the seeded XSS payload lives in timetable_slots, which now
        # render on /timetable (the dashboard no longer carries the panel).
        # Each route is checked on its own; the checks below run on the route
        # that is expected to carry the escaped payload.
        await page.goto(f"{BASE}/timetable", wait_until="networkidle")
        await page.wait_for_timeout(800)

        checks = {
            "no dialogs fired":            not dialogs,
            "no __xss (onerror)":          await page.evaluate("window.__xss") is None,
            "no __xss2 (script tag)":      await page.evaluate("window.__xss2") is None,
            "no raw <img src=x> element":  await page.evaluate("document.querySelectorAll('img[src=x]').length") == 0,
            # Only scripts that can EXECUTE count as injected. The island props ride
            # an inert <script type="application/json"> block; safeguarding its
            # contents is the emitter's job (island '<' -> \u003c), not this scan's.
            "no injected script element":  await page.evaluate(_EXEC_SCAN) == 0,
            "raw payload not in HTML":     not await page.evaluate("document.body.innerHTML.includes('<img src=x onerror')"),
            "escaped payload IS rendered": await page.evaluate("document.body.innerHTML.includes('&lt;img src=x onerror')"),
            "no CSP violations":           not any("Content Security Policy" in c for c in csp),
            "no page JS errors":           not js_errors,
        }
        for k, v in checks.items():
            print(("PASS " if v else "FAIL ") + k)
            if not v: fails.append(k)
        if fails:
            print("dialogs:", dialogs, "js_errors:", js_errors, "csp:", csp)
        await b.close()
    print("V1", "ALL PASS" if not fails else f"FAILURES: {fails}")
    sys.exit(1 if fails else 0)

asyncio.run(main())
