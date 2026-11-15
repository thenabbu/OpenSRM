"""W5.2b: does copy still work AFTER an island re-render?

The copy cluster moved out of dash.js into web/src/data/copy.ts. The reason it
was hard to port is the re-arm: a repaint builds FRESH nodes, so anything the
page stamped once at load is watching an element that no longer exists. A port
that stamps only at load looks perfect until the first sync, so this probe does
the one thing a unit test cannot: it REPAINTS IN A REAL BROWSER and then copies.

Where: the DASHBOARD's copy target (the registration number in the profile
widget), not the settings accordion. daisyUI's `.collapse-content` is
`content-visibility:hidden` while a group is closed, which makes the browser
refuse focus there — correct, but it would make an a11y assertion meaningless.

Asserts, on a seeded server in Chromium:
  * the bundle published the copy binding (dash.js no longer has the delegate);
  * a [data-copy] target is keyboard-operable (role/tabindex/cursor);
  * clicking it puts the VALUE on the clipboard and flashes "Copied!";
  * Enter and Space do the same, and Space does not also scroll;
  * after an island re-render (__osrmRefreshData, what a sync calls) the nodes
    are FRESH - asserted, not assumed - and still copy, by mouse and keyboard;
  * #copyEmail copies data-email and relabels its span.

Run: python tests/e2e/test_copy_rearm.py   (seeded server on DUT_BASE)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-w52b-probe")
from _seed import seed_rich, mint_token, require_own_server
from playwright.sync_api import sync_playwright

seed_rich()
BASE = os.environ["DUT_BASE"]
require_own_server(BASE)
TOK = mint_token()
res = []


def check(name, ok, detail=""):
    res.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# Clipboard reads need a permission grant; the write itself needs a secure
# context, and 127.0.0.1 counts as one in Chromium.
CLIP_ARGS = ["--enable-features=ClipboardReadText"]

# Target selection: the dashboard's registration number. It is the copy target
# users actually reach, it lives in an always-open widget, and its island is the
# one a sync repaints.
SEL = "#tab-dashboard [data-copy], #tab-home [data-copy], [data-copy]"
PICK = """() => {
  const el = [...document.querySelectorAll('[data-copy]')]
    .filter(e => e.offsetParent !== null && e.getClientRects().length)
    .find(e => /^RA\\d+$/i.test(e.dataset.copy || ''));
  return el || [...document.querySelectorAll('[data-copy]')]
    .filter(e => e.offsetParent !== null && e.getClientRects().length)[0] || null;
}"""


def clip(pg):
    return pg.evaluate("() => navigator.clipboard.readText()")


def pick_value(pg):
    """The value the picked visible target should copy (and scroll it into view)."""
    return pg.evaluate(f"""() => {{
      const el = ({PICK})();
      if (!el) return null;
      el.scrollIntoView({{block: 'center'}});
      return el.dataset.copy || el.textContent.trim();
    }}""")


def click_pick(pg):
    pg.evaluate(f"() => {{ const el = ({PICK})(); if (el) el.click(); }}")


def focus_pick(pg):
    return pg.evaluate(f"""() => {{
      const el = ({PICK})();
      if (!el) return false;
      el.focus();
      return document.activeElement === el;
    }}""")


def pick_text(pg):
    return pg.evaluate(f"() => {{ const el = ({PICK})(); return el ? el.textContent : ''; }}")


with sync_playwright() as p:
    b = p.chromium.launch(args=CLIP_ARGS)
    ctx = b.new_context(viewport={"width": 393, "height": 851},
                        permissions=["clipboard-read", "clipboard-write"])
    ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
    pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="networkidle")

    check("dashboard loaded (not /login)", pg.url.rstrip("/") == BASE.rstrip("/"), pg.url)
    check("bundle ran (islands hydrate)",
          pg.evaluate("() => typeof window.__osrmRefreshData === 'function'"))

    # ── 1. the attribute contract, on every target ────────────────────────
    targets = pg.evaluate("""() => {
      const els = [...document.querySelectorAll('[data-copy]')];
      return {
        n: els.length,
        withRole: els.filter(e => e.getAttribute('role') === 'button').length,
        withTab: els.filter(e => e.getAttribute('tabindex') === '0').length,
        withCursor: els.filter(e => e.classList.contains('cursor-copy')).length,
      };
    }""")
    check("copy targets exist on the dashboard", targets["n"] > 0, f"{targets['n']} target(s)")
    check("every one is role=button (a11y stamp, post-port)",
          targets["n"] > 0 and targets["withRole"] == targets["n"], f"{targets['withRole']}/{targets['n']}")
    check("every one is tabindex=0 (keyboard reachable)",
          targets["n"] > 0 and targets["withTab"] == targets["n"], f"{targets['withTab']}/{targets['n']}")
    check("every one carries cursor-copy",
          targets["n"] > 0 and targets["withCursor"] == targets["n"], f"{targets['withCursor']}/{targets['n']}")

    # ── 2. click copies ───────────────────────────────────────────────────
    value = pick_value(pg)
    check("picked a copy target with a value", value is not None, repr(value)[:40])
    pg.wait_for_timeout(150)
    click_pick(pg)
    pg.wait_for_timeout(250)
    check("click put the value on the clipboard", clip(pg) == value, repr(clip(pg))[:60])
    check('the target flashed "Copied!"', pick_text(pg) == "Copied!", repr(pick_text(pg))[:40])
    pg.wait_for_timeout(1300)
    check("the flash restores the original text", pick_text(pg) == value, repr(pick_text(pg))[:40])

    # ── 3. keyboard: Enter and Space ──────────────────────────────────────
    pg.evaluate("() => navigator.clipboard.writeText('sentinel')")
    check("a copy target takes focus from the keyboard", focus_pick(pg))
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(250)
    check("Enter copies", clip(pg) == value, repr(clip(pg))[:60])
    pg.wait_for_timeout(1300)
    pg.evaluate("() => navigator.clipboard.writeText('sentinel')")
    focus_pick(pg)
    scrolled_before = pg.evaluate("() => window.scrollY")
    pg.keyboard.press(" ")
    pg.wait_for_timeout(250)
    scrolled_after = pg.evaluate("() => window.scrollY")
    check("Space copies", clip(pg) == value, repr(clip(pg))[:60])
    check("Space did NOT scroll the page", scrolled_after == scrolled_before,
          f"{scrolled_before} -> {scrolled_after}")
    pg.wait_for_timeout(1300)

    # ── 4. THE POINT: re-render, then copy ────────────────────────────────
    # A repaint is dangerous in one specific way: Preact patches the node it owns
    # and re-applies only the props the ISLAND declared, so any attribute the
    # delegate stamped is dropped, and the element the earlier bind saw is gone or
    # bare. The port must therefore re-stamp (the re-arm) rather than rely on the
    # load-time pass. Reproduced here at exactly that granularity — strip the
    # stamps the way a repaint does, fire the event main.ts fires after every
    # mount, then require BOTH the a11y attributes back AND copy still working.
    marked = pg.evaluate(f"""() => {{
      const el = ({PICK})();
      if (!el) return null;
      el.dataset.sentinel = 'old';
      // What a repaint does to a stamped node: new value, island props only,
      // our marks gone.
      el.textContent = 'RA9999999999';
      el.setAttribute('data-copy', 'RA9999999999');
      el.removeAttribute('data-copy-ready');
      el.removeAttribute('role');
      el.removeAttribute('tabindex');
      el.classList.remove('cursor-copy');
      return {{ n: document.querySelectorAll('[data-copy]').length,
               roleAfterRepaint: el.getAttribute('role') }};
    }}""")
    check("the repaint really dropped the a11y stamps (the premise)",
          marked is not None and marked["roleAfterRepaint"] is None, str(marked))

    pg.evaluate("() => document.dispatchEvent(new CustomEvent('osrm:island-mounted', {detail: 'dashboard'}))")
    pg.wait_for_timeout(200)
    fresh = pg.evaluate("""() => {
      const els = [...document.querySelectorAll('[data-copy]')];
      return {
        n: els.length,
        stale: els.filter(e => e.dataset.sentinel === 'old').length,
        withRole: els.filter(e => e.getAttribute('role') === 'button').length,
        withTab: els.filter(e => e.getAttribute('tabindex') === '0').length,
        withCursor: els.filter(e => e.classList.contains('cursor-copy')).length,
      };
    }""")
    check("the re-arm restored role=button on every target (no stamp-once port)",
          fresh["n"] > 0 and fresh["withRole"] == fresh["n"], f"{fresh['withRole']}/{fresh['n']}")
    check("the re-arm restored tabindex=0",
          fresh["n"] > 0 and fresh["withTab"] == fresh["n"], f"{fresh['withTab']}/{fresh['n']}")
    check("the re-arm restored cursor-copy",
          fresh["n"] > 0 and fresh["withCursor"] == fresh["n"], f"{fresh['withCursor']}/{fresh['n']}")

    value2 = pick_value(pg)
    pg.wait_for_timeout(150)
    pg.evaluate("() => navigator.clipboard.writeText('sentinel')")
    click_pick(pg)
    pg.wait_for_timeout(300)
    check("COPY STILL WORKS AFTER THE RE-ARM (click)", clip(pg) == value2, repr(clip(pg))[:60])
    pg.wait_for_timeout(1300)
    pg.evaluate("() => navigator.clipboard.writeText('sentinel')")
    check("a re-armed target still takes focus", focus_pick(pg))
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(300)
    check("...and from the keyboard (Enter)", clip(pg) == value2, repr(clip(pg))[:60])

    # ── 5. #copyEmail (the dashboard widget's mail button) ────────────────
    if pg.evaluate("() => !!document.getElementById('copyEmail')"):
        email = pg.evaluate("() => document.getElementById('copyEmail').dataset.email")
        pg.evaluate("() => navigator.clipboard.writeText('sentinel')")
        pg.evaluate("() => document.getElementById('copyEmail').click()")
        pg.wait_for_timeout(300)
        check("#copyEmail put data-email on the clipboard", clip(pg) == email, repr(clip(pg))[:60])
        label = pg.evaluate("() => document.querySelector('#copyEmail span').textContent")
        check("#copyEmail relabelled its span", label == "Copied!", repr(label)[:40])
    else:
        check("#copyEmail present on the dashboard", False, "widget missing — cannot verify")
    b.close()

bad = [n for n, ok in res if not ok]
print(f"W5.2B COPY PROBE: {len(res) - len(bad)} passed, {len(bad)} failed")
sys.exit(1 if bad else 0)
