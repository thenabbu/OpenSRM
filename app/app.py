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
import os, json, base64, time, asyncio, sqlite3, secrets, math, re, threading
from functools import wraps
from app.timetable import timetable_html
from flask import Flask, request, redirect, render_template_string, make_response, g

LOGIN_URL = "https://sp.srmist.edu.in/srmiststudentportal/students/loginManager/youLogin.jsp"

DATA_DIR = "/app/data"
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

CAPTCHA_JS = """() => {
    const img = document.querySelector('img[alt="Captcha"]');
    if (!img) return null;
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    c.getContext('2d').drawImage(img, 0, 0);
    return c.toDataURL('image/png').split(',')[1];
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
        executable_path="/usr/bin/chromium",
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
        except Exception:
            await ctx.close()
            return {"ok": False, "error": "login failed (wrong creds or captcha misread)"}

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

        return {"ok": True, "data": data, "personal": personal, "photo": photo_b64, "fetched": int(time.time())}
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
        return {"ok": False, "error": "scrape worker died: %s" % e}
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
        "default-src 'self'; script-src 'self'; "  # F3: scripts externalized; style keeps unsafe-inline (Jinja-interpolated dash CSS)
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; worker-src 'self'; manifest-src 'self'")
    resp.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    return resp

# ── HTML Templates ─────────────────────────────────────────────────

LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/x-icon" href="/static/favicon.ico">
<link rel="icon" type="image/png" sizes="192x192" href="/static/icon-192.png">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<link rel="manifest" href="/static/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="OpenSRM">
<link rel="manifest" href="/static/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="OpenSRM">
<meta name="description" content="Self-hosted attendance dashboard for the SRM Student Portal. Fast, clean, multi-user.">
<meta name="theme-color" content="#0a0a0a">
<meta name="robots" content="noindex, nofollow">
<meta property="og:type" content="website">
<meta property="og:title" content="OpenSRM — Student Attendance Dashboard">
<meta property="og:description" content="Self-hosted attendance dashboard for the SRM Student Portal.">
<meta property="og:image" content="https://srm.200871.xyz/static/icon-512.png">
<meta property="og:url" content="https://srm.200871.xyz">
<meta property="og:site_name" content="OpenSRM">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="OpenSRM — Student Attendance Dashboard">
<meta name="twitter:description" content="Self-hosted attendance dashboard for the SRM Student Portal.">
<meta name="twitter:image" content="https://srm.200871.xyz/static/icon-512.png">
<title>OpenSRM</title>
<link rel="stylesheet" href="/static/login.css"></head><body>
<div class="box">
  <div class="brand">
    <img class="brand-mark" src="/static/icon-192.png" alt="OpenSRM" width="36" height="36">
    <div><h1>OpenSRM</h1><p>Self-hosted portal sync</p></div>
  </div>
  <form id="f">
    <input type="text" id="netid" name="netid" placeholder="Net ID" required
      autocomplete="username" autocapitalize="off" autocorrect="off" pattern="[a-zA-Z0-9]{2,20}" maxlength="20">
    <input type="password" id="pw" name="password" placeholder="Password" required
      autocomplete="current-password" maxlength="128">
    <button type="submit" id="b">
      <span class="spinner"></span><span id="btnLabel">Sign in</span>
    </button>
  </form>
  <div class="status" id="status" role="alert" aria-live="polite"></div>
  <p class="hint">Logs into the SRM student portal and pulls your attendance.<br>Takes about 15 seconds.</p>
</div>
<script src="/static/login.js"></script></body></html>"""

