"""Headless-Chromium SW push DUT: behaviour, not identifiers.

A REAL push is delivered to the installed worker over CDP
(``ServiceWorker.deliverPushMessage``), so the assertions run the registered
listener — title/body/tag/url mapping, the always-show rule, the ``test_id``
receipt, and the malformed-payload fallback to ``text()``. The click path calls
the registered listener through a script-built event that carries its own
``waitUntil``.

Why it looks like this: the suite used to assert ``typeof self.handlePush``
inside the worker and grep the served source for ``addEventListener('push'``.
Both were bundler assertions, not push assertions — the built worker inlines
the handler (grep self.handlePush app/static/sw.js -> 0) and Terser emits
double quotes, so the DUT could never pass on a built bundle no matter how
healthy the push path was. Nothing below depends on a function name or a
quote style; the only source text read is listener registration for
``pushsubscriptionchange``, which needs a real subscription rotation to fire.

Server under test: AGENTS.md (gunicorn). Run via tests/e2e/run_push_duts.sh.
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['DATA_DIR'] = '/tmp/push-sw2'
from _seed import seed, mint_token, require_own_server
from playwright.sync_api import sync_playwright

seed(with_payload=False)
TOK = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:18185')
require_own_server(BASE)
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

    # Observe what the worker shows without touching how it is wired: replace
    # the notification sink and keep anything the handler throws.
    worker.evaluate("""() => {
        self.__shown = []; self.__errs = [];
        self.addEventListener('unhandledrejection', e => self.__errs.push(String(e.reason)));
        self.registration.showNotification = (t, o) => {
            o = o || {};
            self.__shown.push({title: t, body: o.body, tag: o.tag, url: (o.data || {}).url});
            return Promise.resolve();
        };
    }""")

    # Deliver pushes through Chrome's own push plumbing (same path devtools'
    # "Push" button uses) — the listener has to be wired for this to do anything.
    regs = []
    cdp = ctx.new_cdp_session(page)
    cdp.on("ServiceWorker.workerRegistrationUpdated", lambda e: regs.extend(e.get("registrations") or []))
    cdp.send("ServiceWorker.enable")
    reg_id = None
    for _ in range(50):
        hit = next((r for r in regs if (r.get("scopeURL") or "").startswith(BASE) and not r.get("isDeleted")), None)
        if hit:
            reg_id = hit["registrationId"]
            break
        page.wait_for_timeout(200)
    check("found the SW push registration", reg_id is not None, str([r.get("scopeURL") for r in regs]))

    def push(payload):
        """Deliver one push to the installed worker; return what it showed."""
        if reg_id is None:
            return []
        worker.evaluate("() => { self.__shown = []; self.__errs = []; }")
        cdp.send("ServiceWorker.deliverPushMessage", {
            "origin": BASE, "registrationId": reg_id,
            "data": payload if isinstance(payload, str) else json.dumps(payload)})
        shown = []
        for _ in range(30):
            shown = worker.evaluate("() => self.__shown")
            if shown:
                break
            time.sleep(0.2)
        time.sleep(0.2)                      # let a trailing throw land
        errs = worker.evaluate("() => self.__errs")
        if errs:
            print(f"    sw errors: {errs}")
        return shown

    # ── reminder push: one visible notification, every payload field mapped ──
    shown = push({"title": "Operating Systems · starts 11:20", "body": "11:20–12:10 · Lab C-4/5",
                  "tag": "blk-1760000000-os09", "url": "/timetable"})
    check("a real push shows exactly one notification", len(shown) == 1, json.dumps(shown))
    got = shown[0] if shown else {}
    check("push maps title + body",
          got.get("title") == "Operating Systems · starts 11:20" and got.get("body") == "11:20–12:10 · Lab C-4/5",
          json.dumps(got))
    check("push maps tag (block-scoped replace)", got.get("tag") == "blk-1760000000-os09", json.dumps(got))
    check("push maps deep-link url", got.get("url") == "/timetable", json.dumps(got))

    # ── test push: receipt POSTs server-side, after showNotification ──
    test_id = "ab" * 16
    shown2 = push({"title": "OpenSRM test", "body": "Test notification", "tag": f"test-{test_id}",
                   "test_id": test_id, "url": "/"})
    check("test push shows notification", len(shown2) == 1, json.dumps(shown2))
    from app import push_store as S
    receipt_rows = None
    for _ in range(20):
        receipt_rows = S.count_events("zz9999", "receipt", 0)
        if receipt_rows >= 1:
            break
        time.sleep(0.5)
    check("receipt row written server-side", receipt_rows == 1, str(receipt_rows))

    # ── malformed payload: still notifies (Safari revokes without visibility) ──
    shown3 = push("this is not json")
    check("malformed push still notifies via text()",
          len(shown3) == 1 and shown3[0]["title"] == "OpenSRM" and shown3[0]["body"] == "this is not json",
          json.dumps(shown3))

    # ── notificationclick: closes, then opens the notification's url ──
    clicked = worker.evaluate("""async () => {
        const seen = {closed: false, opened: null, focused: 0};
        const ev = new Event('notificationclick');        // script events need their own waitUntil
        ev.notification = {close: () => { seen.closed = true; }, data: {url: '/marks'}};
        ev.waitUntil = p => { seen.done = p; };
        const omatch = self.clients.matchAll, oopen = self.clients.openWindow;
        self.clients.matchAll = async () => [];          // no window to focus: open a fresh one
        self.clients.openWindow = async u => { seen.opened = u; return null; };
        try {
            self.dispatchEvent(ev);
            if (seen.done) await seen.done;
        } finally {
            self.clients.matchAll = omatch; self.clients.openWindow = oopen;
        }
        return seen;
    }""")
    check("notificationclick closes + opens its url",
          clicked.get("closed") is True and clicked.get("opened") == "/marks", json.dumps(clicked))

    # ── registration in the served worker, quote style irrelevant ──
    src = worker.evaluate("async () => (await (await fetch('/static/sw.js')).text())")
    wired = {ev: bool(re.search(r"addEventListener\(\s*['\"]%s['\"]" % ev, src))
             for ev in ("push", "notificationclick", "pushsubscriptionchange")}
    check("push/click/subscriptionchange listeners registered", all(wired.values()),
          json.dumps({**wired, "bytes": len(src)}))

    b.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results)-len(fails)}/{len(results)} PASS")
sys.exit(1 if fails else 0)
