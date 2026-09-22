#!/usr/bin/env python3
"""SRM Attendance — Flask app (multi-user, security-hardened, Sep 2026 audit).

Audit fixes (Sep 16 2026):
  - Passwords encrypted at rest (Fernet, key in /app/data/fernet.key)
  - get_json(silent=True) — requires application/json, no force=True
  - Per-IP login rate limit (CF-Connecting-IP aware) + per-netid scrape limit
  - Security headers (CSP, nosniff, frame-deny, referrer)
  - MAX_CONTENT_LENGTH 16KB
  - Session cookie Secure-flag when behind HTTPS
  - netid validated ^[a-z0-9]{2,20}$
  - Expired session tokens pruned on login

Kept from prior work:
# Xvfb removed Sep 2026: headless=True proven safe (anti-bot bypass via
# webdriver strip + --disable-blink-features). See skill: srm-portal-attendance
# Xvfb removed Sep 2026: headless=True proven safe (anti-bot bypass via
# webdriver strip + --disable-blink-features). See skill: srm-portal-attendance
  - Speed ~9s end-to-end
"""
import asyncio
import base64
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from functools import wraps

# timetable_html is now defined locally (SQLite-backed)
from flask import Flask, make_response, redirect, render_template, request

LOGIN_URL = "https://sp.srmist.edu.in/srmiststudentportal/students/loginManager/youLogin.jsp"

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "srm.db")
SECRET = open(os.path.join(DATA_DIR, "secret")).read().strip() if os.path.exists(os.path.join(DATA_DIR, "secret")) else secrets.token_hex(32)

app = Flask(__name__)
app.secret_key = SECRET
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # audit: bound request bodies

SESSION_MAX_AGE = 60 * 60 * 24 * 30          # 30 days

# ── Crypto: passwords at rest ──────────────────────────────────────
_fernet = None
def get_fernet():
    """Lazy-init Fernet from a persisted key file so restarts don't lose data."""
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet
        key_path = os.path.join(DATA_DIR, "fernet.key")
        if os.path.exists(key_path):
            key = open(key_path, "rb").read()
        else:
            key = Fernet.generate_key()
            with open(key_path, "wb") as f:
                f.write(key)
            os.chmod(key_path, 0o600)
        _fernet = Fernet(key)
    return _fernet

def encrypt_pw(pw):
    return get_fernet().encrypt(pw.encode()).decode()

def decrypt_pw(blob):
    try:
        return get_fernet().decrypt(blob.encode()).decode()
    except Exception:
        return ""

def _import_legacy_timetable():
    """One-time import: timetable.json -> SQLite for existing users."""
    json_path = os.path.join(os.path.dirname(__file__), "data", "timetable.json")
    if not os.path.exists(json_path): return
    data = json.load(open(json_path))
    # Infer group from ng2776's known data
    group_key = "Computer Science and Engineering Cloud Computing_2025_3_A"
    c = db()
    try:
        c.execute("INSERT OR IGNORE INTO timetable_groups(group_key,program,batch,semester,section) "
                  "VALUES(?,?,?,?,?)", (group_key, "B.Tech.-CSE Cloud Computing", 2025, 3, "A"))
        gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (group_key,)).fetchone()[0]
        # Import subjects from attendance data
        for u in c.execute("SELECT personal_details_json, attendance_json FROM users").fetchall():
            if u[0]:
                pd = json.loads(u[0])
                gk = _group_key(pd)
                if gk == group_key and u[1]:
                    att = json.loads(u[1])
                    seen = set()
                    for course in att.get("courses", []):
                        code = course.get("code", "")
                        if code and code not in seen:
                            seen.add(code)
                            c.execute("INSERT OR IGNORE INTO timetable_subjects(group_id,code,name,credits,is_custom) "
                                      "VALUES(?,?,?,0,0)", (gid, code, course.get("description",""), 0))
        # Import slots from JSON
        for day, slots in data.items():
            for i, s in enumerate(slots):
                period = i + 1
                if period > 7: period = 7  # clamp
                c.execute("INSERT OR IGNORE INTO timetable_slots(group_id,day,period,subject_code,subject_name,location) "
                          "VALUES(?,?,?,?,?,?)", (gid, day, period, s.get("code",""), s.get("name",""), s.get("location","")))
        c.commit()
    except: pass
    c.close()
    os.rename(json_path, json_path + ".bak")

