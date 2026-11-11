"""Leg — accessibility audit of all 9 routes using axe-core.

Covers plan unit 9.3, which had only one single-page contrast probe.

axe-core is injected from a vendored copy of the npm package (no CDN — the app's
CSP is `script-src 'self'` and this must run under the same rules a user does).
Fetch it once into app/static/vendor/ or point AXE at an existing copy.

Severity policy — the audit fails on:
  - critical and serious violations, always
  - moderate violations of `color-contrast`, because contrast is the one thing
    the design work here has repeatedly got wrong and regressed
Everything else is reported but not fatal, so the gate stays honest instead of
becoming a list of things nobody will fix.

Usage:  python3 tests/e2e/a11y.py <base-url> <session-token>
Exit 0 = no critical/serious violations on any route.
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18183"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else ""

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AXE_CANDIDATES = [
    os.path.join(REPO, "app", "static", "vendor", "axe.min.js"),
    os.path.join(REPO, "web", "node_modules", "axe-core", "axe.min.js"),
    "/opt/data/opensrm-repo/web/node_modules/axe-core/axe.min.js",
]

ROUTES = [
    ("/", "dashboard"),
    ("/attendance", "attendance"),
    ("/timetable", "timetable"),
    ("/marks", "marks"),
    ("/campus", "campus"),
    ("/academics", "academics"),
    ("/fees", "fees"),
    ("/tools", "tools"),
    ("/settings", "settings"),
]

FATAL_IMPACT = {"critical", "serious"}
FATAL_RULES = {"color-contrast"}

PASS = FAIL = 0


def ok(m):
    global PASS
    PASS += 1
    print(f"  [PASS] {m}")


def bad(m):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {m}")


def find_axe():
    for p in AXE_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def main():
    axe_path = find_axe()
    if not axe_path:
        # Fail loudly. A silent skip is the exact defect this mission keeps
        # finding: an assertion that never runs looks identical to one that passes.
        print("  [FAIL] axe-core not found. Tried:")
        for p in AXE_CANDIDATES:
            print(f"         {p}")
        print("         Install: cd web && pnpm add -D axe-core")
        return 1
    print(f"axe-core: {axe_path}")
    axe_src = open(axe_path, encoding="utf-8").read()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        if TOKEN:
            ctx.add_cookies([{"name": "srm_session", "value": TOKEN, "url": BASE}])

        total = 0
        for path, name in ROUTES:
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)[:140]))
            try:
                resp = page.goto(BASE + path, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1200)
                if resp and resp.status >= 400:
                    bad(f"{name}: HTTP {resp.status} (route may be scope-gated off)")
                    page.close()
                    continue
                # Inject from a same-origin URL, not inline. The app's CSP is
                # `script-src 'self'` and add_script_tag(content=...) counts as
                # inline — it threw on all 9 routes. Serving the vendored file
                # over /static/ makes the audit obey the same policy a user does.
                page.add_script_tag(url="/static/vendor/axe.min.js")
                page.wait_for_function("() => typeof axe !== 'undefined'", timeout=15_000)
                res = page.evaluate(
                    """async () => await axe.run(document, {
                        runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa']},
                        resultTypes: ['violations'],
                    })"""
                )
            except Exception as e:
                bad(f"{name}: threw {str(e).splitlines()[0][:110]}")
                page.close()
                continue

            viol = res.get("violations", [])
            fatal = [
                v for v in viol
                if v.get("impact") in FATAL_IMPACT or v.get("id") in FATAL_RULES
            ]
            total += len(fatal)
            if fatal:
                for v in fatal:
                    nodes = len(v.get("nodes", []))
                    bad(
                        f"{name}: {v['id']} ({v.get('impact')}) — {nodes} node(s): "
                        f"{v.get('help', '')[:70]}"
                    )
            else:
                ok(f"{name}: no critical/serious violations ({len(viol)} advisory)")
            if errors:
                bad(f"{name}: {len(errors)} page error(s) — {errors[0]}")
            page.close()

        ctx.close()
        browser.close()

    print(f"\nfatal violations: {total}")
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
