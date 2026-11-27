#!/usr/bin/env python3
"""Fees tab DUT: layout law + contrast + density, measured on the real page.

Law under test (the fees redesign):
  - A charge is a NAMED card: feetype + the portal's cycle on line 1, the
    22px rupee amount + its deadline + the days-left word on line 2, and the
    late-fee delta under it. The card states the deadline pair the SCOPE row
    actually ships, and "overdue"/"late fee applied" when it is past.
  - The "Owed" total line exists ONLY for 2+ charges: with one charge it is
    the same number twice, 40px apart.
  - Paid rows: date (leftmost) | name | amount (rightmost) on ONE line box,
    THREE tracks — the old decorative 1px rule column is gone (it measured as
    a disconnected divider and ate a phone row's width). Amounts right-align
    on one x, dates on one x, no horizontal borders inside a group, and the
    space under a year header is strictly larger than the row gap.
  - Year headers exist only with 2+ years; one year moves onto the "Paid"
    heading as a label.
  - Zero dues: one plain "Nothing due." sentence, then the Paid header.
  - Receipts: ONE collapsed <details> ("Payment receipts (6)"); inside it each
    receipt is its own collapsed <details>; opening one reveals voucher +
    narration only for that receipt.
  - WCAG at 393x851 AND 1280x900: every text node on its real bg.
  - Geometry at both: no h-overflow, no overlap, positive gaps.

Needs DATA_DIR + DUT_BASE inline; self-seeds every arm (see tests/e2e/_fees_seed.py).
Set FEE_SHOTS=<dir> to also save a full-page PNG per arm/resolution.
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
from playwright.sync_api import TimeoutError as PWTimeout  # noqa: E402
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

# ── paid rows: three tracks, no rule column, uniform gap ---------------------
LAW_JS = """
() => {
  const r = e => e.getBoundingClientRect();
  const panel = document.querySelector('#tab-fees');
  const rows = [...panel.querySelectorAll('section div.grid')];
  const out = {rows: [], headerGaps: [], rowGaps: [], hborders: 0, vborders: 0,
               total: rows.length, yearHeaders: panel.querySelectorAll('section h2').length};
  rows.forEach(row => {
    const [d, n, a] = row.children;
    const rd = r(d), rn = r(n), ra = r(a);
    out.rows.push({left: +rd.left.toFixed(2), name: +rn.left.toFixed(2),
                   amtRight: +ra.right.toFixed(2), top: +rd.top.toFixed(2),
                   h: +rd.height.toFixed(2), tracks: row.children.length,
                   nameClipped: n.scrollWidth > n.clientWidth + 1});
    [row, d, n, a].forEach(el => {
      const cs = getComputedStyle(el);
      if (parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderBottomWidth) > 0) out.hborders++;
      if (parseFloat(cs.borderLeftWidth) > 0 || parseFloat(cs.borderRightWidth) > 0) out.vborders++;
    });
  });
  // group gapping: year-header bottom -> first row top, vs row -> row
  [...panel.querySelectorAll('section')].forEach(s => {
    const head = s.querySelector('h2');
    if (!head) return;
    const first = s.querySelector('div.grid');
    if (!first) return;
    out.headerGaps.push(+(r(first).top - r(head).bottom).toFixed(2));
    const cells = [...s.querySelectorAll('div.grid')].map(r);
    for (let i = 1; i < cells.length; i++) out.rowGaps.push(+(cells[i].top - cells[i - 1].bottom).toFixed(2));
  });
  return out;
}
"""

# ── charge cards: name, amount+deadline+days word, late-fee line -------------
CARDS_JS = """
() => {
  const panel = document.querySelector('#tab-fees');
  const cards = [...panel.querySelectorAll('[data-charge]')];
  const sum = [...panel.children].find(c => /^Owed/.test(c.textContent.trim()));
  return {
    n: cards.length,
    sumText: sum ? sum.textContent.replace(/\\s+/g, ' ').trim() : '',
    sumLevel: sum ? sum.querySelector('.font-mono').className : '',
    cards: cards.map(c => ({
      text: c.textContent.replace(/\\s+/g, ' ').trim(),
      head: c.children[0].children[0].textContent.trim(),
      amt: c.querySelector('.font-mono.font-bold').textContent.trim(),
      amtSize: parseFloat(getComputedStyle(c.querySelector('.font-mono.font-bold')).fontSize),
      amtLevel: c.querySelector('.font-mono.font-bold').className,
      headSize: parseFloat(getComputedStyle(c.children[0].children[0]).fontSize),
    })),
  };
}
"""

# ── receipts: structure + per-receipt accordion behaviour --------------------
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
    return {date: kids[0].textContent.trim(), head: kids[1].textContent.trim(),
            amt: kids[2].textContent.trim(), tracks: kids.length,
            gap: +(kids[1].getBoundingClientRect().left
                 - kids[0].getBoundingClientRect().right).toFixed(1),
            clipped: kids[1].scrollWidth > kids[1].clientWidth + 1};
  });
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

# ── nothing-owed arm: one sentence, then the Paid header --------------------
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


def settle(page, tag):
    """Wait for the fees document to be PAINTED, not for a guessed delay.

    `#tab-fees-tab` is an <a href="/fees">, so the click is a real navigation.
    A bare `wait_for_timeout` raced the stylesheet: when it landed first the law
    was measured on a parsed-but-unstyled document. `#tab-fees` carries
    `max-w-3xl mx-auto`, so its computed maxWidth only becomes a pixel value
    once Tailwind has applied — that is the gate.
    """
    page.wait_for_selector("#tab-fees", state="attached", timeout=15000)
    try:
        page.wait_for_function(
            "() => getComputedStyle(document.querySelector('#tab-fees')).maxWidth !== 'none'",
            timeout=15000)
    except PWTimeout:
        check(f"{tag}: fees stylesheet applied", False, "max-w-3xl never resolved — CSS did not apply")
        return False
    check(f"{tag}: fees stylesheet applied", True)
    return True


def overflow_js():
    return ("() => ({sw: document.documentElement.scrollWidth, "
            "cw: document.documentElement.clientWidth, "
            "worst: Math.max(0, ...[...document.querySelectorAll('#tab-fees *')]"
            ".map(e => e.getBoundingClientRect().right - document.documentElement.clientWidth))})")


SHOTS = os.environ.get("FEE_SHOTS", "")


def shoot(page, arm, w, h):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    page.screenshot(path=os.path.join(SHOTS, f"{arm}-{w}x{h}.png"), full_page=True)


def run(browser, w, h, arm):
    _fees_seed.seed(arm)
    ctx = browser.new_context(viewport={"width": w, "height": h})
    ctx.add_cookies([{"name": "srm_session", "value": make_session_token("zz9999"), "url": BASE}])
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    tag = f"{arm} {w}x{h}"
    with page.expect_navigation():
        page.evaluate("() => document.querySelector('#tab-fees-tab').click()")
    if not settle(page, tag):
        ctx.close()
        return

    if arm == "clear":
        c = page.evaluate(CLEAR_JS)
        check(f"{tag}: no all-clear widget anywhere", not c["hasAllClear"], c["txt"][:80])
        check(f"{tag}: one plain 'Nothing due.' sentence first",
              c["firstTag"] == "P" and c["firstText"] == "Nothing due.", c["firstText"])
        check(f"{tag}: paid groups render", c["stands"] >= 1, str(c["stands"]))

    law = page.evaluate(LAW_JS)
    check(f"{tag}: paid rows present", law["total"] >= 3, str(law["total"]))
    check(f"{tag}: paid rows are THREE tracks (date | name | amount)",
          all(r["tracks"] == 3 for r in law["rows"]), str({r["tracks"] for r in law["rows"]}))
    check(f"{tag}: no horizontal dividers on paid rows", law["hborders"] == 0,
          f"{law['hborders']} border edges")
    check(f"{tag}: the decorative rule column is gone", law["vborders"] == 0,
          f"{law['vborders']} vertical border edges")
    if law["rows"]:
        check(f"{tag}: every date on one x", len({r["left"] for r in law["rows"]}) == 1,
              str({r["left"] for r in law["rows"]}))
        check(f"{tag}: every name on one x", len({r["name"] for r in law["rows"]}) == 1,
              str({r["name"] for r in law["rows"]}))
        check(f"{tag}: every amount on one right edge",
              len({r["amtRight"] for r in law["rows"]}) == 1, str({r["amtRight"] for r in law["rows"]}))
        check(f"{tag}: names never clipped", not any(r["nameClipped"] for r in law["rows"]),
              str([r for r in law["rows"] if r["nameClipped"]]))
        check(f"{tag}: row heights uniform", len({r["h"] for r in law["rows"]}) == 1,
              str({r["h"] for r in law["rows"]}))
        if len(law["rows"]) > 1:
            check(f"{tag}: rows do not overlap", all(
                law["rows"][i]["top"] >= law["rows"][i - 1]["top"] + law["rows"][i - 1]["h"]
                for i in range(1, len(law["rows"]))))
    if law["headerGaps"]:
        hg = min(law["headerGaps"])
        check(f"{tag}: group gapping — header->row gap ({hg}px) > row gap",
              hg > (max(law["rowGaps"]) if law["rowGaps"] else 0),
              f"header {law['headerGaps']} rows {law['rowGaps']}")
        if law["rowGaps"]:
            check(f"{tag}: row gaps uniform and > 0",
                  len(set(law["rowGaps"])) == 1 and min(law["rowGaps"]) > 0, str(law["rowGaps"]))

    cards = page.evaluate(CARDS_JS)
    # the sum line only exists to sum something: 2+ charges, or it is a dup
    check(f"{tag}: 'Owed' total line only with 2+ charges",
          bool(cards["sumText"]) == (cards["n"] >= 2),
          f"{cards['n']} charges, sum line {cards['sumText']!r}")
    for c in cards["cards"]:
        check(f"{tag}: charge {c['head']!r} prints its amount at the 22px hero step",
              c["amtSize"] == 22 and c["amt"].startswith("₹"), f"{c['amtSize']}px {c['amt']}")
        check(f"{tag}: charge {c['head']!r} names the charge at 14px", c["headSize"] == 14,
              f"{c['headSize']}px")

    if arm == "live":
        c = cards["cards"][0]["text"]
        check(f"{tag}: charge is NAMED with a date-like cycle", "Exam Fees" in c and "Nov 2026" in c, c)
        check(f"{tag}: charge states the cheap deadline", "by 5 Dec 2026" in c, c)
        check(f"{tag}: charge states the days left", "days left" in c, c)
        check(f"{tag}: charge states the late-fee DELTA, not the 4,150 total",
              "Late fee ₹1,000 from 6 Dec 2026" in c and "4,150" not in c, c)
        check(f"{tag}: no duplicate total above one charge", cards["sumText"] == "", cards["sumText"])

    if arm == "overdue":
        c = cards["cards"][0]["text"]
        check(f"{tag}: overdue charge says 'was due'", "was due 22 Nov 2026" in c, c)
        check(f"{tag}: overdue charge says 'overdue' in words", "overdue" in c, c)
        check(f"{tag}: applied late fee is named", "Late fee ₹1,000 applied" in c, c)
        check(f"{tag}: overdue amount carries the error colour",
              "text-error" in cards["cards"][0]["amtLevel"], cards["cards"][0]["amtLevel"])

    if arm == "multi":
        check(f"{tag}: two charges, both named", cards["n"] == 2, str(cards["n"]))
        check(f"{tag}: the sum line totals both (3,150 + 1,00,000)",
              "₹1,03,150" in cards["sumText"], cards["sumText"])
        check(f"{tag}: a dateless charge says so instead of inventing a date",
              any("no due date from SRM yet" in c["text"] for c in cards["cards"]),
              str([c["text"][:40] for c in cards["cards"]]))
        check(f"{tag}: two years get their own header rows", law["yearHeaders"] == 2,
              str(law["yearHeaders"]))

    if arm in ("live", "overdue", "clear", "exam"):
        check(f"{tag}: a single year is a label, not a header row",
              law["yearHeaders"] == 0, str(law["yearHeaders"]))

    rc = page.evaluate(RECEIPT_JS)
    check(f"{tag}: receipts is ONE collapsed details",
          rc.get("summary", "").startswith("Payment receipts (")
          and rc.get("openByDefault") is False, str(rc.get("summary")))
    check(f"{tag}: every receipt is its own accordion, all closed at rest",
          rc.get("inner") == 6 and rc.get("innerOpenByDefault") == 0, str(rc.get("inner")))
    check(f"{tag}: no receipt type badge", rc.get("badges") == 0, str(rc.get("badges")))
    sums = rc.get("summaries", [])
    check(f"{tag}: receipt rest line is three tracks", all(s["tracks"] == 3 for s in sums),
          str({s["tracks"] for s in sums}))
    heads = [s["head"] for s in sums]
    check(f"{tag}: receipt head is one short line, no channel tail",
          len(heads) == 6 and all(len(x) <= 44 and "through online" not in x
                                  and "IMPS/" not in x for x in heads), str(heads[:2]))
    check(f"{tag}: receipt summaries keep the date|name gap",
          all(s["gap"] >= 8 for s in sums), str([s["gap"] for s in sums][:3]))
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

    if arm == "exam":
        # the real 2026-11-04 shape: the fee rows all say paid==total, so the
        # charge card can ONLY come from getStudentExamFeesDetails
        c = cards["cards"][0]
        check(f"{tag}: the charge comes from the exam-fee op, not the paid row",
              c["amt"] == "₹3,150" and c["head"] == "Exam fee", f"{c['head']} {c['amt']}")

    shoot(page, arm, w, h)
    ctx.close()


with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    for w, h in ((393, 851), (1280, 900)):
        for arm in ("live", "overdue", "multi", "clear", "exam"):
            print(f"── {arm} {w}x{h}")
            run(b, w, h, arm)
    b.close()

print(f"\n{'PASS' if not FAILS else 'FAIL'}: fees DUT — {len(FAILS)} failing")
sys.exit(1 if FAILS else 0)
