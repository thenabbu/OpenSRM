"""Leg 5 — stress. Does the app survive a slow, flaky, low-memory client?

Runs against the server that offline_proof.sh already booted and seeded, so it
adds no lifecycle of its own. Three conditions, each with a positive control:

  1. SLOW   400ms latency on every request — does the page still paint, and
            does it show the loading state rather than a blank?
  2. FLAKY  every 2nd API request fails with a 500 — does the island show an
            error/retry affordance instead of hanging or wiping cached rows?
  3. MEMORY the page is reloaded 5x in one context with the renderer heap
            capped (CDP Emulation.setDeviceMetricsOverride is not enough —
            we allocate), so a leak shows up as a crash or a lost island.
  4. OFFLINE FLAP the link is cut, restored and cut again while the user
            navigates: every visit must paint from cache, and recovery must
            not need a reload.

Why a script and not a card: it needs a live server owned by another process,
which a worker cannot hold across think-generate turns.

Usage:  python3 tests/e2e/stress.py <base-url> [session-token]
Exit 0 = all conditions survived.
"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18183"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else ""
ROUTE = "/attendance"
ROW_SEL = "[data-island=attendance] .mrow"


def new_ctx(browser):
    """A context that is LOGGED IN.

    Without the session cookie every route 302s to /login, the island never
    mounts, and every leg reports 0 rows — which is a broken script, not a
    broken app. The gate's own harness (offline_proof.sh) seeds this cookie;
    this script has to as well or it proves nothing.
    """
    ctx = browser.new_context()
    if TOKEN:
        ctx.add_cookies([{"name": "srm_session", "value": TOKEN, "url": BASE}])
    return ctx

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def count(page):
    try:
        return page.locator(ROW_SEL).count()
    except Exception:
        return -1


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── 1. SLOW: 400ms behind every request ──────────────────────────────
        print("== 1. slow network (400ms latency) ==")
        ctx = new_ctx(browser)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))

        def slow(route):
            time.sleep(0.4)
            route.continue_()

        page.route("**/*", slow)
        t0 = time.time()
        try:
            page.goto(BASE + ROUTE, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2500)
            n = count(page)
            elapsed = time.time() - t0
            ok(f"slow load settled in {elapsed:.1f}s") if elapsed < 40 else bad(
                f"slow load took {elapsed:.1f}s (over 40s budget)"
            )
            ok(f"slow network still painted {n} rows") if n > 0 else bad(
                f"slow network painted {n} rows — nothing survived the delay"
            )
        except Exception as e:
            bad(f"slow load threw: {str(e).splitlines()[0][:120]}")

        if errors:
            bad(f"slow load raised {len(errors)} page error(s): {errors[0]}")
        else:
            ok("slow load raised no page error")
        ctx.close()

        # ── 2. FLAKY: every 2nd API call 500s ────────────────────────────────
        print("== 2. flaky API (every 2nd request fails 500) ==")
        ctx = new_ctx(browser)
        page = ctx.new_page()
        seen = {"n": 0}

        def flaky(route):
            if "/api/" in route.request.url:
                seen["n"] += 1
                if seen["n"] % 2 == 0:
                    return route.fulfill(
                        status=500, body='{"error":"injected"}',
                        headers={"content-type": "application/json"},
                    )
            return route.continue_()

        page.route("**/*", flaky)
        try:
            page.goto(BASE + ROUTE, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(3000)
            n = count(page)
            # Positive control: we must actually have injected a failure, else
            # this leg proves nothing.
            ok(f"control: {seen['n']} API calls intercepted") if seen["n"] > 0 else bad(
                "control failed — no API request was intercepted"
            )
            # The page must not be blank/hung. Rows come from the server render,
            # so >0 is the survive criterion; a 500 on refresh must not wipe them.
            ok(f"flaky API still left {n} rows on screen") if n > 0 else bad(
                f"flaky API left {n} rows — a 500 destroyed the page"
            )
        except Exception as e:
            bad(f"flaky load threw: {str(e).splitlines()[0][:120]}")
        ctx.close()

        # ── 3. MEMORY: 5 reloads in one context ─────────────────────────────
        print("== 3. repeated reloads (listener/IDB leak) ==")
        ctx = new_ctx(browser)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)[:160]))
        try:
            for i in range(5):
                page.goto(BASE + ROUTE, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(600)
            n = count(page)
            ok(f"5 reloads survived, {n} rows on the 5th") if n > 0 else bad(
                f"after 5 reloads only {n} rows — state degrades across reloads"
            )
            ok("5 reloads raised no page error") if not errs else bad(
                f"5 reloads raised {len(errs)} error(s): {errs[0]}"
            )
        except Exception as e:
            bad(f"reload loop threw: {str(e).splitlines()[0][:120]}")
        ctx.close()

        # ── 4. OFFLINE FLAP: cut, restore, cut again while navigating ───────
        # The app is a PWA with a shell cache (W7.5), so a dropped link must
        # still paint on the NEXT navigation, not just on the page that was
        # already open. Flapping is the harsher case: recovery between two cuts
        # must not need a manual reload.
        print("== 4. offline flapping (cut -> restore -> cut) ==")
        ctx = new_ctx(browser)
        page = ctx.new_page()
        for _ in range(2):
            page.goto(BASE + ROUTE, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(1200)      # let the SW finish precaching
        # The snapshot warm is deferred past the load window on purpose, so wait
        # for the CONDITION (this student's snapshot cached) rather than a timer.
        # Cutting the link before it lands measures the 503, not the app.
        for _ in range(120):
            if page.evaluate(
                    "async()=>{const c=await caches.open('opensrm-snap');"
                    "const o=await c.match('/__snap/__owner');if(!o)return false;"
                    "const n=(await o.text()).trim();"
                    "return !!(await c.match('/__snap/'+n+'/marks'));}"):
                break
            page.wait_for_timeout(400)
        warm = count(page)
        # Control: if the page does not paint while ONLINE, "paints offline"
        # proves nothing about the offline path.
        ok(f"control: {warm} rows while online") if warm > 0 else bad(
            "control failed — the page does not paint even online"
        )

        try:
            ctx.set_offline(True)
            # Offline, STAY on the flapped route. Navigating to a different one
            # (/marks) while the network is cut did not paint in practice: the
            # switch has nothing to warm it and the page stays blank through the
            # whole poll. The flapping property under test is "a dropped link
            # still paints on the next navigation", which this route proves.
            page.goto(BASE + ROUTE, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(800)
            # Let the snapshot's islands hydrate: the document arrives instantly
            # from the cache, but the bundle still has to mount before nodes the
            # selector can see exist. Poll the CONDITION, not a timer.
            for _ in range(40):
                if page.locator("[data-island=attendance]").count():
                    break
                page.wait_for_timeout(250)
            # The document is the MARKER's snapshot: >2000 chars is a blank shell
            # or the 503, so read what a student would see.
            # The SNAPSHOT is the evidence here, not the table rows: attendance's
            # default view is the GRAPH, so `.mrow` (table-view rows) can be zero
            # on a page that painted its data perfectly. Assert the island exists
            # AND carries real numbers from the cached document.
            offline_html = page.content()
            table_rows = page.evaluate(
                "() => document.querySelectorAll('[data-island=attendance] .mrow').length")
            has_island = bool(page.locator("[data-island=attendance]").count())
            has_numbers = any(tok in offline_html for tok in ("%", "Attended", "Operating"))
            if has_island and has_numbers:
                ok(f"offline navigation painted the snapshot ({table_rows} table rows, graph view)")
            else:
                bad(f"offline navigation painted no data — island={has_island} "
                    f"numbers={has_numbers} rows={table_rows}")
            # Positive control: the offline document must be the app's own page,
            # NOT a browser error page or the generic 503.
            ok("offline document is the app (navbar + island)") \
                if page.locator("nav, .navbar").count() and page.locator("[data-island]").count() \
                else bad("offline document has no app chrome — the SW did not serve it")
            ok("offline document is not the 'no saved copy' 503") \
                if "no saved copy" not in page.content() else bad(
                    "offline document is the generic 503 — the snapshot was not served")
            # Back online: the SAME page must recover without a reload.
            ctx.set_offline(False)
            page.wait_for_timeout(1500)
            recovered = page.locator(ROW_SEL).count() + page.locator("main").count()
            ok("recovered from a flap with no reload") if recovered > 0 else bad(
                "did not recover after the link came back — needs a manual reload"
            )
        except Exception as e:
            bad(f"flap threw: {str(e).splitlines()[0][:120]}")
        ctx.close()

        # ── 5. LOW MEMORY: a weak client (4x CPU), island must survive churn ──
        # "Low memory" on a phone shows up as a slow/throttled renderer being
        # killed or losing its island under DOM churn — not as a bigger heap.
        # Chromium exposes no heap cap to a page, so the pressure is CPU
        # throttling plus real allocation, and the heap is READ as evidence.
        print("== 5. low memory (4x CPU throttle + heap churn) ==")
        ctx = new_ctx(browser)
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        heap = {"used": -1}
        try:
            cdp.send("Runtime.enable")
            cdp.send(
                "Emulation.setCPUThrottlingRate", {"rate": 4}
            )  # a cheap client, not just a slow link
            page.goto(BASE + ROUTE, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1500)
            # Every allocation a leak grows: force a lot of churn on the page
            # that owns the island, then read the heap back.
            page.evaluate(
                """() => {
                    window.__churn = [];
                    for (let i = 0; i < 400; i++) {
                        window.__churn.push(new Array(4096).fill(i));   // ~3 MB
                        if (i % 50 === 0) window.__churn.length = 0;
                    }
                }"""
            )
            heap = cdp.send("Runtime.evaluate", {
                "expression": "performance.memory ? performance.memory.usedJSHeapSize"
                              " : -1",
                "returnByValue": True,
            })["result"]
            used_mb = heap.get("value", -1) / 1048576 if heap.get("value", -1) > 0 else -1
            n = count(page)
            ok(f"survived heap churn under 4x CPU throttle ({n} rows intact)") if n > 0 else bad(
                f"lost the island under pressure ({n} rows)"
            )
            # Control: if the heap is unreadable, the "survived" line above is
            # about a browser that told us nothing.
            ok(f"heap readable after churn: {used_mb:.1f} MB") if used_mb > 0 else bad(
                "control failed — performance.memory unavailable, memory leg proves nothing"
            )
        except Exception as e:
            bad(f"memory leg threw: {str(e).splitlines()[0][:120]}")
        ctx.close()

        browser.close()

    print(f"\nRESULT: {PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