DASH_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/x-icon" href="/static/favicon.ico">
<link rel="icon" type="image/png" sizes="192x192" href="/static/icon-192.png">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<meta name="description" content="OpenSRM attendance dashboard for {{ netid }}.">
<meta name="theme-color" content="#0a0a0a">
<meta name="robots" content="noindex, nofollow">
<meta property="og:type" content="website">
<meta property="og:title" content="OpenSRM — {{ netid }}">
<meta property="og:description" content="Student attendance dashboard for the SRM Student Portal.">
<meta property="og:image" content="https://srm.200871.xyz/static/icon-512.png">
<meta property="og:url" content="https://srm.200871.xyz">
<meta property="og:site_name" content="OpenSRM">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="OpenSRM — {{ netid }}">
<meta name="twitter:description" content="Student attendance dashboard for the SRM Student Portal.">
<meta name="twitter:image" content="https://srm.200871.xyz/static/icon-512.png">
<title>OpenSRM \u2014 {{ netid }}</title>
<style>
:root{--bg:#111111;--panel:#161616;--panel-2:#1e1e1e;--border:#2a2a2a;
  --text:#ffffff;--muted:#b0b0b0;--dim:#888888;
  --accent:#ffffff;--accent-hover:#d0d0d0;
  --ok:#4ade80;--warn:#fbbf24;--danger:#f87171;--radius:8px}
*{box-sizing:border-box}
body{font-family:'IBM Plex Sans',-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;
  font-size:14px;line-height:1.5;background:var(--bg);color:var(--text);margin:0;padding-bottom:60px}
h2{font-size:16px;font-weight:600;margin:0 0 10px}
a{color:var(--muted)}
.topbar{position:sticky;top:0;z-index:20;display:flex;justify-content:space-between;
  align-items:center;padding:12px 20px;background:rgba(38,38,38,.94);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--border);box-shadow:0 1px 2px rgba(0,0,0,.3)}
