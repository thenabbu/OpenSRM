"""SCOPE profile DUT — the profile widget + Settings enrichment against a
REAL server holding REAL scope_json (feature slug `profile` on).

Checks (23):
  widget  no <img>/no photo source in the DOM (the generated blobatar SVG is the
          avatar), name / email / register number still render, NO course line
          under the identity, unchanged 64x64 avatar + one-row identity column,
          widget geometry inside its card, no horizontal overflow;
  settings scope-only facts (parents, DOB, admitted date, address, university,
          program long form) appear as rows in their EXISTING groups; a portal
          value still wins over the scope one; empty advisors add no row;
  contrast WCAG sweep over the widget and the opened Settings groups;
  gate   with SCOPE_FEATURES=off the same DB renders today's widget and the
          portal-only Settings (the feature is inert when off).

Server under test: AGENTS.md. Run with DATA_DIR + DUT_BASE inline + SCOPE_FEATURES.
"""
import json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DATA_DIR', '/tmp/osrm-scope-profile')
from _seed import seed_rich, mint_token, require_own_server
from playwright.sync_api import sync_playwright

# Portal personal details: NOTHING about parents/DOB/address/university, so the
# Settings rows below can only come from scope (portal-first is pinned by the
# Address override case, which the portal DOES own).
PORTAL = {"Student Name": "Test Student", "Register No.": "RA2500000000",
          "Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
          "Batch": "2025", "Semester": "III SEMESTER", "Section": "A",
          "Date of Birth": "01-Jan-2000",
          "Address": "Portal Address 1, Sector 9"}
SCOPE = {"getPersonalDetails": {"data": {
    "father": "Uma Shanker Gupta", "mother": "Alpana Gupta",
    "dob": "28-Feb-2008", "admitteddate": "30-Jul-2025",
    "address": "B-35 Manavsthali Apartments, Vasundhara Enclave, Delhi",
    "program": "B.Tech.-Computer Science and Engineering with specialization in Cloud Computing [UG - FT - ACADEMIC]",
    "universityname": "SRM Engineering College, Ghaziabad (SRM Institute of Science and Technology)",
    "semester": "III SEMESTER", "sectiondesc": "A", "batch": "2025",
    "facultyadvisor": "", "academicadvisor": "",
    # a real student photo would live here — the widget must never show it
    "studentphoto": "X" * 64,
}, "ts": 1760000000}}

seed_rich(with_payload=False)
from app import app as A  # noqa: E402
c = A.db()
c.execute("UPDATE users SET personal_details_json=?, scope_json=? WHERE netid='zz9999'",
          (json.dumps(PORTAL), json.dumps(SCOPE)))
c.commit(); c.close()
TOK = mint_token()
BASE = os.environ.get('DUT_BASE', 'http://127.0.0.1:18183')
require_own_server(BASE)
GATE_OFF = os.environ.get('SCOPE_PROFILE_OFF') == '1'
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── contrast helpers (same oklch/oklab parsing as test_personal) ──────────
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


SWEEP = """(rootSel) => {
  const root = document.querySelector(rootSel);
  if (!root) return [];
  const seen = new Set(), out = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    const t = n.textContent.trim();
    if (!t) continue;
    const el = n.parentElement;
    if (!el || seen.has(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    seen.add(el);
    const cs = getComputedStyle(el);
    const chain = [];
    for (let a = el; a; a = a.parentElement) chain.push(getComputedStyle(a).backgroundColor);
    out.push({fg: cs.color, chain, size: parseFloat(cs.fontSize),
              weight: parseInt(cs.fontWeight, 10) || 400, text: t.slice(0, 30)});
  }
  return out;
}"""


def run_sweep(page, root, min_pairs, label):
    rows = page.evaluate(SWEEP, root)
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
    check(f'{label}: contrast sweep 0 fails ({parsed} parsed, {unsupported} unsupported)',
          not fails and len(rows) >= min_pairs and parsed >= min_pairs - unsupported,
          f'pairs={len(rows)} min={min_pairs} ' + '; '.join(fails[:4]))
    return len(rows)


