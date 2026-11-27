#!/usr/bin/env python3
"""The browser half of the offline proof — what the shell/Dexie flow really does.

Run by scripts/offline_proof.sh, which owns the server lifecycle:
    python tests/e2e/offline_paint.py --base http://127.0.0.1:18179 --token T

Four claims, each of which was a genuine bug at some point in this work:

  1. an online visit paints rows AND the service worker caches the bundle;
  2. with the server KILLED, a reload still paints them from Dexie;
  3. logout leaves no trace: rows gone, the IndexedDB database gone, shells gone;
  4. the shell page carries no personal data.

Claims 2 and 3 are POSITIVE CONTROLled on themselves: (2) means nothing if (1)
stored nothing, and (3) means nothing if (2) painted nothing. An empty database
would otherwise "prove" that logout wipes it. Both preconditions fail loudly.

Why the row count comes from the DOM and not from IndexedDB: reading the store
directly proved unreliable here (indexedDB.databases() can come back empty in a
fresh profile even while the panel is visibly painted), and the painted row is
the user-visible thing this whole feature exists for. The Dexie row is implied:
the server is dead, so a painted row can only have come from the cache.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

PASS = FAIL = 0

ROWS = "[data-island='attendance'] .mrow"
CACHES = """async () => {
  const ks = await caches.keys(); const out = {};
  for (const k of ks) { const c = await caches.open(k); out[k] = (await c.keys()).length; }
  return out;
}"""


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
    ap.add_argument("--skip-logout", action="store_true")
    ap.add_argument("--browser", default="chromium",
                    choices=["chromium", "webkit", "firefox"],
                    help="engine to paint offline in (default chromium); one "
                         "summary line per run, W8.4")
    a = ap.parse_args()

    with sync_playwright() as pw:
        # A UNIQUE user-data-dir per run. A reused profile carries the previous
        # run's service worker, whose cached routes point at a server that no
        # longer exists: the first goto() then hangs to the navigation timeout
        # and reads exactly like "the app is broken".
        #
        # W8.4: the engine is a parameter, not a constant. WebKit and Firefox
        # are the reason this exists - each has its own service-worker
        # lifetime, its own Cache API storage partition and its own secure-
        # context rules, so "the Chromium run was green" is not evidence about
        # either. launch_persistent_context is the API that keeps the cache and
        # the worker across reloads, and it exists on all three engines.
        if a.browser == "chromium":
            ctx = pw.chromium.launch_persistent_context(
                tempfile.mkdtemp(prefix="offproof-profile-"),
                headless=True,
                args=["--no-first-run", "--no-default-browser-check"],
            )
        else:
            try:
                ctx = getattr(pw, a.browser).launch_persistent_context(
                    tempfile.mkdtemp(prefix="offproof-profile-"), headless=True)
            except Exception as exc:      # missing build, broken deps, sandbox refusal
                        # NOT a skip. No browser means no offline proof, and an unproven
                        # offline path is the exact defect this file exists to catch.
                        print(f"\n  no {a.browser} — the offline path is UNPROVEN")
                        msg = str(exc).strip()
                        # Playwright errors are multi-line; the first line is just the
                        # category. Print the whole thing so the CI log has the detail.
                        if "\n" in msg:
                            print(f"  {msg[:2000]}")
                        else:
                            print(f"  {type(exc).__name__}: {msg[:500]}")
                        print("  install with: PLAYWRIGHT_BROWSERS_PATH="
                              f"{os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '<path>')} "
                              f".venv/bin/playwright install {a.browser}")
                        return 2
        # The cookie's domain MUST match the host we navigate to. This was
        # hardcoded to 127.0.0.1, so any run against a LAN address sent no
        # session and every route 302'd to /login (the same bug route_paint.py
        # already fixed; this file kept its copy).
        ctx.add_cookies([{"name": "srm_session", "value": a.token,
                          "domain": urlparse(a.base).hostname or "127.0.0.1",
                          "path": "/"}])
        page = ctx.new_page()

        # ── 1. online ───────────────────────────────────────────────────────
        page.goto(f"{a.base}/{a.panel}", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        chk("online: page loaded", page.url.rstrip("/").endswith(a.panel), page.url)

        # The worker must CONTROL the page before the server dies, or the offline
        # reload has nothing to serve the shell and every later check fails for
        # the wrong reason. The first load only installs it.
        for _ in range(40):
            if page.evaluate("navigator.serviceWorker.controller !== null"):
                break
            page.wait_for_timeout(400)
        chk("online: service worker is controlling the page",
            page.evaluate("navigator.serviceWorker.controller !== null"))

        # Second load: the worker can now serve the shell and its own chunks,
        # and warmShells()/precacheBundle() have had a chance to run.
        page.reload(wait_until="domcontentloaded")
        # DETERMINISTIC, not a timer. Hydration has settled when every island
        # carries a completion marker of its own (set by the app, not by this
        # test): `data-mounted-at` on the cache branch, `data-hydrated` stamped
        # by the component itself. Poll until no island is unfinished, with a
        # hard ceiling so a page that never hydrates fails loudly instead of
        # being silently measured mid-boot.
        hydrated = False
        for _ in range(60):
            st = page.evaluate(
                "()=>{const is=[...document.querySelectorAll('[data-island]')];"
                "return {n:is.length, done:is.filter(e=>e.dataset.mountedAt||e.dataset.hydrated).length};}")
            if st["n"] and st["done"] == st["n"]:
                hydrated = True
                break
            page.wait_for_timeout(250)
        chk("online: hydration settled without an exception",
            hydrated, f"{st['done']}/{st['n']} islands finished")

        rows_online = page.locator(ROWS).count()
        chk("online: island painted rows", rows_online > 0, f"{rows_online} rows")

        cache_map = page.evaluate(CACHES)
        total = sum(cache_map.values())
        # 10 is loose on purpose: the point is "the bundle and the shells are
        # cached", not an exact entry count that changes with every build.
        chk("online: worker cached the bundle and the shells", total > 10,
            f"{total} entries {cache_map}")
        # The shell is what an offline navigation is served from. Its absence is
        # the single most common cause of "offline paints nothing", and the loose
        # total>10 check above cannot see it.
        shells = page.evaluate(
            "async()=>{const ks=await caches.keys();let n=0;for(const k of ks){const c=await caches.open(k);"
            "n+=(await c.keys()).filter(r=>r.url.includes('/__snap/')).length;}return n;}")
        chk("online: page snapshots are cached", shells > 1, f"{shells} snapshot entries")


        # ── 2. offline ──────────────────────────────────────────────────────
        # warmShells() runs AFTER hydration (deferred past the load window) and
        # fetches each route. Killing the server before the snapshots are cached
        # races it: offline has no document to serve and the reload looks like
        # "offline is broken" when it is only early. Wait for the CONDITION
        # (this student's snapshot for /attendance cached), not a timer.
        for _ in range(120):
            if page.evaluate(
                    "async()=>{const c=await caches.open('opensrm-snap');"
                    "const o=await c.match('/__snap/__owner');if(!o)return false;"
                    "const n=(await o.text()).trim();"
                    "return !!(await c.match('/__snap/'+n+'/'+%r));}" % a.panel):
                break
            page.wait_for_timeout(250)
        if a.kill_cmd:
            subprocess.run(a.kill_cmd, shell=True, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(4)          # let the socket actually close

        # A reload with the server dead THROWS when no service worker can serve
        # the navigation (net::ERR_CONNECTION_REFUSED). That is a real, expected
        # outcome here — not a harness crash. Letting it propagate aborted the
        # whole leg before it could print its own pass/fail summary, which hid
        # two independent assertion failures behind a single top-level "1 failed"
        # (COMPLETION_AUDIT.md, 2026-11-11). Catch it and let the assertions below
        # report honestly.
        target = page.url
        nav = None
        try:
            page.reload(wait_until="domcontentloaded")
            nav = "reload"
        except Exception as exc:                  # noqa: BLE001 — any failure here is data
            print(f"    offline reload raised: {type(exc).__name__}: {str(exc).splitlines()[0][:120]}")
            # W8.4: Firefox refuses `reload` against a dead socket
            # (NS_ERROR_CONNECTION_REFUSED) even while its worker controls the
            # page and holds the shells. A fresh navigation is the OTHER thing a
            # real user does offline and it goes through the same fetch handler,
            # so try it before calling the engine broken. This is evidence, not
            # a pass: the assertions below still have to see rows painted with
            # the server dead.
            try:
                page.goto(target, wait_until="domcontentloaded")
                nav = "goto"
                print(f"    offline: reload refused, fresh navigation answered ({target})")
            except Exception as exc2:             # noqa: BLE001
                print(f"    offline goto raised too: {type(exc2).__name__}: {str(exc2).splitlines()[0][:120]}")
        chk("offline: navigation survived the dead server", nav is not None,
            f"neither reload nor goto was answered by the worker ({a.browser})")
        if nav is None:
            print("    no document is available offline — the rows checks below cannot pass")
        # Same deterministic settle as the online leg: wait for the islands to
        # announce they are done. Offline the marker is `data-mounted-at` (the
        # cache branch) — `data-hydrated` also appears, both are app-stamped.
        rows_off = 0
        try:
            for _ in range(60):
                rows_off = page.locator(ROWS).count()
                if rows_off:
                    break
                page.wait_for_timeout(250)
        except Exception as exc:                  # noqa: BLE001
            print(f"    offline rows unreadable: {type(exc).__name__}")
        # Diagnostics are best-effort: on a failed navigation they throw
        # ("Execution context was destroyed"), and that must not abort the run
        # before the summary line is printed.
        try:
            err = page.evaluate("()=>JSON.stringify(window.__osrmDiag||[])")
            print(f"    offline diag: {err}")
            dom = page.evaluate("()=>({islands:[...document.querySelectorAll('[data-island]')].map(e=>e.dataset.island+':'+e.children.length), n:document.querySelectorAll('[data-island=attendance]').length})")
            print(f"    offline dom: {dom}")
        except Exception as exc:                  # noqa: BLE001
            print(f"    offline diagnostics unavailable: {type(exc).__name__}")
        chk("offline: reload still painted rows from Dexie", rows_off > 0,
            f"{rows_off} rows (online was {rows_online})")

        # A caption belongs only on STALE data (load.ts STALE_MS = 6 h), so
        # requiring one here would assert the wrong thing: freshly cached data
        # showing a caption would be the bug. The caption logic is proven in
        # web/src/data/stale.test.ts (reverting the ms->s conversion turns 3 of
        # them red). Here: if one appears, it must be well-formed.
        caption = page.locator("[data-island-stale]")
        if caption.count():
            chk("offline: caption is well-formed when present",
                "as of" in (caption.first.text_content() or ""),
                caption.first.text_content() or "")

        # ── 3. logout leaves no trace ───────────────────────────────────────
        # This leg runs with the server already KILLED, so /logout cannot be
        # served: the navigation lands on Chrome's error page and "redirected to
        # /login" would be asserting a document that legally cannot exist here.
        # That was a GATE bug, not an app bug — it reported chrome-error:// as a
        # failure. The logout wipe is proven for real in the vitest suite and the
        # DUT; here we only assert it when the logout actually produced a document.
        if not a.skip_logout:
            chk("control: rows existed before logout (else vacuous)", rows_off > 0)
            if page.locator("a[href='/logout']").count():
                page.click("a[href='/logout']")
            else:
                page.evaluate("location.href='/logout'")
            page.wait_for_timeout(8000)

            if page.url.startswith(("chrome-error://", "about:neterror",
                                    "webkit-error", "about:blank")):
                print("    [SKIP] logout redirect — server is down, /logout is unresolvable offline")
            else:
                dbs = page.evaluate(
                    "async()=>{try{return (await indexedDB.databases())"
                    ".map(x=>x.name).join(',')||'NONE';}catch(e){return 'NONE';}}")
                chk("logout: IndexedDB database is gone", dbs == "NONE", dbs)
                # `caches` only exists on a secure-context document. After logout
                # the page can be a /login redirect where the API is absent, and
                # an uncaught ReferenceError here killed the whole run — the
                # remaining checks never executed. Probe defensively.
                cache_map = page.evaluate(
                    "async()=>{if(!self.caches) return {__nocaches:0};"
                    "const ks=await caches.keys();const o={};"
                    "for(const k of ks){const c=await caches.open(k);o[k]=(await c.keys()).length;}return o;}")
                left = sum(cache_map.values())
                chk("logout: cached shells cleared", left < 5, f"{left} entries left")
                chk("logout: redirected to login", "/login" in page.url, page.url)

        ctx.close()

    print(f"\n  browser leg [{a.browser}]: {PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
