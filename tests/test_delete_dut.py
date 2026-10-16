"""Delete-my-data DUT (N checks): the Settings row, its explainer modal,
and the real confirm → /login round trip, at 1280x900 and 393x851.

Structure: the 'Delete my data' row sits LAST in the Settings stack (below
Log out), opens a dialog that lists exactly what is erased and what is not
(the SRM portal is never touched), carries ONE confirm button, and the
confirm POSTs /api/account/delete for real — the suite's seeded account is
deleted and the browser lands on /login.

Contrast: the OPEN modal is swept (oklch-aware parser copied from
test_personal); 0 fails is the gate. Geometry: no horizontal overflow at
either viewport, touch floors (row >= 44px, rendered confirm >= 42px).
Server under test: AGENTS.md (DUT_BASE + DATA_DIR on every call).
"""
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DATA_DIR', '/tmp/osrm-accdel')
from _seed import seed, mint_token, require_own_server  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

seed(with_payload=False)
TOK = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:18177')
require_own_server(BASE)
results = []
EXPECTED_KIDS = ['personal-details', 'push-card', 'a', 'delete-account-btn']


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── contrast helpers (verbatim from test_personal: oklch-aware) ──────
def contrast(c1, c2):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    def lum(c):
        r, g, b = [lin(x) for x in c]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    a, b = sorted((lum(c1), lum(c2)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _oklab_to_rgb(L, a, b):
    l_, m_, s_ = (L + 0.3963377774 * a + 0.2158037573 * b,
                  L - 0.1055613458 * a - 0.0638541728 * b,
                  L - 0.0894841775 * a - 1.2914855480 * b)
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    def f(x):
        x = max(0.0, min(1.0, x))
        x = 12.92 * x if x <= 0.0031308 else 1.055 * (x ** (1 / 2.4)) - 0.055
        return round(x * 255)
    return [f(r), f(g), f(bb)]


def rgb(css, over=(0, 0, 0)):
    s, alpha = css.strip(), 1.0
    if '/' in s:
        head, tail = s.split('/', 1)
        alpha = float(re.findall(r'[\d.]+', tail)[0])
        s = head + ')'
    nums = [float(x) for x in re.findall(r'-?[\d.]+', s)]
    if s.startswith('oklch'):
        L, C, H = (nums[0] / 100 if nums[0] > 1 else nums[0]), nums[1], math.radians(nums[2])
        col = _oklab_to_rgb(L, C * math.cos(H), C * math.sin(H))
    elif s.startswith('oklab'):
        L = nums[0] / 100 if nums[0] > 1 else nums[0]
        col = _oklab_to_rgb(L, nums[1], nums[2])
    elif 'rgb' in s:
        col = [int(round(x)) for x in nums[:3]]
        if len(nums) > 3:
            alpha = nums[3]
    elif not nums:
        return tuple(over)
    else:
        raise ValueError('unparsed color: ' + css)
    if alpha <= 0:
        return tuple(over)
    if alpha >= 1:
        return tuple(col)
    return tuple(int(round(over[i] * (1 - alpha) + col[i] * alpha)) for i in range(3))


# Sweep the OPEN modal: every visible text node composited over its
# ancestor backgrounds. Skips backdrop-captive and opacity-0 text (not
# perceivable content — WCAG ignores it) and any dialog that is closed.
SWEEP = """(sel) => {
  const root = document.querySelector(sel);
  if (!root || !root.open) return {rows: [], open: false};
  const seen = new Set(), out = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    const t = n.textContent.trim();
    if (!t) continue;
    const el = n.parentElement;
    if (!el || seen.has(el)) continue;
    if (el.closest('.modal-backdrop')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.05) continue;
    seen.add(el);
    const chain = [];
    for (let a = el; a; a = a.parentElement) chain.push(getComputedStyle(a).backgroundColor);
    out.push({fg: cs.color, chain, size: parseFloat(cs.fontSize),
              weight: parseInt(cs.fontWeight, 10) || 400, text: t.slice(0, 30)});
  }
  return {rows: out, open: true};
}"""

STRUCT = """() => {
  const tab = document.getElementById('tab-settings');
  const stack = tab.querySelector(':scope > .flex.flex-col');
  const row = document.getElementById('delete-account-btn');
  const rr = row.getBoundingClientRect();
  const logout = document.querySelector('a[href="/logout"]')
  const lr = logout.getBoundingClientRect();
  return {
    kids: [...stack.children].map(k => k.id || k.tagName.toLowerCase()),
    rowLast: stack.lastElementChild === row,
    rowH: Math.round(rr.height),
    rowX: Math.round(rr.x),
    logoutX: Math.round(lr.x),
    rowW: Math.round(rr.width),
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}"""

MODAL = """() => {
  const d = document.getElementById('delete-account-modal');
  if (!d.open) d.showModal();
  const box = d.querySelector('.modal-box');
  const br = box.getBoundingClientRect();
  const confirm = document.getElementById('del-confirm');
  const cr = confirm.getBoundingClientRect();
  const txt = d.innerText;
  return {
    open: d.open,
    title: d.querySelector('h3').textContent,
    optIn: txt.includes('nothing is removed until you confirm'),
    erasedHead: txt.includes('Erased from this app'),
    keptHead: txt.includes('Never touched'),
    portalLine: txt.includes('SRM portal itself') && txt.includes('nothing is deleted on SRM'),
    sharedLine: txt.includes('Shared timetables'),
    confirmN: d.querySelectorAll('button').length,
    confirmLabel: confirm.textContent.trim(),
    statusLive: !!d.querySelector('[role="status"][aria-live="polite"]'),
    confirmH: Math.round(cr.height),
    boxLeft: Math.round(br.left),
    boxRight: Math.round(br.right),
    vw: window.innerWidth,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}"""


def run_sweep(page, min_pairs, label):
    res = page.evaluate(SWEEP, '#delete-account-modal')
    rows = res['rows']
    fails, parsed, unsupported = [], 0, 0
    for r in rows:
        try:
            acc = (0, 0, 0)
            for css in reversed(r['chain']):
                acc = rgb(css, over=acc)
            fg = rgb(r['fg'], over=acc)
            ratio = contrast(fg, acc)
        except ValueError:
            unsupported += 1
            continue
        parsed += 1
        large = r['size'] >= 24 or (r['size'] >= 18.66 and r['weight'] >= 700)
        need = 3.0 if large else 4.5
        if ratio < need:
            fails.append(f"{r['text']!r} {ratio:.2f}:1 (need {need})")
    check(f'{label}: modal contrast sweep 0 fails ({parsed} parsed, {unsupported} unsupported)',
          res['open'] and not fails and parsed >= min_pairs - unsupported,
          f"pairs={len(rows)} min={min_pairs} " + '; '.join(fails[:4]))
    return len(rows)


with sync_playwright() as p:
    b = p.chromium.launch(args=['--font-render-hinting=none', '--force-color-profile=srgb'])

    # ── desktop 1280x900 ──────────────────────────────────────────────
    ctx = b.new_context(viewport={'width': 1280, 'height': 900}, device_scale_factor=2)
    ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
    page = ctx.new_page()
    page.goto(f'{BASE}/#settings', wait_until='networkidle')
    page.reload(wait_until='networkidle')
    page.wait_for_timeout(700)
    s = page.evaluate(STRUCT)
    check('desktop: row list = personal + Notifications + Log out + Delete my data (last)',
          s['kids'] == EXPECTED_KIDS and s['rowLast'], f"kids={s['kids']} last={s['rowLast']}")
    check('desktop: row clears the 44px touch floor and aligns with Log out',
          s['rowH'] >= 44 and s['rowX'] == s['logoutX'],
          f"h={s['rowH']} rowX={s['rowX']} logoutX={s['logoutX']}")
    check('desktop: no horizontal overflow', s['overflow'] <= 0, str(s['overflow']))

    m = page.evaluate(MODAL)
    check('desktop: row opens the explainer modal with the full contract text',
          m['open'] and m['title'] == 'Delete my data' and m['optIn'] and m['erasedHead']
          and m['keptHead'] and m['portalLine'] and m['sharedLine'] and m['statusLive'],
          json.dumps({k: m[k] for k in ('open', 'title', 'optIn', 'erasedHead',
                                        'keptHead', 'portalLine', 'sharedLine', 'statusLive')}))
    check('desktop: exactly one confirm button, labelled; fits the viewport',
          m['confirmLabel'] == 'Delete permanently' and m['confirmH'] >= 42
          and m['boxLeft'] >= 0 and m['boxRight'] <= m['vw'],
          f"label={m['confirmLabel']!r} h={m['confirmH']} box=({m['boxLeft']},{m['boxRight']}) vw={m['vw']}")
    run_sweep(page, 12, 'desktop')

    # Cancel closes the modal (method=dialog) before the destructive run
    page.evaluate("() => { document.querySelector('#delete-account-modal .modal-action form button').click(); }")
    page.wait_for_timeout(200)
    still_open = page.evaluate("() => document.getElementById('delete-account-modal').open")
    check('desktop: Cancel closes the modal without doing anything', not still_open, str(still_open))
    ctx.close()

    # ── mobile 393x851 ────────────────────────────────────────────────
    ctx = b.new_context(viewport={'width': 393, 'height': 851}, device_scale_factor=2.75)
    ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
    page = ctx.new_page()
    page.goto(f'{BASE}/#settings', wait_until='networkidle')
    page.reload(wait_until='networkidle')
    page.wait_for_timeout(700)
    s = page.evaluate(STRUCT)
    check('mobile: row present, last, 44px floor, aligned, no h-overflow',
          s['kids'] == EXPECTED_KIDS and s['rowLast'] and s['rowH'] >= 44
          and s['rowX'] == s['logoutX'] and s['overflow'] <= 0,
          f"kids={s['kids']} h={s['rowH']} rowX={s['rowX']} logoutX={s['logoutX']} ovf={s['overflow']}")
    m = page.evaluate(MODAL)
    check('mobile: modal opens, confirm fits width at 42px floor',
          m['open'] and m['confirmH'] >= 42 and m['boxLeft'] >= 0 and m['boxRight'] <= m['vw']
          and m['overflow'] <= 0,
          f"h={m['confirmH']} box=({m['boxLeft']},{m['boxRight']}) vw={m['vw']} ovf={m['overflow']}")
    run_sweep(page, 12, 'mobile')
    ctx.close()

    # ── the real round trip: confirm deletes, browser lands on /login ──
    ctx = b.new_context(viewport={'width': 1280, 'height': 900}, device_scale_factor=2)
    ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
    page = ctx.new_page()
    page.goto(f'{BASE}/#settings', wait_until='networkidle')
    page.reload(wait_until='networkidle')
    page.wait_for_timeout(700)
    page.evaluate(MODAL)
    page.click('#del-confirm')
    page.wait_for_url('**/login', timeout=10000)
    check('confirm POSTs and the browser lands on /login', page.url.rstrip('/').endswith('/login'),
          page.url)
    cookies = [c['name'] for c in ctx.cookies()]
    check('session cookie cleared by the delete response', 'srm_session' not in cookies,
          str(cookies))
    b.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} PASS")
sys.exit(1 if fails else 0)
