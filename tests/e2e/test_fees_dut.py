#!/usr/bin/env python3
"""Fees tab DUT: layout law + contrast + the reworked density, measured.

Law under test (agents/rework-fees.md, navya's corrections 1-6):
  - Paid rows: date (leftmost) | 1px vertical rule | name | amount (rightmost),
    all on ONE line box; amounts right-align on one x; no dividers between
    rows (zero horizontal borders inside a group); group gapping: the space
    under a year header is strictly larger than the gap between rows.
  - Receipts: ONE collapsed <details> ("Receipts (6)"); inside it each receipt
    is its own collapsed <details>; opening one reveals voucher + narration
    only for that receipt. No per-receipt type badge.
  - Zero dues: the all-clear widget is GONE — the panel's first element is the
    Paid header (no hero). Dues > 0: the hero is the only coloured object.
  - WCAG at 393x851 AND 1280x900: every text node on its real bg.
  - Geometry at both: no h-overflow, no overlap, positive gaps.

Needs DATA_DIR + DUT_BASE inline; self-seeds both arms (dues / all paid).
"""
import os
import sys

BASE = os.environ.get("DUT_BASE")
DATA_DIR = os.environ.get("DATA_DIR")
if not BASE or not DATA_DIR:
    sys.exit("FAIL: pass DATA_DIR + DUT_BASE inline")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))
sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
from _seed import require_own_server  # noqa: E402

require_own_server(BASE)

import _fees_seed  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.app import make_session_token  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(' — ' + detail) if detail and not ok else ''}")
    if not ok:
        FAILS.append(name)


# ── in-page: contrast over each element's real bg stack (daisyUI 5 emits
# oklch/oklab with DECIMAL alpha — test_marks_dut.py's parser, verbatim idea)
CONTRAST_JS = """
() => {
  const lab2rgb = (L, a, b, A) => {
    const l_ = L + 0.3963377774 * a + 0.2158037573 * b,
          m_ = L - 0.1055613458 * a - 0.0638541728 * b,
          s_ = L - 0.0894841775 * a - 1.2914855480 * b;
    const l = l_ ** 3, mm = m_ ** 3, ss = s_ ** 3;
    let rgb = [4.0767416621 * l - 3.3077115913 * mm + 0.2309699292 * ss,
               -1.2684380046 * l + 2.6097574011 * mm - 0.3413193965 * ss,
               -0.0041960863 * l - 0.7034186147 * mm + 1.7076147010 * ss];
    rgb = rgb.map(v => { v = Math.min(1, Math.max(0, v));
      return v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - 0.055; });
    return {r: rgb[0] * 255, g: rgb[1] * 255, b: rgb[2] * 255, a: A};
  };
  const alpha = s => s.endsWith('%') ? parseFloat(s) / 100 : parseFloat(s);
  const parse = s => {
    s = String(s).trim();
    let m = s.match(/^rgba?\\(([^)]+)\\)$/);
    if (m) { const p = m[1].split(/[,\\s\\/]+/).filter(Boolean).map(Number);
             return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; }
    m = s.match(/^oklch\\(\\s*([\\d.]+)%?\\s+([\\d.]+)\\s+([-\\d.]+)\\s*(?:\\/\\s*([\\d.]+%?))?\\)$/);
    if (m) { const L = +m[1] > 1 ? +m[1] / 100 : +m[1], C = +m[2], H = +m[3] * Math.PI / 180,
                   A = m[4] ? alpha(m[4]) : 1, a = C * Math.cos(H), b = C * Math.sin(H);
             return lab2rgb(L, a, b, A); }
    m = s.match(/^oklab\\(\\s*([\\d.]+)%?\\s+([-\\d.]+)\\s+([-\\d.]+)\\s*(?:\\/\\s*([\\d.]+%?))?\\)$/);
    if (m) { const L = +m[1] > 1 ? +m[1] / 100 : +m[1];
             return lab2rgb(L, +m[2], +m[3], m[4] ? alpha(m[4]) : 1); }
    m = s.match(/^#([0-9a-f]{3,8})$/i);
    if (m) { let h = m[1];
      if (h.length === 3) h = h.split('').map(x => x + x).join('');
      return {r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16),
              b: parseInt(h.slice(4, 6), 16), a: h.length >= 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1}; }
    return null;
  };
  const over = (f, b) => ({r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a),
                           b: f.b * f.a + b.b * (1 - f.a), a: 1});
  const bgStack = el => { const st = []; let n = el;
    while (n) { const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) { st.push(c); if (c.a === 1) break; } n = n.parentElement; }
    let base = {r: 22, g: 22, b: 22, a: 1};
    for (let i = st.length - 1; i >= 0; i--) base = over(st[i], base);
    return base; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 :
    Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  document.querySelectorAll('#tab-fees details').forEach(d => { d.open = true; });
  document.querySelectorAll('#tab-fees div').forEach(d => {
    if (getComputedStyle(d).display === 'none') d.style.display = 'flex'; });
  const panel = document.querySelector('#tab-fees');
  const out = [];
  [...panel.querySelectorAll('*')].forEach(el => {
    if (!el.getBoundingClientRect().width) return;
    const t = [...el.childNodes].filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim()).join(' ').trim();
    if (!t || !/[\\p{L}\\p{N}]/u.test(t)) return;
    const cs = getComputedStyle(el), fg = parse(cs.color), bg = bgStack(el);
    if (!fg) return;
    const eff = over(fg, bg), L1 = lum(eff), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(cs.fontSize), wt = +cs.fontWeight || 400;
    const need = (size >= 24 || (size >= 18.66 && wt >= 700)) ? 3 : 4.5;
    out.push({t: t.slice(0, 34), ratio: +ratio.toFixed(2), need,
              cls: String(el.className).slice(0, 44)});
  });
  return out;
}
"""

