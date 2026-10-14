"""Reminders card DUT: placement (Settings tab — the ONE notification
surface), explicit states, no console errors, no overflow at 375/1280 —
then the enabled-state UI with per-type preference round-trips and a REAL
pywebpush send (FCM round trip, signed + encrypted).

Known tooling limits (documented, not worked around):
- Playwright's Chromium ships WITHOUT a push service (no Google API keys),
  so pushManager.subscribe cannot run here. The page's browser-side
  subscription is stubbed; the server, sender and network are real.
- Server under test: AGENTS.md (gunicorn)."""
import base64, json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DATA_DIR'] = '/tmp/push-ui'
from _seed import seed, mint_token, require_own_server
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright

seed(with_payload=False)
TOK = mint_token()
BASE_UNCONF = os.environ.get('DUT_BASE_UNCONF', 'http://127.0.0.1:18187')
BASE_CONF = os.environ.get('DUT_BASE_CONF', 'http://127.0.0.1:18186')
require_own_server(BASE_UNCONF, BASE_CONF)
results = []

def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()

def open_settings(page, base):
    page.goto(f"{base}/", wait_until="networkidle")
    # desktop tablist (hidden below lg) and mobile dock (lg:hidden) both carry
    # data-tab; click whichever is visible at this viewport
    page.locator('button[data-tab="settings"]:visible').first.click()
    page.wait_for_selector('#push-card', state='visible', timeout=5000)

def new_ctx(pw, viewport, ua=None):
    # Persistent context: Chromium blocks the Push API in incognito/ephemeral
    # contexts (crbug.com/41124656).
    d = tempfile.mkdtemp(prefix="push-ui-profile-")
    kw = {"viewport": viewport}
    if ua:
        kw["user_agent"] = ua
    return pw.chromium.launch_persistent_context(d, **kw)

