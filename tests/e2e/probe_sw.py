"""Probe: why does /static/sw.js fail to install?

Captures the console, page errors and service-worker events that offline_paint.py
does not, so a SW failure has a cause instead of just a red line.
"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18183"

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    page = ctx.new_page()

    page.on("console", lambda m: print(f"  console.{m.type}: {m.text[:200]}"))
    page.on("pageerror", lambda e: print(f"  pageerror: {str(e)[:200]}"))
    page.on("requestfailed", lambda r: print(f"  requestfailed: {r.url[:120]} {r.failure}"))

    page.goto(BASE + "/login", wait_until="domcontentloaded")
    time.sleep(2)

    # Ask the browser directly what it thinks of the registration.
    info = page.evaluate("""async () => {
        const out = {have: !!navigator.serviceWorker, regs: []};
        try {
            const regs = await navigator.serviceWorker.getRegistrations();
            out.regs = regs.map(r => ({
                scope: r.scope,
                active: r.active && r.active.state,
                waiting: r.waiting && r.waiting.state,
                installing: r.installing && r.installing.state,
                script: r.active && r.active.scriptURL,
            }));
        } catch (e) { out.err = String(e); }
        out.controller = navigator.serviceWorker.controller && navigator.serviceWorker.controller.scriptURL;
        return out;
    }""")
    print(f"  registrations: {info}")

    # Fetch the worker the same way the browser would, and report its status.
    probe = page.evaluate("""async () => {
        const r = await fetch('/static/sw.js', {cache: 'no-store'});
        const t = await r.text();
        return {status: r.status, ctype: r.headers.get('content-type'), len: t.length,
                head: t.slice(0, 90)};
    }""")
    print(f"  fetch sw.js: status={probe['status']} type={probe['ctype']} len={probe['len']}")
    print(f"  head: {probe['head']!r}")

    # Does the page even try to register it? The registration lives in the
    # legacy dash.js / a module; report whether any script ran it.
    tries = page.evaluate("""() => ({
        servicWorkerRegs: typeof navigator.serviceWorker.register,
        scripts: [...document.querySelectorAll('script[src]')].map(s => s.src).filter(s => /sw|dash|main/.test(s)),
    })""")
    print(f"  page scripts: {tries}")

    ctx.close()
    b.close()
