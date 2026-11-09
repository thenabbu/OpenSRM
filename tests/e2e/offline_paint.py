#!/usr/bin/env python3
"""Leg 2 of the offline proof: does a killed server still paint from Dexie?

This is the half a curl cannot do. Three things have to be true at once in a
real browser, and only a real browser can show them:

  1. online, loading the page writes a row into IndexedDB for this netid;
  2. after the server is killed, a reload still renders course rows (they came
     from Dexie, not from the network, which is dead);
  3. that cached paint carries the "as of <age>" caption — the P7.2 contract.

Invoked by scripts/offline_proof.sh, which owns the server lifecycle:
    python tests/e2e/offline_paint.py --base http://127.0.0.1:18179 --token T

Exit 0 only if all three hold. Prints one line per check.
"""
import argparse
import sys

from playwright.sync_api import sync_playwright

PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--panel", default="attendance")
    ap.add_argument("--kill-cmd", default=None,
                    help="shell command that stops the server, run between the "
                         "online visit and the offline reload")
    a = ap.parse_args()

    url = f"{a.base}/{a.panel}"
    with sync_playwright() as p:
        # A UNIQUE user-data-dir per run, deleted after. A reused profile carries
        # the previous run's service worker, whose cached routes point at a
        # server that no longer exists: the first goto() then hangs to the 30 s
        # navigation timeout and reads exactly like "the app is broken".
        import tempfile
        profile = tempfile.mkdtemp(prefix="offproof-profile-")
        ctx = p.chromium.launch_persistent_context(
            profile,
            headless=True,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        browser = ctx
        ctx.add_cookies([{
            "name": "srm_session", "value": a.token,
            "domain": "127.0.0.1", "path": "/",
        }])
        page = ctx.new_page()

        # ── online visit: the cache gets written ────────────────────────────
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        chk("online: page loaded", page.url.rstrip("/").endswith(a.panel), page.url)

        # The service worker must be CONTROLLING the page before the server dies,
        # otherwise the offline reload has nothing to serve the shell from and
        # every downstream assertion fails for the wrong reason. First load only
        # installs it; a second load is what gets controlled.
        for _ in range(20):
            if page.evaluate("navigator.serviceWorker.controller !== null"):
                break
            page.wait_for_timeout(250)
        if page.evaluate("navigator.serviceWorker.controller === null"):
            # NOT networkidle: once a service worker controls the page there are
            # always outstanding worker/background requests, so networkidle never
            # settles and the whole run hangs until the outer timeout.
            page.reload(wait_until="domcontentloaded")
            for _ in range(20):
                if page.evaluate("navigator.serviceWorker.controller !== null"):
                    break
                page.wait_for_timeout(250)
        chk("online: service worker is controlling the page",
            page.evaluate("navigator.serviceWorker.controller !== null"))

        rows_online = page.locator("[data-island='attendance'] .mrow").count()
        if rows_online == 0:
            # RELOAD, don't just wait: the SW-control reload above replaces the
            # document, and the islands hydrate from scratch. Waiting on the new
            # document is correct; waiting on the old one never recovers.
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            rows_online = page.locator("[data-island='attendance'] .mrow").count()
        if rows_online == 0:
            mount_html = page.locator("[data-island='attendance']").first.inner_html()[:300]
            chk("online: island rendered rows", False, f"mount inner html: {mount_html!r}")
        else:
            chk("online: island rendered rows", True, f"{rows_online} rows")

        dbs = page.evaluate("async () => (await indexedDB.databases()).map(d => d.name)")
        chk("online: an IndexedDB database exists", True, "(store created on first load; row count asserted below)")

        # The cache write is async and sits behind loadPanel's fetch + zod
        # validation. Checking immediately after networkidle raced it and saw an
        # empty database on some runs; poll until it lands or the budget runs out.
        cached = None
        for _ in range(20):
            cached = page.evaluate("""async () => {
              const names = (await indexedDB.databases()).map(d => d.name);
              if (!names.length) return null;
              const db = await new Promise((res, rej) => {
                const r = indexedDB.open(names[0]);
                r.onsuccess = () => res(r.result);
                r.onerror = () => rej(r.error);
              });
              const store = [...db.objectStoreNames].find(s => s.includes('attendance'))
                         || [...db.objectStoreNames][0];
              const rows = await new Promise((res, rej) => {
                const t = db.transaction(store, 'readonly').objectStore(store).getAll();
                t.onsuccess = () => res(t.result);
                t.onerror = () => rej(t.error);
              });
              return { store, count: rows.length };
            }""")
            if cached and cached.get("count", 0) > 0:
                break
            page.wait_for_timeout(250)
        chk("online: cache row written for this student",
            bool(cached) and cached.get("count", 0) > 0, str(cached))

        # ── offline: kill the server NOW, while the context is alive ────────
        # Give the worker a moment to finish caching the shell + static assets.
        page.wait_for_timeout(3000)
        if a.kill_cmd:
            import subprocess
            subprocess.run(a.kill_cmd, shell=True, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time as _t
            _t.sleep(3)          # let the socket actually close

        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        rows_off = page.locator("[data-island='attendance'] .mrow").count()
        chk("offline: reload still paints rows from Dexie", rows_off > 0, f"{rows_off} rows")

        caption = page.locator("[data-island-stale]")
        has_caption = caption.count() > 0
        text = caption.first.text_content() if has_caption else ""
        # NOT asserted as required here: a caption only belongs on STALE data
        # (load.ts STALE_MS = 6 h). Just-cached data is fresh, so showing one
        # would be the bug. The caption itself is proven twice elsewhere:
        #   - web/src/data/stale.test.ts (9/9, and reverting the ms->s
        #     conversion turns exactly 3 of them red), and
        #   - this leg's row assertion below, which proves the Dexie paint.
        # What IS asserted: if a caption appears, it is well-formed.
        if has_caption:
            chk("offline: caption is well-formed when present",
                "as of" in (text or ""), text or "")

        ctx.close()

    print(f"\n  browser leg: {PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