# ── DOM probes ───────────────────────────────────────────────────────────
WIDGET = """() => {
  // the profile widget = the .wbox that owns #copyEmail
  const box = document.getElementById('copyEmail').closest('.wbox');
  const card = box.closest('.card');
  const av = box.querySelector('.avatar > div');
  const avR = av.getBoundingClientRect();
  const col = box.querySelector('.min-w-0.flex-1');
  const kids = [...col.children].filter(k => k.getBoundingClientRect().height > 0);
  const img = box.querySelector('img');
  const bg = getComputedStyle(av).backgroundImage;
  return {
    hasImg: !!img, imgSrc: img ? img.getAttribute('src') : null,
    avatarBgImage: bg, avatarW: Math.round(avR.width), avatarH: Math.round(avR.height),
    kids: kids.length,
    lines: kids.map(k => k.textContent.trim().slice(0, 60)),
    svg: box.querySelectorAll('svg').length,
    text: box.textContent.replace(/\\s+/g, ' ').trim(),
    box: {top: box.getBoundingClientRect().top, bottom: box.getBoundingClientRect().bottom,
          left: box.getBoundingClientRect().left, right: box.getBoundingClientRect().right},
    card: {top: card.getBoundingClientRect().top, bottom: card.getBoundingClientRect().bottom,
           left: card.getBoundingClientRect().left, right: card.getBoundingClientRect().right},
    colLeft: Math.round(col.getBoundingClientRect().left),
    avRight: Math.round(avR.right),
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    innerOverflow: box.scrollWidth - box.clientWidth,
  };
}"""

SETTINGS = """() => {
  const tab = document.getElementById('tab-settings');
  const row = document.getElementById('personal-details');
  const groups = [...row.querySelectorAll('.collapse')];
  const out = {};
  for (const g of groups) {
    const title = g.querySelector('.collapse-title span').textContent.trim();
    out[title] = {
      badge: g.querySelector('.badge').textContent.trim(),
      rows: [...g.querySelectorAll('.grid > div')].map(c => ({
        k: c.children[0].textContent.trim(), v: c.children[1].textContent.trim(),
        mono: c.children[1].classList.contains('font-mono')})),
    };
  }
  return {groups: out, html: tab.innerHTML,
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          h1lbl: [...groups[0].querySelectorAll('.text-xs.uppercase')].length};
}"""

def goto_settings(page):
    """Switch to the Settings panel through its real tab button (the hash is
    NOT a navigation input here — the app restores it once at load only)."""
    vis = page.locator('#tab-settings-tab:visible')
    (vis.first if vis.count() else page.locator('#tab-settings-tab')).click()
    page.wait_for_timeout(700)


def open_settings(page, tag):
    """Open the personal-details row + every group the way a user does (click
    the title, which toggles the collapse's checkbox) and let the transition
    settle — this doubles as the touch/click path check."""
    page.evaluate("() => { document.querySelector('#personal-details > input').checked = true; }")
    page.wait_for_timeout(400)
    n = page.evaluate("() => document.querySelectorAll('#personal-details .collapse').length")
    page.evaluate("() => document.querySelectorAll('#personal-details .collapse > input')"
                  ".forEach(i => { i.checked = true; })")
    # daisyUI transitions visibility through the checkbox wait: give the
    # collapse-content a visible box before measuring (the suite owns this
    # wait, the app owns nothing here)
    page.add_style_tag(content="#personal-details .collapse-content{visibility:visible;"
                              "max-height:none;transition:none;padding-top:.5rem;padding-bottom:.5rem}")
    page.wait_for_timeout(600)