.topbar-id{display:flex;align-items:center;gap:10px;min-width:0}
.topbar-avatar{width:32px;height:32px;border-radius:50%;object-fit:cover;border:1px solid var(--border)}
.topbar-avatar-fallback{width:32px;height:32px;border-radius:50%;background:var(--panel);color:var(--text);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;font-family:'IBM Plex Mono',monospace;border:1px solid var(--border)}
.topbar-id strong{display:block;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.topbar-id span{display:block;font-size:11px;color:var(--dim)}
.topbar-actions{display:flex;align-items:center;gap:14px}
.btn-refresh{display:flex;align-items:center;gap:6px;background:var(--panel-2);color:var(--text);border:1px solid var(--border);
  padding:8px 14px;border-radius:4px;cursor:pointer;font-size:13px;font-weight:500}
.btn-refresh:hover{background:var(--border)}
.btn-refresh:disabled{background:var(--border);color:var(--dim);cursor:wait}
.btn-refresh .icon{display:inline-block}
.btn-refresh.spinning .icon{animation:spin 1s linear infinite}
.btn-logout{color:var(--muted);text-decoration:none;font-size:13px}
.btn-logout:hover{color:var(--text);text-decoration:underline}
@keyframes spin{to{transform:rotate(360deg)}}
.overlay{position:fixed;inset:0;background:rgba(17,17,17,.92);display:none;align-items:center;
  justify-content:center;flex-direction:column;gap:14px;z-index:50;font-size:13.5px;color:var(--muted)}
.overlay.show{display:flex}
.overlay-spinner{width:32px;height:32px;border-radius:50%;border:3px solid var(--border);
  border-top-color:var(--text);animation:spin .8s linear infinite}
main.wrap{max-width:960px;margin:0 auto;padding:20px}
section{margin-bottom:28px}
.period-chip{display:inline-block;background:var(--panel);border:1px solid var(--border);
  color:var(--muted);padding:6px 12px;border-radius:999px;font-size:12px;margin-bottom:18px}
.period-chip.warn{border-color:var(--warn);color:var(--warn)}
.hero-card{display:flex;align-items:center;gap:22px;background:var(--panel);
  border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:28px}
.hero-card--ok{--ring:var(--ok)} .hero-card--warn{--ring:var(--warn)} .hero-card--danger{--ring:var(--danger)}
.hero-ring{--size:92px;width:var(--size);height:var(--size);border-radius:50%;flex:0 0 auto;
  position:relative;background:conic-gradient(var(--ring) calc(var(--pct)*1%), var(--border) 0)}
.hero-ring::before{content:"";position:absolute;inset:8px;background:var(--panel);border-radius:50%}
.hero-pct{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-family:'IBM Plex Mono',monospace;font-size:19px;font-weight:700}
.hero-detail h2{margin-bottom:3px}
.hero-sub{margin:0 0 6px;color:var(--muted);font-size:13px}
.hero-bunk{margin:0;font-size:13px;color:var(--ring);font-weight:500}
.hero-period{margin:4px 0 0;font-size:11px;color:var(--dim);font-weight:400}
#offline-banner{position:fixed;bottom:0;left:0;right:0;background:var(--warn);color:var(--bg);text-align:center;padding:8px;font-size:13px;z-index:100;font-weight:500}
.empty{color:var(--dim);font-size:13px;padding:16px;background:var(--panel);
  border:1px dashed var(--border);border-radius:var(--radius);text-align:center}
.course-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.course-card{background:var(--panel);border:1px solid var(--border);border-left:3px solid var(--status);
  border-radius:var(--radius);padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.course-card--ok{--status:var(--ok)} .course-card--warn{--status:var(--warn)} .course-card--danger{--status:var(--danger)}
.course-top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.course-code{font-family:'IBM Plex Mono',monospace;font-weight:600}
.course-pct{font-family:'IBM Plex Mono',monospace;font-weight:700;color:var(--status)}
.course-desc{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.course-bar{height:5px;border-radius:3px;background:var(--border);overflow:hidden}
.course-bar-fill{height:100%;background:var(--status);border-radius:3px;transition:width .3s}
.course-stats{display:flex;gap:10px;font-size:11px;color:var(--dim);font-family:'IBM Plex Mono',monospace;flex-wrap:wrap}
.course-bunk{font-size:12px;color:var(--muted);border-top:1px solid var(--border);padding-top:8px}
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--border);border-radius:var(--radius)}
table.month-table{border-collapse:collapse;width:100%;min-width:540px}
table.month-table th,table.month-table td{padding:10px 12px;font-size:12.5px;text-align:left;border-bottom:1px solid var(--border)}
table.month-table th{color:var(--dim);font-weight:600;font-size:11.5px}
table.month-table td{font-family:'IBM Plex Mono',monospace}
table.month-table tr:last-child td{border-bottom:none}
table.month-table tr:hover td{background:var(--panel-2)}
.month-bar-cell{min-width:120px;display:flex;align-items:center;gap:8px}
.month-bar{height:5px;background:var(--border);border-radius:3px;overflow:hidden;width:60px;flex:0 0 auto}
.month-bar-fill{height:100%;background:var(--ok)}
.month-bar-label{font-size:11px;color:var(--dim)}
details.absent-month{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:8px;overflow:hidden}
details.absent-month summary{cursor:pointer;padding:12px 16px;font-weight:600;display:flex;justify-content:space-between;align-items:center;list-style:none}
details.absent-month summary::-webkit-details-marker{display:none}
details.absent-month summary::before{content:"\u25b8";color:var(--accent);margin-right:8px;display:inline-block;transition:transform .15s}
details.absent-month[open] summary::before{transform:rotate(90deg)}
.absent-count{font-size:11px;color:var(--dim);font-weight:400}
.absent-list{border-top:1px solid var(--border)}
.absent-row{display:flex;justify-content:space-between;padding:8px 16px;font-size:12.5px;font-family:'IBM Plex Mono',monospace;color:var(--muted)}
.absent-row:nth-child(odd){background:rgba(255,255,255,.02)}
.tt-wrap{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px}
.tt-hero{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:6px;background:var(--panel-2);margin-bottom:14px;border-left:3px solid var(--border)}
.tt-hero strong{display:block;font-size:13.5px;font-weight:600}
.tt-hero-sub,.tt-hero-loc{font-size:11.5px;color:var(--dim)}
.tt-hero--now{border-left-color:var(--ok)} .tt-hero--next{border-left-color:var(--accent)}
.tt-hero--break{border-left-color:var(--warn)}
.tt-hero-dot{width:8px;height:8px;border-radius:50%;flex:0 0 auto}
.tt-hero-dot--now{background:var(--ok)} .tt-hero-dot--next{background:var(--accent)}
.tt-hero-dot--break{background:var(--warn)} .tt-hero-dot--off{background:var(--dim)}
.tt-radio{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}
.tt-tabbar{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}
.tt-tabbar label{padding:6px 14px;border-radius:999px;background:var(--panel-2);color:var(--muted);font-size:12.5px;cursor:pointer;position:relative}
.tt-tabbar label.tt-today::after{content:"";position:absolute;top:5px;right:6px;width:5px;height:5px;border-radius:50%;background:var(--accent)}
#day-Monday:checked~.tt-tabbar label[for="day-Monday"],#day-Tuesday:checked~.tt-tabbar label[for="day-Tuesday"],#day-Wednesday:checked~.tt-tabbar label[for="day-Wednesday"],#day-Thursday:checked~.tt-tabbar label[for="day-Thursday"],#day-Friday:checked~.tt-tabbar label[for="day-Friday"]{background:var(--accent);color:#fff}
.day-panel{display:none;flex-direction:column;gap:6px}
#day-Monday:checked~.panels #panel-Monday,#day-Tuesday:checked~.panels #panel-Tuesday,#day-Wednesday:checked~.panels #panel-Wednesday,#day-Thursday:checked~.panels #panel-Thursday,#day-Friday:checked~.panels #panel-Friday{display:flex}
.tt-row{display:flex;align-items:center;gap:12px;padding:9px 12px;border-radius:6px;border:1px solid transparent}
.tt-row:nth-child(odd){background:rgba(255,255,255,.02)}
.tt-row--current{border-color:var(--ok);background:rgba(66,190,101,.08)}
.tt-row--upcoming{border-color:var(--accent);background:rgba(255,255,255,.08)}
.tt-time{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--dim);flex:0 0 60px}
.tt-time small{display:block;color:var(--dim)}
.tt-info{flex:1;min-width:0;display:flex;flex-direction:column}
.tt-info strong{font-size:13px;font-family:'IBM Plex Mono',monospace}
.tt-name{font-size:11.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tt-loc{font-size:11px;color:var(--dim)}
.tt-badge{font-size:10.5px;padding:2px 9px;border-radius:999px;background:var(--ok);color:var(--ok);font-weight:600}
.tt-badge--soon{background:var(--text);color:var(--bg)}
.tt-divider{font-size:11px;color:var(--dim);text-align:center;padding:4px 0}
@media(max-width:600px){.topbar{padding:10px 14px}main.wrap{padding:14px}
  .hero-card{flex-direction:column;align-items:flex-start;text-align:left;padding:16px}
  .hero-ring{--size:84px}
  .course-grid{grid-template-columns:1fr}
  .topbar-actions{gap:10px}
  /* Personal Details: on phone, use a clean grouped card layout.
     Key = small muted label on its own line, value = prominent below,
     each field in a padded card cell with consistent spacing. */
  .personal-grid{background:var(--panel);border:0;border-radius:var(--radius);overflow:hidden}
  .personal-row{flex-direction:column;padding:12px 16px;border:0;border-bottom:1px solid var(--border)}
  .personal-row:last-child{border-bottom:none}
  .personal-key{flex:none;width:100%;margin-bottom:2px;font-size:11.5px;color:var(--dim);text-transform:uppercase;letter-spacing:.4px;font-weight:600}
  .personal-val{flex:1;width:100%;font-size:14px;word-break:break-word;color:var(--text);line-height:1.4}
  /* Timetable: give the class name room on narrow screens. */
  .tt-time{flex:0 0 48px;font-size:11px}
  .tt-badge{white-space:nowrap}}

/* -- Tabs -- */
.tab-bar{display:flex;gap:0;border-bottom:2px solid var(--border);margin-bottom:20px}
.tab-bar button{flex:1;padding:10px 0;background:none;border:none;border-bottom:2px solid transparent;
  color:var(--muted);font-size:13px;font-weight:500;cursor:pointer;transition:all .15s;margin-bottom:-2px}
.tab-bar button:hover{color:var(--text)}
.tab-bar button.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-panel{display:none}
.tab-panel.active{display:block}
.personal-grid{display:grid;gap:0;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
.personal-row{display:flex;border-bottom:1px solid var(--border);font-size:13px}
.personal-row:last-child{border-bottom:none}
.personal-key{flex:0 0 180px;padding:10px 14px;color:var(--dim);font-weight:500;background:var(--panel)}
.personal-val{flex:1;padding:10px 14px;font-family:'IBM Plex Mono',monospace}
</style></head><body>

<div class="topbar">
  <div class="topbar-id">
    {% if photo %}<img class="topbar-avatar" src="data:image/jpeg;base64,{{ photo }}" alt="{{ netid }}">{% else %}<span class="topbar-avatar-fallback">{{ netid[:2]|upper }}</span>{% endif %}
    <div><strong>{{ netid }}</strong>
      <span id="lastSync" data-ts="{{ last_epoch }}" data-full="{{ last }} UTC">{{ last }} UTC</span>
    </div>
  </div>
  <div class="topbar-actions">
    <button class="btn-refresh" id="refreshBtn">
      <span class="icon">\u27f3</span><span>Refresh</span>
    </button>
    <a class="btn-logout" href="/logout">Log out</a>
  </div>
</div>

<div class="overlay" id="overlay">
  <div class="overlay-spinner"></div>
  <div>Syncing attendance\u2026</div>
</div>

<main class="wrap">
  {% if hours_old and hours_old > 24 %}
  <div class="period-chip warn">⚠ Data is {{ hours_old }} hours old — click Refresh</div>
  {% endif %}

  <div class="tab-bar">
    <button class="active" data-tab="attendance">Attendance</button>
    <button data-tab="timetable">Timetable</button>
    <button data-tab="personal">Personal Details</button>
  </div>

  <div id="tab-attendance" class="tab-panel active">
    <section class="hero-card hero-card--{{ overall.status }}">
      <div class="hero-ring" style="--pct: {{ overall.pct }}">
        <span class="hero-pct">{{ overall.pct }}%</span>
      </div>
      <div class="hero-detail">
        <h2>Overall attendance</h2>
        <p class="hero-sub">{{ overall.attended }} of {{ overall.max_hours }} hours attended</p>
        {% if overall.bunk_line %}<p class="hero-bunk">{{ overall.bunk_line }}</p>{% endif %}
        {% if period %}<p class="hero-period">{{ period.from }} → {{ period.to }}</p>{% endif %}
      </div>
    </section>

    {% if not has_data %}
    <div class="empty">No attendance data yet. Hit refresh once a sync has completed.</div>
    {% endif %}

    <section>
      <h2>Courses</h2>
      <div class="course-grid">
        {% for c in courses %}
        <div class="course-card course-card--{{ c.status }}">
          <div class="course-top">
            <span class="course-code">{{ c.code }}</span>
            <span class="course-pct">{{ c.pct }}%</span>
          </div>
          <div class="course-desc" title="{{ c.description }}">{{ c.description }}</div>
          <div class="course-bar"><div class="course-bar-fill" style="width: {{ c.pct }}%"></div></div>
          <div class="course-stats">
            <span>{{ c.attended }} attended</span><span>{{ c.absent }} absent</span><span>{{ c.max_hours }} total</span>
          </div>
          {% if c.bunk_line %}<div class="course-bunk">{{ c.bunk_line }}</div>{% endif %}
        </div>
        {% endfor %}
      </div>
    </section>

    <section>
      <h2>Monthly attendance</h2>
      <div class="table-scroll">
        <table class="month-table"><thead><tr>
          <th>Month</th><th>Present</th><th>Absent</th><th>OD (P)</th><th>OD (A)</th><th>ML</th><th></th>
        </tr></thead><tbody>
        {% for m in monthly %}
        <tr>
          <td>{{ m.month }}</td><td>{{ m.present }}</td><td>{{ m.absent }}</td>
          <td>{{ m.od_present }}</td><td>{{ m.od_absent }}</td><td>{{ m.ml }}</td>
          <td>{% if m.pct is not none %}
            <div class="month-bar-cell">
              <div class="month-bar"><div class="month-bar-fill" style="width: {{ m.pct }}%"></div></div>
              <span class="month-bar-label">{{ m.pct }}%</span>
            </div>{% endif %}
          </td>
        </tr>
        {% endfor %}
        </tbody></table>
      </div>
    </section>

    <section>
      <h2>Daily absences</h2>
      {% if daily_absent %}
        {% for month, days in daily_absent.items() %}
        <details class="absent-month" {% if loop.first %}open{% endif %}>
          <summary><span>{{ month }}</span>
            <span class="absent-count">{{ days|length }} day{{ '' if days|length == 1 else 's' }}</span>
          </summary>
          <div class="absent-list">
            {% for d in days %}<div class="absent-row"><span>{{ d.date }}</span><span>{{ d.hours }} hr</span></div>{% endfor %}
          </div>
        </details>
        {% endfor %}
      {% else %}
        <p class="empty">No absences recorded — perfect attendance across all months.</p>
      {% endif %}
    </section>
  </div>

  <div id="tab-timetable" class="tab-panel">
    {{ timetable|safe }}
  </div>

  <div id="tab-personal" class="tab-panel">
    {% if personal %}
    <div class="personal-grid">
      {% for key, value in personal.items() %}
      <div class="personal-row">
        <span class="personal-key">{{ key }}</span>
        <span class="personal-val">{{ value }}</span>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <div class="empty">No personal details available yet. Click Refresh to fetch.</div>
    {% endif %}
  </div>
</main>

<script src="/static/dash.js"></script>
<script>
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/sw.js', {scope: '/'}).catch(function(){});
}
</script>
</body></html>"""

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

    return render_template_string(
        DASH_HTML, netid=netid, courses=courses, monthly=monthly, overall=overall,
        period=data.get("period"), photo=row["photo_b64"] if row and "photo_b64" in row.keys() else "", daily_absent=data.get("daily_absent", {}),
        last=last, last_epoch=last_epoch, hours_old=hours_old, has_data=bool(courses),
        timetable=timetable_html(),
        personal=json.loads(row["personal_details_json"]) if row and row["personal_details_json"] else {})

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
    return render_template_string(LOGIN_HTML)

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

    netid = (d.get("netid") or "").strip().lower() if isinstance(d.get("netid"), str) else ""
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
    c.execute("INSERT INTO users(netid,password,attendance_json,last_fetch,personal_details_json,photo_b64) VALUES(?,?,?,?,?,?) "
              "ON CONFLICT(netid) DO UPDATE SET password=excluded.password, attendance_json=excluded.attendance_json, "
              "last_fetch=excluded.last_fetch, personal_details_json=excluded.personal_details_json, photo_b64=excluded.photo_b64",
              (netid, encrypt_pw(password), json.dumps(res["data"]), res["fetched"],
               json.dumps(res.get("personal", {})), res.get("photo", "")))
    c.commit(); c.close()
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