# ── paid-row geometry + law (collapsed state, real layout)
LAW_JS = """
() => {
  const r = e => e.getBoundingClientRect();
  const panel = document.querySelector('#tab-fees');
  const rows = [...panel.querySelectorAll('section > div.flex > div')];
  const out = {rows: [], headerGaps: [], rowGaps: [], borders: 0, badges: 0, total: 0};
  out.total = rows.length;
  rows.forEach(row => {
    const [d, v, n, a] = row.children;
    const rd = r(d), rv = r(v), rn = r(n), ra = r(a);
    out.rows.push({left: +rd.left.toFixed(2), rule: +rv.left.toFixed(2),
                   ruleW: +rv.width.toFixed(2), ruleH: +rv.height.toFixed(2),
                   name: +rn.left.toFixed(2), amtRight: +ra.right.toFixed(2),
                   top: +rd.top.toFixed(2), h: +rd.height.toFixed(2),
                   nameClipped: n.scrollWidth > n.clientWidth + 1});
    [row, d, v, n, a].forEach(el => {
      const cs = getComputedStyle(el);
      if (parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderBottomWidth) > 0) out.borders++;
    });
  });
  // gaps: header bottom -> first row top (group gapping) vs row -> row (uniform)
  [...panel.querySelectorAll('section')].forEach(s => {
    const head = s.firstElementChild, first = s.querySelector('div.flex > div');
    out.headerGaps.push(+(r(first).top - r(head).bottom).toFixed(2));
    const cs = [...s.querySelectorAll('div.flex')[1].children].map(r);
    for (let i = 1; i < cs.length; i++) out.rowGaps.push(+(cs[i].top - cs[i - 1].bottom).toFixed(2));
  });
  out.badges = panel.querySelectorAll('section .badge').length;
  return out;
}
"""

# ── receipts: structure + per-receipt accordion behaviour
RECEIPT_JS = """
() => {
  const panel = document.querySelector('#tab-fees');
  const shell = [...panel.querySelectorAll('details')][0];
  if (!shell) return {error: 'no receipts <details>'};
  const out = {summary: shell.querySelector('summary').textContent.replace(/\\s+/g, ' ').trim(),
               openByDefault: shell.open, inner: shell.querySelectorAll('details').length,
               innerOpenByDefault: [...shell.querySelectorAll('details')].filter(d => d.open).length,
               badges: panel.querySelectorAll('.badge').length};
  shell.open = true;
  const inner = [...shell.querySelectorAll('details')];
  out.summaries = inner.map(d => {
    const kids = [...d.querySelector('summary').children];
    return {date: kids[0].textContent.trim(), head: kids[2].textContent.trim(),
            amt: kids[3].textContent.trim(), gap: +(kids[2].getBoundingClientRect().left
                 - kids[1].getBoundingClientRect().right).toFixed(1)};
  });
  // open the 2nd receipt only: its content shows, the 1st stays closed
  const body = d => d.querySelector('.collapse-content');
  inner[1].open = true;
  const shown = getComputedStyle(body(inner[1])).visibility !== 'hidden'
                && body(inner[1]).getBoundingClientRect().height > 0
                && getComputedStyle(body(inner[1])).opacity !== '0';
  const hidden = (() => { const b = body(inner[0]);
    return getComputedStyle(b).visibility === 'hidden' || b.getBoundingClientRect().height < 1
           || getComputedStyle(b).opacity === '0'; })();
  out.oneATA = shown && hidden;
  out.bodyText = body(inner[1]).textContent.replace(/\\s+/g, ' ').trim().slice(0, 80);
  out.hasVoucher = body(inner[1]).textContent.includes('#');
  inner[1].open = false; shell.open = false;
  return out;
}
"""

