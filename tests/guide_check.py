"""Login Flow UX Guide — checklist DUT (DOM/browser half).

Verdicts: PASS / FAIL / SKIP (deliberate, documented) / N/A (doesn't apply).
/api/login* is mocked (delayed 401) so NOTHING reaches the real SRM portal.
Server half: guide_server.py. Exit 1 if any FAIL.
"""
import json, os, sys, time
from playwright.sync_api import sync_playwright

BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:8084")
GENERIC = "invalid credentials — check your NetID/password"   # mocked server body
rows = []

def mark(item, verdict, ev=""):
    rows.append((item, verdict, ev))
    print(f"[{verdict:4}] {item}" + (f"  — {ev}" if ev else ""))

def ck(item, cond, ev=""):
    mark(item, "PASS" if cond else "FAIL", ev)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    # instrument BEFORE any page script: count conditional-UI passkey calls
    ctx.add_init_script("""
      window.__condCalls = 0;
      if (navigator.credentials && navigator.credentials.get) {
        const orig = navigator.credentials.get.bind(navigator.credentials);
        navigator.credentials.get = function (o) {
          if (o && o.mediation === 'conditional') window.__condCalls++;
          return orig(o);
        };
      }
    """)
    page = ctx.new_page()
    posts = []          # real /api/login POSTs only (preflight is a different path)
    seen = []           # every mocked request, for the timeline below
    def mock(route):
        url = route.request.url
        seen.append((round(time.time() * 1000) % 100000, url.rsplit("/", 1)[-1]))
        if url.rstrip("/").endswith("/api/login") and route.request.method == "POST":
            posts.append(url)
        time.sleep(0.6)                       # window to observe loading state
        route.fulfill(status=401, content_type="application/json",
                      body=json.dumps({"ok": False, "error": GENERIC}))
    page.route("**/api/login**", mock)
    page.route("**/api/login*", mock)
    page.goto(BASE + "/login", wait_until="networkidle")
    page.wait_for_timeout(300)

    ev = lambda s: page.evaluate(s)
    # record every disabled/label change so the loading state is proven from a
    # timeline, not from one racy 120ms sample
    page.evaluate("""()=>{window.__btn=[];
      const b=document.getElementById('b');
      new MutationObserver(()=>window.__btn.push(
          [Date.now(), b.disabled, document.getElementById('btnLabel').textContent])
        ).observe(b, {attributes:true, attributeFilter:['disabled']});}""")
    # ── §1 identifier field ────────────────────────────────────────────────
    ck("§1 identifier type=text (not email)", ev("()=>document.getElementById('netid').type") == "text",
       f"type={ev('()=>document.getElementById(\"netid\").type')}")
    a = ev("()=>document.getElementById('netid').getAttribute('autocomplete')")
    ck('§1 autocomplete="username webauthn"', a == "username webauthn", repr(a))
    ck("§1 inputmode=email", ev("()=>document.getElementById('netid').inputMode") == "email")
    ck("§1 autocapitalize=off", ev("()=>document.getElementById('netid').getAttribute('autocapitalize')") == "off")
    ck("§1 autocorrect=off", ev("()=>document.getElementById('netid').getAttribute('autocorrect')") == "off")
    ck("§1 spellcheck=false", ev("()=>document.getElementById('netid').spellcheck") is False)
    ck("§1 required", ev("()=>document.getElementById('netid').required"))
    lbl = ev("""()=>{const l=document.querySelector('label[for=netid]');
                     return (l?l.textContent:'').trim().replace(/\\s+/g,' ')}""")
    ck("§1 label states the dual purpose up front", "NetID" in lbl and ("Email" in lbl or "email" in lbl), repr(lbl))

    # ── §2 password field ──────────────────────────────────────────────────
    ck("§2 password type=password", ev("()=>document.getElementById('pw').type") == "password")
    a2 = ev("()=>document.getElementById('pw').getAttribute('autocomplete')")
    ck('§2 autocomplete="current-password"', a2 == "current-password", repr(a2))
    ck("§2 toggle exists with aria-label",
       ev("""()=>{const t=document.getElementById('pw-toggle');
                  return !!t && t.tagName==='BUTTON' && (t.getAttribute('aria-label')||'').length>0}"""))
    # paste must never be blocked (guide §2)
    prevented = ev("""()=>{const e=new Event('paste',{bubbles:true,cancelable:true});
                           document.getElementById('pw').dispatchEvent(e);
                           return e.defaultPrevented}""")
    ck("§2 paste is never blocked", prevented is False, f"defaultPrevented={prevented}")
    page.focus("#pw")
    ck("§2 no readonly-on-focus trick (kills manager fill)",
       ev("()=>document.activeElement.readOnly") is False)
    # caps lock warning (guide §2)
    btn_before = ev("()=>document.getElementById('b').getBoundingClientRect().top")
    page.evaluate("""()=>{const e=new KeyboardEvent('keydown',{key:'CapsLock',bubbles:true});
                          Object.defineProperty(e,'getModifierState',{value:()=>true});
                          document.getElementById('pw').dispatchEvent(e)}""")
    page.wait_for_timeout(150)
    caps = ev("()=>document.getElementById('caps').textContent").strip()
    btn_after = ev("()=>document.getElementById('b').getBoundingClientRect().top")
    ck("§2 Caps Lock warning shows", caps == "Caps Lock is on", repr(caps))
    ck("§2 Caps warning causes zero layout shift", btn_before == btn_after, f"{btn_before}->{btn_after}")
    page.evaluate("""()=>{const e=new KeyboardEvent('keyup',{key:'CapsLock',bubbles:true});
                          Object.defineProperty(e,'getModifierState',{value:()=>false});
                          document.getElementById('pw').dispatchEvent(e)}""")

    # ── §3 form structure ──────────────────────────────────────────────────
    ck("§3 real <form> element", ev("()=>document.querySelectorAll('form').length") == 1)
    ck("§3 submit is type=submit", ev("""()=>{const b=document.getElementById('b');
        return b.type==='submit' && b.form!==null}"""))
    # Enter submits from the identifier field
    page.fill("#netid", "probe1"); page.fill("#pw", "x")
    page.focus("#netid"); page.keyboard.press("Enter")
    page.wait_for_timeout(120)
    page.wait_for_timeout(900)
    ck("§3 Enter submits from the identifier field", len(posts) == 1, f"login POSTs={len(posts)} seen={seen}")
    tl = ev("()=>window.__btn")
    was_disabled = any(x[1] for x in tl)
    was_loading = any("Signing in" in (x[2] or "") for x in tl)
    ck("§3 button disabled + loading state immediately", was_disabled and was_loading,
       f"timeline={tl}")
    ck("§3 button restored after response", ev("()=>document.getElementById('b').disabled") is False)
    # Enter submits from the password field (refill: the failed submit cleared it,
    # and required on an empty field legitimately blocks implicit submission)
    page.fill("#pw", "x")
    page.focus("#pw"); page.keyboard.press("Enter")
    page.wait_for_timeout(1000)
    ck("§3 Enter submits from the password field", len(posts) == 2, f"login POSTs={len(posts)} seen={seen}")
    # §5/§6 client side: one generic error, rendered once, in an aria-live region
    err = ev("()=>document.getElementById('status').textContent").strip()
    ck("§5 generic error rendered verbatim from server", err == GENERIC, repr(err))
    ck("§6 errors live in an aria-live region",
       ev("""()=>{const s=document.getElementById('status');
                  return s.getAttribute('aria-live')==='polite' && s.getAttribute('role')==='alert'}"""))
    ck("§3 on error: identifier kept, password cleared",
       ev("()=>document.getElementById('netid').value") == "probe1"
       and ev("()=>document.getElementById('pw').value") == "",
       f"netid={ev('()=>document.getElementById(\"netid\").value')!r}, pw={ev('()=>document.getElementById(\"pw\").value')!r}")

    # ── §4 passkeys (deliberate skip — see reason) ─────────────────────────
    page.wait_for_timeout(300)
    calls = ev("()=>window.__condCalls")
    ck("§4 autocomplete token for conditional UI is present",
       ev("()=>document.getElementById('netid').getAttribute('autocomplete')").find("webauthn") >= 0)
    mark("§4 conditional-UI passkey call on page load", "SKIP",
         f"{calls} navigator.credentials.get({{mediation:'conditional'}}) calls — needs a server-side "
         f"WebAuthn challenge/registration flow; this app delegates auth to the SRM portal (no passkey support)")

    # ── §5 password reset ──────────────────────────────────────────────────
    has_reset_ui = ev("""()=>/reset|forgot/i.test(document.body.innerText)""")
    mark("§5 generic 'if that account exists' reset message", "N/A",
         f"no reset/forgot route or UI exists in this app ({has_reset_ui=}); SRM portal owns passwords")

    # ── §6 accessibility ───────────────────────────────────────────────────
    for f in ("netid", "pw"):
        ck(f"§6 real <label for={f}> (not placeholder-as-label)",
           ev(f"()=>!!document.querySelector('label[for={f}]')"))
    fs1 = ev("()=>parseFloat(getComputedStyle(document.getElementById('netid')).fontSize)")
    fs2 = ev("()=>parseFloat(getComputedStyle(document.getElementById('pw')).fontSize)")
    ck("§6 input font-size >= 16px (no mobile-Safari focus zoom)", fs1 >= 16 and fs2 >= 16, f"{fs1}/{fs2}px")
    outline = ev("""()=>{const e=document.getElementById('netid'); e.focus();
        const c=getComputedStyle(e);
        return JSON.stringify({outline: c.outlineStyle+' '+c.outlineWidth, shadow: c.boxShadow.slice(0,60)})}""")
    o = json.loads(outline)
    visible_focus = (o["outline"].split()[0] != "none") or (o["shadow"] not in ("none", ""))
    ck("§6 visible focus indicator (outline or focus ring)", visible_focus, outline)
    boxes = {}
    for sel in ("#netid", "#pw", "#b", "#pw-toggle"):
        r = ev(f"""()=>{{const b=document.querySelector('{sel}').getBoundingClientRect();
                        return [Math.round(b.width), Math.round(b.height)]}}""")
        boxes[sel] = r
    small = {k: v for k, v in boxes.items() if v[0] < 44 or v[1] < 44}
    ck("§6 touch targets >= 44x44 (inputs, button, toggle)", not small, f"{boxes}")

    b.close()

fails = [r for r in rows if r[1] == "FAIL"]
print("\n" + "=" * 72)
print(f"DOM/CHECKLIST: {len(rows)} items | PASS {sum(1 for r in rows if r[1]=='PASS')} | "
      f"FAIL {len(fails)} | SKIP {sum(1 for r in rows if r[1]=='SKIP')} | "
      f"N/A {sum(1 for r in rows if r[1]=='N/A')}")
for r in fails:
    print("  FAILED:", r[0], "->", r[2])
print("ALL PASS" if not fails else "FAILURES PRESENT")
sys.exit(1 if fails else 0)
