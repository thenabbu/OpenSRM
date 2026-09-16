#!/usr/bin/env python3
"""Upgraded SRM attendance scraper — extracts structured data from DOM after navigation.

Speed-tuned version of srm_attendance.py:
  - swapped blind wait_for_timeout() sleeps for targeted wait_for_selector/wait_for_url
  - wait_until="domcontentloaded" instead of "networkidle" (a portal with any
    background polling/analytics can keep "networkidle" from settling far longer
    than the page actually needs)
  - headless=True (flip back to False if captcha solve rate drops -- can't verify
    detection behavior without testing against the live portal)
  - per-character typing delay trimmed, and username uses .fill() since it isn't
    part of the captcha/bot check
  - daily "absent details" fetches for each month now fire concurrently inside the
    page (Promise.all) instead of one sequential round trip per month

Same flow as before: funSetFormId(9) -> wait for the injected table -> DOM has it all.
"""
import asyncio, json, re, time
from playwright.async_api import async_playwright

LOGIN_URL = "https://sp.srmist.edu.in/srmiststudentportal/students/loginManager/youLogin.jsp"
CAPLAB_URL = "http://127.0.0.1:8377/solve"
NETID = "ng2776"
PASSWORD = "Gunnu@2008"

MONTHS = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
          "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"}

CAPTCHA_JS = """
() => {
    const img = document.querySelector('img[alt="Captcha"]');
    if (!img) return null;
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    c.getContext('2d').drawImage(img, 0, 0);
    return c.toDataURL('image/png').split(',')[1];
}
"""

async def solve_captcha(page):
    b64 = await page.evaluate(CAPTCHA_JS)
    if not b64:
        return None
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(CAPLAB_URL, json={"b64": b64}) as r:
            return (await r.json())["text"]


def _cells(row_html):
    return [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]


def parse_attendance(html):
    """Parse the studentAttendanceDetails.jsp HTML into structured data.
    Only extracts BASE data (not derivable: percentages, totals are computed from hours)."""
    out = {"courses": [], "monthly": [], "period": None}

    m = re.search(r"During the Period.*?<b>([^<]+)</b>\s*To\s*<b>([^<]+)</b>", html, re.S)
    if m:
        out["period"] = {"from": m.group(1).strip(), "to": m.group(2).strip()}

    tbody = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    if tbody:
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody.group(1), re.S):
            cells = _cells(row)
            if not cells or len(cells) < 5:
                continue
            if cells[0].lower() == "total" or len(cells) == 7:
                continue
            out["courses"].append({
                "code": cells[0], "description": cells[1],
                "max_hours": cells[2], "attended": cells[3], "absent": cells[4],
            })

    cum = re.search(r"Cumulative Attendance.*?<table[^>]*>.*?<tbody>(.*?)</tbody>", html, re.S)
    if cum:
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", cum.group(1), re.S):
            cells = _cells(row)
            if len(cells) >= 6:
                out["monthly"].append({
                    "month": cells[0], "present": cells[1], "absent": cells[2],
                    "od_present": cells[3], "od_absent": cells[4], "ml": cells[5],
                })

    return out


async def _fetch_rich(netid, password):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox",
                  "--disable-gpu", "--disable-dev-shm-usage"])
        ctx = await browser.new_context()
        await ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = await ctx.new_page()

        # domcontentloaded instead of networkidle: any tracker/analytics ping on
        # the portal keeps "networkidle" from settling quickly. click()/type() below
        # already auto-wait for the fields to be actionable, so no manual sleep needed.
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_selector('input[name="username"]', state="visible")
        await page.fill('input[name="username"]', netid)          # no need to fake typing here
        await page.click('input[name="password"]')
        await page.type('input[name="password"]', password, delay=35)
        captcha = await solve_captcha(page)
        if not captcha:
            await browser.close()
            return {"ok": False, "error": "captcha image not found"}
        await page.click('input[name="captcha"]')
        await page.type('input[name="captcha"]', captcha, delay=35)
        await page.mouse.move(500, 400, steps=10)
        await page.click('button:has-text("Login")')

        # Wait for the actual redirect instead of a flat sleep + a URL check after
        # the fact -- resolves the moment it happens, and fails fast if it doesn't.
        try:
            await page.wait_for_url(lambda url: "HRDSystem" in url, timeout=15000)
        except Exception:
            await browser.close()
            return {"ok": False, "error": "login failed (wrong creds or captcha misread)"}

        await page.evaluate("funSetFormId(9)")
        # Wait for the attendance rows to actually land instead of guessing 3s.
        try:
            await page.wait_for_selector("#divMainDetails table tbody tr", timeout=15000)
        except Exception:
            pass  # fall through -- parse_attendance will just come back mostly empty
        await page.wait_for_timeout(400)  # small buffer for any rows that fill in late

        content_html = await page.evaluate('() => document.getElementById("divMainDetails")?.innerHTML || document.body.innerHTML')
        data = parse_attendance(content_html)

        # Build the list of months needing a daily-absent lookup, then fire all
        # those requests concurrently inside the page instead of one at a time.
        targets = []
        for mo in data.get("monthly", []):
            mstr = mo["month"]
            mm = re.search(r"([A-Z]+)\s*/\s*(\d{4})", mstr)
            if not mm:
                continue
            absent_val = mo["absent"].replace("&nbsp;", " ").strip()
            if not absent_val or int(absent_val) <= 0:
                continue
            month_name = mm.group(1).upper()
            if month_name not in MONTHS:
                continue
            targets.append({"mstr": mstr, "mon": MONTHS[month_name], "year": mm.group(2)})

        daily = {}
        if targets:
            results = await page.evaluate("""
                async (targets) => {
                    const reqs = targets.map(t =>
                        fetch("../../students/report/studentAttendanceDetailsInner.jsp", {
                            method: "POST",
                            headers: {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"},
                            body: "ids=1&attendanceMonth=" + t.mon + "&attendanceYear=" + t.year
                        }).then(r => r.text())
                    );
                    return Promise.all(reqs);
                }
            """, targets)
            for t, inner in zip(targets, results):
                rows = []
                for row in re.findall(r"<tr[^>]*>(.*?)</tr>", inner, re.S):
                    cells = _cells(row)
                    if len(cells) >= 2 and re.match(r"\d{2}-\d{2}-\d{4}", cells[0]):
                        rows.append({"date": cells[0], "hours": cells[1]})
                daily[t["mstr"]] = rows
        data["daily_absent"] = daily

        await browser.close()
        return {"ok": True, "data": data, "fetched": int(time.time())}


def fetch_rich(netid, password):
    return asyncio.run(_fetch_rich(netid, password))


if __name__ == "__main__":
    res = fetch_rich(NETID, PASSWORD)
    print(json.dumps(res, indent=2))
