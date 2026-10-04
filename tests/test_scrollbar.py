"""Scrollbar DUT (9 checks): the universal scrollbar rule set ships in the
shared theme partial (both pages), wins over the UA default on every element
(scrollbar-* is not inherited, hence the universal selector), and its thumb
clears WCAG 1.4.11 (3:1) on both surfaces. Chromium ignores ::-webkit-scrollbar
width while scrollbar-width is non-auto, so the webkit block is gated behind
@supports and the base takes over as Firefox fallback. Server under test:
AGENTS.md; DATA_DIR seeded, token minted inside the test (setdefault trap)."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DATA_DIR', '/tmp/osrm-scrollbar')
from _seed import seed, mint_token
from playwright.sync_api import sync_playwright

seed(with_payload=False)
TOK = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:18183')
results = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

def contrast(c1, c2):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    def lum(c):
        r, g, b = [lin(x) for x in c]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    a, b = sorted((lum(c1), lum(c2)), reverse=True)
    return (a + 0.05) / (b + 0.05)

def oklab_alpha_rgb(css, over):
    """oklab(1 0 0 / 0.4) composited over a surface -> (r, g, b)."""
    head, tail = css.split('/', 1)
    alpha = float(re.findall(r'[\d.]+', tail)[0])
    nums = [float(x) for x in re.findall(r'-?[\d.]+', head)]
    L = nums[0] / 100 if nums[0] > 1 else nums[0]
    l_, m_, s_ = (L + 0.3963377774 * nums[1] + 0.2158037573 * nums[2],
                  L - 0.1055613458 * nums[1] - 0.0638541728 * nums[2],
                  L - 0.0894841775 * nums[1] - 1.2914855480 * nums[2])
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b = -0.0041960863 * l - 0.7034186147 * m + 1.7076148010 * s
    def f(c):
        c = max(0.0, min(1.0, c))
        c = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
        return c * 255
    col = [f(r), f(g), f(b)]
    return tuple(over[i] * (1 - alpha) + col[i] * alpha for i in range(3))

BASE100 = (22, 22, 22)   # oklch(20% 0 0)  — page background
BASE200 = (9, 9, 9)      # oklch(14% 0 0)  — cards / navbar
THIN_PX = '8px'

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1280, 'height': 900})
    ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
    pg = ctx.new_page()
    pg.goto(BASE + '/', wait_until='networkidle')
    pg.wait_for_timeout(200)

    # Force real scroll containers first: a page without overflow has NO
    # scrollbar box, and ::-webkit-* computed styles then return garbage
    # (measured: width=1280px, thumb=oklch(0.2 0 0)) — a probe on an
    # empty dashboard tests nothing.
    probe = pg.evaluate("""() => {
      const v = document.createElement('div');
      v.style.cssText = 'height:4000px;width:50px;overflow-y:scroll';
      document.body.appendChild(v);
      const h = document.createElement('div');
      h.style.cssText = 'width:200px;height:40px;overflow-x:scroll';
      h.innerHTML = '<div style="width:4000px;height:10px"></div>';
      document.body.appendChild(h);
      const g = (e, s) => getComputedStyle(e, s);
      return {
        gate: CSS.supports('selector(::-webkit-scrollbar)'),
        vW: g(v, '::-webkit-scrollbar').width,
        vH: g(v, '::-webkit-scrollbar').height,
        hH: g(h, '::-webkit-scrollbar').height,
        thumb: g(v, '::-webkit-scrollbar-thumb').backgroundColor,
        thumbRadius: g(v, '::-webkit-scrollbar-thumb').borderRadius,
        track: g(v, '::-webkit-scrollbar-track').backgroundColor,
        rootW: g(document.documentElement, '::-webkit-scrollbar').width,
      };
    }""")

    # 1. Both pages ship the rule set: login page carries the same block.
    login_html = pg.request.get(BASE + '/login').text()
    check('theme block present on /login',
          '::-webkit-scrollbar-thumb' in login_html and '@supports selector(::-webkit-scrollbar)' in login_html)

    # 2. The @supports gate fires in Chromium; 8px (not Chromium's 10px
    #    scrollbar-width:thin gutter, measured) proves the webkit block won.
    check('@supports selector(::-webkit-scrollbar) fires', probe['gate'])
    check('8px webkit scrollbar (vertical scroller)', probe['vW'] == THIN_PX,
          probe['vW'])

    # 3. Horizontal bar matches + page root scroller styled (universal = every element).
    check('horizontal bar = 8px (height)', probe['hH'] == THIN_PX, probe['hH'])
    check('root/page scroller styled', probe['rootW'] == THIN_PX, probe['rootW'])

    # 4. Thumb color is the token mix, not a hex.
    check('thumb = base-content 40% token mix',
          probe['thumb'] == 'oklab(1 0 0 / 0.4)', probe['thumb'])

    # 5. Track transparent.
    check('track transparent', probe['track'] in ('rgba(0, 0, 0, 0)', 'transparent'), probe['track'])

    # 6. Contrast: thumb over base-100 (page) and base-200 (cards).
    if '/' in probe['thumb']:
        over100 = oklab_alpha_rgb(probe['thumb'], BASE100)
        over200 = oklab_alpha_rgb(probe['thumb'], BASE200)
        c100, c200 = contrast(over100, BASE100), contrast(over200, BASE200)
    else:
        c100 = c200 = 0.0   # not an alpha color -> contrast unparseable, FAIL
    check('thumb contrast >= 3:1 on base-100 (WCAG 1.4.11)', c100 >= 3.0, f"{c100:.2f}:1")
    check('thumb contrast >= 3:1 on base-200', c200 >= 3.0, f"{c200:.2f}:1")
    b.close()

fails = sum(1 for _, ok, _ in results if not ok)
print(f"\n{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