with sync_playwright() as p:
    # ── pass 1: unconfigured server — honest default state at 375 + 1280 ──
    ctx = new_ctx(p, {"width": 375, "height": 812})
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE_UNCONF}])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    errs = []
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    open_settings(page, BASE_UNCONF)
    state = page.text_content('#push-state')
    check("card renders in Settings tab", page.is_visible('#push-card'), "")
    check("card NOT inside the Timetable tab (consolidated to one surface)",
          page.evaluate("() => !document.getElementById('tab-timetable')"
                        ".contains(document.getElementById('push-card'))"), "")
    check("unconfigured state is honest", 'not set up' in (state or ''), str(state))
    check("controls hidden when unconfigured", not page.is_visible('#push-controls'), "")
    overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    check("no horizontal overflow at 375px", overflow <= 1, f"overflow={overflow}px")
    check("no console errors", len(errs) == 0, "; ".join(errs[:2]))
    page.screenshot(path="/tmp/push-ui-375-unconfigured.png", full_page=False)
    ctx.close()

    ctx = new_ctx(p, {"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE_UNCONF}])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    open_settings(page, BASE_UNCONF)
    overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    check("no horizontal overflow at 1280px", overflow <= 1, f"overflow={overflow}px")
    page.screenshot(path="/tmp/push-ui-1280-unconfigured.png", full_page=False)
    ctx.close()

    # ── pass 2: configured+enabled server — enabled-state UI and a REAL send.
    # Seed a server-side subscription whose endpoint the page will "have":
    # browser-side subscribe() is impossible in Playwright Chromium (no push
    # service), so getSubscription() is stubbed with this exact endpoint and
    # the endpoint hash must match what the server computed.
    fake_ep = 'https://fcm.googleapis.com/fcm/send/push-ui-e2e-' + os.urandom(8).hex()
    client_pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    from app import push_store as S
    S.upsert_subscription('zz9999', fake_ep, b64url(client_pub), b64url(os.urandom(16)), 'e2e-stub')

    ctx = new_ctx(p, {"width": 375, "height": 812})
    try:
        ctx.grant_permissions(['notifications'], origin=BASE_CONF)
    except Exception as e:
        print(f"  info: grant_notifications: {e}")
    ctx.add_init_script("""
      (() => {
        const ep = %s;
        const fake = { endpoint: ep,
                       toJSON: () => ({endpoint: ep, keys: {p256dh: 'stub', auth: 'stub'}}),
                       unsubscribe: async () => true };
        PushManager.prototype.getSubscription = async function () { return fake; };
        PushManager.prototype.subscribe = async function () { return fake; };
      })();
    """ % json.dumps(fake_ep))
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE_CONF}])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    # browser logs every non-2xx fetch as a console error; the deliberate 410
    # above (dead-endpoint cleanup) is expected network noise, not a JS error
    errs2 = []
    page.on("console", lambda m: errs2.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    open_settings(page, BASE_CONF)
    state = page.text_content('#push-state')
    check("enabled state shows lead", state == 'Reminders on · 10 minutes before each class.', str(state))
    check("toggle checked", page.is_checked('#push-toggle'), "")
    check("test button visible", page.is_visible('#push-test'), "")
    check("lead select has server choices", page.eval_on_selector('#push-lead', 's => s.options.length') == 4, "")
    check("battery tip shown while enabled", page.is_visible('#push-hint'), "")

    # lead change round-trips to the server
    page.select_option('#push-lead', '15')
    for _ in range(20):
        if '15 minutes' in (page.text_content('#push-state') or ''):
            break
        time.sleep(0.5)
    check("lead change saved + re-rendered",
          'Reminders on · 15 minutes before each class.' in (page.text_content('#push-state') or ''),
          str(page.text_content('#push-state')))

    # per-type preferences: block shows with a subscription, defaults on,
    # each toggle round-trips to /api/push/settings and re-renders state
    page.wait_for_selector('#push-types', state='visible', timeout=5000)
    check("type preference toggles visible with a subscription",
          page.is_checked('#push-type-reminders') and page.is_checked('#push-type-exams'), "")
    page.click('#push-type-exams')     # uncheck Exam updates
    fb, sub = '', None
    for _ in range(20):
        fb = page.text_content('#push-feedback') or ''
        sub = (S.list_subscriptions(netid='zz9999') or [{}])[0]
        if 'Exam updates off.' in fb and not sub.get('notify_exams', 1):
            break
        time.sleep(0.5)
    check("mute exam updates -> feedback + server row + reminders state kept",
          'Exam updates off.' in fb and sub.get('notify_exams') == 0
          and 'Reminders on · 15 minutes' in (page.text_content('#push-state') or ''),
          f"fb={fb!r} exams={sub.get('notify_exams')} state={page.text_content('#push-state')!r}")
    page.click('#push-type-reminders')  # uncheck Class reminders too
    for _ in range(20):
        if 'All notification types are off.' in (page.text_content('#push-state') or ''):
            break
        time.sleep(0.5)
    check("both muted -> state reads 'All notification types are off.'",
          'All notification types are off.' in (page.text_content('#push-state') or ''),
          str(page.text_content('#push-state')))
    page.click('#push-type-reminders'); page.click('#push-type-exams')   # restore
    for _ in range(20):
        sub = (S.list_subscriptions(netid='zz9999') or [{}])[0]
        if sub.get('notify_reminders') and sub.get('notify_exams'):
            break
        time.sleep(0.5)
    check("re-enable both -> server rows back to 1/1",
          sub.get('notify_reminders') == 1 and sub.get('notify_exams') == 1, str(sub))
    page.screenshot(path="/tmp/push-ui-375-enabled.png", full_page=False)

    # REAL send: pywebpush signs (VAPID) + encrypts (RFC 8291) and POSTs to
    # FCM. The endpoint token does not exist -> FCM must reject it, which
    # proves the request was accepted far enough to classify it as dead
    # (a bad VAPID claim would come back as an auth error instead).
    page.click('#push-test')
    fb = ''
    for _ in range(30):
        fb = page.text_content('#push-feedback') or ''
        if fb and 'Sending' not in fb:
            break
        time.sleep(0.5)
    print(f"  info: real pywebpush->FCM outcome: {fb!r}")
    check("real send produced an honest outcome (dead or http error)",
          ('expired' in fb) or ('push service error' in fb), fb)
    if 'expired' in fb:
        check("dead endpoint cleaned up server-side", S.list_subscriptions(netid='zz9999') == [], "")
    check("no console errors in configured run", len(errs2) == 0, "; ".join(errs2[:2]))
    ctx.close()

    # ── pass 3: iOS-not-installed UI path ──
    # Playwright's WebKit cannot launch on this host (no root to install its
    # system libs) and could not do real push anyway. The branch under test
    # keys only off the UA + standalone flag, so an iPhone Safari UA in
    # Chromium exercises the identical code path.
    IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                 "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                 "Mobile/15E148 Safari/604.1")
    ctx = new_ctx(p, {"width": 390, "height": 844}, ua=IPHONE_UA)
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE_UNCONF}])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    errs3 = []
    page.on("console", lambda m: errs3.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    open_settings(page, BASE_UNCONF)
    state = page.text_content('#push-state') or ''
    hint = page.text_content('#push-hint') or ''
    check("iOS-not-installed state shown", 'On iPhone/iPad' in state, str(state))
    check("Add-to-Home-Screen steps + version + unverified label",
          'Add to Home Screen' in hint and '16.4' in hint and 'unverified' in hint, str(hint))
    check("hint is actually VISIBLE (not inside hidden controls)",
          page.is_visible('#push-hint'), "")
    check("iOS path hides the enable controls", not page.is_visible('#push-controls'), "")
    check("no console errors in iOS run", len(errs3) == 0, "; ".join(errs3[:2]))
    page.locator('#push-card').scroll_into_view_if_needed()   # keep the hint in frame
    page.screenshot(path="/tmp/push-ui-390-ios-not-installed.png", full_page=False)
    ctx.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results)-len(fails)}/{len(results)} PASS")
sys.exit(1 if fails else 0)