# ── dues-absent arm: the all-clear widget is gone entirely
CLEAR_JS = """
() => {
  const panel = document.querySelector('#tab-fees');
  const first = panel.firstElementChild;
  return {txt: panel.textContent, firstTag: first.tagName,
          firstText: first.textContent.replace(/\\s+/g, ' ').trim().slice(0, 40),
          hasAllClear: /all clear/i.test(panel.textContent),
          stands: panel.querySelectorAll('section').length};
}
"""

# ── dues arm: hero present, first, and the single coloured object
DUES_JS = """
() => {
  const panel = document.querySelector('#tab-fees');
  const hero = panel.firstElementChild;
  const num = hero.querySelector('.text-2xl');
  return {firstText: hero.textContent.replace(/\\s+/g, ' ').trim().slice(0, 60),
          dueText: num ? num.textContent.trim() : '',
          level: num ? num.className : '',
          coloured: [...panel.querySelectorAll('*')].filter(el => {
            if (!el.getBoundingClientRect().width) return false;
            const t = [...el.childNodes].filter(n => n.nodeType === 3)
              .map(n => n.textContent.trim()).join(' ').trim();
            if (!t) return false;
            const c = getComputedStyle(el).color;
            return /oklch\\(0\\.(6[5-9]|7|8)/.test(c) || /warning|error|success/.test(el.className);
          }).map(el => el.textContent.trim().slice(0, 24))};
}
"""


def overflow_js():
    return ("() => ({sw: document.documentElement.scrollWidth, "
            "cw: document.documentElement.clientWidth, "
            "worst: Math.max(0, ...[...document.querySelectorAll('#tab-fees *')]"
            ".map(e => e.getBoundingClientRect().right - document.documentElement.clientWidth))})")


