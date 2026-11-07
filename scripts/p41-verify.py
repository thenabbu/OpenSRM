#!/usr/bin/env python3
"""P4.1 browser check: the sync-age island hydrates under the REAL CSP.

Boots the worktree's app (gunicorn, production CSP from app/app.py) on a full
seed + injected scope, then for GET /:
  * zero CSP violations, zero console errors, zero page errors
  * no executable inline <script>
  * server HTML already correct with JS disabled (progressive enhancement)
  * after hydration: data-hydrated marker, identical caption, identical box
  * the island's own 60s tick re-ages the caption (no reload, no fetch)
Exit 0 = every check passes.
"""
import importlib.util
import os
import subprocess
import sys
import time
import urllib.request

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/data/cache/scratch/pw-browsers"
DATA = "/tmp/osrm-p41-verify"
WT = os.environ.get("WT", "/opt/data/cache/scratch/preact-p4/wt")
PY = "/opt/data/opensrm-repo/.venv/bin/python"
PORT = 18211

subprocess.run(["rm", "-rf", DATA], check=False)
os.makedirs(DATA, exist_ok=True)
sys.path.insert(0, WT)
os.environ["DATA_DIR"] = DATA
os.environ["SCOPE_FEATURES"] = "all"

from tests._seed import seed_rich, mint_token          # noqa: E402
seed_rich()
tok = mint_token()
spec = importlib.util.spec_from_file_location(
    "cap", "/opt/data/missions/opensrm-preact/scripts/capture.py")
cap = importlib.util.module_from_spec(spec)
sys.modules["cap"] = cap
spec.loader.exec_module(cap)
cap.inject_scope(DATA)

# the seed's last_fetch is "now", which is legitimately "" (fresh = no caption);
# backdate it so the server MUST paint an age
from app.db import db as _db                            # noqa: E402
with _db() as c:
    c.execute("UPDATE users SET last_fetch = last_fetch - 5400 WHERE netid = 'zz9999'")

env = dict(os.environ, DATA_DIR=DATA, LOG_LEVEL="ERROR", SCOPE_FEATURES="all")
srv = subprocess.Popen(
    [PY, "-m", "gunicorn", "-w", "1", "--threads", "4",
     "-b", f"127.0.0.1:{PORT}", "app.app:app"],
    cwd=WT, env=env, stdout=open("/tmp/osrm-p41-srv.log", "w"), stderr=subprocess.STDOUT)
base = f"http://127.0.0.1:{PORT}"
fails = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


