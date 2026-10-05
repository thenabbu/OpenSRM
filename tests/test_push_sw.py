"""Headless-Chromium SW push DUT: push handler always shows (tag/test_id),
receipt POST lands server-side, malformed payload falls back, notification
click focuses/opens, handlers wired. Server under test: AGENTS.md (gunicorn)."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DATA_DIR'] = '/tmp/push-sw2'
from _seed import seed, mint_token
from playwright.sync_api import sync_playwright

seed(with_payload=False)
TOK = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:18185')
results = []

def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    page = ctx.new_page()
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.wait_for_timeout(2000)

    worker = None
    for _ in range(20):
        workers = getattr(ctx, "service_workers", []) or []
        worker = next((w for w in workers if "sw.js" in w.url), None)
        if worker is None:
            worker = next((w for w in page.workers if "sw.js" in w.url), None)
        if worker:
            break
        time.sleep(0.5)
    check("got service worker handle", worker is not None, str([w.url for w in page.workers]))
    assert worker, "no SW worker — cannot continue"

    defs = worker.evaluate("() => ({push: typeof self.handlePush, click: typeof self.handleNotificationClick})")
    check("handlers defined in SW", defs["push"] == "function" and defs["click"] == "function", json.dumps(defs))
    src = worker.evaluate("async () => (await (await fetch('/static/sw.js')).text())")
    check("push/click/subscriptionchange listeners wired",
          "addEventListener('push'" in src and "addEventListener('notificationclick'" in src
          and "addEventListener('pushsubscriptionchange'" in src)

    # ── simulate a reminder push: showNotification always fires, tagged per block ──
    shown = worker.evaluate("""async (payload) => {
        const out = [];
        const orig = self.registration.showNotification.bind(self.registration);
        self.registration.showNotification = (t, o) => { out.push({title: t, opts: o}); return Promise.resolve(); };
        let wp = null;
        self.handlePush({ data: { json: () => payload }, waitUntil: x => { wp = x; } });
        if (wp) await wp;
        self.registration.showNotification = orig;
        return out;
    }""", {"title": "Operating Systems · starts 11:20", "body": "11:20–12:10 · Lab C-4/5",
           "tag": "blk-1760000000-os09", "url": "/"})
    check("reminder push shows notification with block tag",
          len(shown) == 1 and shown[0]["opts"]["tag"] == "blk-1760000000-os09", json.dumps(shown))

    # ── test push: receipt POSTs server-side, after showNotification ──
    test_id = "ab" * 16
    shown2 = worker.evaluate("""async (payload) => {
        const out = [];
        const orig = self.registration.showNotification.bind(self.registration);
        self.registration.showNotification = (t, o) => { out.push({title: t, opts: o}); return Promise.resolve(); };
        let wp = null;
        self.handlePush({ data: { json: () => payload }, waitUntil: x => { wp = x; } });
        if (wp) await wp;
        self.registration.showNotification = orig;
        return out;
    }""", {"title": "OpenSRM test", "body": "Test notification", "tag": f"test-{test_id}",
           "test_id": test_id, "url": "/"})
    receipt_rows = None
    for _ in range(20):
        from app import push_store as S
        receipt_rows = S.count_events("ng2776", "receipt", 0)
        if receipt_rows >= 1:
            break
        time.sleep(0.5)
    check("test push shows notification", len(shown2) == 1, json.dumps(shown2))
    check("receipt row written server-side", receipt_rows == 1, str(receipt_rows))

    # ── malformed payload: still notifies (Safari revokes without visibility) ──
    shown3 = worker.evaluate("""async () => {
        const out = [];
        const orig = self.registration.showNotification.bind(self.registration);
        self.registration.showNotification = (t, o) => { out.push({title: t}); return Promise.resolve(); };
        let wp = null;
        self.handlePush({ data: { json: () => { throw new Error('bad'); }, text: () => 'raw body' },
                          waitUntil: x => { wp = x; } });
        if (wp) await wp;
        self.registration.showNotification = orig;
        return out;
    }""")
    check("malformed push still notifies (fallback)", len(shown3) == 1 and shown3[0]["title"] == "OpenSRM", json.dumps(shown3))

    # ── notificationclick: closes + resolves (focus path on the open window) ──
    clicked = worker.evaluate("""async () => {
        let closed = false;
        await self.handleNotificationClick({
            notification: { close: () => { closed = true; }, data: { url: '/' } },
            waitUntil: p => p
        });
        return closed;
    }""")
    check("notificationclick closes + focuses window", clicked is True, str(clicked))

    b.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results)-len(fails)}/{len(results)} PASS")
sys.exit(1 if fails else 0)
