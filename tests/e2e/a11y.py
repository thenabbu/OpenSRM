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
FATAL_RULES = {
    "color-contrast",
    # Landmark rules are BEST-PRACTICE in axe, so the wcag-only tag filter never
    # reports them — which is how "landmarks/names" was in the plan yet absent
    # from this audit. Named explicitly so they are gated, not merely run.
    "landmark-one-main",
    "landmark-unique",
    "region",
}

# Uncaught page errors are as fatal as a violation: a route that throws while
# serving an accessible-looking DOM is still a broken route.
TAGS = ["wcag2a", "wcag2aa", "wcag21aa", "best-practice"]

# Keyboard leg. 12 stops is more than every route's chrome (skip target, 5 nav
# links, dock, main controls) so a trap or a dead end shows up as a repeat.
TAB_STOPS = 12
MIN_STOPS = 5

PASS = FAIL = 0


def ok(m):
    global PASS
    PASS += 1
    print(f"  [PASS] {m}")


def bad(m):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {m}")


# One predicate for both the keyboard walk and its positive control, so the
# control proves the same code path the assertions trust.
FOCUS_JS = """() => {
    const el = document.activeElement;
    if (!el || el === document.body) return {tag: 'body'};
    const cs = getComputedStyle(el);
    const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0)
              || (cs.boxShadow && cs.boxShadow !== 'none');
    const text = (el.innerText || el.getAttribute('aria-label')
                  || el.getAttribute('title') || el.getAttribute('alt') || '')
                 .trim().replace(/\\s+/g, ' ').slice(0, 24);
    return {tag: el.tagName.toLowerCase(), text: text, visible: !!ring};
}"""


def tab_walk(page, stops):
    """Press Tab `stops` times and report what took focus each time."""
    out = []
    for _ in range(stops):
        page.keyboard.press("Tab")
        out.append(page.evaluate(FOCUS_JS))
    return out


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
                        runOnly: {type: 'tag', values: %s},
                        resultTypes: ['violations'],
                    })""" % TAGS
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
                    nodes = v.get("nodes", [])
                    # The selector, not just the count: "1 node" sends nobody to
                    # the file. It is the first thing a fixer needs.
                    tgt = ", ".join(
                        str(n.get("target", ["?"])[0]) for n in nodes[:2]
                    ) or "-"
                    bad(
                        f"{name}: {v['id']} ({v.get('impact')}) — {len(nodes)} "
                        f"node(s) {tgt}: {v.get('help', '')[:60]}"
                    )
            else:
                ok(f"{name}: no critical/serious violations ({len(viol)} advisory)")

            # ── keyboard navigation + visible focus ───────────────────────
            # axe cannot see either: it scores markup, not a live tab order, and
            # it has no rule for "the ring is visible". These are the two
            # behaviours the plan names that a markup audit structurally misses.
            if name == "dashboard":
                # Positive control for the ring detector. An element with the
                # indicator stripped MUST be flagged, else "every stop is
                # visible" is a sentence about nothing (R-115).
                page.evaluate(
                    """() => {
                        const a = document.createElement('a');
                        a.id = 'focus-probe'; a.href = '#';
                        a.tabIndex = 0; a.textContent = 'probe';
                        a.style.cssText = 'outline:none!important;'
                                        + 'box-shadow:none!important';
                        document.body.appendChild(a);
                        a.focus();
                    }"""
                )
                probe = page.evaluate(FOCUS_JS)
                page.evaluate("() => document.getElementById('focus-probe').remove()")
                if probe.get("tag") == "a" and probe.get("visible") is False:
                    ok("control: the focus detector flags a stripped indicator")
                else:
                    bad(f"control failed — stripped-indicator probe read as {probe}")

            walk = tab_walk(page, TAB_STOPS)
            stops = [s for s in walk if s["tag"] != "body"]
            if len(stops) >= MIN_STOPS:
                ok(f"{name}: {len(stops)}/{TAB_STOPS} Tabs land on a control")
            else:
                bad(f"{name}: only {len(stops)}/{TAB_STOPS} Tabs reach any control "
                    f"— keyboard users cannot get into the page")

            blind = [s for s in stops if not s["visible"]]
            if blind:
                b0 = blind[0]
                bad(f"{name}: {len(blind)}/{len(stops)} focus stops draw NO visible "
                    f"ring (e.g. {b0['tag']} '{b0['text']}')")
            elif stops:
                ok(f"{name}: all {len(stops)} focus stops draw a visible ring")

            # A trap hands focus back to an element already seen instead of
            # moving on; allow one repeat (wrap-around at the end of the page).
            distinct = len({(s["tag"], s["text"]) for s in stops})
            if stops and distinct < len(stops) - 1:
                bad(f"{name}: focus repeats — {distinct} distinct of {len(stops)} "
                    f"stops, looks like a trap")

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
