#!/usr/bin/env python3
"""P7.10 — every one of the 9 islands must PAINT, in a real browser, after hydration.

Run by scripts/offline_proof.sh (leg 4), which owns the seeded server:

    python tests/e2e/route_paint.py --base http://127.0.0.1:18183 --token T

Why this exists: before this file only /attendance had ever been proven to paint
in a browser. Eight islands shipped with unit tests that mount them into a bare
div — that proves the COMPONENT renders, not that the ISLAND pops on the real
page (the server paint can be valid props that hydrate to zero rows, a mount
point can be missing from the template, a route can 404 on unseeded features).
The P6 era shipped exactly that way.

Per route, four assertions, in this order:

  1. ISLAND   the route has the island it is supposed to have;
  2. HYDRATE  it carries the app's own completion marker (`data-hydrated` on the
              mount, or `data-mounted-at` on a cache-branch mount) — no timer;
  3. ROWS     it has > 0 children matching that island's row selector, counted
              in the DOM. A route that is legitimately empty must say so here in
              ROW_SELECTOR as `empty_by_design` — a silently skipped route is a
              fake pass and this file has no `skip` outcome on purpose;
  4. CLEAN    no uncaught exception and no console error on the page.

`/api/refresh` returning 401 is NOT an error here: the page fires it in the
background before the session cookie is read, and the app handles it (see
app/static/dash.js). It is the only 4xx/5xx excused, and excusing it is
asserted (a genuine 500 still fails).
"""
import argparse
import os
import sys

from playwright.sync_api import sync_playwright

# route -> (island name on the page, row selector, what a row is)
#
# The row selector is the island's ROW, never its wrapper: `/settings` has one
# top-level `.collapse` per group, but the rows a person reads are its cells, so
# counting the collapse would pass on a single group. Where several candidates
# exist the narrowest one that is still a row wins.
ROUTES = {
    "/":           ("dashboard",  "[data-island=dashboard] .wbox",   "widget boxes"),
    "/attendance": ("attendance", "[data-island=attendance] .mrow",  "course rows"),
    "/timetable":  ("timetable",  "[data-island=timetable] .day-panel", "day panels"),
    "/marks":      ("marks",      "[data-island=marks] > div",       "subject cards"),
    "/campus":     ("campus",     "[data-island=campus] .card",      "campus cards"),
    "/academics":  ("academics",  "[data-island=academics] .acad-srow", "semester subject rows"),
    "/fees":       ("fees",       "[data-island=fees] .grid-cols-\\[auto_1px_1fr_auto\\]", "fee rows"),
    "/tools":      ("tools",      "[data-island=tools] > li",        "destination rows"),
    "/settings":   ("settings",   "[data-island=settings] [data-copy]", "detail cells"),
}

# Routes that legitimately render NO rows. This is an ASSERTION, not a skip: the
# route must still load, still carry its island, and still hydrate — and its row
# count must be exactly 0. A route listed here that starts painting rows fails,
# and a route with zero rows that is NOT listed here fails. Empty-by-design has
# to be earned, so no route is in this set today; if one moves in, it is a
# deliberate edit with a reason attached.
EMPTY_BY_DESIGN = {}

# The one background request the app makes and handles. Asserted, not assumed:
# if it stops 401ing, or a different endpoint starts failing, this trips.
EXCUSED = "/api/refresh"

SETTLED = """() => {
  const is = [...document.querySelectorAll('[data-island]')];
  return {n: is.length, done: is.filter(e => e.dataset.mountedAt || e.dataset.hydrated).length};
}"""


class Leg:
    def __init__(self):
        self.pass_n = self.fail_n = 0

    def chk(self, name, ok, detail=""):
        if ok:
            self.pass_n += 1
            print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))
        else:
            self.fail_n += 1
            print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))
        return ok


