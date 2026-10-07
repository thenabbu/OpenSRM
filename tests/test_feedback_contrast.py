#!/usr/bin/env python3
"""Contrast probe: Teachers card text/bg pairs (WCAG 4.5:1 body, 3:1 large).

oklch/oklab->sRGB parser + bg-stack blending cribbed from tests/test_marks_dut.py
(daisyUI 5 exposes OKLCH computed colors; rgb()-only parsers measure nothing).
daisyUI 5.7 emits opacity-modified tokens as oklab(L a b / alpha) with the
alpha as a DECIMAL number (0.5 = 50%) — dividing by 100 unconditionally turns
every /60 token into 0.006 alpha and the whole card reads as 1:1 contrast.
"""
import os
import sys

BASE = os.environ.get("DUT_BASE")
DATA_DIR = os.environ.get("DATA_DIR")
if not BASE or not DATA_DIR:
    sys.exit("FAIL: pass DATA_DIR + DUT_BASE inline")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

FACULTY = {
    "DATA STRUCTURES AND ALGORITHMS": {
        "subject_id": "90001",
        "staff": [["50001", "Dr.Test Alpha-Theory"], ["50002", "Dr.Test Beta-Theory"]]},
    "PROFESSIONAL ETHICS": {"subject_id": "90002", "staff": [["50003", "Dr.Test Gamma-Practical"]]},
}
COURSES = [{"code": "21CSC201J", "name": "DATA STRUCTURES AND ALGORITHMS", "credits": 4},
           {"code": "21LEM201T", "name": "PROFESSIONAL ETHICS", "credits": 0}]
PERSONAL = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
            "Batch": "2025", "Semester": "III SEMESTER", "Section": "A",
            "Student Name": "Test Student", "Register No.": "RA2500000000"}

import json
import time
from app import app as A
now = int(time.time())
c = A.db()
c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
             attendance_json, faculty_map_json, last_fetch) VALUES(?,?,?,?,?,?)""",
          ("ng2776", "x", json.dumps(PERSONAL),
           json.dumps({"courses": COURSES, "monthly": [], "period": None, "daily_absent": {}}),
           json.dumps(FACULTY), now))
c.commit(); c.close()

from playwright.sync_api import sync_playwright
from app.app import make_session_token

JS = """
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
    s = s.trim();
    let m = s.match(/^rgba?\\(([^)]+)\\)$/);
    if (m) { const p = m[1].split(/[,\\s\\/]+/).filter(Boolean).map(Number);
             return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; }
    m = s.match(/^oklch\\(\\s*([\\d.]+)%?\\s+([\\d.]+)\\s+([-\\d.]+)\\s*(?:\\/\\s*([\\d.]+%?))?\\)$/);
    if (m) {
      const L = +m[1] > 1 ? +m[1] / 100 : +m[1], C = +m[2], H = +m[3] * Math.PI / 180,
            A = m[4] ? alpha(m[4]) : 1, a = C * Math.cos(H), b = C * Math.sin(H);
      return lab2rgb(L, a, b, A);
    }
    m = s.match(/^oklab\\(\\s*([\\d.]+)%?\\s+([-\\d.]+)\\s+([-\\d.]+)\\s*(?:\\/\\s*([\\d.]+%?))?\\)$/);
    if (m) {
      const L = +m[1] > 1 ? +m[1] / 100 : +m[1];
      return lab2rgb(L, +m[2], +m[3], m[4] ? alpha(m[4]) : 1);
    }
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
  const card = [...document.querySelectorAll('div')].find(d =>
    d.className.includes('rounded-box') && d.textContent.includes('From the mid-sem feedback form'));
  if (!card) return {error: 'card not found'};
  const out = [];
  const seen = new Set();
  [...card.querySelectorAll('*')].forEach(el => {
    if (!el.getBoundingClientRect().width) return;
    // direct text nodes only (nested spans measured separately)
    const t = [...el.childNodes].filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim()).join(' ').trim();
    if (!t || !/[\\p{L}\\p{N}]/u.test(t)) return;
    const cs = getComputedStyle(el), fg = parse(cs.color), bg = bgStack(el);
    if (!fg) return;
    const eff = over(fg, bg), L1 = lum(eff), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(cs.fontSize), wt = +cs.fontWeight || 400;
    const need = (size >= 24 || (size >= 18.66 && wt >= 700)) ? 3 : 4.5;
    const key = (el.className || '') + '|' + Math.round(ratio * 10);
    if (seen.has(key)) return;
    seen.add(key);
    out.push({t: t.slice(0, 30), ratio: +ratio.toFixed(2), need, cls: String(el.className).slice(0, 50)});
  });
  return out;
}
"""

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "srm_session", "value": make_session_token("ng2776"), "url": BASE}])
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    pairs = page.evaluate(JS)
    browser.close()

if "error" in pairs:
    print("FAIL:", pairs["error"]); sys.exit(1)
fails = 0
for p in pairs:
    ok = p["ratio"] + 0.01 >= p["need"]
    if not ok:
        fails += 1
    print(f"  {'ok ' if ok else 'FAIL'} {p['ratio']:5.2f}:1 (need {p['need']}) {p['t']!r} [{p['cls']}]")
print(f"\n{len(pairs) - fails}/{len(pairs)} pairs pass WCAG")
sys.exit(1 if fails else 0)
