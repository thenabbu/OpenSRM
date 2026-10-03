"""Navbar DUT (12 checks): desktop bar sheds the netid echo, the selected tab
has a perceivable tint (daisyUI .btn-active is a no-op on this dark surface),
the sync caption is a relative age to the right of the refresh button and
disappears when fresh, the mobile bar shows no version badge, and the wordmark
carries a 4px minor radius. Server under test: AGENTS.md."""
import json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DATA_DIR', '/tmp/osrm-navbar')
from _seed import seed, mint_token
from playwright.sync_api import sync_playwright

seed(with_payload=False)
TOK = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:18178')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NETID = 'ng2776'
VERSION = open(os.path.join(REPO, 'VERSION')).read().strip()
results = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

def contrast(c1, c2):
    """WCAG contrast from two 'r, g, b' channels (0-255)."""
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    def lum(c):
        r, g, b = [lin(x) for x in c]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    a, b = sorted((lum(c1), lum(c2)), reverse=True)
    return (a + 0.05) / (b + 0.05)

def _oklab_to_rgb(L, a, b):
    """OKLab -> sRGB 0-255 (computed styles come back as oklab()/oklch())."""
    l_, m_, s_ = (L + 0.3963377774 * a + 0.2158037573 * b,
                  L - 0.1055613458 * a - 0.0638541728 * b,
                  L - 0.0894841775 * a - 1.2914855480 * b)
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    def f(c):
        c = max(0.0, min(1.0, c))
        c = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
        return round(c * 255)
    return [f(r), f(g), f(bb)]

def rgb(css, over=(0, 0, 0)):
    """Parsed computed color -> (r, g, b). Handles rgb(a)/oklab/oklch/transparent;
    translucent fills composite over `over` (the surface they sit on)."""
    s, alpha = css.strip(), 1.0
    if '/' in s:                       # oklab(1 0 0 / 0.1)
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
    elif not nums:                     # transparent
        return tuple(over)
    else:
        raise ValueError('unparsed color: ' + css)
    if alpha <= 0:
        return tuple(over)
    if alpha >= 1:
        return tuple(col)
    return tuple(int(round(over[i] * (1 - alpha) + col[i] * alpha)) for i in range(3))