def run(browser, w, h, arm):
    _fees_seed.seed(arm)
    ctx = browser.new_context(viewport={"width": w, "height": h})
    ctx.add_cookies([{"name": "srm_session", "value": make_session_token("zz9999"), "url": BASE}])
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    page.evaluate("() => document.querySelector('#tab-fees-tab').click()")
    page.wait_for_timeout(250)
    tag = f"{arm} {w}x{h}"

    if arm == "clear":
        c = page.evaluate(CLEAR_JS)
        check(f"{tag}: no all-clear widget anywhere", not c["hasAllClear"], c["txt"][:80])
        check(f"{tag}: page starts at the Paid header",
              c["firstTag"] == "DIV" and c["firstText"].startswith("Paid"), c["firstText"])
        check(f"{tag}: paid groups render", c["stands"] >= 1, str(c["stands"]))

    law = page.evaluate(LAW_JS)
    check(f"{tag}: paid rows present", law["total"] >= 3, str(law["total"]))
    check(f"{tag}: no horizontal dividers/borders on paid rows", law["borders"] == 0,
          f"{law['borders']} border edges")
    check(f"{tag}: no per-row badge/chip", law["badges"] == 0, str(law["badges"]))
    if law["rows"]:
        r0 = law["rows"][0]
        check(f"{tag}: date is leftmost, rule, then name, amount rightmost",
              r0["left"] < r0["rule"] and r0["rule"] + r0["ruleW"] <= r0["name"]
              and r0["name"] < r0["amtRight"], str(r0))
        check(f"{tag}: vertical rule is 1px", abs(r0["ruleW"] - 1) < 0.01, str(r0["ruleW"]))
        check(f"{tag}: vertical rule spans the row height", r0["ruleH"] >= r0["h"], f"{r0['ruleH']} vs {r0['h']}")
        check(f"{tag}: every date on one x", len({r["left"] for r in law["rows"]}) == 1,
              str({r["left"] for r in law["rows"]}))
        check(f"{tag}: every rule on one x", len({r["rule"] for r in law["rows"]}) == 1)
        check(f"{tag}: every amount on one right edge", len({r["amtRight"] for r in law["rows"]}) == 1,
              str({r["amtRight"] for r in law["rows"]}))
        check(f"{tag}: names never clipped", not any(r["nameClipped"] for r in law["rows"]))
        if len(law["rows"]) > 1:
            check(f"{tag}: rows do not overlap", all(
                law["rows"][i]["top"] >= law["rows"][i - 1]["top"] + law["rows"][i - 1]["h"]
                for i in range(1, len(law["rows"]))))
    check(f"{tag}: row heights uniform", len({r["h"] for r in law["rows"]}) == 1,
          str({r["h"] for r in law["rows"]}))
    if law["headerGaps"]:
        hg = min(law["headerGaps"])
        check(f"{tag}: group gapping — header→first row gap ({hg}px) > row gap",
              hg > (max(law["rowGaps"]) if law["rowGaps"] else 0),
              f"header {law['headerGaps']} rows {law['rowGaps']}")
        if law["rowGaps"]:
            check(f"{tag}: row gaps uniform and > 0", len(set(law["rowGaps"])) == 1 and min(law["rowGaps"]) > 0,
                  str(law["rowGaps"]))

    rc = page.evaluate(RECEIPT_JS)
    check(f"{tag}: receipts is ONE collapsed details", rc.get("summary", "").startswith("Receipts (")
          and rc.get("openByDefault") is False, str(rc.get("summary")))
    check(f"{tag}: every receipt is its own accordion, all closed at rest", rc.get("inner") == 6
          and rc.get("innerOpenByDefault") == 0, str(rc.get("inner")))
    check(f"{tag}: no receipt type badge", rc.get("badges") == 0, str(rc.get("badges")))
    heads = [s["head"] for s in rc.get("summaries", [])]
    check(f"{tag}: receipt rest line = date | head (no channel tail, one line)",
          len(heads) == 6 and all("through online" not in x and "IMPS/" not in x for x in heads),
          str(heads[:2]))
    check(f"{tag}: receipt summaries keep the date|name gap", all(s["gap"] >= 8 for s in rc.get("summaries", [])),
          str([s["gap"] for s in rc.get("summaries", [])][:3]))
    check(f"{tag}: opening one receipt hides the others", rc.get("oneATA") is True, str(rc.get("oneATA")))
    check(f"{tag}: opened receipt carries voucher + narration",
          rc.get("hasVoucher") and len(rc.get("bodyText", "")) > 40, str(rc.get("bodyText"))[:60])

    ov = page.evaluate(overflow_js())
    check(f"{tag}: no horizontal page overflow", ov["sw"] <= ov["cw"], str(ov))
    check(f"{tag}: nothing crosses the right edge", ov["worst"] <= 0.5, str(ov["worst"]))

    pairs = page.evaluate(CONTRAST_JS)
    bad = [p for p in pairs if p["ratio"] + 0.01 < p["need"]]
    check(f"{tag}: WCAG contrast {len(pairs) - len(bad)}/{len(pairs)} pairs", not bad,
          str([(p["t"], p["ratio"], p["need"]) for p in bad[:4]]))

    if arm == "dues":
        d = page.evaluate(DUES_JS)
        check(f"{tag}: dues hero is the first element", d["firstText"].startswith("Outstanding dues"),
              d["firstText"])
        check(f"{tag}: dues hero holds the loud number", d["dueText"].startswith("₹"), d["dueText"])
        check(f"{tag}: exactly one coloured object (the dues number)", len(d["coloured"]) == 1,
              str(d["coloured"]))
    ctx.close()


with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    for w, h in ((393, 851), (1280, 900)):
        for arm in ("dues", "clear"):
            print(f"── {arm} {w}x{h}")
            run(b, w, h, arm)
    b.close()

print(f"\n{'PASS' if not FAILS else 'FAIL'}: fees DUT — {len(FAILS)} failing")
sys.exit(1 if FAILS else 0)