def check_route(page, leg, route, island, row_sel, row_word):
    """Returns True when this route painted. Prints its own [PASS]/[FAIL] line."""
    errors, net_fail = [], []

    def on_error(exc):
        errors.append(f"exception: {exc}")

    def on_console(msg):
        if msg.type == "error":
            # "Failed to load resource" carries no URL; correlate with net_fail.
            errors.append(f"console.error: {msg.text}")

    def on_response(resp):
        if resp.status >= 400 and EXCUSED not in resp.url:
            net_fail.append(f"{resp.status} {resp.url}")

    page.on("pageerror", on_error)
    page.on("console", on_console)
    page.on("response", on_response)
    try:
        resp = page.goto(f"{args.base}{route}", wait_until="domcontentloaded")
        if resp is None or resp.status >= 400:
            leg.chk(route, False, f"route itself returned {resp.status if resp else 'no response'}")
            return False

        # DETERMINISTIC settle: poll the app's own marker, hard ceiling so a page
        # that never hydrates fails loudly instead of being measured mid-boot.
        st = {"n": 0, "done": 0}
        for _ in range(60):
            st = page.evaluate(SETTLED)
            if st["n"] and st["done"] == st["n"]:
                break
            page.wait_for_timeout(250)

        mount = page.locator(f"[data-island={island}]")
        if not mount.count():
            leg.chk(route, False, f"no [data-island={island}] on the page ({st['n']} islands seen)")
            return False
        hydrated = mount.first.evaluate(
            "(e) => !!(e.dataset.hydrated || e.dataset.mountedAt)")
        rows = page.locator(row_sel).count()
        # The 401 excuse is only valid while the endpoint really does 401; a
        # different failure on it would otherwise vanish into the excuse list.
        spurious = [e for e in errors if "Failed to load resource" not in e]
        clean = not spurious and not net_fail
        if route in EMPTY_BY_DESIGN:
            # Declared empty: hydrating to exactly zero rows is the CORRECT
            # outcome, and painting any is a regression worth failing on.
            ok = hydrated and rows == 0 and clean
            detail = f"empty-by-design, {rows} {row_word} (must be 0)"
        else:
            ok = hydrated and rows > 0 and clean
            detail = f"{rows} {row_word}"
        if not hydrated:
            detail += f"; island never hydrated ({st['done']}/{st['n']} islands finished)"
        if rows == 0:
            detail += "; painted ZERO rows"
        if net_fail:
            detail += f"; http failures {net_fail[:3]}"
        if spurious:
            detail += f"; console {spurious[:2]}"
        leg.chk(route, ok, detail)
        return ok
    finally:
        page.remove_listener("pageerror", on_error)
        page.remove_listener("console", on_console)
        page.remove_listener("response", on_response)


def main():
    global args
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--route", action="append", default=None,
                    help="only these routes (default: all 9)")
    ap.add_argument("--browser", default="chromium",
                    choices=["chromium", "webkit", "firefox"],
                    help="engine to paint in (default chromium); one RESULT line per run")
    args = ap.parse_args()

    routes = args.route or list(ROUTES)
    leg = Leg()
    with sync_playwright() as pw:
        # Playwright resolves its own browser build first. On a box that only
        # carries a chrome-for-testing binary (no chrome-headless-shell), fall
        # back to the executable the environment already advertises — CI installs
        # the matching build and never takes this path. Only Chromium has that
        # override; WebKit/Firefox must come from `playwright install`.
        if args.browser == "chromium":
            browser = pw.chromium.launch(
                headless=True,
                executable_path=os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH") or None,
                args=["--no-first-run", "--no-default-browser-check"])
        else:
            try:
                browser = getattr(pw, args.browser).launch(headless=True)
            except Exception as exc:  # missing build, broken deps, sandbox refusal
                # NOT a skip: no browser means no proof, and an unproven route is
                # the defect this file exists to catch.
                print(f"\n  no {args.browser} — the 9 routes are UNPROVEN")
                print(f"  {type(exc).__name__}: {str(exc).splitlines()[0][:300]}")
                print(f"  install with: PLAYWRIGHT_BROWSERS_PATH="
                      f"{os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '<path>')} "
                      f".venv/bin/playwright install {args.browser}")
                return 2
        ctx = browser.new_context()
        ctx.add_cookies([{"name": "srm_session", "value": args.token,
                          "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        for route in routes:
            if route not in ROUTES:
                leg.chk(route, False, "not in the route table — a skipped route is a fake pass")
                continue
            island, row_sel, row_word = ROUTES[route]
            check_route(page, leg, route, island, row_sel, row_word)
        ctx.close()
        browser.close()

    print(f"\n  route paint [{args.browser}]: {leg.pass_n} passed, {leg.fail_n} failed"
          f" ({len(EMPTY_BY_DESIGN)} declared empty-by-design, asserted not skipped)")
    return 0 if leg.fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