with sync_playwright() as p:
    b = p.chromium.launch()

    # ── desktop 1280x900 ────────────────────────────────────────────
    ctx = b.new_context(viewport={'width': 1280, 'height': 900})
    ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
    page = ctx.new_page()
    page.goto(f'{BASE}/', wait_until='networkidle')
    page.wait_for_timeout(600)

    d = page.evaluate("""() => {
      const nav = document.querySelector('.navbar.hidden');
      const tabs = [...nav.querySelectorAll('[role="tab"]')];
      const on = tabs.find(t => t.getAttribute('aria-selected') === 'true');
      const off = tabs.find(t => t.getAttribute('aria-selected') === 'false');
      const end = [...nav.querySelector('.navbar-end').children];
      const sync = nav.querySelector('.sync-line');
      const refresh = nav.querySelector('[data-refresh]');
      const logo = nav.querySelector('img');
      return {
        start: nav.querySelector('.navbar-start').innerText,
        onBg: getComputedStyle(on).backgroundColor,
        offBg: getComputedStyle(off).backgroundColor,
        onTab: on.dataset.tab,
        logoRadius: getComputedStyle(logo).borderRadius,
        syncText: sync.textContent, syncDisplay: getComputedStyle(sync).display,
        syncTitle: sync.title,
        endOrder: end.map(c => c.tagName + (c.dataset && c.dataset.refresh ? ':refresh' : '')),
        overflow: document.documentElement.scrollWidth - window.innerWidth
      };
    }""")
    nav_bg = rgb(page.evaluate("() => getComputedStyle(document.querySelector('.navbar.hidden')).backgroundColor"))
    # NOTE: translucent fills must composite over the surface they sit on (nav_bg),
    check('desktop: navbar has no (netid) echo', f'({NETID})' not in d['start'], d['start'].replace('\n', ' '))
    check('desktop: wordmark radius = 4px (minor, not the 8px box token)', d['logoRadius'] == '4px', d['logoRadius'])
    r_on, r_off = contrast(rgb(d['onBg'], nav_bg), nav_bg), contrast(rgb(d['offBg'], nav_bg), nav_bg)
    check('desktop: selected tab tint vs navbar >= 1.15:1', r_on >= 1.15, f"{d['onTab']} = {d['onBg']} -> {r_on:.3f}:1")
    check('desktop: unselected tab stays flush with navbar', d['offBg'] in ('rgba(0, 0, 0, 0)', 'transparent'), f"{d['offBg']} -> {r_off:.3f}:1")
    check('desktop: caption follows the refresh button in the DOM',
          d['endOrder'] == ['BUTTON', 'SPAN', 'A'], str(d['endOrder']))
    check('desktop: fresh sync shows no caption', d['syncText'] == '' and d['syncDisplay'] == 'none',
          f"text={d['syncText']!r} display={d['syncDisplay']}")

    # caption formatting across every age bucket (drives renderSyncLines directly)
    ages = [(900, '(15m ago)'), (7200, '(2h ago)'), (200000, '(2d ago)'), (0, 'Never synced'), (120, '')]
    got = []
    for age, want in ages:
        ts = 0 if age == 0 else int(__import__('time').time()) - age
        got.append(page.evaluate("""(ts) => {
          const el = document.querySelector('.navbar.hidden .sync-line');
          el.dataset.ts = String(ts);
          renderSyncLines();
          return {text: el.textContent, display: getComputedStyle(el).display, title: el.title !== ''};
        }""", ts) | {'want': want})
    check('desktop: caption format per age bucket',
          all(g['text'] == g['want'] for g in got) and got[-1]['display'] == 'none' and all(g['title'] for g in got),
          json.dumps([(g['want'], g['text']) for g in got]))

    geo = page.evaluate("""() => {
      const nav = document.querySelector('.navbar.hidden');
      const sync = nav.querySelector('.sync-line'), refresh = nav.querySelector('[data-refresh]');
      sync.dataset.ts = String(Math.floor(Date.now() / 1000) - 900);
      renderSyncLines();
      const sr = sync.getBoundingClientRect(), rr = refresh.getBoundingClientRect();
      return {visible: getComputedStyle(sync).display !== 'none',
              gap: sr.x - rr.right, within: sr.right <= nav.getBoundingClientRect().right};
    }""")
    check('desktop: visible caption sits just right of the refresh button, in-bar',
          geo['visible'] and 0 <= geo['gap'] <= 16 and geo['within'], json.dumps(geo))
    page.reload(wait_until='networkidle')   # restore server-rendered state

    page.click('#tab-attendance-tab')
    page.wait_for_timeout(300)
    moved = page.evaluate("""() => {
      const tabs = [...document.querySelectorAll('.navbar.hidden [role="tab"]')];
      const bg = t => getComputedStyle(t).backgroundColor;
      return {on: tabs.find(t => t.getAttribute('aria-selected') === 'true').dataset.tab,
              onBg: bg(tabs.find(t => t.getAttribute('aria-selected') === 'true')),
              prevBg: bg(tabs.find(t => t.dataset.tab === 'dashboard'))};
    }""")
    check('desktop: tint follows the tab you select', moved['on'] == 'attendance'
          and moved['prevBg'] in ('rgba(0, 0, 0, 0)', 'transparent'), json.dumps(moved))
    # state must not be carried by color alone (WCAG 1.4.1): the selected tab
    # also draws the same currentColor bar the mobile dock uses
    ind = page.evaluate("""() => {
      const tabs = [...document.querySelectorAll('.navbar.hidden [role="tab"]')];
      const style = t => { const cs = getComputedStyle(t, '::after');
        return {h: cs.height, bg: cs.backgroundColor, pos: cs.position,
                w: cs.width, left: cs.left, right: cs.right}; };
      const on = tabs.find(t => t.getAttribute('aria-selected') === 'true');
      const off = tabs.find(t => t.getAttribute('aria-selected') === 'false');
      return {on: style(on), off: style(off),
              pillW: Math.round(on.getBoundingClientRect().width),
              padW: on.clientWidth};   /* ::after offsets resolve against the PADDING box */
    }""")
    check('desktop: selected tab carries a non-color state bar (WCAG 1.4.1)',
          ind['on']['h'] == '2px' and ind['on']['bg'] not in ('rgba(0, 0, 0, 0)', 'transparent')
          and ind['off']['h'] in ('0px', 'auto', '') and ind['off']['bg'] in ('rgba(0, 0, 0, 0)', 'transparent'),
          json.dumps(ind))
    # the bar must span the pill minus its 8px insets: an undeclared width lets
    # daisyUI .dock-active:after{width:2.5rem} leak in (40px, lopsided 8/41)
    bar_w = float(ind['on']['w'].replace('px', ''))
    check('desktop: bar spans pill minus 8px insets (no dock-active width leak)',
          abs(bar_w - (ind['padW'] - 16)) <= 1
          and ind['on']['left'] == '8px' and ind['on']['right'] == '8px',
          f"bar={bar_w}px paddingBox={ind['padW']}px pill={ind['pillW']}px "
          f"left={ind['on']['left']} right={ind['on']['right']}")
    check('desktop: no horizontal overflow', d['overflow'] <= 0, str(d['overflow']))
    ctx.close()

    # ── mobile 393x851 ──────────────────────────────────────────────
    ctx = b.new_context(viewport={'width': 393, 'height': 851}, device_scale_factor=2)
    ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
    page = ctx.new_page()
    page.goto(f'{BASE}/', wait_until='networkidle')
    page.wait_for_timeout(600)
    m = page.evaluate("""() => {
      const nav = document.querySelector('.navbar.lg\\\\:hidden');
      const sync = nav.querySelector('.sync-line');
      const refresh = nav.querySelector('[data-refresh]');
      return {
        versionBadges: document.querySelectorAll('.version-badge').length,
        navText: nav.innerText,
        logoRadius: getComputedStyle(nav.querySelector('img')).borderRadius,
        syncDisplay: getComputedStyle(sync).display,
        endOrder: [...nav.querySelector('.navbar-end').children].map(c => c.tagName),
        overflow: document.documentElement.scrollWidth - window.innerWidth
      };
    }""")
    check('mobile: no version badge in the navbar',
          m['versionBadges'] == 0 and f'v{VERSION}' not in m['navText'] and VERSION not in m['navText'],
          f"badges={m['versionBadges']} text={m['navText']!r}")
    check('mobile: wordmark radius = 4px (minor, not the 8px box token)', m['logoRadius'] == '4px', m['logoRadius'])
    check('mobile: caption follows refresh in the DOM and is hidden when fresh',
          m['endOrder'] == ['BUTTON', 'SPAN', 'A'] and m['syncDisplay'] == 'none',
          f"{m['endOrder']} display={m['syncDisplay']}")
    check('mobile: no horizontal overflow', m['overflow'] <= 0, str(m['overflow']))
    b.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results)-len(fails)}/{len(results)} PASS")
sys.exit(1 if fails else 0)
