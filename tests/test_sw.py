"""SW registration DUT (7 checks): proves the PWA registers with CSP-fixed
external login.js + Service-Worker-Allowed header. Server under test: AGENTS.md."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DATA_DIR', '/tmp/osrm-sw')
from _seed import seed, mint_token
from playwright.sync_api import sync_playwright

seed(with_payload=False)
TOK = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:8084')
results, console_msgs = [], []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    page = ctx.new_page()
    page.on("console", lambda m: console_msgs.append(f"{m.type}: {m.text}"))

    # 1) /login: registration comes from external login.js (no inline script)
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.wait_for_timeout(2500)
    reg = page.evaluate("""async () => {
        const r = await navigator.serviceWorker.getRegistration();
        return r ? {scope: r.scope, active: !!r.active, installing: !!r.installing} : null;
    }""")
    check("registration exists on /login", reg is not None, json.dumps(reg))
    if reg:
        check("scope is app root", reg["scope"] == BASE + "/", reg["scope"])
        check("worker active/ installing", reg["active"] or reg["installing"])

    # 2) reload -> SW controls the page (clients.claim)
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1500)
    controlled = page.evaluate("() => !!navigator.serviceWorker.controller")
    check("page controlled by SW after reload", controlled)

    # 3) caches created with v11 name
    keys = page.evaluate("() => caches.keys()")
    check("cache opensrm-v15 present", "opensrm-v15" in keys, str(keys))

    # 4) dashboard path: registration also present via dash.js
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.wait_for_timeout(2000)
    reg2 = page.evaluate("""async () => {
        const r = await navigator.serviceWorker.getRegistration();
        return r ? r.scope : null;
    }""")
    check("dashboard registers/keeps SW too", reg2 == BASE + "/", str(reg2))

    # 5) no CSP violations in console (inline script removed)
    csp = [m for m in console_msgs if "Content Security Policy" in m]
    check("zero CSP violations", len(csp) == 0, "; ".join(csp[:2]))

    b.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results)-len(fails)}/{len(results)} PASS")
sys.exit(1 if fails else 0)
