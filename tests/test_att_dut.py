"""DUT: attendance tab view toggle + merged absences card (v1.15.0).

Seeds attendance in the SAME DB the gunicorn under test uses (DATA_DIR decides
both). Payload mirrors the real portal shape: 9-char codes (21CSC201J), ALL-CAPS
descriptions, plain-string hours ("46"), a CL / CLASS IN CHARGE junk row,
monthly "MMM / YYYY", daily rows DD-MM-YYYY {date, hours} — values fabricated.
Usage: DATA_DIR=/tmp/x DUT_BASE=http://127.0.0.1:P python tests/test_att_dut.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18187")

FAILS = []
PASSES = []


def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  <- {detail}" if not cond and detail else ""))


def main():
    from playwright.sync_api import sync_playwright

    from tests._seed import mint_token, seed
    seed()
    # real portal shape (code 9ch / ALL CAPS / string hours / CL junk row / MMM YYYY months)
    attendance = {"courses": [
        {"code": "21CSC201J", "description": "DATA STRUCTURES AND ALGORITHMS", "max_hours": "46", "attended": "45", "absent": "1"},
        {"code": "21CSC202J", "description": "OPERATING SYSTEMS", "max_hours": "44", "attended": "39", "absent": "5"},
        {"code": "21CSC203P", "description": "ADVANCED PROGRAMMING PRACTICE", "max_hours": "55", "attended": "30", "absent": "25"},
        {"code": "21CSS201T", "description": "COMPUTER ORGANIZATION AND ARCHITECTURE", "max_hours": "45", "attended": "43", "absent": "2"},
        {"code": "21DCS201P", "description": "DESIGN THINKING AND METHODOLOGY", "max_hours": "30", "attended": "26", "absent": "4"},
        {"code": "21LEM201T", "description": "PROFESSIONAL ETHICS", "max_hours": "11", "attended": "10", "absent": "1"},
        {"code": "21MAB206T", "description": "NUMERICAL METHODS AND ANALYSIS", "max_hours": "44", "attended": "38", "absent": "6"},
        {"code": "CL", "description": "CLASS IN CHARGE", "max_hours": "4", "attended": "2", "absent": "2"},
    ],
        "period": {"from": "20/Jul/2026", "to": "07/Oct/2026"},
        "monthly": [
            {"month": "JUL / 2026", "present": "53", "absent": "1", "od_present": "0", "od_absent": "0", "ml": "0"},
            {"month": "AUG / 2026", "present": "81", "absent": "7", "od_present": "0", "od_absent": "0", "ml": "0"},
            {"month": "SEP / 2026", "present": "101", "absent": "12", "od_present": "0", "od_absent": "0", "ml": "0"},
            {"month": "OCT / 2026", "present": "19", "absent": "5", "od_present": "0", "od_absent": "0", "ml": "0"}],
        "daily_absent": {
            "JUL / 2026": [{"date": "21-07-2026", "hours": "1"}],
            "AUG / 2026": [{"date": "17-08-2026", "hours": "1"}, {"date": "18-08-2026", "hours": "1"}, {"date": "22-08-2026", "hours": "1"}],
            "SEP / 2026": [{"date": "03-09-2026", "hours": "1"}, {"date": "10-09-2026", "hours": "1"}, {"date": "24-09-2026", "hours": "2"}, {"date": "29-09-2026", "hours": "1"}],
            "OCT / 2026": [{"date": "01-10-2026", "hours": "1"}, {"date": "06-10-2026", "hours": "2"}]}}
    from app import app as A
    c = A.db()
    c.execute("UPDATE users SET attendance_json=?, last_fetch=? WHERE netid='ng2776'",
              (json.dumps(attendance), int(time.time())))
    c.commit(); c.close()
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

        # 7) portal's CL / CLASS IN CHARGE junk row is filtered from both views
        r = page.evaluate("""() => {
          const names = [...document.querySelectorAll('.mrow .mname')].map(e => e.textContent.trim());
          const codes = [...document.querySelectorAll('.att-table tbody tr td:first-child')].map(e => e.textContent.trim());
          return {names, codes, meters: names.length, rows: codes.length};
        }""")
        junk_names = [n for n in r["names"] if "CLASS IN CHARGE" in n.upper()]
        junk_codes = [c for c in r["codes"] if c == "CL"]
        check("CL / CLASS IN CHARGE filtered from meters + table",
              not junk_names and not junk_codes and r["meters"] == 7 and r["rows"] == 7, str(r))

        ctx.close()
        b.close()
    print()
    print(f"{len(PASSES)}/{len(PASSES)+len(FAILS)} PASS")
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)


if __name__ == "__main__":
    main()