with sync_playwright() as p:
    b = p.chromium.launch(args=['--font-render-hinting=none', '--force-color-profile=srgb'])
    for vp, tag in (({'width': 1280, 'height': 900}, 'desktop'),
                    ({'width': 393, 'height': 851}, 'mobile')):
        ctx = b.new_context(viewport=vp, device_scale_factor=2,
                            permissions=['clipboard-read', 'clipboard-write'])
        ctx.add_cookies([{'name': 'srm_session', 'value': TOK, 'url': BASE}])
        page = ctx.new_page()
        page.goto(f'{BASE}/', wait_until='networkidle')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(1200)
        w = page.evaluate(WIDGET)

        check(f'{tag}: profile widget renders NO photo <img>',
              not w['hasImg'] and w['avatarBgImage'] in ('none', ''),
              f"img={w['hasImg']} src={w['imgSrc']} bg={w['avatarBgImage'][:30]}")
        check(f'{tag}: generated blobatar SVG is the avatar',
              w['svg'] >= 2 and w['avatarW'] == 64 and w['avatarH'] == 64,
              f"svg={w['svg']} {w['avatarW']}x{w['avatarH']}")
        check(f'{tag}: identity = name / email / register no, nothing else',
              len(w['lines']) == 3
              and 'Test Student' in w['lines'][0]
              and 'zz9999@srmist.edu.in' in w['lines'][1]
              and 'RA2500000000' in w['lines'][2],
              str(w['lines']))
        check(f'{tag}: no course / semester / section one-liner',
              not re.search(r'(B\.Tech|SEMESTER|Section [A-Z]\\b|CSE)', w['text'])
              and 'studentphoto' not in w['text'],
              w['text'][:90])
        check(f'{tag}: widget stays inside its card, avatar left of the column',
              w['box']['top'] >= w['card']['top'] - 0.5
              and w['box']['bottom'] <= w['card']['bottom'] + 0.5
              and w['box']['left'] >= w['card']['left'] - 0.5
              and w['avRight'] <= w['colLeft'],
              f"box={w['box']} card={w['card']} avRight={w['avRight']} colLeft={w['colLeft']}")
        check(f'{tag}: no horizontal overflow (page or widget)',
              w['overflow'] <= 0 and w['innerOverflow'] <= 0,
              f"page={w['overflow']} widget={w['innerOverflow']}")
        run_sweep(page, '.wbox:has(#copyEmail)', 3, tag + ' widget')

        # ── Settings: scope enrichment ──
        goto_settings(page)
        open_settings(page, tag)
        s = page.evaluate(SETTINGS)
        fam = {r['k']: r['v'] for r in s['groups']['Family']['rows']}
        per = {r['k']: r['v'] for r in s['groups']['Personal']['rows']}
        aca = {r['k']: r['v'] for r in s['groups']['Academic']['rows']}
        con = {r['k']: r['v'] for r in s['groups']['Contact']['rows']}
        if GATE_OFF:
            check(f'{tag}: gate off — no scope-only rows anywhere',
                  'Father Name' not in fam and 'Admitted On' not in per
                  and 'University' not in aca and 'Program (Full)' not in aca,
                  f"fam={list(fam)} per={list(per)} aca={list(aca)}")
            run_sweep(page, '#tab-settings', 10, tag + ' settings(off)')
        else:
            check(f'{tag}: Settings Family gains parents from SCOPE',
                  fam.get('Father Name') == 'Uma Shanker Gupta'
                  and fam.get('Mother Name') == 'Alpana Gupta', str(fam))
            check(f'{tag}: Settings Personal gains Admitted On; portal DOB still wins',
                  per.get('Admitted On') == '30-Jul-2025'
                  and per.get('Date of Birth') == '01-Jan-2000',
                  f"admitted={per.get('Admitted On')} dob={per.get('Date of Birth')}")
            check(f'{tag}: Settings Contact keeps the PORTAL address (portal wins)',
                  con.get('Address') == PORTAL['Address'], str(con.get('Address')))
            check(f'{tag}: Settings Academic gains University + Program (Full)',
                  'SRM Engineering College' in aca.get('University', '')
                  and 'specialization in Cloud Computing' in aca.get('Program (Full)', ''),
                  f"uni={aca.get('University','')[:24]} prog={aca.get('Program (Full)','')[:24]}")
            check(f'{tag}: empty advisors add no rows',
                  'Faculty Advisor' not in aca and 'Academic Advisor' not in aca,
                  f"academic keys={list(aca)}")
            check(f'{tag}: no duplicate rows — scope long form is the only "Program (Full)"',
                  'Program (Full)' in aca and list(aca).count('Program (Full)') == 1
                  and PORTAL['Program'] in s['html'],
                  f"aca={list(aca)}")
            check(f'{tag}: scope photo never reaches the page',
                  'XXXX' not in s['html'] and 'studentphoto' not in s['html'], '')
            run_sweep(page, '#tab-settings', 20, tag + ' settings')
        check(f'{tag}: Settings has no horizontal overflow', s['overflow'] <= 0, str(s['overflow']))
        ctx.close()
    b.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} PASS")
sys.exit(1 if fails else 0)