try:
    for _ in range(120):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    from playwright.sync_api import sync_playwright  # noqa: E402

    with sync_playwright() as p:
        b = p.chromium.launch()

        # ── 1. JS disabled: server markup must already be right ─────────
        nojs = b.new_context(java_script_enabled=False, viewport={"width": 1440, "height": 900})
        nojs.add_cookies([{"name": "srm_session", "value": tok, "url": base}])
        pg0 = nojs.new_page()
        r0 = pg0.goto(base + "/", wait_until="load")
        assert pg0.evaluate("() => !!document.querySelector('.navbar.hidden .sync-line')"), \
            f"no sync-line at {pg0.url} (status {r0.status if r0 else '?'}); " \
            f"log: {open('/tmp/osrm-p41-srv.log').read()[-1200:]}"
        ssr = pg0.evaluate("""() => {
            const el = document.querySelector('.navbar.hidden .sync-line');
            const cs = getComputedStyle(el), r = el.getBoundingClientRect();
            const block = document.getElementById((el.getAttribute('data-props') || '').slice(1));
            return {text: el.textContent, island: el.getAttribute('data-island'),
                    props: block && block.textContent,
                    blockType: block && block.type,
                    hydrated: el.hasAttribute('data-hydrated'),
                    title: el.title, box: [r.x, r.y, r.width, r.height],
                    display: cs.display, color: cs.color, size: cs.fontSize}; }""")
        check("no-JS: caption is server-rendered (correct text on first paint)",
              ssr["text"] not in (None, ""), repr(ssr["text"]))
        check("no-JS: mount point + inert application/json props block",
              ssr["island"] == "sync-age" and ssr["blockType"] == "application/json"
              and '"ts"' in (ssr["props"] or ""), f'{ssr["props"]} (type={ssr["blockType"]})')
        check("no-JS: not hydrated (the marker is JS-only)", ssr["hydrated"] is False)
        nojs.close()

        # ── 2. JS on, real CSP: violations + hydration ──────────────────
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
        ctx.add_cookies([{"name": "srm_session", "value": tok, "url": base}])
        page = ctx.new_page()
        console, violations = [], []
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: violations.append(f"pageerror: {e}"))
        page.on("console", lambda m: "Content Security Policy" in m.text
                and violations.append(f"CSP: {m.text}"))

        # layout the server HTML alone produces: same cookie, island module blocked
        probe_ctx = b.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
        probe_ctx.add_cookies([{"name": "srm_session", "value": tok, "url": base}])
        probe = probe_ctx.new_page()
        blocked = []

        def _abort(route):
            blocked.append(route.request.url)
            route.abort()

        probe.route("**/assets/*.js", _abort)
        probe.goto(base + "/", wait_until="load")
        box_blocked = probe.evaluate("""() => {
            const el = document.querySelector('.navbar.hidden .sync-line');
            const r = el.getBoundingClientRect();
            return [r.x, r.y, r.width, r.height, el.hasAttribute('data-hydrated')]; }""")
        probe_ctx.close()
        check("island JS blocked: page still renders (progressive enhancement)",
              bool(blocked) and box_blocked[4] is False,
              f"blocked {len(blocked)} module request(s)")

        page.goto(base + "/", wait_until="networkidle")
        page.wait_for_function(
            "document.querySelector('.navbar.hidden .sync-line').hasAttribute('data-hydrated')",
            timeout=10000)
        # the hydrated island's immediately-post-mount paint (dash.js may still
        # be morphing the bar afterwards — that is legacy behaviour, not P4.1)
        after = page.evaluate("""() => {
            const el = document.querySelector('.navbar.hidden .sync-line');
            const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
            return {marker: el.getAttribute('data-hydrated'), text: el.textContent,
                    title: el.title, box: [r.x, r.y, r.width, r.height], cls: el.className,
                    display: cs.display, color: cs.color, size: cs.fontSize}; }""")

        check("hydration: data-hydrated set by the mounted island", after["marker"] == "1")
        check("hydration: caption identical to the server's (no text shift)",
              after["text"] == ssr["text"], f"{ssr['text']!r} -> {after['text']!r}")
        check("hydration: same box as the un-hydrated server HTML (no layout shift)",
              after["box"] == box_blocked[:4], f"{box_blocked[:4]} -> {after['box']}")
        check("hydration: same computed colour/size (the island did not restyle it)",
              (after["color"], after["size"]) == (ssr["color"], ssr["size"]),
              f"{ssr['color']}/{ssr['size']} vs {after['color']}/{after['size']}")
        check("hydration: server classes preserved", "sync-line" in after["cls"], after["cls"])

        inline = page.evaluate("""() => Array.from(document.querySelectorAll('script'))
            .filter(s => !s.src && s.type !== 'application/json').map(s => s.type + '/' + s.textContent.slice(0, 40))""")
        check("CSP-safe: no executable inline <script> on the page", inline == [],
              f"{len(inline)} inline: {inline[:3]}")

        # Errors as the page LOADED (an empty filter means zero errors).
        # The seeded account has no stored portal password, so its background
        # auto-refresh answers 401 by design (dash.js handles it: "background
        # sync failed"); that one known console line is the fixture's, not ours.
        load_errors = [c for c in console if c.startswith("error")
                       and "401 (UNAUTHORIZED)" not in c]
        check("CSP: zero violations under script-src 'self'", not violations,
              "; ".join(violations[:5]))
        check("console: zero errors while loading (excluding the seed's no-creds 401)",
              not load_errors, "; ".join(load_errors[:5]))

        # ── 3. the island is alive: it re-ages the caption on its own tick ─
        # Server painted (1h ago). 31 minutes later only the hydrated island's
        # 60s interval can move it to (2h ago) — no reload, no fetch. Playwright
        # takes over Date/timeouts from here on and fast-forwards through them.
        page.clock.install()
        page.clock.pause_at(time.time() + 1)
        page.clock.run_for("00:31:00")
        aged = page.evaluate("""() => {
            const el = document.querySelector('.navbar.hidden .sync-line');
            return {text: el.textContent, marker: el.getAttribute('data-hydrated')}; }""")
        check("island alive: its own 60s tick re-aged the caption (1h -> 2h)",
              aged["marker"] == "1" and aged["text"] == "(2h ago)",
              f"{ssr['text']!r} -> {aged['text']!r}")

        ctx.close()
        b.close()
finally:
    srv.terminate()

print()
if fails:
    print(f"RESULT: FAIL — {len(fails)} check(s): {fails}")
    sys.exit(1)
print("RESULT: PASS — island hydrated under CSP 'self', zero violations")
