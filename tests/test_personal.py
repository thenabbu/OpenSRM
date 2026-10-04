"""Personal-details panel DUT (18 checks): identity header + 4 checkbox
collapse groups (V2 structure, V3 density), responsive default state (all
open on desktop, first group only on mobile), label-above-value grid with
the 0<8<12 spacing ladder, click-to-copy wiring, and an oklch-aware WCAG
contrast sweep over the panel. Server under test: AGENTS.md."""
import json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DATA_DIR', '/tmp/osrm-personal')
from _seed import seed, mint_token
from playwright.sync_api import sync_playwright

FULL = {"Student Name": "Aarav Rohan Mehta",
        "Register No.": "RA2511028039999",
        "Institution": "SRM Institute of Science and Technology, Delhi-NCR Campus",
        "Program": "Computer Science and Engineering with Specialization in Cloud Computing and Virtualization Technology [B.Tech]",
        "Batch": "2025", "Semester": "III SEMESTER", "Section": "A",
        "ABC NUMBER": "45012398765412398765432",
        "Date of Birth": "05-Aug-2007", "Gender": "Male", "Religion": "Hinduism",
        "Nationality": "Indian", "Blood Group": "B+",
        "Father Name": "Rajesh Mehta", "Mother Name": "Sunita Mehta",
        "Parent Contact No.": "9812345670", "Parent Email ID": "rajesh.mehta@example.com",
        "Address": "Flat 402, Skyline Residency Apartments, Sector 44, Golf Course Road, Gurugram, Haryana 122003",
        "Pincode": "122003", "District": "Gurugram", "State": "Haryana",
        "Personal Email ID": "aarav.mehta2025@gmail.com",
        "Student Mobile No.": "9876543210",
        "Alternative Student Mobile No.": "9123456780"}

seed(with_payload=False)
from app import app as A  # noqa: E402  (same DATA_DIR as the server under test)
c = A.db()
c.execute("UPDATE users SET personal_details_json=? WHERE netid='ng2776'",
          (json.dumps(FULL),))
c.commit()
TOK = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:18179')
GROUP_TITLES = ['Academic', 'Personal', 'Family', 'Contact']
GROUP_COUNTS = ['6', '5', '4', '7']
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── contrast helpers (same oklch-aware parsing as test_navbar) ─────────
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


SWEEP = """() => {
  const root = document.getElementById('tab-personal');
  const seen = new Set(), out = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    const t = n.textContent.trim();
    if (!t) continue;
    const el = n.parentElement;
    if (!el || seen.has(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;   // closed collapse content
    seen.add(el);
    const cs = getComputedStyle(el);
    const chain = [];
    for (let a = el; a; a = a.parentElement) chain.push(getComputedStyle(a).backgroundColor);
    out.push({fg: cs.color, chain, size: parseFloat(cs.fontSize),
              weight: parseInt(cs.fontWeight, 10) || 400, text: t.slice(0, 30)});
  }
  return out;
}"""


def run_sweep(page, min_pairs, label):
    rows = page.evaluate(SWEEP)
    fails, parsed, unsupported = [], 0, 0
    for r in rows:
        try:
            acc = (0, 0, 0)
            for css in reversed(r['chain']):        # composite whole chain, root first
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
    check(f'{label}: contrast sweep 0 fails ({parsed} parsed, {unsupported} unsupported)',
          not fails and len(rows) >= min_pairs and parsed >= min_pairs - unsupported,
          f'pairs={len(rows)} min={min_pairs} ' + '; '.join(fails[:4]))
    return len(rows)


GEO = """() => {
  const tab = document.getElementById('tab-personal');
  const wrap = tab.querySelector('.flex.flex-col');
  const cards = [...wrap.children];
  const groups = cards.filter(c => c.classList.contains('collapse'));
  const st = groups.map(g => g.querySelector('input').checked);
  const titles = groups.map(g => g.querySelector('.collapse-title span').textContent);
  const badges = groups.map(g => g.querySelector('.badge').textContent);
  const titleH = groups.map(g => Math.round(g.querySelector('.collapse-title').getBoundingClientRect().height));
  const gaps = [];
  for (let i = 1; i < cards.length; i++)
    gaps.push(+(cards[i].getBoundingClientRect().top - cards[i - 1].getBoundingClientRect().bottom).toFixed(1));
  const open = groups.filter(g => g.querySelector('input').checked);
  const closed = groups.filter(g => !g.querySelector('input').checked);
  const grid = groups[0].querySelector('.grid');
  const gs = getComputedStyle(grid);
  const cell = grid.children[1];
  const lbl = cell.children[0], val = cell.children[1];
  const spanCells = [...tab.querySelectorAll('.grid [class*="col-span"]')];
  const plain = [...grid.children].find(c => !c.className.includes('col-span'));
  const copies = [...tab.querySelectorAll('[data-copy]')];
  const dock = document.querySelector('.dock');
  return {
    cards: cards.length, st, titles, badges, titleH, gaps,
    gridCols: gs.gridTemplateColumns.split(' ').filter(Boolean).length,
    rowGap: parseFloat(gs.rowGap), colGap: parseFloat(gs.columnGap),
    labelToValue: +(val.getBoundingClientRect().top - lbl.getBoundingClientRect().bottom).toFixed(1),
    openContentH: open.length ? Math.round(open[0].querySelector('.collapse-content').getBoundingClientRect().height) : -1,
    closedContentH: closed.length ? Math.round(closed[0].querySelector('.collapse-content').getBoundingClientRect().height) : -1,
    spanW: spanCells.map(c => Math.round(c.getBoundingClientRect().width)),
    spanGridW: spanCells.map(c => Math.round(c.parentElement.getBoundingClientRect().width)),
    plainW: plain ? Math.round(plain.getBoundingClientRect().width) : -1,
    gridW: Math.round(grid.getBoundingClientRect().width),
    copies: copies.length,
    wired: copies.every(c => c.getAttribute('role') === 'button' && c.getAttribute('tabindex') === '0'),
    html: tab.innerHTML,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    dockH: dock ? Math.round(dock.getBoundingClientRect().height) : 0,
    mainPb: parseFloat(getComputedStyle(document.querySelector('main')).paddingBottom),
  };
}"""

