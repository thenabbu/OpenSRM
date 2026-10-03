"""Internal-marks tab DUT (server under test: AGENTS.md; default port 18180).

Layers, in order: neutral-colour rules (exactly ONE accent), uniform chips +
aligned dates, uniform row heights with top-pinned content, WCAG contrast (marks AND dashboard tabs),
then the tag round-trip (derived -> confirmed IE-2 -> persisted -> reset).
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-marks")
from _seed import seed, mint_token
from playwright.sync_api import sync_playwright

seed(with_payload=False)
from app.app import db
MARKS = [
    {"code": "21CSS201T", "title": "COMPUTER ORGANIZATION AND ARCHITECTURE",
     "components": [{"name": "FT-I", "entered": "04/Sep/2026", "scored": 4.5, "max": 5.0},
                    {"name": "FT-II", "entered": "09/Sep/2026", "scored": 11.7, "max": 15.0}],
     "scored_total": 16.2, "max_total": 20.0},
    {"code": "21MAB206T", "title": "NUMERICAL METHODS AND ANALYSIS",
     # dates deliberately NOT in name order: name sort must win over date sort
     "components": [{"name": "FT-I", "entered": "21/Sep/2026", "scored": 5.0, "max": 5.0},
                    {"name": "FT-II", "entered": "07/Sep/2026", "scored": 8.4, "max": 15.0}],
     "scored_total": 13.4, "max_total": 20.0},
    {"code": "21LEM201T", "title": "PROFESSIONAL ETHICS",
     "components": [{"name": "FML-I", "entered": "09/Sep/2026", "scored": 17.5, "max": 20.0}],
     "scored_total": 17.5, "max_total": 20.0},
    {"code": "21CSC203P", "title": "ADVANCED PROGRAMMING PRACTICE",
     "components": [{"name": "FP-I", "entered": "23/Sep/2026", "scored": 7.2, "max": 10.0}],
     "scored_total": 7.2, "max_total": 10.0},
]
c = db()
c.execute("UPDATE users SET marks_json=? WHERE netid='ng2776'", (json.dumps(MARKS),))
c.execute("DELETE FROM component_tags")
c.commit(); c.close()
TOK = mint_token()
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18180")
results = []

def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

JS_AUDIT = r"""() => {
  const out = {overflow: null, chips: [], dateGroups: {}, overlaps: [], status: [],
               accent: 0, contrast: [], pctTexts: [], cards: [], overall: null};
  out.overflow = document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth;
  const marks = document.getElementById('tab-marks');
  out.overall = /Overall internal marks/.test(marks.innerText);

  marks.querySelectorAll('span.bg-base-300.rounded-full').forEach(el => {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    out.chips.push({w: +r.width.toFixed(2), bg: cs.backgroundColor, bw: cs.borderWidth});
  });

  [...marks.querySelectorAll('.rounded-box.p-4')].forEach(card => {
    const cr = card.getBoundingClientRect();
    const dates = [...card.querySelectorAll('span')].filter(s =>
      /^\d{2} [A-Z][a-z]{2}$/.test((s.textContent || '').trim()) && s.getBoundingClientRect().width);
    if (dates.length) out.dateGroups[cr.left] = [...new Set(dates.map(d =>
      +(d.getBoundingClientRect().left - cr.left).toFixed(1)))];
    // uniform grid rows + top-pinned content: row geometry per card
    out.cards.push({t: +cr.top.toFixed(1), b: +cr.bottom.toFixed(1),
                    gap: +(card.firstElementChild.getBoundingClientRect().top - cr.top).toFixed(1)});
    // row overlap: chip < date < score < summary (and inside the nested IE row)
    card.querySelectorAll('.py-1 > .flex').forEach(row => {
      const parts = [...row.children].map(ch => {
        const r = ch.getBoundingClientRect();
        return {l: r.left, r: r.right, t: (ch.textContent || '').trim().slice(0, 8)};
      }).filter(p => p.r > p.l);
      for (let i = 1; i < parts.length; i++)
        if (parts[i].l < parts[i - 1].r - 0.5)
          out.overlaps.push(parts[i - 1].t + ' > ' + parts[i].t);
    });
  });

  // contrast sweep of whichever tabpanel is visible (oklch -> sRGB in JS)
  const parse = s => {
    s = s.trim();
    let m = s.match(/^rgba?\(([^)]+)\)$/);
    if (m) { const p = m[1].split(/[,\s\/]+/).filter(Boolean).map(Number);
             return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; }
    m = s.match(/^oklch\(\s*([\d.]+)%?\s+([\d.]+)\s+([-\d.]+)\s*(?:\/\s*([\d.]+)%?)?\)$/);
    if (m) {
      const L = +m[1] > 1 ? +m[1] / 100 : +m[1], C = +m[2], H = +m[3] * Math.PI / 180,
            A = m[4] ? +m[4] / 100 : 1, a = C * Math.cos(H), b = C * Math.sin(H);
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
    }
    m = s.match(/^#([0-9a-f]{3,8})$/i);
    if (m) { let h = m[1];
      if (h.length === 3) h = h.split('').map(x => x + x).join('');
      return {r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16),
              b: parseInt(h.slice(4, 6), 16), a: h.length >= 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1}; }
    return null;
  };
  const near = (c, t, tol) => c && Math.abs(c.r - t[0]) <= tol && Math.abs(c.g - t[1]) <= tol &&
                              Math.abs(c.b - t[2]) <= tol;
  const STATUS = [[229, 0, 6], [165, 180, 25], [208, 135, 0], [0, 130, 206]];  // error/warn/info hues
  marks.querySelectorAll('*').forEach(el => {
    const t = (el.textContent || '').trim();
    if (!t || el.children.length || !el.getBoundingClientRect().width) return;
    const col = parse(getComputedStyle(el).color);
    if (STATUS.some(h => near(col, h, 8))) out.status.push(t + '|' + getComputedStyle(el).color);
    if (near(col, [244, 48, 152], 8)) out.accent++;        // theme secondary (the one accent)
    if (/^\d+(\.\d+)?%$/.test(t)) out.pctTexts.push(t);
  });

  const over = (f, b) => ({r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a),
                           b: f.b * f.a + b.b * (1 - f.a), a: 1});
  const bgStack = el => { const st = []; let n = el;
    while (n) { const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) { st.push(c); if (c.a === 1) break; } n = n.parentElement; }
    let base = {r: 22, g: 22, b: 22, a: 1};               // page bg-base-100 #161616
    for (let i = st.length - 1; i >= 0; i--) base = over(st[i], base);
    return base; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 :
    Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const root = [...document.querySelectorAll('[data-tabpanel]')]
    .find(p => p.style.display !== 'none') || document.body;
  [...root.querySelectorAll('*')].forEach(el => {
    if (!el.getBoundingClientRect().width || el.children.length) return;
    const t = (el.textContent || '').trim();
    if (!t || !/[\p{L}\p{N}]/u.test(t)) return;           // skip icon glyphs / ·
    const cs = getComputedStyle(el), fg = parse(cs.color), bg = bgStack(el);
    if (!fg) return;
    const eff = over(fg, bg), L1 = lum(eff), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(cs.fontSize), wt = +cs.fontWeight || 400;
    const need = (size >= 24 || (size >= 18.66 && wt >= 700)) ? 3 : 4.5;
    if (ratio + 0.01 < need)
      out.contrast.push({t: t.slice(0, 28), cls: el.className.toString().slice(0, 60),
                         ratio: +ratio.toFixed(2), need, fg: cs.color, size});
  });
  return out;
}"""

with sync_playwright() as p:
    b = p.chromium.launch(args=["--font-render-hinting=none", "--force-color-profile=srgb"])
    for label, vp in (("393x851", {"width": 393, "height": 851}),
                      ("1280x900", {"width": 1280, "height": 900})):
        ctx = b.new_context(viewport=vp, device_scale_factor=2)
        ctx.add_cookies([{"name": "srm_session", "value": TOK, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        tag = f"[{label}] "
        page.goto(f"{BASE}/#marks", wait_until="networkidle")
        page.wait_for_timeout(800)
        a = page.evaluate(JS_AUDIT)
        check(tag + "no horizontal page overflow", a["overflow"] <= 0, str(a["overflow"]))
        check(tag + "overall strip removed", not a["overall"])
        check(tag + "subject % count == 4 (no per-component %)",
              len(a["pctTexts"]) == 4, str(a["pctTexts"]))
        check(tag + "no status-coloured text (success/warning/error/info)",
              not a["status"], str(a["status"][:4]))
        check(tag + "exactly one accent (the outlier)", a["accent"] == 1, str(a["accent"]))
        ws = [ch["w"] for ch in a["chips"]]
        check(tag + f"chips uniform width 56px ({len(ws)} chips)",
              ws and all(abs(w - 56) <= 0.5 for w in ws), str(sorted(set(ws))))
        check(tag + "chips solid fill, border-width 0",
              a["chips"] and all(ch["bg"] not in ("rgba(0, 0, 0, 0)", "transparent")
                                 and ch["bw"] == "0px" for ch in a["chips"]),
              str(a["chips"][0] if a["chips"] else None))
        bad = {k: v for k, v in a["dateGroups"].items() if len(v) > 1}
        check(tag + "dates share one x per card (badge width never shifts them)",
              a["dateGroups"] and not bad, str(bad or a["dateGroups"]))
        check(tag + "no overlapping elements inside rows", not a["overlaps"],
              str(a["overlaps"][:4]))
        rows = {}
        for c in a["cards"]:
            rows.setdefault(c["t"], []).append(c["b"])
        ragged = {t: bs for t, bs in rows.items() if len(set(bs)) > 1}
        check(tag + "same-row cards share one height (uniform)",
              a["cards"] and not ragged, str(ragged or a["cards"]))
        gaps = [c["gap"] for c in a["cards"]]
        check(tag + "content pinned to card top (gap == p-4)",
              gaps and all(abs(g - 16) <= 1.5 for g in gaps), str(gaps))
        tips = page.evaluate("""() => [...document.querySelectorAll('#tab-marks summary')].map(s =>
            ({tip: s.dataset.tip || '', cls: /tooltip/.test(s.className)}))""")
        check(tag + "every edit button carries a daisyUI tooltip",
              tips and all(x["tip"] and x["cls"] for x in tips), str(tips[:2]))
        page.hover("#tab-marks .py-1 summary >> nth=0")
        page.wait_for_timeout(350)
        t = page.evaluate("""() => { const s = document.querySelector('#tab-marks .py-1 summary');
            const b = getComputedStyle(s, '::before'), a = getComputedStyle(s, '::after');
            return {text: b.content, textOpacity: b.opacity, tailOpacity: a.opacity,
                    display: getComputedStyle(s).display}; }""")
        # daisyUI 5.7: text lives in ::before (attr(data-tip)), ::after is only the tail
        check(tag + "tooltip reveals on hover (before-text + opacity)",
              "IE-1/IE-2" in t["text"] and float(t["textOpacity"]) > 0.5
              and float(t["tailOpacity"]) > 0.5, str(t))
        page.mouse.move(0, 0)
        check(tag + "marks tab contrast: 0 fails (AA 4.5 / 3 large)",
              not a["contrast"], json.dumps(a["contrast"][:4]))
        ie = page.evaluate("""() => [...document.querySelectorAll('#tab-marks .py-1')]
          .filter(r => /IE-/.test(r.innerText))
          .map(r => { const main = r.querySelector(':scope > .flex');
            const nested = [...r.children].find(k => /^IE-/.test((k.textContent||'').trim()));
            const chip = e => e.querySelector('.bg-base-300').getBoundingClientRect().left;
            return {indent: +(chip(nested) - chip(main)).toFixed(1),
                    text: nested.innerText.replace(/\\s+/g, ' ').trim()}; })""")
        check(tag + "IE rows nested + indented under their component",
              len(ie) == 3 and all(x["indent"] >= 20 for x in ie), json.dumps(ie))
        check(tag + "IE-1 converts 11.70/15 -> 39.00/50",
              any("39.00/50" in x["text"] for x in ie), json.dumps(ie))
        names = page.evaluate("""() => [...document.querySelectorAll('#tab-marks .rounded-box.p-4')]
          .map(c => [...c.querySelectorAll('.py-1 > .flex:first-child span:first-child')].map(s => s.textContent.trim()))""")
        check(tag + "components sorted by name, not date (FT-I before FT-II)",
              all(n == sorted(n) for n in names), str(names))
        if label == "393x851":
            dock = page.evaluate("""() => ({dockH: document.querySelector('.dock').getBoundingClientRect().height,
                 padB: parseFloat(getComputedStyle(document.querySelector('main')).paddingBottom)})""")
            check(tag + "main clears the fixed dock (pb-24 >= dock)",
                  dock["padB"] >= dock["dockH"], str(dock))
        # dashboard tab: glance redesign + its own contrast sweep
        page.click('[data-tab="dashboard"]:visible')
        page.wait_for_timeout(500)
        d = page.evaluate(JS_AUDIT)
        check(tag + "dashboard glance: no overall number, no accent, contrast clean",
              not d["overall"] and d["accent"] == 0 and not d["contrast"],
              json.dumps({"overall": d["overall"], "accent": d["accent"],
                          "contrast": d["contrast"][:3]}))
        g = page.evaluate("""() => {
          const panels = [...document.querySelectorAll('[role=tabpanel]')].filter(p => p.getBoundingClientRect().width);
          const hdr = panels.flatMap(p => [...p.querySelectorAll('div')])
            .find(d => !d.children.length && d.textContent.trim().toLowerCase() === 'internal marks');
          if (!hdr) return null;
          const chips = [...hdr.parentElement.querySelectorAll('.badge')].map(b => b.textContent.trim());
          return {chips: chips, pct: chips.filter(c => /%/.test(c))}; }""")
        check(tag + "glance chips = marks/max as synced, no %",
              g and g["chips"] and not g["pct"] and all("/" in c for c in g["chips"]),
              json.dumps(g))
        # ── tag round-trip (marks tab) ─────────────────────────────────
        page.click('[data-tab="marks"]:visible')
        page.wait_for_timeout(400)
        page.click("#tab-marks .py-1 summary >> nth=1")   # FT-II (derived IE-1)
        page.wait_for_timeout(300)
        form = page.evaluate("""() => { const f = document.querySelector('#tab-marks details[open] form');
          if (!f) return null; const r = f.getBoundingClientRect();
          return {l: +r.left.toFixed(1), r: +r.right.toFixed(1), vw: innerWidth,
                  role: f.querySelector('[name=role]').value,
                  note: f.querySelector('p').textContent.trim()}; }""")
        check(tag + "tag panel opens fully inside the viewport",
              form and form["l"] >= 0 and form["r"] <= form["vw"], str(form))
        check(tag + "select preselects the derived role", form and form["role"] == "IE-1", str(form))
        check(tag + "panel states derived vs confirmed",
              form and "not confirmed yet" in form["note"], str(form))
        # outside-click light dismiss — Save must never be the only way out
        page.click("#tab-marks h3 >> nth=0")
        page.wait_for_timeout(150)
        check(tag + "panel closes on outside click",
              page.evaluate("() => !document.querySelector('#tab-marks details[open]')"),
              "details still open")
        page.click("#tab-marks .py-1 summary >> nth=1")
        page.wait_for_timeout(250)
        page.select_option("#tab-marks details[open] select[name=role]", "IE-2")
        page.click("#tab-marks details[open] button:has-text('Save')")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        check(tag + "save redirects back to the marks tab",
              page.evaluate("() => location.hash") == "#marks", page.url)
        after = page.evaluate("""() => [...document.querySelectorAll('#tab-marks .py-1')]
          .filter(r => /^FT-II/.test((r.querySelector('.bg-base-300') || {}).textContent || ''))
          .map(r => r.innerText.replace(/\\s+/g, ' ').trim())""")
        check(tag + "confirmed IE-2 renders as 46.80/60", any("46.80/60" in t for t in after),
              str(after))
        c = db()
        row = [(r[0], r[1], r[2]) for r in
               c.execute("SELECT role, raw_max, scaled_max FROM component_tags").fetchall()]
        c.close()
        check(tag + "tag persisted class-scoped (role / raw 60 / scaled 15)",
              row == [("IE-2", 60.0, 15.0)], str(row))
        c = db(); c.execute("DELETE FROM component_tags"); c.commit(); c.close()
        ctx.close()
    b.close()

fails = [n for n, ok in results if not ok]
print(f"\nTOTAL: {len(results)} checks | PASS {len(results)-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