def db():

    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        netid TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        attendance_json TEXT,
        marks_json TEXT DEFAULT '[]',
        last_fetch INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS cookies(
        token TEXT PRIMARY KEY,
        netid TEXT NOT NULL,
        created INTEGER NOT NULL
    )""")
    # v2: personal details column (idempotent migration)
    try:
        c.execute("ALTER TABLE users ADD COLUMN personal_details_json TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        c.execute("ALTER TABLE users ADD COLUMN photo_b64 TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        c.execute("ALTER TABLE users ADD COLUMN marks_json TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass  # column already exists
    _import_legacy_timetable()
    c.execute("""CREATE TABLE IF NOT EXISTS timetable_groups (
        id INTEGER PRIMARY KEY, group_key TEXT UNIQUE NOT NULL,
        program TEXT, batch INTEGER, semester INTEGER, section TEXT,
        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS timetable_slots (
        id INTEGER PRIMARY KEY,
        group_id INTEGER NOT NULL REFERENCES timetable_groups(id) ON DELETE CASCADE,
        day TEXT NOT NULL, period INTEGER NOT NULL,
        subject_code TEXT, subject_name TEXT, location TEXT DEFAULT '',
        UNIQUE(group_id, day, period))""")
    c.execute("""CREATE TABLE IF NOT EXISTS timetable_subjects (
        id INTEGER PRIMARY KEY,
        group_id INTEGER NOT NULL REFERENCES timetable_groups(id) ON DELETE CASCADE,
        code TEXT NOT NULL, name TEXT NOT NULL, credits INTEGER DEFAULT 0,
        is_custom INTEGER DEFAULT 0, UNIQUE(group_id, code))""")
    c.commit(); c.close()

_solver = None
def get_solver():
    global _solver
    if _solver is None:
        import ddddocr
        _solver = ddddocr.DdddOcr(beta=True)
    return _solver

def solve_captcha_b64(b64):
    return get_solver().classification(base64.b64decode(b64))

def get_current_user():
    token = request.cookies.get("srm_session")
    if not token: return None
    c = db()
    row = c.execute("SELECT netid FROM cookies WHERE token=?", (token,)).fetchone()
    c.close()
    return row["netid"] if row else None

def make_session_token(netid):
    token = secrets.token_hex(32)
    c = db()
    c.execute("DELETE FROM cookies WHERE netid=?", (netid,))
    # audit: prune expired tokens while we're here
    c.execute("DELETE FROM cookies WHERE created < ?", (int(time.time()) - SESSION_MAX_AGE,))
    c.execute("INSERT INTO cookies(token,netid,created) VALUES(?,?,?)", (token, netid, int(time.time())))
    c.commit(); c.close()
    return token

def require_login(f):
    @wraps(f)
    def w(*a, **kw):
        if not get_current_user():
            return redirect("/login")
        return f(*a, **kw)
    return w

# audit: Secure flag only when the request actually arrived via HTTPS
# (Cloudflare sets X-Forwarded-Proto; plain LAN http:// access keeps working)
def _cookie_secure():
    return request.headers.get("X-Forwarded-Proto") == "https"

CAPTCHA_JS = """async () => {
    const img = document.querySelector('img[alt="Captcha"]');
    // The captcha blob may not have painted yet — a 0x0 canvas yields a
    // blank image and a garbage OCR read, so the login always fails the
    // captcha. Poll until the image actually has dimensions.
    for (let i = 0; i < 40; i++) {
        if (img && img.complete && img.naturalWidth > 0) {
            const c = document.createElement('canvas');
            c.width = img.naturalWidth; c.height = img.naturalHeight;
            c.getContext('2d').drawImage(img, 0, 0);
            return c.toDataURL('image/png').split(',')[1];
        }
        await new Promise(r => setTimeout(r, 250));
    }
    return null;
}"""

MONTHS = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}

NETID_RE = re.compile(r"^[a-z0-9]{2,20}$")  # audit: SRM NetIDs are lowercase alnum

# ── Concurrency guard ──────────────────────────────────────────────
# audit F1 fix: threading.Lock, not asyncio.Semaphore — gunicorn gthread
# runs views in a thread pool, so the guard must be thread-safe, and it
# must be shared process-wide. Pair with gunicorn -w 1 (Dockerfile CMD)
# so counters below are also process-wide.
_scrape_lock = threading.Lock()

# ── Rate limiting ──────────────────────────────────────────────────
# Two independent limits:
#   per-netid scrape limit — portal-friendliness (each scrape = real SRM login)
#   per-IP login limit    — brute-force protection (netid rotation-proof)
_login_attempts = {}   # netid -> [ts, ...]  (scrapes, 10-min window)
_ip_attempts = {}      # ip -> [ts, ...]    (login POSTs, 1-hour window)

def _check_rate(netid):
    now = time.time()
    attempts = _login_attempts.get(netid, [])
    _login_attempts[netid] = [t for t in attempts if now - t < 600]
    if len(_login_attempts[netid]) >= 3:
        return False
    _login_attempts[netid].append(now)
    return True

def _check_ip_rate(ip):
    now = time.time()
    attempts = _ip_attempts.get(ip, [])
    _ip_attempts[ip] = [t for t in attempts if now - t < 3600]
    if len(_ip_attempts[ip]) >= 10:
        return False
    _ip_attempts[ip].append(now)
    return True
def _client_ip():
    # Behind the CF tunnel, remote_addr is cloudflared itself; CF sets the
    # real client IP. LAN clients without the header fall back to remote_addr.
    return request.headers.get("CF-Connecting-IP") or request.remote_addr or "?"

# ── HTML parsing ───────────────────────────────────────────────────
def _cells(row_html):
    return [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]

ROMAN = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10}

def _semester_int(semester_str):
    """Convert 'III SEMESTER' -> 3."""
    roman = semester_str.split()[0].strip()
    return ROMAN.get(roman, 0)

def _group_key(personal):
    """Extract timetable group from personal details dict."""
    program = personal.get("Program", "")
    program = re.sub(r"\[.*?\]", "", program).strip()
    batch = personal.get("Batch", "")
    semester = _semester_int(personal.get("Semester", ""))
    section = personal.get("Section", "")
    if not all([program, batch, semester, section]):
        return None
    short = re.sub(r"B\.Tech\.\s*-\s*", "", program).strip()
    short = re.sub(r"with specialization in\s*", "", short).strip()
    short = short.replace(",", "")
    return f"{short}_{batch}_{semester}_{section}"

def parse_attendance(html):
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


# ── Personal details (formId 17) ───────────────────────────────
def parse_personal_details(html):
    """Extract key-value pairs from the personal details page (formId 17).
    The portal renders label/value table rows inside #divMainDetails."""
    out = {}
    for m in re.finditer(
            r'<td[^>]*>\s*([^<]+?)\s*</td>\s*<td[^>]*>\s*(.*?)\s*</td>', html, re.S):
        key = re.sub(r'<[^>]+>', '', m.group(1)).strip().rstrip(':').strip()
        val = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if key and val and key.lower() not in ('', 's.no', 's. no'):
            out[key] = val
    return out


# ── Persistent browser + event-loop singletons (speed warm-up, Sep 2026) ──
# Launch Chromium ONCE and reuse it across requests via a dedicated worker
# event loop. Each scrape gets a FRESH context (isolated cookies); we close
# only the context, never the shared browser. This removes ~2.5-3s of
# per-request browser launch and ~3s ddddocr cold start.
# Requires gunicorn -w 1 (singletons are process-local). Thread-safe: all
# browser access serializes through _scrape_lock in fetch_attendance.
_pw = None
_browser = None
_loop = None
_loop_thread = None



# -- Internal marks (formId 13) --
def parse_marks(html):
    """Parse internal marks from studentInternalMarkDetails.jsp."""
    out = []
    if not html:
        return out
    if re.search(r"no\s+record\s+found", html, re.I):
        return out
    table_m = re.search(r"<table[^>]*>.*?<tr[^>]*>(.*?)</tr>(.*?)</table>", html, re.S)
    if not table_m:
        return out
    headers = [re.sub(r"<[^>]+>", "", h).strip().lower()
               for h in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", table_m.group(1), re.S)]
    if not headers or not any("code" in h for h in headers):
        return out
    code_i = next((i for i, h in enumerate(headers) if "code" in h), 0)
    desc_i = next((i for i, h in enumerate(headers)
                    if any(k in h for k in ("desc", "course", "subject"))), 1)
    test_i = next((i for i, h in enumerate(headers)
                    if any(k in h for k in ("test", "exam", "assess", "component"))), None)
    by_code = {}
    order = []
    pair_re = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table_m.group(2), re.S):
        cells = [re.sub(r"<[^>]+>", "", c).replace("\xa0", " ").strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 3:
            continue
        code = cells[code_i] if code_i < len(cells) else ""
        if not code or re.match(r"total|s\.?\s*no", code, re.I):
            continue
        scored = maximum = 0.0
        for cell in cells:
            m = pair_re.search(cell)
            if m:
                scored, maximum = float(m.group(1)), float(m.group(2))
                break
        if maximum <= 0:
            continue
        desc = cells[desc_i] if desc_i < len(cells) and desc_i != code_i else ""
        test_name = ""
        if test_i is not None and test_i < len(cells):
            val = cells[test_i].strip()
            if val and val.lower() not in ("view details", "nil", "-", ""):
                test_name = val
        if not test_name:
            if maximum <= 5:
                n = sum(1 for v in by_code.get(code, {}).get("components", [])
                        if v.get("max", 0) <= 5) + 1
                test_name = f"FT{n}"
            else:
                n = sum(1 for v in by_code.get(code, {}).get("components", [])
                        if v.get("max", 0) > 5) + 1
                test_name = f"CT {n}"
        if code not in by_code:
            by_code[code] = {"code": code, "title": desc, "components": [],
                             "scored_total": 0.0, "max_total": 0.0}
            order.append(code)
        elif not by_code[code]["title"] and desc:
            by_code[code]["title"] = desc
        by_code[code]["components"].append(
            {"name": test_name, "scored": scored, "max": maximum})
        by_code[code]["scored_total"] = round(by_code[code]["scored_total"] + scored, 2)
        by_code[code]["max_total"] = round(by_code[code]["max_total"] + maximum, 2)
    return [by_code[c] for c in order]

def _ensure_loop():
    """Return a long-lived asyncio loop running in a daemon thread."""
    global _loop, _loop_thread
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True,
                                        name="srm-async-loop")
        _loop_thread.start()
    return _loop

async def _get_browser():
    """Lazily start ONE shared Chromium. Callers must NOT close it."""
    global _pw, _browser
    if _browser is not None:
        try:
            if _browser.is_connected():
                return _browser
        except Exception:
            _browser = None
    if _pw is None:
        from playwright.async_api import async_playwright
        _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch(
        headless=True,
        executable_path=os.environ.get("CHROMIUM_PATH", "/usr/bin/chromium"),
        args=["--disable-blink-features=AutomationControlled",
              "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
    return _browser

# ── Speed-optimized scraper ──────────────────────────────────────── ────────────────────────────────────────
async def _fetch_rich_optimized(netid, password):
    # Shared browser; per-scrape isolated context (fresh cookies per login).
    browser = await _get_browser()
    ctx = await browser.new_context()
    await ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    page = await ctx.new_page()
    try:

        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_selector('input[name="username"]', state="visible")
        await page.fill('input[name="username"]', netid)
        await page.click('input[name="password"]')
        await page.type('input[name="password"]', password, delay=35)

        MAX_CAPTCHA_RETRIES = 3
        for _ca in range(MAX_CAPTCHA_RETRIES):
            b64 = await page.evaluate(CAPTCHA_JS)
            if not b64:
                await ctx.close()
                return {"ok": False, "error": "captcha image not found"}
            captcha = solve_captcha_b64(b64)

            await page.click('input[name="captcha"]')
            await page.type('input[name="captcha"]', captcha, delay=35)
            await page.mouse.move(500, 400, steps=10)
            await page.click('button:has-text("Login")')

            try:
                await page.wait_for_url(lambda url: "HRDSystem" in url, timeout=15000)
                break  # success
            except Exception:
                if _ca < MAX_CAPTCHA_RETRIES - 1:
                    # Reload page and retry with fresh captcha
                    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
                    await page.wait_for_selector('input[name="username"]', state="visible")
                    await page.fill('input[name="username"]', netid)
                    await page.click('input[name="password"]')
                    await page.type('input[name="password"]', password, delay=35)
                    continue
                await ctx.close()
                return {"ok": False, "error": f"login failed after {MAX_CAPTCHA_RETRIES} captcha attempts (wrong creds or persistent captcha misread)"}

        # Grab student photo — non-critical, fail silently.
        # Wait briefly for the portal dashboard to render the photo (loaded via AJAX).
        photo_b64 = ""
        try:
            await page.wait_for_timeout(1500)
            photo_b64 = await page.evaluate("""
                () => {
                    const img = document.querySelector(
                        'img.imgPhoto, img.img-account-profile, img[alt*=Student], img[src*=sphotos], img[src*=photo]');
                    if (!img) return "NO_IMG_FOUND";
                    if (!img.naturalWidth && !img.complete) {
                        img.scrollIntoView();
                        return "IMG_NOT_LOADED_YET";
                    }
                    if (!img.naturalWidth) return "IMG_NO_NATURAL_WIDTH";
                    const c = document.createElement("canvas");
                    c.width = img.naturalWidth; c.height = img.naturalHeight;
                    c.getContext("2d").drawImage(img, 0, 0);
                    return c.toDataURL("image/jpeg", 0.85).split(",")[1] || "";
                }
            """)
        except Exception:
            pass

        await page.evaluate("funSetFormId(9)")
        try:
            await page.wait_for_selector("#divMainDetails table tbody tr", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(400)

        content_html = await page.evaluate('() => document.getElementById("divMainDetails")?.innerHTML || document.body.innerHTML')
        data = parse_attendance(content_html)

        # Guard: a reachable attendance page ALWAYS has the course table. When
        # the portal soft-locks the account (e.g. 1st-years blocked until ABC ID
        # Generation is submitted) every formId — including 9 — renders the
        # gate page instead, so parsing yields empty lists. Fail loudly rather
        # than storing an empty record that looks like real data.
        if not data.get("courses"):
            raw = await page.evaluate(
                '() => (document.getElementById("divMainDetails")||document.body).innerText || ""')
            if "ABC ID" in raw or "Aadhaar" in raw:
                await ctx.close()
                return {"ok": False, "error": "Portal requires ABC ID Generation first — "
                                              "log in at sp.srmist.edu.in and complete the "
                                              "Aadhaar/ABC ID form, then try again."}
            await ctx.close()
            return {"ok": False, "error": "Attendance page did not load (portal returned no "
                                          "course table). The portal may be slow or your "
                                          "account may be restricted."}

        targets = []
        for mo in data.get("monthly", []):
            mstr = mo["month"]
            mm = re.search(r"([A-Z]+)\s*/\s*(\d{4})", mstr)
            if not mm:
                continue
            absent_val = mo["absent"].replace("\u00a0", " ").strip()
            if not absent_val or int(absent_val) <= 0:
                continue
            name = mm.group(1).upper()
            if name not in MONTHS:
                continue
            targets.append({"mstr": mstr, "mon": MONTHS[name], "year": mm.group(2)})

        daily = {}
        if targets:
            results = await page.evaluate("""
                async (targets) => {
                    const reqs = targets.map(t =>
                        fetch("../../students/report/studentAttendanceDetailsInner.jsp", {
                            method: "POST",
                            headers: {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                      "X-Requested-With": "XMLHttpRequest"},
                            body: "ids=1&attendanceMonth=" + t.mon + "&attendanceYear=" + t.year
                        }).then(r => r.text())
                    );
                    return Promise.all(reqs);
                }
            """, targets)
            for t, inner in zip(targets, results):
                rows = []
                for row in re.findall(r"<tr[^>]*>(.*?)</tr>", inner, re.S):
                    cells = [re.sub(r"<[^>]+>", "", c).replace("\u00a0", " ").strip()
                             for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
                    if len(cells) >= 2 and re.match(r"\d{2}-\d{2}-\d{4}", cells[0]):
                        rows.append({"date": cells[0], "hours": cells[1]})
                daily[t["mstr"]] = rows
        data["daily_absent"] = daily

        # v2: personal details (formId 17) — non-critical, never fail the scrape
        personal = {}
        try:
            await page.evaluate("funSetFormId(17)")
            await page.wait_for_timeout(2500)
            personal_html = await page.evaluate(
                '() => document.getElementById("divMainDetails")?.innerHTML || ""')
            if personal_html:
                personal = parse_personal_details(personal_html)
        except Exception:
            pass

        # v2: course list (formId 7) — for timetable subjects, non-critical
        courses = []
        try:
            await page.evaluate("funSetFormId(7)")
            await page.wait_for_selector("#divMainDetails table tbody tr", timeout=10000)
            await page.wait_for_timeout(400)
            course_html = await page.evaluate(
                '() => document.getElementById("divMainDetails")?.innerHTML || ""')
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", course_html, re.S):
                cells = _cells(row)
                if len(cells) >= 3 and cells[0] and not cells[0].lower().startswith("total"):
                    courses.append({"code": cells[0], "name": cells[1], "credits": int(cells[2] or 0)})
        except Exception:
            pass

        # marks: internal marks (formId 13, non-critical)
        marks = []
        try:
            await page.evaluate("funSetFormId(13)")
            await page.wait_for_timeout(2000)
            marks_html = await page.evaluate(
                '() => document.getElementById("divMainDetails")?.innerHTML || ""')
            if marks_html:
                marks = parse_marks(marks_html)
        except Exception:
            pass

        return {"ok": True, "data": data, "personal": personal, "photo": photo_b64, "courses": courses, "marks": marks, "fetched": int(time.time())}
    finally:
        await ctx.close()

def fetch_attendance(netid, password):
    if not _check_rate(netid):
        return {"ok": False, "error": "Too many sync attempts for this account. Try again in 10 minutes."}
    # audit F1 fix: blocking acquire in the worker thread; no try/except race
    if not _scrape_lock.acquire(blocking=False):
        return {"ok": False, "error": "Sync in progress. Try again in 30 seconds."}
    try:
        loop = _ensure_loop()
        future = asyncio.run_coroutine_threadsafe(_fetch_rich_optimized(netid, password), loop)
        return future.result(timeout=60)  # browser lives on the worker loop, survives across calls
    except Exception as e:
        # Loop/browser may have died — force a fresh launch next time.
        global _browser, _loop_thread
        _browser = None
        msg = str(e) or repr(e)
        return {"ok": False, "error": "scrape worker died: %s" % msg}
    finally:
        _scrape_lock.release()

# ── View model ─────────────────────────────────────────────────────
ATTENDANCE_TARGET = 0.75
ATTENDANCE_WARN = 0.65

def _safe_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0

def _status_for_pct(pct):
    if pct >= ATTENDANCE_TARGET * 100: return "ok"
    if pct >= ATTENDANCE_WARN * 100: return "warn"
    return "danger"

def _bunk_line(attended, max_hours, threshold=ATTENDANCE_TARGET):
    if max_hours <= 0: return None
    pct_target = threshold * 100
    room = attended / threshold - max_hours
    if room >= -1e-9:
        n = max(0, math.floor(room + 1e-9))
        if n == 0:
            return "One more miss drops you below %.0f%%" % pct_target
        return "Can miss %d more class%s and stay above %.0f%%" % (n, "" if n == 1 else "es", pct_target)
    need = max(1, math.ceil((threshold * max_hours - attended) / (1 - threshold) - 1e-9))
    return "Attend the next %d class%s in a row to reach %.0f%%" % (need, "" if need == 1 else "es", pct_target)

def _course_view(c):
    attended = _safe_int(c.get("attended"))
    max_hours = _safe_int(c.get("max_hours"))
    absent = _safe_int(c.get("absent"))
    pct = min(100.0, round((attended / max_hours) * 100, 1)) if max_hours > 0 else 0.0
    return {"code": c.get("code", ""), "description": c.get("description", ""),
            "max_hours": max_hours, "attended": attended, "absent": absent,
            "pct": pct, "status": _status_for_pct(pct), "bunk_line": _bunk_line(attended, max_hours)}

def _month_view(m):
    present = _safe_int(m.get("present"))
    absent = _safe_int(m.get("absent"))
    total = present + absent
    out = dict(m)
    out["pct"] = round((present / total) * 100, 1) if total > 0 else None
    return out

def _overall_view(courses):
    total_att = sum(c["attended"] for c in courses)
    total_max = sum(c["max_hours"] for c in courses)
    pct = min(100.0, round((total_att / total_max) * 100, 1)) if total_max > 0 else 0.0
    return {"attended": total_att, "max_hours": total_max, "pct": pct,
            "status": _status_for_pct(pct), "bunk_line": _bunk_line(total_att, total_max)}

# ── Security headers ───────────────────────────────────────────────
@app.after_request
def set_security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://api.dicebear.com; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; worker-src 'self'; manifest-src 'self'")
    resp.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    return resp

# ── HTML Templates ─────────────────────────────────────────────────

# ── Routes ─────────────────────────────────────────────────────────
@app.route("/")
@require_login
def index():
    netid = get_current_user()
    c = db()
    row = c.execute("SELECT attendance_json, last_fetch, personal_details_json, photo_b64 FROM users WHERE netid=?", (netid,)).fetchone()
    c.close()
    data = json.loads(row["attendance_json"]) if row and row["attendance_json"] else {"courses": [], "monthly": [], "period": None, "daily_absent": {}}
    last_epoch = row["last_fetch"] if row and row["last_fetch"] else 0
    last = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(last_epoch)) if last_epoch else "never"

    hours_old = int((time.time() - last_epoch) / 3600) if last_epoch else None
    courses = [_course_view(x) for x in data.get("courses", [])]
    monthly = [_month_view(x) for x in data.get("monthly", [])]
    overall = _overall_view(courses)

    # Extract student name from personal details
    personal_data = json.loads(row["personal_details_json"]) if row and row["personal_details_json"] else {}
    student_name = personal_data.get("Student Name", "").title()

    return render_template(
        "dashboard.html", netid=netid, courses=courses, monthly=monthly, overall=overall,
        period=data.get("period"), daily_absent=data.get("daily_absent", {}),
        last=last, last_epoch=last_epoch, hours_old=hours_old, has_data=bool(courses),
        student_name=student_name,
        timetable=timetable_html(_group_key(json.loads(row["personal_details_json"])) if row and row["personal_details_json"] else None),
        personal=personal_data)

# ── Timetable (SQLite-backed, per-group) ─────────────────────────
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
SLOTS = [
    {"period": 1, "start": "09:30", "end": "10:20", "type": "class"},
    {"period": 2, "start": "10:20", "end": "11:10", "type": "class"},
    {"period": 0, "start": "11:10", "end": "11:20", "type": "break", "name": "Break"},
    {"period": 3, "start": "11:20", "end": "12:10", "type": "class"},
    {"period": 4, "start": "12:10", "end": "13:00", "type": "class"},
    {"period": 0, "start": "13:00", "end": "14:10", "type": "break", "name": "Lunch"},
    {"period": 5, "start": "14:10", "end": "15:00", "type": "class"},
    {"period": 6, "start": "15:00", "end": "15:50", "type": "class"},
    {"period": 0, "start": "15:50", "end": "16:00", "type": "break", "name": "Break"},
    {"period": 7, "start": "16:00", "end": "16:50", "type": "class"},
]

def _now_next_from_slots(day, slots):
    now_mins = datetime.now().hour * 60 + datetime.now().minute
    for s in slots:
        sm = int(s["start"].split(":")[0]) * 60 + int(s["start"].split(":")[1])
        em = int(s["end"].split(":")[0]) * 60 + int(s["end"].split(":")[1])
        if sm <= now_mins < em:
            if s.get("type") == "break":
                return {"kind": "break", "label": s.get("name","Break"), "until": s["end"]}
            return {"kind": "current", "code": s["code"], "name": s["name"],
                    "loc": s.get("location",""), "until": s["end"]}
    upcoming = [s for s in slots if s.get("type") != "break" and
                int(s["start"].split(":")[0])*60 + int(s["start"].split(":")[1]) > now_mins]
    if upcoming:
        s = upcoming[0]
        sm = int(s["start"].split(":")[0])*60 + int(s["start"].split(":")[1])
        return {"kind": "next", "code": s["code"], "name": s["name"],
                "loc": s.get("location",""), "at": s["start"],
                "in_mins": sm - now_mins}
    return {"kind": "done"} if slots else None

def timetable_html(group_key):
    if not group_key:
        return ("<div class=\"tt-wrap\"><div class=\"tt-hero tt-hero--off\">"
                "<span class=\"tt-hero-dot tt-hero-dot--off\"></span>"
                "<div><strong>No timetable found</strong>"
                "<div class=\"tt-hero-sub\">No timetable exists for your group yet.</div></div></div></div>")
    c = db()
    gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (group_key,)).fetchone()
    if not gid:
        c.close()
        return ("<div class=\"tt-wrap\"><div class=\"tt-hero tt-hero--off\">"
                "<span class=\"tt-hero-dot tt-hero-dot--off\"></span>"
                "<div><strong>No timetable set</strong>"
                "<div class=\"tt-hero-sub\">Your group has no timetable. Use the editor to build one.</div></div></div></div>")
    gid = gid[0]
    day_slots = {}
    for r in c.execute("SELECT day,period,subject_code,subject_name,location FROM timetable_slots WHERE group_id=?", (gid,)):
        if r[0] not in day_slots: day_slots[r[0]] = {}
        day_slots[r[0]][r[1]] = {"code": r[2], "name": r[3], "location": r[4] or ""}
    c.close()
    # If no slots at all, show empty state
    has_slots = any(day_slots.get(d) for d in DAY_ORDER)
    if not has_slots:
        return ("<div class=\"tt-wrap\"><div class=\"tt-hero tt-hero--off\">"
                "<span class=\"tt-hero-dot tt-hero-dot--off\"></span>"
                "<div><strong>Timetable empty</strong>"
                "<div class=\"tt-hero-sub\">Use the editor to map out your schedule.</div></div></div></div>")
    # Build today's slots for hero
    today = datetime.now().strftime("%A")
    today_slots = []
    for s in SLOTS:
        if s["type"] == "break":
            today_slots.append(s)
        elif today in day_slots and s["period"] in day_slots[today]:
            m = day_slots[today][s["period"]]
            today_slots.append({**s, "code": m["code"], "name": m["name"], "location": m["location"]})
    hero_status = _now_next_from_slots(today, today_slots)
    # Hero HTML
    if hero_status is None or hero_status["kind"] == "done":
        hero = ("<div class=\"tt-hero tt-hero--done\"><span class=\"tt-hero-dot tt-hero-dot--off\"></span>"
                "<div><strong>Done for today</strong><div class=\"tt-hero-sub\">No more classes</div></div></div>")
    elif hero_status["kind"] == "break":
        hero = ("<div class=\"tt-hero tt-hero--break\"><span class=\"tt-hero-dot tt-hero-dot--break\"></span>"
                "<div><strong>{label}</strong><div class=\"tt-hero-sub\">Until {until}</div></div></div>").format(**hero_status)
    elif hero_status["kind"] == "current":
        hero = ("<div class=\"tt-hero tt-hero--now\"><span class=\"tt-hero-dot tt-hero-dot--now\"></span>"
                "<div><strong>{code} \u2014 {name}</strong>"
                "<div class=\"tt-hero-sub\">Ends {until}</div>"
                "<div class=\"tt-hero-loc\">{loc}</div></div></div>").format(**hero_status)
    elif hero_status["kind"] == "next":
        hero = ("<div class=\"tt-hero tt-hero--next\"><span class=\"tt-hero-dot tt-hero-dot--next\"></span>"
                "<div><strong>{code} \u2014 {name}</strong>"
                "<div class=\"tt-hero-sub\">Starts at {at} (in {in_mins}m)</div>"
                "<div class=\"tt-hero-loc\">{loc}</div></div></div>").format(**hero_status)
    else:
        hero = ("<div class=\"tt-hero tt-hero--off\"><span class=\"tt-hero-dot tt-hero-dot--off\"></span>"
                "<div><strong>No classes today</strong></div></div>")
    # Day tabs + panels
    default_day = today if today in DAY_ORDER else "Monday"
    radios = "".join("<input type=radio name=ttday id=day-{0} class=tt-radio{1}>".format(d, " checked" if d == default_day else "") for d in DAY_ORDER)
    tabs = "".join("<label for=day-{0}{1}>{2}</label>".format(d, " class=tt-today" if d == today else "", d[:3]) for d in DAY_ORDER)
    panels = []
    for d in DAY_ORDER:
        rows = []
        for s in SLOTS:
            if s["type"] == "break":
                rows.append("<div class=tt-divider>{0}</div>".format(s["name"]))
                continue
            sl = day_slots.get(d, {}).get(s["period"])
            if not sl:
                continue
            code, name, loc = sl["code"], sl["name"], sl.get("location", "")
            now_mins = datetime.now().hour * 60 + datetime.now().minute
            sm = int(s["start"].split(":")[0])*60 + int(s["start"].split(":")[1])
            em = int(s["end"].split(":")[0])*60 + int(s["end"].split(":")[1])
            hl = ""
            if d == today and sm <= now_mins < em:
                hl = "current"
            elif d == today and now_mins < sm and (sm - now_mins) <= 120:
                hl = "upcoming"
            cls = " tt-row--" + hl if hl else ""
            badge = ""
            if hl == "current": badge = "<span class=tt-badge>Now</span>"
            elif hl == "upcoming": badge = "<span class=tt-badge tt-badge--soon>Soon</span>"
            loc_html = "<span class=tt-loc>{0}</span>".format(loc) if loc else ""
            rows.append("<div class=tt-row{0}><div class=tt-time>{1}<small>{2}</small></div>"
                        "<div class=tt-info><strong>{3}</strong><span class=tt-name>{4}</span>{5}</div>"
                        "{6}</div>".format(cls, s["start"], s["end"], code, name, loc_html, badge))
        panels.append("<div class=day-panel id=panel-{0}>{1}</div>".format(d, "".join(rows)))
    return ("<div class=tt-wrap>" + hero
            + "<div class=tt-tabs>" + radios
            + "<div class=tt-tabbar>" + tabs + "</div>"
            + "<div class=panels>" + "".join(panels) + "</div>"
            + "</div></div>")


@app.route("/api/marks")
@require_login
def api_marks():
    netid = get_current_user()
    if not netid:
        return {"ok": False, "error": "not logged in"}, 401
    c = db()
    row = c.execute("SELECT marks_json FROM users WHERE netid=?", (netid,)).fetchone()
    c.close()
    marks = json.loads(row["marks_json"]) if row and row["marks_json"] else []
    return {"ok": True, "marks": marks}

@app.route("/static/<path:filename>")
def static_no_cache(filename):
    from flask import send_from_directory
    resp = send_from_directory("/app/app/static", filename)
    # Service worker and manifest need cacheable responses; CSS stays no-store
    if filename.endswith(('.js', '.json')):
        resp.headers["Cache-Control"] = "public, max-age=3600"
    else:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.route("/login")
def login():
    if get_current_user(): return redirect("/")
    return render_template("login.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    # audit: no force=True — require real application/json content-type
    d = request.get_json(silent=True)
    # audit F4: validation failures return 400, not 200
    if d is None:
        return {"ok": False, "error": "invalid request \u2014 Content-Type must be application/json"}, 400
    if not isinstance(d, dict):
        return {"ok": False, "error": "invalid request body"}, 400

    # audit F1: single gunicorn worker (-w 1 in Dockerfile) makes these
    # in-process counters shared — the recon bypass came from per-worker
    # state. Malformed POSTs return 400 above without counting: they never
    # reach Playwright, and not counting them keeps junk floods from
    # bloating the counter dict.
    if not _check_ip_rate(_client_ip()):
        return {"ok": False, "error": "Too many attempts from your address. Try again in an hour."}, 429

    netid = (d.get("netid") or "").strip().lower().split("@")[0] if isinstance(d.get("netid"), str) else ""
    password = d.get("password") if isinstance(d.get("password"), str) else ""
    if not netid or not password:
        return {"ok": False, "error": "netid and password required"}, 400
    if not NETID_RE.match(netid):  # audit: validate before it hits Playwright/DB
        return {"ok": False, "error": "invalid NetID format"}, 400
    if len(password) > 128:
        return {"ok": False, "error": "invalid password"}, 400

    res = fetch_attendance(netid, password)
    if not res["ok"]:
        # audit F4: auth failures are 401; busy/rate are 429/503
        code = 401 if "login failed" in res["error"] else (429 if "Too many" in res["error"] else 503)
        return {"ok": False, "error": res["error"]}, code
    c = db()
    c.execute("INSERT INTO users(netid,password,attendance_json,last_fetch,personal_details_json,photo_b64,marks_json) VALUES(?,?,?,?,?,?,?) "
              "ON CONFLICT(netid) DO UPDATE SET password=excluded.password, attendance_json=excluded.attendance_json, marks_json=excluded.marks_json, "
              "last_fetch=excluded.last_fetch, personal_details_json=excluded.personal_details_json, photo_b64=excluded.photo_b64",
              (netid, encrypt_pw(password), json.dumps(res["data"]), res["fetched"],
               json.dumps(res.get("personal", {})), res.get("photo", ""), json.dumps(res.get("marks", []))))
    c.commit(); c.close()

    # Save timetable group and scraped subjects (non-critical, separate tx)
    try:
        personal = json.loads(json.dumps(res.get("personal", {})))
        gk = _group_key(personal)
        if gk and res.get("courses"):
            c2 = db()
            c2.execute("INSERT INTO timetable_groups(group_key,program,batch,semester,section) "
                       "VALUES(?,?,?,?,?) ON CONFLICT(group_key) DO UPDATE SET updated_at=excluded.updated_at",
                       (gk, personal.get("Program",""), int(personal.get("Batch",0)),
                        _semester_int(personal.get("Semester","")), personal.get("Section","")))
            gid = c2.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()[0]
            for sub in res.get("courses", []):
                c2.execute("INSERT INTO timetable_subjects(group_id,code,name,credits,is_custom) "
                           "VALUES(?,?,?,?,0) ON CONFLICT(group_id,code) DO UPDATE SET name=excluded.name",
                           (gid, sub["code"], sub["name"], sub["credits"]))
            c2.commit(); c2.close()
    except Exception:
        pass

    token = make_session_token(netid)
    resp = make_response({"ok": True})
    resp.set_cookie("srm_session", token, max_age=SESSION_MAX_AGE, httponly=True,
                    samesite="Lax", secure=_cookie_secure())
    return resp

@app.route("/api/refresh", methods=["POST"])
@require_login
def api_refresh():
    netid = get_current_user()
    c = db()
    row = c.execute("SELECT password FROM users WHERE netid=?", (netid,)).fetchone()
    c.close()
    if not row: return {"ok": False, "error": "no stored creds"}
    password = decrypt_pw(row["password"])  # audit: was plaintext, now Fernet
    if not password:
        return {"ok": False, "error": "stored credentials unreadable \u2014 log in again"}
    res = fetch_attendance(netid, password)
    if not res["ok"]:
        # audit F4: match /api/login's status-code discipline
        code = 401 if "login failed" in res["error"] else (429 if "Too many" in res["error"] else 503)
        return {"ok": False, "error": res["error"]}, code
    c = db()
    c.execute("UPDATE users SET attendance_json=?, last_fetch=?, personal_details_json=? WHERE netid=?",
              (json.dumps(res["data"]), res["fetched"], json.dumps(res.get("personal", {})), netid))
    c.commit(); c.close()
    return {"ok": True}

# ── Timetable API ───────────────────────────────────────────────
@app.route("/api/timetable", methods=["GET"])
def api_get_timetable():
    netid = get_current_user()
    if not netid: return {"ok": False, "error": "not logged in"}, 401
    personal = {}
    try:
        c = db()
        r = c.execute("SELECT personal_details_json FROM users WHERE netid=?", (netid,)).fetchone()
        c.close()
        if r and r[0]: personal = json.loads(r[0])
    except: pass
    gk = _group_key(personal)
    if not gk: return {"ok": True, "slots": {}, "subjects": [], "group_key": None}
    c = db()
    gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()
    if not gid: c.close(); return {"ok": True, "slots": {}, "subjects": [], "group_key": gk}
    gid = gid[0]
    slots = {}
    for r in c.execute("SELECT day,period,subject_code,subject_name,location FROM timetable_slots WHERE group_id=?", (gid,)):
        slots[str(r[0]) + "-" + str(r[1])] = {"code": r[2], "name": r[3], "location": r[4] or ""}
    subjects = [{"code":r[0], "name":r[1], "credits":r[2], "custom":bool(r[3])}
                for r in c.execute("SELECT code,name,credits,is_custom FROM timetable_subjects WHERE group_id=?", (gid,))]
    c.close()
    return {"ok": True, "slots": slots, "subjects": subjects, "group_key": gk}

@app.route("/api/timetable", methods=["POST"])
def api_save_timetable():
    netid = get_current_user()
    if not netid: return {"ok": False, "error": "not logged in"}, 401
    data = request.get_json(silent=True) or {}
    slots = data.get("slots", {})
    custom = data.get("custom_subjects", [])
    personal = {}
    try:
        c = db()
        r = c.execute("SELECT personal_details_json FROM users WHERE netid=?", (netid,)).fetchone()
        c.close()
        if r and r[0]: personal = json.loads(r[0])
    except: pass
    gk = _group_key(personal)
    if not gk: return {"ok": False, "error": "could not determine group"}, 400
    c = db()
    c.execute("INSERT INTO timetable_groups(group_key,program,batch,semester,section) "
              "VALUES(?,?,?,?,?) ON CONFLICT(group_key) DO UPDATE SET updated_at=excluded.updated_at",
              (gk, personal.get("Program",""), int(personal.get("Batch",0)),
               _semester_int(personal.get("Semester","")), personal.get("Section","")))
    gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()[0]
    for sub in custom:
        c.execute("INSERT INTO timetable_subjects(group_id,code,name,credits,is_custom) "
                  "VALUES(?,?,?,0,1) ON CONFLICT(group_id,code) DO UPDATE SET name=excluded.name",
                  (gid, sub["code"], sub["name"]))
    c.execute("DELETE FROM timetable_slots WHERE group_id=?", (gid,))
    for key, val in slots.items():
        if val:
            parts = key.rsplit("-", 1)
            if len(parts) == 2:
                day, period = parts
                c.execute("INSERT INTO timetable_slots(group_id,day,period,subject_code,subject_name) "
                          "VALUES(?,?,?,?,?)", (gid, day, int(period), val.get("code",""), val.get("name","")))
    c.commit(); c.close()
    return {"ok": True}

@app.route("/logout")
def logout():
    token = request.cookies.get("srm_session")
    if token:
        c = db(); c.execute("DELETE FROM cookies WHERE token=?", (token,)); c.commit(); c.close()
    resp = make_response(redirect("/login"))
    # audit F2 fix: same flags on the clearing path — recon saw a bare
    # 'Secure; Path=/' Set-Cookie here because delete_cookie didn't inherit them
    resp.delete_cookie("srm_session", secure=_cookie_secure(), httponly=True, samesite="Lax")
    return resp

# Pre-warm ddddocr on import so the first real scrape isn't +3s cold.
import threading as _tw

_tw.Thread(target=get_solver, daemon=True, name="srm-captcha-prewarm").start()

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