with sync_playwright() as p:
    b = p.chromium.launch(args=['--font-render-hinting=none', '--force-color-profile=srgb'])

    # ── desktop 1280x900: V2 structure + V3 density, everything open ──
    ctx = b.new_context(viewport={'width': 1280, 'height': 900}, device_scale_factor=2,
                        permissions=['clipboard-read', 'clipboard-write'])
    ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
    page = ctx.new_page()
    page.goto(f'{BASE}/#personal', wait_until='networkidle')
    page.reload(wait_until='networkidle')
    page.wait_for_timeout(900)
    d = page.evaluate(GEO)

    check('desktop: identity header + 4 group cards', d['cards'] == 5, str(d['cards']))
    check('desktop: group titles + present-field counts', d['titles'] == GROUP_TITLES
          and d['badges'] == GROUP_COUNTS, f"{d['titles']} {d['badges']}")
    check('desktop: all groups open by default', all(d['st']), str(d['st']))
    check('desktop: 2-col grid, gap-2 rows / gap-x-4 cols',
          d['gridCols'] == 2 and d['rowGap'] == 8 and d['colGap'] == 16,
          f"cols={d['gridCols']} rowGap={d['rowGap']} colGap={d['colGap']}")
    check('desktop: label sits attached above value (gap 0)', d['labelToValue'] == 0, str(d['labelToValue']))
    check('desktop: spacing ladder 0 < row 8 < stack 12',
          d['labelToValue'] < d['rowGap'] < min(d['gaps'])
          and set(d['gaps']) == {12.0}, str(d['gaps']))
    check('desktop: Institution/Address each span their grid\'s full width',
          len(d['spanW']) == 2
          and all(abs(w - gw) <= 2 for w, gw in zip(d['spanW'], d['spanGridW']))
          and abs(d['plainW'] * 2 + d['colGap'] - d['gridW']) <= 2,
          f"span={d['spanW']} grids={d['spanGridW']} plain={d['plainW']} grid={d['gridW']}")
    check('desktop: collapse title >= 44px touch target', min(d['titleH']) >= 44, str(d['titleH']))
    check('desktop: no horizontal overflow', d['overflow'] <= 0, str(d['overflow']))
    check('desktop: 24 data-copy targets, all keyboard-wired',
          d['copies'] == 24 and d['wired'], f"copies={d['copies']} wired={d['wired']}")
    missing = [k for k, v in FULL.items() if v not in d['html']]
    check('desktop: all 24 field values render', not missing, str(missing))
    run_sweep(page, 50, 'desktop')

    # click-to-copy round trip
    el = page.query_selector('#tab-personal [data-copy]')
    el.click()
    page.wait_for_timeout(150)
    flashed = page.evaluate("() => document.querySelector('#tab-personal [data-copy]').textContent")
    page.wait_for_timeout(1400)
    restored = page.evaluate("() => document.querySelector('#tab-personal [data-copy]').textContent")
    check('desktop: copy click flashes Copied! then restores value',
          flashed == 'Copied!' and restored == FULL['Student Name'],
          f'{flashed!r} -> {restored!r}')
    ctx.close()

    # ── mobile 393x851: compact default (first group open) ─────────────
    ctx = b.new_context(viewport={'width': 393, 'height': 851}, device_scale_factor=2.75)
    ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
    page = ctx.new_page()
    page.goto(f'{BASE}/#personal', wait_until='networkidle')
    page.reload(wait_until='networkidle')
    page.wait_for_timeout(900)
    m = page.evaluate(GEO)

    check('mobile: default = first group open, rest collapsed', m['st'] == [True, False, False, False],
          str(m['st']))
    check('mobile: single-column grid; closed content height 0, open content laid out',
          m['gridCols'] == 1 and m['closedContentH'] == 0 and m['openContentH'] > 100,
          f"cols={m['gridCols']} closed={m['closedContentH']} open={m['openContentH']}")
    check('mobile: main clears the fixed dock (padding-bottom >= dock height)',
          m['mainPb'] >= m['dockH'], f"pb={m['mainPb']} dock={m['dockH']}")
    check('mobile: no horizontal overflow', m['overflow'] <= 0, str(m['overflow']))
    run_sweep(page, 14, 'mobile')
    b.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} PASS")
sys.exit(1 if fails else 0)
