"""DUT: attendance tab view toggle + merged absences card (v1.13.0).
Boots its own server via run pattern of test_sw: DATA_DIR decides DB.
Usage: DATA_DIR=/tmp/x DUT_BASE=http://127.0.0.1:P python tests/test_att_dut.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18187")

FAILS = []
PASSES = []


def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  <- {detail}" if not cond and detail else ""))


def main():
    from playwright.sync_api import sync_playwright
    from tests._seed import mint_token
    tok = mint_token()

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 393, "height": 851}, device_scale_factor=2.75,
                            service_workers="block")
        ctx.add_cookies([{"name": "srm_session", "value": tok, "url": BASE}])
        page = ctx.new_page()
        page.goto(BASE + "/#attendance", wait_until="networkidle")
        page.reload()
        page.evaluate("localStorage.removeItem('attView')")
        page.reload()

        # 1) toggle exists next to the Subjects header
        r = page.evaluate("""() => ({
          h: document.querySelector('#tab-attendance h1')?.textContent.trim(),
          g: !!document.getElementById('att-view-graph'),
          t: !!document.getElementById('att-view-table'),
          graphVisible: getComputedStyle(document.getElementById('att-graph')).display,
          tableHidden: document.getElementById('att-table').hidden})""")
        check("toggle buttons present in Subjects row", r["g"] and r["t"] and r["h"] == "Subjects", str(r))
        check("graph view default", r["graphVisible"] != "none" and r["tableHidden"], str(r))

        # 2) table view renders the five columns + margin colors
        page.click('#att-view-table')
        r = page.evaluate("""() => {
          const ths = [...document.querySelectorAll('.att-table th')].map(t => t.textContent.trim());
          const rows = document.querySelectorAll('.att-table tbody tr').length;
          const pos = getComputedStyle(document.querySelector('.att-pos')).color;
          const neg = getComputedStyle(document.querySelector('.att-neg')).color;
          return {ths, rows, pos, neg, graphGone: document.getElementById('att-graph').hidden};
        }""")
        check("table columns = code/subject/total/attended/margin",
              r["ths"] == ["Code", "Subject", "Total", "Attended", "Margin"], str(r["ths"]))
        check("table has rows + graph hidden", r["rows"] > 0 and r["graphGone"])
        check("margin colors differ (pos vs neg)", r["pos"] != r["neg"], str(r))

        # 3) persistence
        page.reload()
        r = page.evaluate("""() => getComputedStyle(document.getElementById('att-table')).display""")
        check("table view persists across reload", r != "none", r)
        page.click('#att-view-graph')

        # 4) graph view: numbers row above meter, percentage row below
        r = page.evaluate("""() => {
          const row = document.querySelector('.mrow');
          const kids = [...row.children].map(c => c.className.split(' ')[0]);
          return {kids};
        }""")
        check("row order: mtop, pnums, meter, pcts[, pconn]",
              r["kids"][:4] == ["mtop", "pnums", "meter", "pcts"], str(r["kids"]))

        # 5) zero same-row label overlaps (both rows, both viewports checked at 393 here)
        r = page.evaluate("""() => {
          const bad = [];
          document.querySelectorAll('.mrow').forEach(row => {
            ['.pn', '.pct'].forEach(sel => {
              const labs = [];
              row.querySelectorAll(sel).forEach(el => {
                if (getComputedStyle(el).visibility === 'hidden') return;
                const b = el.getBoundingClientRect();
                labs.push({t: el.textContent.trim(), x1: b.x, x2: b.x + b.width});
              });
              for (let i=0;i<labs.length;i++) for (let j=i+1;j<labs.length;j++) {
                const a=labs[i], b2=labs[j];
                if (a.x1 < b2.x2 - 0.5 && b2.x1 < a.x2 - 0.5) bad.push(a.t+'~'+b2.t);
              }
            });
          });
          return bad;
        }""")
        check("zero label overlaps at 393", r == [], str(r))

        # 6) absences card: month blocks = bar + chips; no <details> Monthly breakdown
        r = page.evaluate("""() => {
          const card = document.querySelector('.att-abs-card');
          const months = card ? card.querySelectorAll('.att-month').length : 0;
          const chips = card ? card.querySelectorAll('.badge').length : 0;
          const bars = card ? card.querySelectorAll('progress').length : 0;
          const details = [...document.querySelectorAll('#tab-attendance details')]
            .filter(d => d.textContent.includes('Monthly breakdown')).length;
          return {months, chips, bars, details};
        }""")
        check("absences: month blocks with bar + chips", r["months"] >= 4 and r["bars"] == r["months"]
              and r["chips"] >= 9, str(r))
        check("no standalone Monthly breakdown <details>", r["details"] == 0, str(r))

        ctx.close()
        b.close()
    print()
    print(f"{len(PASSES)}/{len(PASSES)+len(FAILS)} PASS")
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)


if __name__ == "__main__":
    main()
