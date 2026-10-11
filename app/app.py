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
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from functools import wraps
from html import escape as _hesc  # audit: escape DB values before |safe timetable HTML
from html import unescape as _hescu
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

# timetable_html is now defined locally (SQLite-backed)
from flask import Flask, make_response, redirect, render_template, request
from werkzeug.exceptions import HTTPException

from . import push_calc, push_send, push_store
from .logging_setup import log_with_kv, setup_logging
from .migrations import migrate_db

LOGIN_URL = "https://sp.srmist.edu.in/srmiststudentportal/students/loginManager/youLogin.jsp"

# Single source of truth for the visible app version (task 16).
# Bump policy: patch = fix, minor = feature, major = breaking/user-visible redesign.
with open(os.path.join(os.path.dirname(__file__), "..", "VERSION")) as _vf:
    APP_VERSION = _vf.read().strip()

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "srm.db")
_secret_path = os.path.join(DATA_DIR, "secret")
if not os.path.exists(_secret_path):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_secret_path, "w") as f:
        f.write(secrets.token_hex(32))
    os.chmod(_secret_path, 0o600)
SECRET = open(_secret_path).read().strip()

# audit 2026-09-27: disable Flask's built-in /static route — it registers the
# SAME rule as static_no_cache() below and wins the match (registered first),
# so that function never ran anywhere: no Service-Worker-Allowed header, no
# intended cache policy. Nothing calls url_for('static'), so removal is safe.
app = Flask(__name__, static_folder=None)
app.secret_key = SECRET
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # audit: bound request bodies

from blobatar.flask import init_app as _init_blobatar

_init_blobatar(app)  # GET /avatar/<name> + `blobatar` Jinja filter

setup_logging()
log = logging.getLogger("opensrm")
log_http = logging.getLogger("opensrm.http")
log_auth = logging.getLogger("opensrm.auth")
log_portal = logging.getLogger("opensrm.portal")
log_db = logging.getLogger("opensrm.db")

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
    except Exception as e:
        log.warning("stored password unreadable — user must re-login: %r", e)
        return ""

def _import_legacy_timetable():
    """One-time import: timetable.json -> SQLite for existing users.
    Re-runnable: deletes the group's slots first, so a corrected importer
    repairs previously-shifted data on next boot."""
    paths = [os.path.join(os.path.dirname(__file__), "data", "timetable.json"),
             os.path.join(DATA_DIR, "timetable.json")]
    json_path = next((p for p in paths if os.path.exists(p)), None)
    if not json_path: return
    # audit B11: open+parse INSIDE the try — a corrupt legacy timetable.json
    # used to escape init_db() at import time and crash-loop the container
    c = db()
    try:
        with open(json_path) as f:
            data = json.load(f)
        # Infer group from the imported timetable's known cohort data
        group_key = "Computer Science and Engineering Cloud Computing_2025_3_A"
        c.execute("INSERT OR IGNORE INTO timetable_groups(group_key,program,batch,semester,section) "
                  "VALUES(?,?,?,?,?)", (group_key, "B.Tech.-CSE Cloud Computing", 2025, 3, "A"))
        gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (group_key,)).fetchone()[0]
        c.execute("DELETE FROM timetable_slots WHERE group_id=?", (gid,))
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
                                      "VALUES(?,?,?,0,0)", (gid, code, course.get("description","")))
        # Import slots from JSON. Rows include BREAK/LUNCH entries — those are
        # rendered as dividers from SLOTS, NOT stored as class periods. Map each
        # class row to its period by START TIME (SLOTS defines the grid); the old
        # index→period mapping shifted classes after breaks and clamped the
        # 8th row away (AWS/VA vanished from Thu/Tue).
        _slot_start = {s["start"]: s["period"] for s in SLOTS if s["type"] == "class"}
        for day, slots in data.items():
            for s in slots:
                per = _slot_start.get(s.get("start", ""))
                if not per:
                    continue  # break/lunch rows or unknown times
                c.execute("INSERT OR IGNORE INTO timetable_slots(group_id,day,period,subject_code,subject_name,location) "
                          "VALUES(?,?,?,?,?,?)", (gid, day, per, s.get("code",""), s.get("name",""), s.get("location","")))
        c.commit()
        os.rename(json_path, json_path + ".bak")   # only consume on success
    except Exception:
        log.exception("legacy timetable import failed")
    c.close()

def db():

    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    migrate_db(c)  # versioned migration system — handles all schema upgrades
    _import_legacy_timetable()
    c.close()

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
    row = c.execute("SELECT netid, created FROM cookies WHERE token=?", (token,)).fetchone()
    if row and time.time() - row["created"] > SESSION_MAX_AGE:
        # audit 2026-09-27: enforce expiry at READ time. Previously pruning
        # happened only inside make_session_token() (i.e. when that same user
        # logged in again), so a leaked srm_session cookie stayed valid
        # server-side indefinitely — the 30-day client cookie was the only cap.
        c.execute("DELETE FROM cookies WHERE token=?", (token,))
        c.commit()
        row = None
    c.close()
    return row["netid"] if row else None

def make_session_token(netid):
    token = secrets.token_hex(32)
    c = db()
    # incident 2026-10-10: this previously ran `DELETE FROM cookies WHERE
    # netid=?` — one session per account, globally. Every login on any device
    # silently evicted every other device's session: over Sep 22 - Oct 10 the
    # main account logged in 58 times from 13 IPs, and 41 of those 58 re-logins
    # were its OWN earlier login killing the current session (33 from a
    # different IP = cross-device). Sessions are now concurrent per account,
    # each still bounded by SESSION_MAX_AGE at read time.
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

# audit: Only trust CF headers when request came through Cloudflare (cf-ray present)
def _behind_cf():
    return bool(request.headers.get("cf-ray"))

def _cookie_secure():
    return _behind_cf() and request.headers.get("X-Forwarded-Proto") == "https"

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
        await new Promise(r => setTimeout(r, 100));
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

# ── Session cache: skip login when cookies are still valid ──────────
_SESSION_CACHE_TTL = 4 * 3600  # 4 hours

def _save_session(netid, cookies_json):
    """Persist portal cookies for session reuse (portal_sessions table)."""
    c = db()
    c.execute("INSERT OR REPLACE INTO portal_sessions(netid, cookies_json, created) VALUES(?, ?, ?)",
              (netid, cookies_json, int(time.time())))
    c.commit(); c.close()

def _load_session(netid):
    """Load cached portal cookies if still valid (< TTL)."""
    c = db()
    row = c.execute("SELECT cookies_json, created FROM portal_sessions WHERE netid=?", (netid,)).fetchone()
    c.close()
    if not row: return None
    if time.time() - row["created"] > _SESSION_CACHE_TTL:
        return None  # expired
    return row["cookies_json"]

def _clear_session(netid):
    """Remove cached portal cookies (on failed session restore)."""
    c = db()
    c.execute("DELETE FROM portal_sessions WHERE netid=?", (netid,))
    c.commit(); c.close()

# ── Login progress (in-memory; single worker) ────────────────────────
_login_progress = {}  # netid -> {"step": str, "ts": int, "pct": int}

def _set_progress(netid, step, pct):
    _login_progress[netid] = {"step": step, "ts": int(time.time()), "pct": pct}

# ── Rate limiting ──────────────────────────────────────────────────
# Two independent limits:
#   per-netid scrape limit — portal-friendliness (each scrape = real SRM login)
#   per-IP login limit    — brute-force protection (netid rotation-proof)
_login_attempts = {}   # netid -> [ts, ...]  (scrapes, 10-min window)
_ip_attempts = {}      # ip -> [ts, ...]    (login POSTs, 1-hour window)
_RATE_CAP = 10000      # ponytail: memory exhaustion guard; upgrade to LRU if throughput matters
_rate_lock = threading.Lock()  # audit: check-and-append is atomic only under one lock shared by gthread workers

# audit 2026-09-27: AGGREGATE cap on outbound portal-bound work. Per-netid and
# per-IP limits don't bind an attacker rotating source IPs: N IPs => N*10
# attempts/hour through OUR single egress IP — which is exactly how the portal
# rate-limits/bans the server and takes every user down with it. Counts jobs
# that actually reach the pipeline (sync + preflight), not rejected requests.
_portal_attempts = []  # timestamps, 10-min window
_PORTAL_CAP = 30       # across all clients, all netids

def _check_portal_budget():
    now = time.time()
    with _rate_lock:
        _portal_attempts[:] = [t for t in _portal_attempts if now - t < 600]
        if len(_portal_attempts) >= _PORTAL_CAP:
            return False
        _portal_attempts.append(now)
        return True

def _check_rate(netid):
    now = time.time()
    with _rate_lock:
        if len(_login_attempts) > _RATE_CAP:
            # audit: clear() wiped EVERYONE's counters (a flood resets the cap
            # for all) — drop only stale keys instead
            for k in [k for k, v in _login_attempts.items() if not v or now - max(v) >= 600]:
                _login_attempts.pop(k, None)
            if len(_login_attempts) > _RATE_CAP * 2:  # ponytail: blowout guard; 20k live netids impossible here
                _login_attempts.clear()
        attempts = _login_attempts.get(netid, [])
        _login_attempts[netid] = [t for t in attempts if now - t < 600]
        if len(_login_attempts[netid]) >= 3:
            return False
        _login_attempts[netid].append(now)
        return True

def _retry_text(oldest, window):
    """Guide §5 core: honest countdown from a window's oldest entry, so the
    promise can't drift from what the matching checker will actually allow."""
    left = max(1, int(window - (time.time() - oldest)))
    return f"{left} seconds" if left < 90 else f"{(left + 59) // 60} minutes"


def _ip_retry_text(ip):
    """Guide §5: an honest lockout message names the remaining time instead of
    "try again later". Reads the SAME window _check_ip_rate prunes against, so
    the countdown can't drift from the actual limit."""
    with _rate_lock:
        oldest = min(_ip_attempts.get(ip) or [time.time()])
    return _retry_text(oldest, 3600)


def _netid_retry_text(netid):
    """Per-netid sync cap countdown. The old message promised a flat
    "10 minutes" while the sliding window could have <2 minutes left — users
    were told to wait five times longer than the actual lockout."""
    with _rate_lock:
        oldest = min(_login_attempts.get(netid) or [time.time()])
    return _retry_text(oldest, 600)


def _check_ip_rate(ip):
    now = time.time()
    with _rate_lock:
        if len(_ip_attempts) > _RATE_CAP:
            # audit: same as _login_attempts — prune stale keys, don't reset everyone
            for k in [k for k, v in _ip_attempts.items() if not v or now - max(v) >= 3600]:
                _ip_attempts.pop(k, None)
            if len(_ip_attempts) > _RATE_CAP * 2:  # ponytail: blowout guard
                _ip_attempts.clear()
        attempts = _ip_attempts.get(ip, [])
        _ip_attempts[ip] = [t for t in attempts if now - t < 3600]
        if len(_ip_attempts[ip]) >= 10:
            return False
        _ip_attempts[ip].append(now)
        return True

# -- Portal cooldown ------------------------------------------------
# When the SRM portal silently rejects logins (rate-limiting our IP),
# pause ALL login attempts to avoid worsening the block.
_portal_cooldown_until = 0   # unix timestamp; 0 = no cooldown
_portal_consecutive_fails = 0
_request_fail_counted = False

def _portal_fail():
    global _portal_cooldown_until, _portal_consecutive_fails
    _portal_consecutive_fails += 1
    if _portal_consecutive_fails >= 3:
        minutes = min(30, 5 * (2 ** (_portal_consecutive_fails - 3)))
        _portal_cooldown_until = time.time() + minutes * 60
        log.warning("portal cooldown %d min after %d consecutive fails",
                     minutes, _portal_consecutive_fails)

def _portal_fail_once():
    """Count ONE fail per login request, not one per captcha retry inside it.
    ponytail: per-user isolation needs per-netid counters — add when multi-user load is real."""
    global _portal_consecutive_fails, _request_fail_counted
    if _request_fail_counted:
        return
    _request_fail_counted = True
    _portal_fail()

def _portal_ok():
    global _portal_cooldown_until, _portal_consecutive_fails
    _portal_consecutive_fails = 0
    _portal_cooldown_until = 0

def _portal_cooldown_remaining():
    remaining = _portal_cooldown_until - time.time()
    return max(0, remaining)

def _client_ip():
    # Only trust CF-Connecting-IP when request came through Cloudflare.
    # Direct access spoofing the header would bypass rate limiting otherwise.
    if _behind_cf():
        return request.headers.get("CF-Connecting-IP") or request.remote_addr or "?"
    return request.remote_addr or "?"

# ── HTML parsing ───────────────────────────────────────────────────
def _cells(row_html):
    return [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]

# audit: portal dates ('12/09/2026', '12-Sep-2026') also match the score
# pattern \d+/\d+ — parsers must recognize date cells before scanning scores
_DATE_CELL_RE = re.compile(r"\d{1,2}[/ -](?:\w{3,9}|\d{1,2})[/ -]\d{2,4}")

ROMAN = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10}

def _semester_int(semester_str):
    """Convert 'III SEMESTER' -> 3. Empty/None -> 0: split()[0] raised
    IndexError (probe-verified) and 500'd every page calling _group_key."""
    parts = (semester_str or "").split()
    return ROMAN.get(parts[0].strip(), 0) if parts else 0

def _program_short(program):
    """Portal Program -> stable branch id: drop the bracketed suffix and the
    'B.Tech.-'/'with specialization in' boilerplate, so the same programme
    always maps to one string ('...Cloud Computing[UG - FT - ACADEMIC]' ->
    'Computer Science and Engineering Cloud Computing')."""
    short = re.sub(r"\[.*?\]", "", program).strip()
    short = re.sub(r"B\.Tech\.\s*-\s*", "", short).strip()
    short = re.sub(r"with specialization in\s*", "", short).strip()
    return short.replace(",", "")

def _group_key(personal):
    """Extract timetable group from personal details dict."""
    program = re.sub(r"\[.*?\]", "", personal.get("Program", "")).strip()
    batch = personal.get("Batch", "")
    semester = _semester_int(personal.get("Semester", ""))
    section = personal.get("Section", "")
    if not all([program, batch, semester, section]):
        return None
    return f"{_program_short(program)}_{batch}_{semester}_{section}"

def _class_key(personal, netid):
    """Class context for component tags: year|branch|section — deliberately no
    semester, because a teacher's components belong to the whole class every
    term (one student's confirmation then applies to the whole class).
    ponytail: a profile missing any field falls back to a per-student key
    instead of a shared '?' bucket, so an incomplete profile can never leak a
    tag into another class."""
    ctx = [personal.get("Batch", ""), _program_short(personal.get("Program", "")),
           personal.get("Section", "")]
    return "|".join(ctx if all(ctx) else [f"net:{netid}"])

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
            # audit: numeric columns must look numeric — a portal column change
            # would shift text into them and silently poison attendance
            if not all(re.fullmatch(r"-?\d+(?:\.\d+)?", n) or n in ("", "-")
                       for n in (cells[2], cells[3], cells[4])):
                log.warning("attendance row layout shifted, skipped: %r", cells[:5])
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
    """Parse internal marks from studentInternalMarkDetails.jsp.
    Returns (marks_list, subject_map) where subject_map maps code -> {id, status}."""
    out = []
    if not html:
        return out, {}   # audit: ALWAYS a 2-tuple — callers unpack (out, subject_map)
    if re.search(r"no\s+record\s+found", html, re.I):
        return out, {}
    # Extract subjectId + status from onclick="funViewComponentWiseMarks(id, code, desc, status)"
    subject_map = {}
    for fm in re.finditer(r"funViewComponentWiseMarks\('(\d+)',\s*'([^']+)',\s*'([^']+)',\s*(\d+)\)", html):
        sid, scode, _sdesc, sstatus = fm.group(1), fm.group(2), fm.group(3), int(fm.group(4))
        subject_map[scode] = {"id": int(sid), "status": sstatus}
    table_m = re.search(r"<table[^>]*>.*?<tr[^>]*>(.*?)</tr>(.*?)</table>", html, re.S)
    if not table_m:
        return out, {}   # audit: 2-tuple (bare list crashed the unpack, was swallowed -> silent empty marks)
    headers = [re.sub(r"<[^>]+>", "", h).strip().lower()
               for h in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", table_m.group(1), re.S)]
    if not headers or not any("code" in h for h in headers):
        return out, {}   # audit: 2-tuple (see above)
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
            if _DATE_CELL_RE.search(cell):
                continue  # audit: '12/09/2026' would match pair_re as 12/9
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
    return [by_code[c] for c in order], subject_map

def _parse_component_inner(html):
    """Parse inner JSP response for component-wise marks breakdown."""
    comps = []
    if not html:
        return comps
    if re.search(r"no\s+record\s+found", html, re.I):
        return comps
    pair_re = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")
    date_re = _DATE_CELL_RE  # shared: broadened to numeric months too
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).replace("\xa0", " ").strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 2:
            continue
        scored = maximum = 0.0
        for cell in cells:
            if _DATE_CELL_RE.search(cell):
                continue  # audit: '12/09/2026' would match pair_re as 12/9
            m = pair_re.search(cell)
            if m:
                scored, maximum = float(m.group(1)), float(m.group(2))
                break
        if maximum <= 0:
            continue
        name, entered = "", ""
        # component JSP rows: [entered_on, component_name, score/max]
        if len(cells) >= 3 and date_re.search(cells[0]):
            entered = cells[0]
            if not pair_re.search(cells[1]):
                name = cells[1]
        if not name:
            for cell in cells:
                t = cell.strip()
                if t and not pair_re.search(t) and t.lower() not in ("", "-", "nil", "total"):
                    name = t
                    break
        if not name:
            name = f"Assessment {len(comps)+1}"
        comps.append({"name": name, "entered": entered, "scored": scored, "max": maximum})
    return comps


def parse_exam_schedule(html):
    """ScribeInner.jsp (iden=1, ANY hdnExamMonth/Year — portal doesn't
    validate against the official dropdown) -> end-sem exam rows.

    Structure verified live Sep 27 2026: checkbox td (strips to '') then
    code / description / date / session / type / amount. Empty sessions
    return 'No subject found'.
    """
    if not html or "No subject found" in html:
        return []
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = _cells(row)
        # td[0] is the checkbox cell -> ''; real columns shift by 1
        if len(cells) >= 6 and re.fullmatch(r"\d{2}-\d{2}-\d{4}", cells[3] or ""):
            out.append({"code": cells[1], "name": cells[2], "date": cells[3],
                        "session": cells[4], "type": cells[5]})
    return out


def parse_exam_timetable(html):
    """StudentExamTimeTable.jsp (iden=126, official 'Exam Time Table' page)
    -> end-sem exam rows. Verified live Oct 7 2026 (the ONLY published source
    with exact clock times).

    Columns: Sem/Year/Trim | Subject Code | Subject Description | Date & Session
    | Hall No. | Seat No. (+ a month banner) — cells at the Date & Session
    position hold `DD-MMM-YYYY AN  (02:00-05:00)`; subjects without a slot yet
    render `- -`. Empty page = 'No subjects found'.

    Column positions are resolved from the header row so the portal can
    REORDER or INSERT columns (hall allotment day may add fields) without
    breaking known fields; unknown labels are ignored. Falls back to the
    positional shape above when no header row exists.

    Returns rows, [] (clean empty — 'No subjects found'), or None (table
    present but unparseable: label/column drift or blanked rows — callers
    MUST preserve stored rows, never treat as empty).
    """
    if not html or "No subjects found" in html:
        return []
    # header-driven indexes: label -> column position (known fields only)
    labels = {"subject code": "code", "subject description": "name",
              "date & session": "date", "hall no.": "hall", "seat no.": "seat"}
    idx = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        ths = re.findall(r"<th[^>]*>(.*?)</th>", tr, re.S)
        if len(ths) >= 4:
            for i, th in enumerate(ths):
                lbl = _hescu(re.sub(r"<[^>]+>", "", th)).replace("\xa0", " ").strip().lower()
                if lbl in labels:
                    idx.setdefault(labels[lbl], i)
            break
    got_header = bool(idx)
    pos = {"code": 1, "name": 2, "date": 3, "hall": 4, "seat": 5}  # positional fallback
    # header found but a known label missing -> the column is GONE (do not
    # guess positionally — that would read a neighbour cell as the field)
    def _i(field):
        if field in idx:
            return idx[field]
        return None if got_header else pos[field]

    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = _cells(row)
        i_date, i_code = _i("date"), _i("code")
        need = [i for i in (i_date, i_code, _i("hall"), _i("seat")) if i is not None]
        if not need or len(cells) <= max(need) or i_date is None or i_code is None:
            continue
        ds = cells[i_date] or ""
        dm = re.match(r"(\d{2})-([A-Z]{3})-(\d{4})", ds)
        if not dm or not cells[i_code]:
            continue  # header/banner rows, pending `- -`, blanked cells
        mon = MONTHS.get(dm.group(2), "00")
        tm = re.search(r"\((\d{2}:\d{2})-(\d{2}:\d{2})\)", ds)
        out.append({
            "code": cells[i_code], "name": (cells[_i("name")] or "") if _i("name") is not None else "",
            "date": f"{dm.group(1)}-{mon}-{dm.group(3)}",
            "session": (re.search(r"\b(AN|FN)\b", ds) or [None, ""])[1],
            "slot": f"{tm.group(1)}-{tm.group(2)}" if tm else "",
            "hall": (cells[_i("hall")] or "") if _i("hall") is not None else "",
            "seat": (cells[_i("seat")] or "") if _i("seat") is not None else "",
        })
    if not out and "<table" in html:
        # table present but nothing parsed: label/column drift or blanked rows.
        # NOT a clean empty — callers must preserve stored rows (Oct 4 2026 rule).
        log.debug("exam timetable: table present but 0 dated rows parsed (shape drift?)")
        return None
    return out


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


# ── Persistent browser context ───────────────────────────────────────
# ponytail: single global ctx, enough for one-user portal.
_persistent_ctx = None
_persistent_page = None
_persistent_owner = None  # netid whose cookies live in this context


async def _get_persistent_page(netid):
    """Reuse one browser context across scrapes. Returns (page, ctx)."""
    global _persistent_ctx, _persistent_page, _persistent_owner
    # Reuse only if alive AND owned by the same user
    if _persistent_page is not None and _persistent_owner == netid:
        try:
            url = _persistent_page.url
            if "HRDSystem" in url or "youLogin" in url:
                return _persistent_page, _persistent_ctx
        except Exception:
            _persistent_ctx = None
            _persistent_page = None
            _persistent_owner = None
    else:
        # Different user or dead context — start clean so cookies don't mix
        if _persistent_ctx is not None:
            try:
                await _persistent_ctx.close()
            except Exception:
                pass
        _persistent_ctx = None
        _persistent_page = None
        _persistent_owner = None

    # Create fresh context
    browser = await _get_browser()
    _persistent_ctx = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        locale="en-IN",
    )
    await _persistent_ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    _persistent_page = await _persistent_ctx.new_page()
    _persistent_owner = netid
    return _persistent_page, _persistent_ctx


# ── Speed-optimized scraper ──────────────────────────────────────── ────────────────────────────────────────

async def _do_login(page, ctx, netid, password):
    """Perform login with captcha retry. Returns (ok, error_or_none)."""
    global _request_fail_counted
    _request_fail_counted = False  # one portal-fail per request, not per retry
    # Check global portal cooldown before attempting
    cooldown = _portal_cooldown_remaining()
    if cooldown > 0:
        return False, (f"SRM portal temporarily rate-limiting our server. "
                       f"Try again in {int(cooldown / 60) + 1} minutes.")

    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.fill('input[name="username"]', netid)
    await page.click('input[name="password"]')
    await page.type('input[name="password"]', password, delay=10)

    MAX_CAPTCHA_RETRIES = 5
    last_err = ""
    for _ca in range(MAX_CAPTCHA_RETRIES):
        b64 = await page.evaluate(CAPTCHA_JS)
        if not b64:
            log.warning("playwright login netid=%s abort=captcha_image_empty (portal served no image)", netid)
            return False, "captcha image failed to load — portal may be slow"
        captcha = solve_captcha_b64(b64)
        if not captcha:
            log.warning("playwright login netid=%s abort=ocr_empty", netid)
            return False, "captcha OCR returned empty"
        await page.click('input[name="captcha"]')
        await page.type('input[name="captcha"]', captcha, delay=10)
        await page.mouse.move(300, 200, steps=3)
        await page.click('button:has-text("Login")')
        try:
            await page.wait_for_url(lambda url: "HRDSystem" in url, timeout=8000)
            _portal_ok()
            return True, None
        except Exception:
            # Extract the specific error the portal showed
            try:
                err_text = await page.evaluate("() => (document.body.innerText || '')")
                err_lower = err_text.lower()
                current_url = page.url
                if ("invalid credentials" in err_lower
                        or "invalid login credentials" in err_lower):
                    # Wrong password never becomes right by re-reading the captcha.
                    # Don't retry, don't count toward global portal cooldown.
                    # Portal alert verbatim is "Invalid login credentials …" —
                    # the word 'login' sits in the middle, so the old exact
                    # substring missed it and the fallback path retried a wrong
                    # password as if the captcha were unreadable.
                    log.warning("playwright login attempt %d/%d reject=credentials "
                                "portal_alert=%r", _ca + 1, MAX_CAPTCHA_RETRIES,
                                next((ln.strip()[:160] for ln in err_text.splitlines()
                                      if "invalid" in ln.lower()), ""))
                    return False, "invalid credentials — check your NetID/password"
                elif "captcha expired" in err_lower:
                    last_err = "captcha expired"
                elif "invalid captcha" in err_lower:
                    last_err = f"invalid captcha (read: {captcha})"
                elif "HRDSystem" not in current_url and "login" in current_url.lower():
                    # Silent rejection: portal returned login page with no error
                    # This means portal rate-limited us
                    last_err = "portal rate-limited (silent rejection)"
                    _portal_fail_once()
                    if _ca < MAX_CAPTCHA_RETRIES - 1:
                        await asyncio.sleep(5)
                        # re-rendered form comes back empty — refill or the
                        # retry submits blank credentials (audit L1)
                        await page.fill('input[name="username"]', netid)
                        await page.fill('input[name="password"]', password)
                    continue
                else:
                    last_err = f"rejected (read: {captcha})"
            except Exception:
                last_err = f"rejected (read: {captcha})"
            log.warning("login attempt %d/%d failed for %s: %s",
                        _ca + 1, MAX_CAPTCHA_RETRIES, netid, last_err)
            if _ca < MAX_CAPTCHA_RETRIES - 1:
                await asyncio.sleep(3)  # backoff between retries
                await page.goto(LOGIN_URL, wait_until="domcontentloaded")
                await page.fill('input[name="username"]', netid)
                await page.click('input[name="password"]')
                await page.type('input[name="password"]', password, delay=10)
                continue
            return False, f"login failed after {MAX_CAPTCHA_RETRIES} attempts — last: {last_err}"
    # All retries exhausted via silent-rejection continues
    return False, f"login failed after {MAX_CAPTCHA_RETRIES} attempts — last: {last_err or 'silent rejection'}"

async def _fetch_rich_optimized(netid, password, cold=True):
    # Persistent context — reuse across scrapes for speed.
    page, ctx = await _get_persistent_page(netid)
    try:

        # Fast path: persistent page is already logged in on HRDSystem
        logged_in = False
        if "HRDSystem" in page.url:
            logged_in = True
        if not logged_in:
            # Cached cookies path (container restarted etc.)
            cached = _load_session(netid)
            if cached:
                try:
                    cookies = json.loads(cached)
                    await ctx.add_cookies(cookies)
                    await page.goto("https://sp.srmist.edu.in/srmiststudentportal/students/template/HRDSystem.jsp",
                                    wait_until="domcontentloaded", timeout=8000)
                    if "HRDSystem" in page.url:
                        logged_in = True
                except Exception:
                    _clear_session(netid)

        if not logged_in:
            ok, err = await _do_login(page, ctx, netid, password)
            if not ok:
                return {"ok": False, "error": err}
            # Save session for next time
            try:
                cookies = await ctx.cookies()
                _save_session(netid, json.dumps(cookies))
            except Exception as e:
                log.warning("portal session save failed netid=%s (next sync pays a full login): %r", netid, e)


        # ── Parallel fetch (hot always; cold when requested) ─────────
        _all_jsps = {
            "1": "../../students/report/studentProfile.jsp",
            "9": "../../students/report/studentAttendanceDetails.jsp",
            "13": "../../students/report/studentInternalMarkDetails.jsp",
            "17": "../../students/report/studentPersonalDetails.jsp",
            "7": "../../students/report/studentSubjectLists.jsp",
            "126": "../../students/transaction/StudentExamTimeTable.jsp"
        }
        _fetch_jsps = {f: u for f, u in _all_jsps.items()
                       if f in ("9", "13", "126") or cold}
        parallel_html = await page.evaluate("""async (JSPS) => {
            const r = {};
            await Promise.all(Object.entries(JSPS).map(([f, u]) =>
                $.post(u, [
                    {name:'iden', value:parseInt(f)},
                    {name:'filter', value:''},
                    {name:'hdnFormDetails', value:1},
                    {name:'csrfPreventionSalt', value:''}
                ], 'html').then(h => { r[f] = h; }).catch(() => { r[f] = ''; })
            ));
            return r;
        }""", _fetch_jsps)

        # Photo: removed Sep 25 2026 — unused in any workflow (blobatar avatars instead)

        content_html = parallel_html.get("9", "")
        if "youLogin" in content_html or ("Login" in content_html[:2000] and "captcha" in content_html.lower()):
            # Session silently expired mid-scrape — relogin and refetch
            _clear_session(netid)
            ok, err = await _do_login(page, ctx, netid, password)
            if not ok:
                return {"ok": False, "error": err}
            try:
                cookies = await ctx.cookies()
                _save_session(netid, json.dumps(cookies))
            except Exception as e:
                log.warning("portal session save failed netid=%s (next sync pays a full login): %r", netid, e)
            parallel_html = await page.evaluate("""async (JSPS) => {
                const r = {};
                await Promise.all(Object.entries(JSPS).map(([f, u]) =>
                    $.post(u, [
                        {name:'iden', value:parseInt(f)},
                        {name:'filter', value:''},
                        {name:'hdnFormDetails', value:1},
                        {name:'csrfPreventionSalt', value:''}
                    ], 'html').then(h => { r[f] = h; }).catch(() => { r[f] = ''; })
                ));
                return r;
            }""", _fetch_jsps)
            content_html = parallel_html.get("9", "")
        data = parse_attendance(content_html)

        # Guard: ABC ID gate check
        if not data.get("courses"):
            raw = await page.evaluate(
                '() => (document.getElementById("divMainDetails")||document.body).innerText || ""')
            if "ABC ID" in raw or "Aadhaar" in raw:
                return {"ok": False, "error": "Portal requires ABC ID Generation first — "
                                              "log in at sp.srmist.edu.in and complete the "
                                              "Aadhaar/ABC ID form, then try again."}
            return {"ok": False, "error": "Attendance page did not load (portal returned no "
                                          "course table). The portal may be slow or your "
                                          "account may be restricted."}

        # Daily absence drill-downs (unchanged — already parallel)
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

        # Personal details (from parallel fetch)
        personal = {}
        try:
            personal_html = parallel_html.get("17", "")
            if personal_html:
                personal = parse_personal_details(personal_html)
        except Exception as e:
            log.warning("personal details parse failed — profile renders empty: %r", e)

        # Course list (from parallel fetch)
        courses = []
        try:
            course_html = parallel_html.get("7", "")
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", course_html, re.S):
                cells = _cells(row)
                if len(cells) >= 3 and cells[0] and not cells[0].lower().startswith("total"):
                    courses.append({"code": cells[0], "name": cells[1], "credits": int(cells[2] or 0)})
        except Exception as e:
            log.warning("course list parse failed — subjects missing from dashboard: %r", e)

        # Marks (from parallel fetch)
        marks = []
        subject_map = {}
        try:
            marks_html = parallel_html.get("13", "")
            if marks_html:
                marks, subject_map = parse_marks(marks_html)
                # Parallel drill-downs for all subjects
                drill_subjects = [{"sid": v["id"], "st": v["status"], "code": k}
                                  for k, v in subject_map.items() if v.get("id")]
                if drill_subjects:
                    all_drill = await page.evaluate("""async (subjects) => {
                        const results = [];
                        await Promise.all(subjects.map(s =>
                            fetch('../../students/report/studentInternalMarkDetailsInner.jsp', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/x-www-form-urlencoded',
                                          'X-Requested-With': 'XMLHttpRequest'},
                                body: 'iden=1&hdnSubjectId=' + s.sid + '&status=' + s.st
                            }).then(r => r.ok ? r.text() : '').then(html => {
                                if (html) results.push({code: s.code, html: html});
                            })
                        ));
                        return results;
                    }""", drill_subjects)
                    for drill in all_drill:
                        for m in marks:
                            if m["code"] == drill["code"]:
                                comps = _parse_component_inner(drill["html"])
                                if comps:
                                    m["components"] = comps
                                    m["scored_total"] = round(sum(x["scored"] for x in comps), 2)
                                    m["max_total"] = round(sum(x["max"] for x in comps), 2)
                                break
        except Exception as e:
            log.warning("marks/component parse failed — marks render empty: %r", e)

        # End-sem schedule: official 126 table wins; scribe rows fill the rest.
        # Key present ONLY when the merge produced rows — same contract as
        # http_scraper.fetch (omit = preserve stored schedule). An absent/
        # unparseable table returns None; storing it would write the literal
        # "null" over exam_schedule_json and wipe the card (Oct-4 never-wipe rule).
        from app.http_scraper import _merge_exam_results
        exams = _merge_exam_results([], official_html=parallel_html.get("126", ""))
        out = {"ok": True, "data": data, "personal": personal, "courses": courses, "marks": marks, "subjects": subject_map, "fetched": int(time.time())}
        if exams is not None:
            out["exams"] = exams
        return out
    finally:
        # Don't close persistent context — keep alive for next request
        pass

def fetch_attendance(netid, password):
    global _request_fail_counted
    loop = future = None  # except block references both; may not be reached
    # audit 2026-09-30: the lock comes FIRST. _check_rate() used to run above
    # it, so a busy/cooldown/budget rejection still consumed one of the
    # account's 3 syncs per 10 minutes while reaching the portal zero times —
    # three "Sync in progress" clicks locked an account that never synced out
    # for 10 minutes (prod 2026-09-30 16:45–16:53). Only count a sync once we
    # know it can actually run.
    # audit F1 fix: blocking acquire in the worker thread; no try/except race
    if not _scrape_lock.acquire(blocking=False):
        return {"ok": False, "error": "Sync in progress. Try again in 30 seconds."}
    try:
        # audit 2026-09-27: reset HERE (under the scrape lock, one pipeline at a
        # time). Previously the flag was only reset inside Playwright's _do_login,
        # so in the normal pure-HTTP path the first counted fail latched it True
        # forever and _portal_fail_once() became a no-op — the portal cooldown
        # could never arm and we'd keep hammering a rate-limiting portal.
        _request_fail_counted = False
        if not _check_portal_budget():
            return {"ok": False, "error": ("Too many portal requests from the server "
                                           "(rate-limit protection). Try again in 10 minutes.")}
        cooldown = _portal_cooldown_remaining()
        if cooldown > 0:
            return {"ok": False, "error": (f"SRM portal temporarily rate-limiting our server. "
                                           f"Try again in {int(cooldown / 60) + 1} minutes.")}
        if not _check_rate(netid):
            return {"ok": False, "error": f"Too many sync attempts for this account. Try again in {_netid_retry_text(netid)}."}
        # ── New pipeline: pure-HTTP first ─────────────────────────────
        helpers = {"portal_fail_once": _portal_fail_once, "portal_ok": _portal_ok,
                   "save_session": _save_session, "load_session": _load_session,
                   "clear_session": _clear_session, "set_progress": _set_progress}
        # Hot/cold split: cold data (personal/courses) re-fetched only when
        # stale >24h; hot (attendance/marks) always.
        c = db()
        row = c.execute("SELECT cold_fetch FROM users WHERE netid=?", (netid,)).fetchone()
        c.close()
        cold = True
        if row and row["cold_fetch"] and time.time() - row["cold_fetch"] < 24 * 3600:
            cold = False
            log.debug("cold data fresh netid=%s — hot-only sync", netid)
        try:
            from . import http_scraper
        except ImportError as e:
            # audit 2026-10-07: the HTTP pipeline going silently missing doubled
            # every sync's latency with no log line — log the cause loudly
            log.error("http_scraper unavailable — playwright-only mode: %r", e)
            http_scraper = None
        if http_scraper:
            # only on the HTTP path — this line printed pipeline=http even on
            # the exact ImportError path where http_scraper is None
            log.debug("pipeline=http netid=%s", netid)
            try:
                # Consume any warm login the browser preflighted while the
                # user was typing their password (single-use, 150s TTL).
                prepared = None
                try:
                    prepared = http_scraper.take_preflight(netid)
                except Exception as e:
                    log.debug("preflight take failed err=%r", e)
                _set_progress(netid, "Connecting to SRM portal…", 5)
                res = http_scraper.fetch(netid, password, helpers, cold=cold, prepared=prepared)
                if res.get("ok") and cold:
                    try:
                        c = db()
                        c.execute("UPDATE users SET cold_fetch=? WHERE netid=?", (int(time.time()), netid))
                        c.commit(); c.close()
                    except Exception as e:
                        log.debug("cold_fetch update failed err=%r", e)
                return res
            except http_scraper.HttpScraperError as e:
                log.warning("http pipeline failed (%r) — falling back to playwright", e)
                _portal_fail_once()
            except Exception as e:
                log.warning("http pipeline crashed (%r) — falling back to playwright", e)
                _portal_fail_once()
        # ── Fallback: Playwright ──────────────────────────────────────
        loop = _ensure_loop()
        future = asyncio.run_coroutine_threadsafe(_fetch_rich_optimized(netid, password, cold=cold), loop)
        return future.result(timeout=150)  # 5 captcha retries w/ backoffs ≈ 90s worst case; 60s caused guaranteed TimeoutError + zombie retries
    except Exception:
        # audit: a timeout leaves the coroutine driving the shared page after
        # the lock is released (zombie double-drive) — cancel it. Setting
        # _browser=None without closing leaked one Chromium per failed scrape.
        # Raw exception internals never go to API clients.
        global _browser, _loop_thread
        if future is not None:
            try:
                future.cancel()
            except Exception:
                pass
        old_browser, _browser = _browser, None
        if old_browser is not None and loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(old_browser.close(), loop).result(timeout=5)
            except Exception:
                pass  # loop dead too — next launch replaces both anyway
        log.warning("playwright pipeline failed", exc_info=True)
        return {"ok": False, "error": "Scrape failed server-side — check the server log, then try again."}
    finally:
        _scrape_lock.release()

# ── View model ─────────────────────────────────────────────────────
ATTENDANCE_TARGET = 0.75
ATTENDANCE_WARN = 0.65
WORKING_DAYS = 90  # 90-working-day skip-budget horizon (spec §3); no academic calendar exists (see _attendance_budgets)

def _safe_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0

def _status_for_pct(pct):
    if pct >= ATTENDANCE_TARGET * 100: return "ok"
    if pct >= ATTENDANCE_WARN * 100: return "warn"
    return "danger"

def _bunk_counts(attended, total, threshold=ATTENDANCE_TARGET):
    """(skip_now, attend_now) — the numbers behind _bunk_line's prose (spec §3).
    Exactly one side is non-None when total > 0; (None, None) when nothing was held.
    The ±1e-9 epsilon and max(1, …) are the original _bunk_line's semantics [F10] —
    _bunk_line renders these; the meter connector + timetable glance need the NUMBER."""
    if total <= 0:
        return (None, None)
    room = attended / threshold - total
    if room >= -1e-9:
        return (max(0, math.floor(room + 1e-9)), None)
    return (None, max(1, math.ceil((threshold * total - attended) / (1 - threshold) - 1e-9)))

def _bunk_line(attended, max_hours, threshold=ATTENDANCE_TARGET):
    if max_hours <= 0: return None
    pct_target = threshold * 100
    skip, attend = _bunk_counts(attended, max_hours, threshold)
    if skip is not None:
        if skip == 0:
            return "One more miss drops you below %.0f%%" % pct_target
        return "Can miss %d more class%s and stay above %.0f%%" % (skip, "" if skip == 1 else "es", pct_target)
    return "Attend the next %d class%s in a row to reach %.0f%%" % (attend, "" if attend == 1 else "es", pct_target)

def _weekdays(a, b):
    """Mon–Fri count with BOTH ends inclusive (0 when b < a) [F13]."""
    if not a or not b or b < a:
        return 0
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n

def _exam_stop(exams):
    """One global attendance horizon for every subject: first parseable endsem date − 1 day
    (spec §0/R6 — portal marking stops at the FIRST exam of ANY subject). None when
    exam_schedule is empty/junk: callers degrade, never guess a date."""
    dates = []
    for r in exams or []:
        try:
            dates.append(datetime.strptime(str(r.get("date", "")), "%d-%m-%Y").date())
        except ValueError:
            continue  # junk rows fall back in _exams_view; they must not anchor the horizon
    return (min(dates) - timedelta(days=1)) if dates else None

def _attendance_budgets(attended, max_hours, w, period=None, exams=None, today=None):
    """Semester skip budgets (spec §3): 90-working-day model + endsem-date model.
    Every value degrades to None (template renders `--` / hides) — never a fake zero:
    no exams → m_end/days_left_exam None; w = 0 → both budgets None; period absent or
    elapsed ≤ 0 → days_left_90 dropped (column keeps its budgets) [F9].
    ponytail: period.from may be a rolling window; if days-left ever looks wrong, add
    academic_calendar_json (migration v11 is free) — ceiling disclosed in the PR [R7]."""
    today = today or date.today()
    stop = _exam_stop(exams)
    out = {"m90": None, "m_end": None, "days_left_90": None, "days_left_exam": None, "stop": stop}
    if w > 0:
        T = math.ceil(WORKING_DAYS * w / 5)
        N = T - max_hours
        out["m90"] = max(0, math.floor(attended + N - ATTENDANCE_TARGET * T))
        if stop is not None:
            # ceil REQUIRED here: floor/raw gives DBMS 4 where the frozen table says 5 [F1]
            N_e = math.ceil(w * _weekdays(today + timedelta(days=1), stop) / 5)
            T_e = max_hours + N_e
            out["m_end"] = max(0, math.floor(attended + N_e - ATTENDANCE_TARGET * T_e))
    if stop is not None:
        out["days_left_exam"] = (stop - today).days
    frm = period.get("from") if isinstance(period, dict) else None
    if frm:
        try:
            elapsed = _weekdays(datetime.strptime(str(frm), "%d/%b/%Y").date(), today)
        except ValueError:
            elapsed = 0
        if elapsed > 0:
            out["days_left_90"] = WORKING_DAYS - min(elapsed, WORKING_DAYS)
    return out

def _weekly_slots(group_key):
    """w = weekly slot count per subject_code, scoped to THIS user's group [F4].
    Precedent: _day_slots / timetable_html / /api/timetable all scope by group_id."""
    if not group_key:
        return {}
    c = db()
    gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (group_key,)).fetchone()
    out = {}
    if gid:
        out = {r[0]: r[1] for r in c.execute(
            "SELECT subject_code, COUNT(*) FROM timetable_slots "
            "WHERE group_id=? AND subject_code IS NOT NULL AND subject_code != '' "
            "GROUP BY subject_code", (gid[0],))}
    c.close()
    return out

def _absences_view(daily):
    """Absences card (review R4): month-grouped; each row is `date · hours` ONLY —
    no subject column [R5] (daily_absent rows carry none; deriving one would be a lie)."""
    out = []
    for label, rows in (daily or {}).items():
        disp_rows = []
        for r in rows or []:
            raw = str(r.get("date", ""))
            try:
                disp = datetime.strptime(raw, "%d-%m-%Y").strftime("%d %b")
            except ValueError:
                disp = raw  # unknown shape: show it raw rather than hide the absence
            disp_rows.append({"date": disp, "hours": r.get("hours", "")})
        if disp_rows:
            out.append({"label": _title_case(str(label).replace(" / ", " ")), "rows": disp_rows})
    return out

def _norm_subject(s):
    """Join key: upper / strip / squash whitespace (spec §4.3)."""
    return " ".join(str(s or "").upper().split())

def _title_case(s):
    """Display only (review R2): portal names arrive ALL CAPS -> Title Case.
    No-op on mixed-case strings (custom timetable names keep their casing);
    join keys still go through _norm_subject, so casing is render-time only."""
    s = str(s or "")
    return s.title() if s.isupper() else s

def _attendance_index(courses):
    """spec §4 join index built in index(): code-exact map + normalized-name fallback map."""
    by_code = {c["code"]: c for c in courses if c.get("code")}
    by_name = {}
    for c in courses:
        key = _norm_subject(c.get("description"))
        if key:
            by_name.setdefault(key, c)
    return {"by_code": by_code, "by_name": by_name}

def _join_attendance(index, custom_codes, code, name):
    """spec §4 order is load-bearing: custom (is_custom=1) → code-exact → normalized name
    → None. None means neutral "no data" — an unmatched slot must NEVER render as 0% [F9]."""
    if not index:
        return None
    if code in custom_codes:
        return None  # a custom subject typed with a portal-matching name must never join
    return index["by_code"].get(code) or index["by_name"].get(_norm_subject(name))

def _course_view(c):
    attended = _safe_int(c.get("attended"))
    max_hours = _safe_int(c.get("max_hours"))
    pct = min(100.0, round((attended / max_hours) * 100, 1)) if max_hours > 0 else 0.0
    skip, attend = _bunk_counts(attended, max_hours)
    # status/absent outputs dropped: grep showed no template/route consumer —
    # the monthly bar's band lives on the MONTH dict now (_month_view)
    return {"code": c.get("code", ""), "description": _title_case(c.get("description", "")),
            "max_hours": max_hours, "attended": attended,
            "pct": pct, "bunk_line": _bunk_line(attended, max_hours),
            # meter-row fields (spec §1.1): display 0dp, fill EXACT A/C [F12],
            # pct_disp None = `--` (C = 0 holds nothing → no fill, no pinned numbers)
            "pct_disp": int(pct + 0.5) if max_hours > 0 else None,
            "fill": (100.0 * attended / max_hours) if max_hours > 0 else None,
            "t75": math.ceil(ATTENDANCE_TARGET * max_hours),
            "skip_now": skip, "attend_now": attend,
            # fill tint: red = pct < 75 · orange(warn) = pct ≥ 75 AND skip-now == 0 · gray = comfortable
            "tint": "red" if pct < ATTENDANCE_TARGET * 100 else ("warn" if skip == 0 else "gray"),
            # table view: attended − ceil(0.75·total); None = no classes held (no margin exists)
            "margin": (attended - math.ceil(ATTENDANCE_TARGET * max_hours)) if max_hours > 0 else None}

_BAND_BAR = {"ok": "success", "warn": "warning", "danger": "error"}

def _month_view(m):
    present = _safe_int(m.get("present"))
    absent = _safe_int(m.get("absent"))
    total = present + absent
    out = dict(m)
    out["pct"] = round((present / total) * 100, 1) if total > 0 else None
    # bar class derived in Python from the ONE threshold source — the old
    # template ternary re-typed >=75/>=65 as a second copy of _status_for_pct
    out["bar"] = _BAND_BAR[_status_for_pct(out["pct"])] if out["pct"] is not None else None
    return out


# ── Request logging ─────────────────────────────────────────────────
@app.before_request
def _log_request_start():
    request._start_time = time.monotonic()

@app.after_request
def _log_request(resp):
    duration_ms = int((time.monotonic() - getattr(request, "_start_time", time.monotonic())) * 1000)
    # audit 2026-10-07: 86% of the log file was the docker healthcheck's
    # urllib GET pair (66,003 of 76,857 lines) — synthetic traffic now logs
    # at DEBUG. Real 4xx responses log at WARNING with the error body, 5xx at
    # ERROR (NtfyHandler pages on ERROR/5xx, never on routine 4xx) — every
    # failure carries its cause on the request line itself.
    ua = request.headers.get("user-agent", "")
    if resp.status_code >= 400:
        kv = dict(method=request.method, path=request.path,
                  status=resp.status_code, duration_ms=duration_ms)
        body = resp.get_json(silent=True)
        err = (body or {}).get("error") if isinstance(body, dict) else None
        if err:
            kv["error"] = str(err)[:120]
        # 5xx is a real fault: ALWAYS ERROR (NtfyHandler pages on ERROR/5xx),
        # even from a urllib monitor — healthcheck 4xx noise stays DEBUG.
        lvl = (logging.ERROR if resp.status_code >= 500
               else logging.WARNING if not ua.startswith("Python-urllib")
               else logging.DEBUG)
        log_with_kv(log_http, lvl, "request", **kv)
    else:
        lvl = logging.DEBUG if ua.startswith("Python-urllib") else logging.INFO
        log_with_kv(log_http, lvl, "request",
                    method=request.method, path=request.path,
                    status=resp.status_code, duration_ms=duration_ms)
    return resp

# ── Security headers ───────────────────────────────────────────────
@app.errorhandler(Exception)
def _unhandled_error(e):
    """Safety net: one greppable opensrm ERROR line for anything the app
    fails to catch (audit: no handler existed — sqlite lock errors and
    parser crashes surfaced as a bare Flask 500 with no opensrm.* line)."""
    if isinstance(e, HTTPException):
        return e
    # error=%r rides getMessage() — the ntfy alert carries only the message,
    # so path/method alone told WHERE the crash was, never WHAT.
    log.error("unhandled error path=%s method=%s error=%r", request.path, request.method, e,
              exc_info=(type(e), e, e.__traceback__))
    # browsers navigating a page must not be handed a raw JSON body; fetch()
    # callers (Accept: application/json first) keep the JSON contract
    if request.accept_mimetypes.best == "text/html":
        return ("<!doctype html><html lang=en><meta charset=utf-8>"
                "<title>500 — something broke</title><h1>Something went wrong</h1>"
                "<p>Reload the page. If it keeps failing, the error is logged "
                "with this path and will show up on the next sync.</p>"), 500, \
               {"Content-Type": "text/html; charset=utf-8"}
    return {"ok": False, "error": "internal server error"}, 500

@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; worker-src 'self'; manifest-src 'self'")
    resp.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    # audit: HSTS only when the request came through the CF edge (cf-ray) —
    # plain-HTTP local dev must never receive it
    if request.headers.get("cf-ray"):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp

# ── HTML Templates ─────────────────────────────────────────────────

# ── Faculty card / feedback plan (view helpers, not routes) ────────
def _faculty_view(faculty_map, courses):
    """Stored faculty map + scraped courses -> sorted card rows.
    {} / no staff entries -> [] (card hidden). Joins the feedback form's
    subject NAME to the scraped course CODE via whitespace-normalised match.

    Course rows come from attendance_json, whose real shape is `description`
    (seen live Oct 8 2026: KeyError 'name' 500'd every dashboard); `name` is
    the test-seed shape — accept both."""
    _by_name = {" ".join((c.get("name") or c.get("description") or "").split()).upper():
                c.get("code", "") for c in courses}
    out = []
    for name, entry in faculty_map.items():
        staff = [(sid, " ".join(nm.split("-")[0].split()).title(),
                  (nm.split("-")[1].strip() if "-" in nm else ""))
                 for sid, nm in (entry.get("staff") or [])]
        # the harvester's Unknown placeholder (portal listed no staff) is not a person
        if not staff or all(sid == "0" for sid, _n, _k in staff):
            continue
        code = _by_name.get(" ".join(name.split()).upper(), "")
        out.append({"code": code, "name": name.title(), "raw": name, "staff": staff})
    out.sort(key=lambda x: x["name"])
    return out


def _fb_plan(faculty_map):
    """Stored map -> [{subject, teacher, staff_id, comment}] — the exact rows the
    fill endpoint submits. EVERY listed teacher gets their own row: the portal
    takes one form per teacher within a subject, so a subject with 2 staff
    becomes 2 rows.

    SINGLE builder: the modal preview AND POST /api/feedback/fill both call
    this, so what the student saw IS what gets sent. {} / unknown-only -> [].
    """
    plan = []
    for r in _faculty_view(faculty_map, []):
        for sid, tname, kind in r["staff"]:
            plan.append({"subject": r["name"],
                         "teacher": f"{tname} ({kind})" if kind else tname,
                         "staff_id": sid,
                         "comment": "none"})
    return plan


def _jload(raw, default):
    """json.loads over a stored row: degrade to `default` + log the
    corruption. index()/api_marks decoded unguarded — one corrupt row
    500'd the whole dashboard on every load (audit B1-B4). Also checks
    shape: valid-JSON-wrong-type used to reach renderers as a 500 (B10)."""
    if not raw:
        return default
    try:
        v = json.loads(raw)
    except (ValueError, TypeError) as e:
        log.warning("corrupt stored json — returning default: %r", e)
        return default
    if not isinstance(v, type(default)):
        log.warning("stored json wrong shape — returning default")
        return default
    return v

def _track(event, target="", detail="", user=""):
    """One usage-event row: page views, syncs, feature usage. Closed
    vocabulary (usage_events), no PII — user is the netid already stored
    in the DB; never passwords, tokens, or portal payloads. ponytail:
    plain INSERT, no batching — a few rows/day at this scale."""
    try:
        c = db()
        c.execute("INSERT INTO usage_events(day, user, event, target, detail) VALUES(?,?,?,?,?)",
                  (time.strftime("%Y-%m-%d"), user, event, target[:64], detail[:64]))
        c.commit(); c.close()
    except Exception as e:
        # INFO, not debug: a permanently broken usage_events table (lock
        # errors, missed migration on a restored backup) used to fail forever
        # with zero trace at prod LOG_LEVEL=INFO — the silent-failure class
        # the reliability audit outlawed. Telemetry failing must stay visible;
        # telemetry working stays quiet.
        log.info("usage track failed event=%s error=%r", event, e)

# ── Routes ─────────────────────────────────────────────────
@app.route("/")
@require_login
def index():
    netid = get_current_user()
    if not netid:
        # race: require_login validated, then the row vanished before this
        # re-read (logout in another tab mid-request) — redirect, not 500.
        return redirect("/login")
    c = db()
    # one row read: marks/faculty live on the same users row (was three queries)
    row = c.execute("SELECT attendance_json, last_fetch, personal_details_json, exam_schedule_json, marks_json, faculty_map_json FROM users WHERE netid=?", (netid,)).fetchone()
    c.close()
    _track("page_view", target="dashboard", user=netid)
    data = _jload(row["attendance_json"] if row else None,
                  {"courses": [], "monthly": [], "period": None, "daily_absent": {}})
    last_epoch = row["last_fetch"] if row and row["last_fetch"] else 0
    last = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(last_epoch)) if last_epoch else "never"

    hours_old = int((time.time() - last_epoch) / 3600) if last_epoch else None
    # CL / CLASS IN CHARGE is kept: it is real portal attendance — its hours
    # are in the portal's own Total row (7 subjects 289 + CL 5 = 294) and
    # students asked to see it (Oct 2026). w=0 (absent from the timetable)
    # keeps it out of the Estimates budgets automatically.
    courses = sorted((_course_view(x) for x in data.get("courses", [])), key=lambda c: c["pct"])  # risk-first: lowest % first
    # Absences card: one structure per month — the monthly attendance bar with
    # that month's absence chips directly under it (absence rows join by the
    # same normalized label _absences_view produces).
    abs_by_label = {g["label"]: g["rows"] for g in _absences_view(data.get("daily_absent", {}))}
    monthly = []
    for m in data.get("monthly", []):
        v = _month_view(m)
        label = _title_case(str(m.get("month", "")).replace(" / ", " "))
        v["label"] = label
        v["abs_rows"] = abs_by_label.pop(label, [])
        monthly.append(v)
    for label, rows in abs_by_label.items():  # degrade: drill-down months with no cumulative row
        # pct None = chip-only block (template skips the bar entirely — a
        # fallback month must never render as a numeric 0% / fake red bar,
        # DESIGN §4.15; a junk daily_absent key lands here as label+chips too)
        monthly.append({"month": label, "label": label, "pct": None, "abs_rows": rows})

    # Extract student name from personal details
    personal_data = _jload(row["personal_details_json"] if row else None, {})
    student_name = personal_data.get("Student Name", "").title()

    # Marks: server-rendered (tab + dashboard widget). Re-synced hot data.
    marks_raw = _jload(row["marks_json"] if row else None, [])
    marks_view = _marks_view(marks_raw,
                             _load_component_tags(_class_key(personal_data, netid), marks_raw))
    marks_summary = _marks_summary(marks_raw)

    # End-sem schedule card (official iden=126 table primary, scribe probe as
    # fallback; None -> card hidden). Rows are kept: _exam_stop needs the raw
    # dates for the budget horizon (spec §1.2).
    exam_rows = _jload(row["exam_schedule_json"] if row else None, [])
    exams = _exams_view(exam_rows)

    # Faculty map card (harvested from the mid-sem feedback form; {} -> hidden).
    # Keyed by subject NAME — the feedback form carries no subject codes.
    faculty_map = _jload(row["faculty_map_json"] if row else None, {})
    faculty_view = _faculty_view(faculty_map, data.get("courses", []))
    # Preview of what the opt-in fill would submit (same builder as the endpoint).
    fb_plan = _fb_plan(faculty_map)

    # Dashboard home tab: profile + today/week brief
    group_key = _group_key(personal_data) if personal_data else None
    # Attendance budgets (spec §3): w is gid-scoped to THIS user; stop is one global
    # horizon shared by every subject (min parsed exam date − 1, §0/R6).
    weekly = _weekly_slots(group_key)
    today = date.today()
    for c in courses:
        c["w"] = weekly.get(c["code"], 0)
        c.update(_attendance_budgets(c["attended"], c["max_hours"], c["w"],
                                     data.get("period"), exam_rows, today))
    # no timetable -> no budgets anywhere -> the Estimates card would render
    # header-only (empty-state rule DESIGN §8); hide the whole block instead
    has_budgets = any(c.get("m90") is not None or c.get("m_end") is not None for c in courses)
    attendance = _attendance_index(courses)  # spec §4 join — consumed by timetable_html
    dash = {
        "email": personal_data.get("Personal Email ID", "") or netid,
        "reg_no": personal_data.get("Register No.", ""),
        "today": _today_brief(group_key),
        "week": _week_updates(data.get("daily_absent", {})),
        "absent_today": any(
            r.get("date") == datetime.now().strftime("%d-%m-%Y")
            for rows in (data.get("daily_absent") or {}).values() for r in rows),
    }

    return render_template(
        "dashboard.html", netid=netid, courses=courses, monthly=monthly,
        days_left_90=next((c["days_left_90"] for c in courses if c["days_left_90"] is not None), None),
        stop=next((c["stop"] for c in courses if c["stop"] is not None), None),
        days_left_exam=next((c["days_left_exam"] for c in courses if c["days_left_exam"] is not None), None),
        last=last, last_epoch=last_epoch, hours_old=hours_old, has_budgets=has_budgets,
        student_name=student_name, dash=dash, marks=marks_view, marks_summary=marks_summary,
        exams=exams, faculty=faculty_view, fb_plan=fb_plan,
        version=APP_VERSION,
        timetable=timetable_html(group_key, attendance),
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
            # _att must ride along: the hero's 22px sig block reads it (spec §1.B);
            # dropping it here silently rendered hero without the stat
            return {"kind": "current", "code": s["code"], "name": s["name"],
                    "loc": s.get("location",""), "until": s["end"],
                    **({"_att": s["_att"]} if "_att" in s else {})}
    upcoming = [s for s in slots if s.get("type") != "break" and
                int(s["start"].split(":")[0])*60 + int(s["start"].split(":")[1]) > now_mins]
    if upcoming:
        s = upcoming[0]
        sm = int(s["start"].split(":")[0])*60 + int(s["start"].split(":")[1])
        return {"kind": "next", "code": s["code"], "name": s["name"],
                "loc": s.get("location",""), "at": s["start"],
                "in_mins": sm - now_mins}
    return {"kind": "done"} if slots else None

def _day_slots(group_key):
    """group_key -> {day: {period: slot}} or None when no timetable exists."""
    if not group_key:
        return None
    c = db()
    gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (group_key,)).fetchone()
    if not gid:
        c.close()
        return None
    day_slots = {}
    for r in c.execute("SELECT day,period,subject_code,subject_name,location FROM timetable_slots WHERE group_id=?", (gid[0],)):
        if r[0] not in day_slots: day_slots[r[0]] = {}
        day_slots[r[0]][r[1]] = {"code": r[2], "name": r[3], "location": r[4] or ""}
    c.close()
    return day_slots

def _today_brief(group_key):
    """Dashboard: today's class count + next class from the timetable."""
    day_slots = _day_slots(group_key)
    out = {"count": 0, "next": None, "day_done": False}
    if not day_slots:
        return out
    today = datetime.now().strftime("%A")
    todays = day_slots.get(today, {})
    out["count"] = len(todays)
    for s in SLOTS:
        if s["type"] == "break" or s["period"] not in todays:
            continue
        sm = int(s["start"].split(":")[0]) * 60 + int(s["start"].split(":")[1])
        em = int(s["end"].split(":")[0]) * 60 + int(s["end"].split(":")[1])
        now_mins = datetime.now().hour * 60 + datetime.now().minute
        if sm <= now_mins < em:
            sl = todays[s["period"]]
            out["next"] = {"kind": "now", "code": sl["code"], "at": s["end"]}
            return out
        if now_mins < sm:
            sl = todays[s["period"]]
            out["next"] = {"kind": "next", "code": sl["code"], "at": s["start"]}
            return out
    out["day_done"] = True
    return out

def _week_updates(daily_absent):
    """Dashboard: absences in the current Mon–Sun week (IST server time)."""
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    hits, hours = [], 0.0
    for _month, rows in (daily_absent or {}).items():
        for r in rows:
            try:
                d = datetime.strptime(r.get("date", ""), "%d-%m-%Y").date()
            except ValueError:
                continue
            if monday <= d <= sunday:
                hits.append({"date": r["date"], "hours": r.get("hours", "")})
                try:
                    hours += float(str(r.get("hours", "0")).split("-")[0])
                except ValueError:
                    pass
    hits.sort(key=lambda x: x["date"])
    return {"days": len(hits), "hours": hours, "dates": hits,
            "today_absent": any(h["date"] == today.strftime("%d-%m-%Y") for h in hits)}

def _tt_att_sig(course):
    """One glance signal for a timetable slot (spec §1.B): the text carries the
    meaning, colour only reinforces. None → neutral "no data", never a numeric 0%."""
    if not course or course.get("max_hours", 0) <= 0:
        return None
    skip, attend = course.get("skip_now"), course.get("attend_now")
    if skip is None and attend is None:
        return None
    if attend is not None:
        return {"cls": "danger", "text": "attend %d" % attend, "num": attend}
    if skip == 0:
        return {"cls": "warn", "text": "no margin", "num": 0}
    return {"cls": "ok", "text": "can skip %d" % skip, "num": skip}

def timetable_html(group_key, attendance=None):
    if not group_key:
        return ("<div class=\"tt-wrap\"><div class=\"tt-hero\">"
                ""
                "<div><strong>No timetable found</strong>"
                "<div class=\"tt-hero-sub\">No timetable exists for your group yet.</div></div></div></div>")
    c = db()
    gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (group_key,)).fetchone()
    if not gid:
        c.close()
        return ("<div class=\"tt-wrap\"><div class=\"tt-hero\">"
                ""
                "<div><strong>No timetable set</strong>"
                "<div class=\"tt-hero-sub\">Your group has no timetable. Use the editor to build one.</div></div></div></div>")
    gid = gid[0]
    day_slots = {}
    # attendance join (spec §4): custom short-circuits BEFORE any name match —
    # a custom subject typed with a portal-matching name must never join.
    custom_codes = set()
    if attendance:
        for r in c.execute("SELECT code FROM timetable_subjects WHERE group_id=? AND is_custom=1", (gid,)):
            if r[0]:
                custom_codes.add(r[0])
    for r in c.execute("SELECT day,period,subject_code,subject_name,location FROM timetable_slots WHERE group_id=?", (gid,)):
        if r[0] not in day_slots: day_slots[r[0]] = {}
        # audit 2026-09-27: slots are written by ANY user of the group via
        # /api/timetable and rendered with {{ timetable | safe }} — escape at
        # this single choke point (covers hero + panels + loc) or one student's
        # custom subject name becomes stored XSS in classmates' dashboards.
        day_slots[r[0]][r[1]] = {"code": _hesc(str(r[2] or "")),
                                 "name": _hesc(str(r[3] or "")),
                                 "location": _hesc(str(r[4] or ""))}
        # raw (unescaped) pair for the join + sig lookup; rendered values above stay escaped
        day_slots[r[0]][r[1]]["_att"] = _join_attendance(attendance, custom_codes, str(r[2] or ""), str(r[3] or ""))
    c.close()
    # If no slots at all, show empty state
    has_slots = any(day_slots.get(d) for d in DAY_ORDER)
    if not has_slots:
        return ("<div class=\"tt-wrap\"><div class=\"tt-hero\">"
                ""
                "<div><strong>Timetable empty</strong>"
                "<div class=\"tt-hero-sub\">Use the editor to map out your schedule.</div></div></div></div>")
    # Build today's slots for hero
    today = datetime.now().strftime("%A")
    # index of the day's LAST filled class slot: a break at/after it is NOT
    # part of today's schedule (otherwise the hero says "Break until 16:00"
    # after the last class instead of "Done for today")
    last_cls = -1
    for i, s in enumerate(SLOTS):
        if s["type"] == "class" and today in day_slots and s["period"] in day_slots[today]:
            last_cls = i
    today_slots = []
    for i, s in enumerate(SLOTS):
        if s["type"] == "break":
            if i < last_cls:
                today_slots.append(s)
        elif today in day_slots and s["period"] in day_slots[today]:
            m = day_slots[today][s["period"]]
            today_slots.append({**s, "code": m["code"], "name": m["name"], "location": m["location"],
                                **({"_att": m["_att"]} if "_att" in m else {})})
    hero_status = _now_next_from_slots(today, today_slots)
    # Hero HTML
    if hero_status is None or hero_status["kind"] == "done":
        hero = ("<div class=\"tt-hero tt-hero--done\"><strong>Done for today</strong>"
                "<div class=\"tt-hero-sub\">No more classes</div></div>")
    elif hero_status["kind"] == "break":
        hero = ("<div class=\"tt-hero tt-hero--break\"><strong>{label}</strong>"
                "<div class=\"tt-hero-sub\">Until {until}</div></div>").format(**hero_status)
    elif hero_status["kind"] == "current":
        # today's-slot hero: when the current class carries a skip stat, the stat is
        # the loud object (22px number) and the hero edge takes the RISK colour, not
        # the temporal now-tint (spec §1.B) — one edge, one meaning.
        hero = ("<div class=\"tt-hero tt-hero--now{riskcls}\">"
                "<div class=\"tt-hero-sub\">Now \u00b7 ends {until}</div>"
                "<strong>{code} \u2014 {name}</strong>{sig}</div>").format(
            # review R2: no dot, no badge; hue only on the faint left rim = deviation
            riskcls=" tt-hero--risk-danger" if (sig_txt := _tt_att_sig(hero_status.get("_att")) if "_att" in hero_status else None) and sig_txt["cls"] == "danger"
                   else (" tt-hero--risk-warn" if sig_txt and sig_txt["cls"] == "warn" else ""),
            code=hero_status["code"], name=_title_case(hero_status["name"]), until=hero_status["until"],
            sig=("<div class=\"tt-hero-sig\"><span class=\"tt-hero-num\">{num}</span>{txt}</div>"
                 .format(num=sig_txt["num"], txt="classes in a row to hold 75%" if sig_txt["cls"] == "danger"
                         else "skippable and still hold 75%" if sig_txt["cls"] == "ok"
                         else "left — one miss drops below 75%") if sig_txt else ""))
    elif hero_status["kind"] == "next":
        hero = ("<div class=\"tt-hero tt-hero--next\"><strong>{code} \u2014 {name}</strong>"
                "<div class=\"tt-hero-sub\">Starts at {at} (in {in_mins}m)</div>"
                "<div class=\"tt-hero-loc\">{loc}</div></div>").format(
            **{**hero_status, "name": _title_case(hero_status["name"])})
    else:
        hero = ("<div class=\"tt-hero\"><strong>No classes today</strong></div>")
    # Day tabs + panels
    default_day = today if today in DAY_ORDER else "Monday"
    radios = "".join("<input type=radio name=ttday id=day-{0} class=tt-radio{1}>".format(d, " checked" if d == default_day else "") for d in DAY_ORDER)
    tabs = "".join("<label for=day-{0}{1}>{2}</label>".format(d, " class=tt-today" if d == today else "", d[:3]) for d in DAY_ORDER)
    panels = []
    for d in DAY_ORDER:
        # which class slots this day actually has — a break divider only makes
        # sense BETWEEN two rendered classes (no trailing "Break" after the
        # day's last class, no orphan divider above the first one)
        present = [s["type"] == "class" and s["period"] in day_slots.get(d, {}) for s in SLOTS]
        last_cls = max((i for i, p in enumerate(present) if p), default=-1)
        rows = []
        for i, s in enumerate(SLOTS):
            if s["type"] == "break":
                if any(present[:i]) and i < last_cls:
                    rows.append("<div class=tt-divider>{0}</div>".format(s["name"]))
                continue
            sl = day_slots.get(d, {}).get(s["period"])
            if not sl:
                continue
            code, name, loc = sl["code"], _title_case(sl["name"]), sl.get("location", "")
            now_mins = datetime.now().hour * 60 + datetime.now().minute
            sm = int(s["start"].split(":")[0])*60 + int(s["start"].split(":")[1])
            em = int(s["end"].split(":")[0])*60 + int(s["end"].split(":")[1])
            hl = ""
            if d == today and sm <= now_mins < em:
                hl = "current"
            elif d == today and now_mins < sm and (sm - now_mins) <= 120:
                hl = "upcoming"
            cls = " tt-row--" + hl if hl else ""
            # review R6/R9: no Now badge (the hero already says it); Soon stays
            badge = "<span class=tt-badge tt-badge--soon>Soon</span>" if hl == "upcoming" else ""
            loc_html = "<span class=tt-loc>{0}</span>".format(loc) if loc else ""
            # attendance glance (review R7): the slim risk rim IS the can-be-missed
            # indicator; the bare number is data. Neutral "no data" for
            # unmatched/custom (opacity-50, never a numeric 0%)
            sig = _tt_att_sig(sl.get("_att"))
            riskbar = ('<span class="tt-riskbar{}"></span>'.format(
                " tt-riskbar--danger" if sig and sig["cls"] == "danger" else " tt-riskbar--warn" if sig and sig["cls"] == "warn" else ""))
            sig_html = ('<div class="tt-sub">{loc}<span class="tt-sig{cls}">{text}</span></div>'
                        ).format(loc=loc_html, cls=" tt-sig--" + sig["cls"] if sig else " tt-sig--none",
                                 text=sig["text"] if sig else "no data")
            rows.append('<div class="tt-row{cls}">{risk}'
                        '<div class="tt-time">{start}<small>{end}</small></div>'
                        '<div class="tt-info"><strong>{code}</strong><span class="tt-name">{name}</span></div>'
                        '{badge}{sig}</div>'.format(cls=cls, risk=riskbar, start=s["start"], end=s["end"],
                                                     code=code, name=name, badge=badge, sig=sig_html))
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
    marks = _jload(row["marks_json"] if row else None, [])
    return {"ok": True, "marks": marks}

@app.route("/api/feedback/fill", methods=["POST"])
@require_login
def api_feedback_fill():
    """OPT-IN mid-sem feedback submit (sync only harvests the map read-only).

    No request body: the server rebuilds the plan from the stored faculty map
    with _fb_plan() — the SAME builder that rendered the dashboard preview —
    so what the student saw IS what gets sent. Re-verified live per subject
    (already-registered / teacher-changed / window-closed all report honestly).
    """
    netid = get_current_user()
    if not netid:
        return {"ok": False, "error": "not logged in"}, 401
    c = db()
    row = c.execute("SELECT faculty_map_json FROM users WHERE netid=?", (netid,)).fetchone()
    c.close()
    fmap = _jload(row["faculty_map_json"] if row else None, {})
    plan = _fb_plan(fmap)
    if not plan:
        return {"ok": False, "error": "no feedback data yet — sync first"}, 400
    cookies = _load_session(netid)
    if not cookies:
        return {"ok": False, "error": "portal session expired — sync first"}, 400
    from . import http_scraper
    t0 = time.monotonic()
    try:
        res = http_scraper.fill_feedback(netid, plan, cookies)
    except http_scraper.HttpScraperError as e:
        log_with_kv(log_portal, logging.WARNING, "feedback fill error", netid=netid, error=str(e)[:80])
        _track("feedback_fill_fail", detail=str(e)[:60], user=netid)
        return {"ok": False, "error": str(e)}, 502
    ms = int((time.monotonic() - t0) * 1000)
    log_with_kv(log_portal, logging.INFO, "feedback fill done",
                netid=netid, filled=len(res.get("filled", [])), already=len(res.get("already", [])),
                failed=len(res.get("failed", [])), total_ms=ms)
    _track("feedback_fill_ok", detail=f"{ms}ms", user=netid)
    return {"ok": True, **res}

def _fmt_score(v):
    """Score keeps 2 decimals: 11.7 -> '11.70'. Junk/None -> '?' — a stored
    null score used to TypeError into a 500 (audit B9)."""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "?"

def _fmt_max(v):
    """Maxima are whole marks on the portal: 15.0 -> '15' (never '15.00')."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "?"
    return str(int(f)) if f.is_integer() else f"{f:.2f}"

def _fmt_date(s):
    """Portal date '04/Sep/2026' -> muted display '04 Sep'; junk passes through."""
    try:
        return datetime.strptime(s, "%d/%b/%Y").strftime("%d %b")
    except (ValueError, TypeError):
        return s or ""

def _derive_ie(code, maximum):
    """IE-1/IE-2 are never labelled by the portal — guess IE-1 from the
    component's scaled max (the /15 component; /10 for practicals like
    21CSC203P). A confirmed tag always wins; this is the 'derived' state."""
    if maximum == 15:
        return "IE-1"
    if maximum == 10 and str(code).endswith("P"):
        return "IE-1"
    return None

def _load_component_tags(class_key, marks):
    """Confirmed IE tags for this class's components -> {(code, name): row}.
    Keys carry no netid on purpose: one student's confirmation applies to the
    whole class (and is later reused by the GPA predictor)."""
    wanted = {f"{class_key}|{s.get('code', '')}|{c.get('name', '')}":
              (s.get("code", ""), c.get("name", ""))
              for s in marks for c in s.get("components", [])}
    if not wanted:
        return {}
    q = ",".join("?" * len(wanted))
    c = db()
    rows = c.execute(f"SELECT tag_key, role, raw_max, scaled_max FROM component_tags "
                     f"WHERE tag_key IN ({q})", list(wanted)).fetchall()
    c.close()
    return {wanted[r[0]]: {"role": r[1], "raw_max": r[2], "scaled_max": r[3]} for r in rows}

def _marks_view(marks, tags=None):
    """Marks tab view model: title-cased subjects, components sorted by NAME
    (the portal's order is by entry, dates jump around), '04 Sep' dates,
    integer maxima with 2-decimal scores, and IE rows converted back to their
    raw /50 (IE-1) or /60 (IE-2) marks. `tags` = confirmed overrides."""
    tags = tags or {}
    out = []
    for s in marks:
        code = s.get("code", "")
        comps = []
        for cpt in sorted(s.get("components", []), key=lambda c: str(c.get("name", ""))):
            maximum, scored = cpt.get("max", 0.0), cpt.get("scored", 0.0)
            tag = tags.get((code, cpt.get("name", "")))
            derived = _derive_ie(code, maximum)
            role = tag["role"] if tag else derived   # confirmed wins, incl. 'none'
            ie = None
            if role in ("IE-1", "IE-2"):
                raw = (tag.get("raw_max") if tag and tag.get("raw_max")
                       else (50.0 if role == "IE-1" else 60.0))
                ie = {"role": role, "confirmed": bool(tag), "max_disp": _fmt_max(raw),
                      "score_disp": _fmt_score(scored * raw / maximum) if maximum else _fmt_score(0)}
            comps.append({"name": cpt.get("name", ""), "date_disp": _fmt_date(cpt.get("entered", "")),
                          "score_disp": _fmt_score(scored), "max_disp": _fmt_max(maximum),
                          "derived": derived or "", "confirmed": tag["role"] if tag else None,
                          "ie": ie})
        st, mt = s.get("scored_total", 0.0), s.get("max_total", 0.0)
        out.append({"code": code, "title": (s.get("title") or "").title(),
                    "scored_disp": _fmt_score(st), "max_disp": _fmt_max(mt),
                    "pct": round(st / mt * 100, 1) if mt else 0.0, "outlier": False,
                    "components": comps})
    # One muted accent per screen (DESIGN.md §2.7): the UNIQUE lowest subject,
    # and only below the 75% target — everything else on this page is neutral.
    ranked = sorted(out, key=lambda x: x["pct"])
    if len(ranked) > 1 and ranked[0]["pct"] < ranked[1]["pct"] and ranked[0]["pct"] < 75:
        ranked[0]["outlier"] = True
    return out

def _marks_summary(marks):
    """Dashboard glance: the 3 lowest subjects (risk-first order — the chip
    shows marks/max, no %, per brief; ordering still surfaces weakest first).
    None when empty. No aggregate/overall number."""
    if not marks:
        return None
    low = sorted(marks, key=lambda m: (m.get("scored_total", 0) / m["max_total"])
                 if m.get("max_total") else 1)[:3]
    return [{"code": m.get("code", ""),
             "scored": _fmt_score(m.get("scored_total", 0)),
             "max": _fmt_max(m.get("max_total", 0))} for m in low]

def _exams_view(rows):
    """Dashboard card: end-sem rows sorted by real date + countdown.
    None when empty (card hidden)."""
    if not rows:
        return None
    def ts(r):
        try:
            return datetime.strptime(r.get("date", ""), "%d-%m-%Y")
        except ValueError:
            return datetime.max
    rows = sorted(rows, key=ts)
    for r in rows:  # display fields; junk dates fall back to the raw value
        try:
            d = datetime.strptime(r.get("date", ""), "%d-%m-%Y")
        except ValueError:
            d = None
        r["short"] = d.strftime("%d %b") if d else r.get("date", "")
        r["day"] = str(d.day) if d else r.get("date", "")[:2]
        r["dow"] = d.strftime("%a") if d else ""
        # portal returns ALL-CAPS names; shouty when wrapped on a narrow screen
        r["name_disp"] = " ".join(w.capitalize() for w in r.get("name", "").split())
        # portal codes: students know AN/FN natively — show them as-is
        r["session_disp"] = r.get("session", "")
    first = ts(rows[0])
    last = ts(rows[-1])
    days = (first.date() - datetime.now().date()).days
    if (first.year, first.month) == (last.year, last.month):
        label = first.strftime("%b %Y")
    elif first.year == last.year:
        label = first.strftime("%b") + "\u2013" + last.strftime("%b %Y")
    else:
        label = first.strftime("%b %Y") + "\u2013" + last.strftime("%b %Y")
    # Source badge: rows from the official 126 table carry a clock "slot";
    # scribe-leak rows don't. Mixed view = official dates + scribe estimates.
    n_official = sum(1 for r in rows if r.get("slot"))
    source = ("Official" if n_official == len(rows)
              else "Official + est." if n_official else "Estimated")
    return {"rows": rows, "label": label, "days_until": days, "source": source}


# ── exam event pushes (one-shot) ───────────────────────────────────────────
EXAM_EVT_TTL = 12 * 3600  # offline phones: deliver for 12 h, then drop


def _exam_events(old_json, new_rows):
    """One-shot exam push triggers, detected at save time as TRANSITIONS:
    estimate -> official release (the official 126 table supersedes the scribe
    estimate), and halls/seats newly published (the portal shows room numbers
    ~1 day before each exam — students crowd notice boards for them).

    Returns event dicts {claim, title, body, tag, url}. Claim keys are
    content-stable: re-detecting the same transition never mints a new claim.
    Fresh users (nothing stored) get no 'released' note — the card already
    shows the official schedule."""
    try:
        old = json.loads(old_json) if old_json else []
    except ValueError:
        old = []
    if not isinstance(old, list):
        old = []
    new_rows = new_rows or []
    events = []
    # estimate -> official release (only when we actually held estimates)
    old_off = any(r.get("slot") for r in old)
    new_off = [r for r in new_rows if r.get("slot")]
    if old and not old_off and new_off:
        first = min((r["date"] for r in new_off if r.get("date")), default="")
        try:
            first_disp = datetime.strptime(first, "%d-%m-%Y").strftime("%d %b")
        except ValueError:
            first_disp = first or "TBA"
        events.append({
            "claim": "official-" + (first or "unknown"),
            "title": "Official exam timetable",
            "body": f"{len(new_off)} exams \u00b7 starts {first_disp}",
            "tag": "exam-official-" + (first or "x"),
            "url": "/",
        })
    # halls/seats newly published or CHANGED (room corrections re-notify)
    old_hall = {r.get("code"): (r.get("hall", ""), r.get("seat", "")) for r in old}
    changed = [r for r in new_rows if r.get("hall")
               and old_hall.get(r.get("code")) != (r.get("hall", ""), r.get("seat", ""))]
    if changed:
        digest = hashlib.md5("|".join(
            f"{r.get('code')}:{r.get('hall')}:{r.get('seat')}" for r in
            sorted(changed, key=lambda r: r.get("code", ""))).encode()).hexdigest()[:12]
        if len(changed) == 1:
            r0 = changed[0]
            body = f"{r0['code']} \u00b7 Hall {r0['hall']}"
            if r0.get("seat"):
                body += f" \u00b7 Seat {r0['seat']}"
        else:
            body = " \u00b7 ".join(f"{r['code']} H{r['hall']}" for r in changed[:3])
            if len(changed) > 3:
                body += f" +{len(changed) - 3}"
        events.append({
            "claim": f"hall-{digest}",
            "title": ("Exam room allotted" if len(changed) == 1
                      else f"Exam rooms allotted ({len(changed)})"),
            "body": body, "tag": f"exam-hall-{digest}", "url": "/",
        })
    return events


def _notify_exam_events(netid, events, conf=None, send_batch=None):
    """Fire exam event pushes INLINE from the save path (right after commit —
    events are rare, a couple per semester, so no tick scheduling needed).

    At-most-once per device via push_sent_log's unique claim with a permanent
    local_date ('event'): the claim row can never be minted again, so a crash
    between claim and send loses the notification rather than duplicating it.
    dry-run / allowlist-held audits WITHOUT claiming — the one-shot transition
    is then gone (accepted: test modes don't keep history).

    ponytail: failed sends are dropped, not retried — move into the minute
    tick if retries ever matter. Injectable conf/send_batch for tests.
    Returns jobs handed to send_batch (0 = nothing sent)."""
    if not events:
        return 0
    if conf is None:
        conf = _push_conf()
    if not (conf["enabled"] and conf["configured"]):
        return 0
    subs = push_store.list_subscriptions(netid, enabled_only=True)
    if not subs:
        return 0
    jobs = []
    for ev in events:
        for sub in subs:
            if conf["dry_run"] or (conf["allow"] and netid not in conf["allow"]):
                log_with_kv(log_push, logging.INFO, "exam event held (dry-run/allowlist)",
                            netid=netid, ev=ev["claim"])
                continue
            if not push_store.claim_send(sub["id"], "event", 0, ev["claim"]):
                continue  # already claimed for this device — at-most-once
            row_id = push_store.sent_row_id(sub["id"], "event", 0, ev["claim"])
            if row_id is None:
                continue
            jobs.append({"sub": sub, "row_id": row_id, "claim": ev["claim"],
                         "ttl": EXAM_EVT_TTL, "payload": {
                             "title": ev["title"], "body": ev["body"],
                             "tag": ev["tag"], "url": ev["url"]}})
    if not jobs:
        return 0
    send_batch = send_batch or push_send.send_batch
    sent = 0
    for job in send_batch(jobs, time.monotonic() + 10):
        oc = job.get("outcome") or {}
        row_id, sub_row = job["row_id"], job["sub"]
        if oc.get("reason") == "deadline":
            push_store.record_send_result(row_id, push_store.STATUS_SKIPPED)
            continue
        if oc.get("ok"):
            push_store.record_send_result(row_id, push_store.STATUS_SENT, oc.get("http_status"))
            push_store.record_subscription_result(sub_row["id"], True, oc.get("http_status"))
            sent += 1
            status = "sent"
        elif oc.get("dead"):
            push_store.record_send_result(row_id, push_store.STATUS_FAILED, oc.get("http_status"))
            push_store.delete_subscription_by_id(sub_row["id"])
            status = "dead_cleanup"
        else:
            final = push_store.STATUS_FAILED if oc.get("retryable") else push_store.STATUS_SKIPPED
            push_store.record_send_result(row_id, final, oc.get("http_status"))
            push_store.record_subscription_result(sub_row["id"], False, oc.get("http_status"))
            status = final
        log_with_kv(log_push, logging.INFO, "exam event push", netid=netid,
                    ev=job["claim"], http=oc.get("http_status"), status=status)
    return sent


@app.route("/static/<path:filename>")
def static_no_cache(filename):
    from flask import send_from_directory
    # audit: was hardcoded "/app/app/static" — only worked inside the container
    # (local runs 404'd). Derive from __file__ like every other path here.
    resp = send_from_directory(os.path.join(os.path.dirname(__file__), "static"), filename)
    # Service worker and manifest need cacheable responses; CSS stays no-store
    if filename.endswith(('.js', '.json')):
        resp.headers["Cache-Control"] = "public, max-age=3600"
    else:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    if filename == "sw.js":
        # audit 2026-09-27: without this header a scope of "/" is rejected
        # (default max scope = the script's directory, /static/) and
        # registration fails — swallowed by .catch(), so the PWA silently
        # never worked. Registration now lives in login.js/dash.js (external
        # files pass script-src 'self').
        resp.headers["Service-Worker-Allowed"] = "/"
    return resp

def _login_error_code(err):
    """Audit: explicit status mapping — 401 auth, 429 rate/cooldown, 503 backend/portal.
    The old check keyed on the substring 'login failed', which the most common
    error string ('invalid credentials — check your NetID/password') never
    contains: every wrong-password attempt came back 503 instead of 401."""
    e = err.lower()
    if "invalid credentials" in e or "login failed" in e:
        return 401
    if "too many" in e or "rate-limit" in e:  # per-netid cap, per-IP cap, portal cooldown
        return 429
    return 503

@app.route("/login")
def login():
    if get_current_user(): return redirect("/")
    return render_template("login.html", version=APP_VERSION)

def _merge_fetch_result(existing, res):
    """preserve-if-empty merge shared by /api/login and /api/refresh (audit B6).

    An absent/empty fetch key must never clobber stored data: parse failures
    return marks=[] / personal={} with ok=True. The two routes had separate
    copies of this contract and drifted — refresh was missing the subjects
    preserve, so a hot-only refresh wiped stored subjects_json on the exact
    marks-page failure that preserved marks_json. One copy now.
    `existing` = current users row (dict row, or None on first fetch).
    Returns (personal_json, marks_json, subjects_json, exams_json,
    faculty_json, exam_events)."""
    def _col(key, col):
        if res.get(key):
            return json.dumps(res[key])
        if existing and existing[col]:
            return existing[col]   # transition events read PRE-write rows
        return json.dumps({"personal": {}, "marks": [], "subjects": {}}[key])
    personal_json = _col("personal", "personal_details_json")
    marks_json = _col("marks", "marks_json")
    subjects_json = _col("subjects", "subjects_json")
    # exams: key absent (probe unreliable / Playwright fallback) -> preserve stored
    if "exams" in res:
        exams_json = json.dumps(res["exams"])
        exam_events = _exam_events(existing["exam_schedule_json"] if existing else None,
                                   res["exams"])
    else:
        exams_json = (existing["exam_schedule_json"] if existing and existing["exam_schedule_json"] else "[]")
        exam_events = []
    # faculty map: key absent (window closed / harvest failed) -> preserve stored
    if "faculty" in res:
        faculty_json = json.dumps(res["faculty"])
    else:
        faculty_json = (existing["faculty_map_json"] if existing and existing["faculty_map_json"] else "{}")
    return personal_json, marks_json, subjects_json, exams_json, faculty_json, exam_events


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
    netid = (d.get("netid") or "").strip().lower().split("@")[0] if isinstance(d.get("netid"), str) else ""
    password = d.get("password") if isinstance(d.get("password"), str) else ""
    if not netid or not password:
        return {"ok": False, "error": "netid and password required"}, 400
    if not NETID_RE.match(netid):  # audit: validate before it hits Playwright/DB
        return {"ok": False, "error": "invalid NetID format"}, 400
    if len(password) > 128:
        return {"ok": False, "error": "invalid password"}, 400

    # audit 2026-09-27: count the per-IP budget AFTER validation (was before).
    # Previously 11 trivial `{}` POSTs (valid JSON dict, no credentials) burned
    # the 10/hour budget and 429'd the rest of the hour — a cheap self-DoS on
    # shared campus NAT that never even reached the portal.
    if not _check_ip_rate(_client_ip()):
        log_with_kv(log_auth, logging.WARNING, "login ip limited", ip=_client_ip())
        return {"ok": False, "error": f"Too many login attempts from this device (10/hour). Try again in {_ip_retry_text(_client_ip())}."}, 429

    login_t0 = time.monotonic()
    res = fetch_attendance(netid, password)
    login_ms = int((time.monotonic() - login_t0) * 1000)
    if not res["ok"]:
        log_with_kv(log_auth, logging.WARNING, "login failed", netid=netid, ip=_client_ip(),
                    error=res["error"][:80], duration_ms=login_ms)
        _track("login_fail", detail=res["error"][:60], user=netid)
        # audit F4: auth failures are 401; busy/rate are 429/503
        code = _login_error_code(res["error"])
        return {"ok": False, "error": res["error"]}, code
    log_with_kv(log_auth, logging.INFO, "login ok", netid=netid, ip=_client_ip(),
                duration_ms=login_ms, subjects=len(res.get("marks", [])))
    _track("login_ok", detail=f"{login_ms}ms", user=netid)
    c = db()
    # Hot/cold + audit B6: empty/absent fetch keys preserve stored cold data
    # (single shared contract — see _merge_fetch_result)
    existing = c.execute("SELECT personal_details_json, subjects_json, exam_schedule_json, marks_json, faculty_map_json FROM users WHERE netid=?", (netid,)).fetchone()
    (personal_json, marks_json, subjects_json, exams_json, faculty_json,
     exam_events) = _merge_fetch_result(existing, res)
    # photo_b64 dropped: write-only since photo scraping was removed Sep 25 2026
    c.execute("INSERT INTO users(netid,password,attendance_json,last_fetch,personal_details_json,marks_json,subjects_json,exam_schedule_json,faculty_map_json) VALUES(?,?,?,?,?,?,?,?,?) "
              "ON CONFLICT(netid) DO UPDATE SET password=excluded.password, attendance_json=excluded.attendance_json, marks_json=excluded.marks_json, subjects_json=excluded.subjects_json, "
              "last_fetch=excluded.last_fetch, personal_details_json=excluded.personal_details_json, exam_schedule_json=excluded.exam_schedule_json, faculty_map_json=excluded.faculty_map_json",
              (netid, encrypt_pw(password), json.dumps(res["data"]), res["fetched"],
               personal_json, marks_json, subjects_json, exams_json, faculty_json))
    c.commit(); c.close()
    # one-shot exam pushes (official release / room allotment): post-commit,
    # background thread — detection already read pre-write rows, and the
    # single gunicorn worker must not wait on a push round-trip
    if exam_events:
        threading.Thread(target=_notify_exam_events, args=(netid, exam_events),
                         daemon=True, name="srm-exam-evt").start()

    # Save timetable group and scraped subjects (non-critical, separate tx)
    try:
        personal = dict(res.get("personal", {}))
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
    except Exception as e:
        log.warning("timetable group/subject save failed netid=%s: %r", netid, e, exc_info=True)

    token = make_session_token(netid)
    resp = make_response({"ok": True})
    resp.set_cookie("srm_session", token, max_age=SESSION_MAX_AGE, httponly=True,
                    samesite="Lax", secure=_cookie_secure())
    return resp

@app.route("/api/refresh", methods=["POST"])
@require_login
def api_refresh():
    netid = get_current_user()
    if not netid:
        return {"ok": False, "error": "not logged in"}, 401
    c = db()
    row = c.execute("SELECT password FROM users WHERE netid=?", (netid,)).fetchone()
    c.close()
    if not row:
        log_with_kv(log_auth, logging.WARNING, "refresh blocked", netid=netid, reason="no_stored_creds")
        return {"ok": False, "error": "no stored creds"}, 401
    password = decrypt_pw(row["password"])  # audit: was plaintext, now Fernet
    if not password:
        log_with_kv(log_auth, logging.WARNING, "refresh blocked", netid=netid, reason="unreadable_creds")
        return {"ok": False, "error": "stored credentials unreadable \u2014 log in again"}, 401
    res = fetch_attendance(netid, password)
    if not res["ok"]:
        # audit 2026-09-30: refresh failures were invisible — prod 07:43 logged
        # only "status=503" with no reason anywhere, so the failure class could
        # not be diagnosed after the fact. Same KV line as /api/login.
        log_with_kv(log_auth, logging.WARNING, "refresh failed", netid=netid,
                    error=res["error"][:80])
        _track("sync_fail", detail=res["error"][:60], user=netid)
        # audit F4: match /api/login's status-code discipline
        code = _login_error_code(res["error"])
        return {"ok": False, "error": res["error"]}, code
    c = db()
    # Hot/cold + audit B6: same single preserve contract as login
    row2 = c.execute("SELECT personal_details_json, subjects_json, exam_schedule_json, marks_json, faculty_map_json FROM users WHERE netid=?", (netid,)).fetchone()
    (personal_json, marks_json, subjects_json, exams_json, faculty_json,
     exam_events) = _merge_fetch_result(row2, res)
    c.execute("UPDATE users SET attendance_json=?, last_fetch=?, personal_details_json=?, marks_json=?, subjects_json=?, exam_schedule_json=?, faculty_map_json=? WHERE netid=?",
              (json.dumps(res["data"]), res["fetched"], personal_json,
               marks_json, json.dumps(res.get("subjects", {})), exams_json, faculty_json, netid))
    c.commit(); c.close()
    _track("sync_ok", user=netid)
    # same one-shot exam pushes as login — post-commit, background thread
    if exam_events:
        threading.Thread(target=_notify_exam_events, args=(netid, exam_events),
                         daemon=True, name="srm-exam-evt").start()
    return {"ok": True}

# ── Login preflight: browser fires this when the user focuses the
#    password field — warms the portal session + solves the captcha
#    while they finish typing. Consumed by /api/login via fetch_attendance.
_preflight_last = {}   # netid -> ts (30s per-netid cooldown)
_preflight_ip = {}     # ip -> [ts, ...] (10 per 10 min per IP)

def _run_preflight(netid):
    try:
        from . import http_scraper
        http_scraper.preflight(netid)
    except Exception as e:
        # audit 2026-10-07: warm-login loss was DEBUG-only — now visible at WARNING
        log.warning("preflight failed netid=%s err=%r", netid, e)

@app.route("/api/login/preflight", methods=["POST"])
def api_login_preflight():
    d = request.get_json(silent=True)
    netid = ((d.get("netid") or "").strip().lower().split("@")[0]
             if isinstance(d, dict) and isinstance(d.get("netid"), str) else "")
    if not netid or not NETID_RE.match(netid):
        return {"ok": False}, 400
    now = time.time()
    ip = _client_ip()
    hits = [t for t in _preflight_ip.get(ip, []) if now - t < 600]
    if len(hits) >= 10:  # ponytail: preflight is unauthenticated — cap hard
        log_with_kv(log_auth, logging.WARNING, "preflight ip limited", netid=netid, ip=ip)
        return {"ok": False, "error": "rate"}, 429
    if now - _preflight_last.get(netid, 0) < 30:
        return {"ok": True, "cooldown": True}
    if _portal_cooldown_remaining() > 0 or _scrape_lock.locked():
        log_with_kv(log_auth, logging.WARNING, "preflight busy", netid=netid, ip=ip)
        return {"ok": False, "error": "portal busy"}, 503
    if not _check_portal_budget():  # audit: per-IP caps don't bind IP rotation — aggregate egress cap does
        return {"ok": False, "error": "rate"}, 429
    _preflight_ip[ip] = hits + [now]
    _preflight_last[netid] = now
    threading.Thread(target=_run_preflight, args=(netid,), daemon=True,
                     name="srm-preflight").start()
    log_with_kv(log_auth, logging.DEBUG, "preflight start", netid=netid, ip=ip)
    return {"ok": True}

@app.route("/api/login/progress", methods=["POST"])
def api_login_progress():
    # audit: GET put netid in the URL (access logs, history, referrers).
    # Mid-login, session auth can't apply — the body keeps it out of logs.
    data = request.get_json(silent=True) or {}
    netid = str(data.get("netid", "")).strip().lower()
    if not netid or not NETID_RE.match(netid):
        return {"step": "", "pct": 0}, 400
    p = _login_progress.get(netid)
    # ponytail: entries purged when >10min old; fine for a ~5-30s flow
    if p and time.time() - p["ts"] > 600:
        _login_progress.pop(netid, None)
        p = None
    return {"step": p["step"], "pct": p["pct"]} if p else {"step": "", "pct": 0}

# ── Timetable API ───────────────────────────────────────────────
def _load_personal(netid):
    """personal_details_json for a netid; corrupt/missing row -> {}.

    One shared decode — was copy-pasted (with a different comment) across the
    three timetable routes."""
    try:
        c = db()
        r = c.execute("SELECT personal_details_json FROM users WHERE netid=?", (netid,)).fetchone()
        c.close()
        v = json.loads(r[0]) if r and r[0] else {}
        return v if isinstance(v, dict) else {}
    except Exception as e:  # corrupt/unreadable row → proceed with empty personal details
        log.warning("corrupt personal_details_json netid=%s: %r", netid, e)
        return {}


@app.route("/api/timetable", methods=["GET"])
def api_get_timetable():
    netid = get_current_user()
    if not netid: return {"ok": False, "error": "not logged in"}, 401
    personal = _load_personal(netid)
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

def _tt_sort_key(key):
    """'Monday-3' -> (day index, period); unknown days sort last."""
    day, _, period = key.rpartition("-")
    try:
        di = DAY_ORDER.index(day)
    except ValueError:
        di = 99
    return (di, int(period) if period.isdigit() else 99)

def _tt_diff(old, new):
    """Slot-level diff for the edit log: added/removed/changed entries."""
    out = []
    for key in sorted(set(old) | set(new), key=_tt_sort_key):
        o, n = old.get(key), new.get(key)
        day, period = key.rsplit("-", 1)
        base = {"day": day, "period": int(period) if period.isdigit() else 0}
        if o and not n:
            out.append({**base, "action": "removed", "from": o})
        elif n and not o:
            out.append({**base, "action": "added", "to": n})
        elif o != n:
            out.append({**base, "action": "changed", "from": o, "to": n})
    return out

@app.route("/api/timetable/history", methods=["GET"])
def api_timetable_history():
    """Edit log for the caller's own group (classmates share group_key)."""
    netid = get_current_user()
    if not netid: return {"ok": False, "error": "not logged in"}, 401
    personal = _load_personal(netid)
    gk = _group_key(personal)
    if not gk: return {"ok": True, "entries": []}
    c = db()
    gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()
    if not gid: c.close(); return {"ok": True, "entries": []}
    entries = []
    for r in c.execute("SELECT editor_netid,editor_name,created_at,changes_json "
                       "FROM timetable_edit_log WHERE group_id=? ORDER BY id DESC LIMIT 50",
                       (gid[0],)):
        try:
            changes = json.loads(r[3] or "[]")
        except Exception as e:
            log.warning("corrupt timetable edit changes_json: %r", e)
            changes = []
        entries.append({"netid": r[0], "name": r[1] or "", "at": r[2], "changes": changes})
    c.close()
    return {"ok": True, "entries": entries}

@app.route("/api/timetable", methods=["POST"])
def api_save_timetable():
    netid = get_current_user()
    if not netid: return {"ok": False, "error": "not logged in"}, 401
    data = request.get_json(silent=True) or {}
    slots = data.get("slots", {})
    custom = data.get("custom_subjects", [])
    personal = _load_personal(netid)
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
    # audit feature: diff old vs new BEFORE the delete-and-replace so the
    # shared timetable's edit log records exactly who changed what.
    old_rows = {f"{r[0]}-{r[1]}": {"code": r[2] or "", "name": r[3] or "",
                                   "location": r[4] or ""}
                for r in c.execute("SELECT day,period,subject_code,subject_name,location "
                                   "FROM timetable_slots WHERE group_id=?", (gid,))}
    old_slots = {k: {"code": v["code"], "name": v["name"]} for k, v in old_rows.items()}
    new_slots = {}
    for key, val in slots.items():
        if val and len(key.rsplit("-", 1)) == 2:
            new_slots[key] = {"code": str(val.get("code", "")), "name": str(val.get("name", ""))}
    changes = _tt_diff(old_slots, new_slots)
    c.execute("DELETE FROM timetable_slots WHERE group_id=?", (gid,))
    for key, val in new_slots.items():
        day, period = key.rsplit("-", 1)
        # fix 2026-10-05: the editor has no location field, so a blind
        # delete+re-insert used to wipe `location` for the WHOLE group on
        # every save (proved: 'Test Hall' -> ''). Carry the room forward
        # while the slot's subject CODE is unchanged; a swapped subject
        # drops the old room (it belonged to the old class).
        prev = old_rows.get(key)
        loc = prev["location"] if prev and prev["code"] == val["code"] else ""
        c.execute("INSERT INTO timetable_slots(group_id,day,period,subject_code,subject_name,location) "
                  "VALUES(?,?,?,?,?,?)", (gid, day, int(period), val["code"], val["name"], loc))
    if changes:  # no-op saves stay out of the log
        c.execute("INSERT INTO timetable_edit_log(group_id,editor_netid,editor_name,changes_json) "
                  "VALUES(?,?,?,?)",
                  (gid, netid, str(personal.get("Student Name", "")), json.dumps(changes, ensure_ascii=False)))
        # ponytail: keep the last 200 entries per group (spam ceiling);
        # raise the LIMIT if sections start legitimately editing that often
        c.execute("DELETE FROM timetable_edit_log WHERE group_id=? AND id NOT IN "
                  "(SELECT id FROM timetable_edit_log WHERE group_id=? ORDER BY id DESC LIMIT 200)",
                  (gid, gid))
    c.commit(); c.close()
    return {"ok": True}

@app.route("/marks/tag", methods=["POST"])
def marks_tag():
    """Confirm (or refuse) the IE-1/IE-2 tag of one component. Server-side only:
    the scaled max comes from the live portal row, never from the form.
    The tag key is class-scoped, so one student's confirmation applies to the
    whole class — persisted for the future GPA predictor. Redirects back to the
    marks tab (#marks restores it)."""
    netid = get_current_user()
    if not netid:
        return redirect("/login")
    form = request.form
    code = (form.get("code") or "").strip()[:32]
    name = (form.get("component") or "").strip()[:32]
    role = form.get("role")
    if role not in ("IE-1", "IE-2", "none") or not code or not name:
        return redirect("/#marks")
    c = db()
    row = c.execute("SELECT marks_json, personal_details_json FROM users WHERE netid=?",
                    (netid,)).fetchone()
    try:
        marks = json.loads(row[0]) if row and row[0] else []
        personal = json.loads(row[1]) if row and row[1] else {}
    except (ValueError, TypeError):
        marks, personal = [], {}
    scaled = next((cp.get("max", 0.0) for s in marks if s.get("code") == code
                   for cp in s.get("components", []) if cp.get("name") == name), 0.0)
    if not scaled:
        c.close()
        return redirect("/#marks")
    # raw_max: the marks the component stands for on paper (50 / 60); 'none'
    # keeps it NULL — the row exists either way, which is what 'confirmed' means.
    raw = {"IE-1": 50.0, "IE-2": 60.0}.get(role)
    key = f"{_class_key(personal, netid)}|{code}|{name}"
    c.execute("""INSERT INTO component_tags(tag_key, role, raw_max, scaled_max, confirmed_by, updated_at)
                 VALUES(?,?,?,?,?,?)
                 ON CONFLICT(tag_key) DO UPDATE SET role=excluded.role, raw_max=excluded.raw_max,
                 scaled_max=excluded.scaled_max, confirmed_by=excluded.confirmed_by,
                 updated_at=excluded.updated_at""",
              (key, role, raw, scaled, netid, int(time.time())))
    c.commit(); c.close()
    return redirect("/#marks")

# ── Web push: config, tick endpoint ───────────────────────────────────
# All secrets come from env (identical on every host / Vercel). The app
# NEVER generates or falls back to generated keys: missing keys => the
# feature reports "not configured" and sends nothing.
PUSH_TICK_HEADER = "X-Push-Tick"
TICK_DEADLINE_S = 20.0       # cron-job.org's hard budget is ~30s; keep 10s margin
STALE_CLAIM_S = 120          # claims older than this with no outcome -> orphaned
log_push = logging.getLogger("opensrm.push")


def _push_conf():
    env_b = lambda k: os.environ.get(k, "").strip().lower() in ("1", "true", "yes")
    priv = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    pub = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    sub = os.environ.get("VAPID_SUBJECT", "").strip()
    return {
        "enabled": env_b("PUSH_ENABLED"),
        "dry_run": env_b("PUSH_DRY_RUN"),
        "allow": {n.strip().lower() for n in os.environ.get("PUSH_ALLOW_NETIDS", "").split(",") if n.strip()},
        "tick_secret": os.environ.get("PUSH_TICK_SECRET", ""),
        "private": priv, "public": pub, "subject": sub,
        "configured": bool(priv and pub and sub),
    }


def _endpoint_hash(endpoint):
    """Capability URL must never be logged in full — short hash prefix only."""
    return hashlib.sha256(endpoint.encode()).hexdigest()[:12]


def _push_groups(netids):
    """netid -> group_key from stored personal details (one query)."""
    if not netids:
        return {}
    c = db()
    q = ",".join("?" * len(netids))
    out = {}
    for r in c.execute(f"SELECT netid, personal_details_json FROM users WHERE netid IN ({q})", list(netids)):
        try:
            pd = json.loads(r[1]) if r[1] else {}
        except (ValueError, TypeError):
            pd = {}
        out[r[0]] = _group_key(pd)
    c.close()
    return out


def _push_timetable(group_keys):
    """{group_key: {day: {period: {code,name,location}}}} for the given groups."""
    group_keys = [g for g in group_keys if g]
    if not group_keys:
        return {}
    c = db()
    q = ",".join("?" * len(group_keys))
    gids = {r[0]: r[1] for r in c.execute(f"SELECT id, group_key FROM timetable_groups WHERE group_key IN ({q})", group_keys)}
    out = {}
    if gids:
        qi = ",".join("?" * len(gids))
        for r in c.execute(f"SELECT group_id, day, period, subject_code, subject_name, location FROM timetable_slots WHERE group_id IN ({qi})", list(gids)):
            day = out.setdefault(gids[r[0]], {}).setdefault(r[1], {})
            day[r[2]] = {"code": r[3] or "", "name": r[4] or "", "location": r[5] or ""}
    c.close()
    return out


def _run_tick(now=None, conf=None, send_batch=None, deadline_s=TICK_DEADLINE_S):
    """One tick: compute due from LIVE data, claim, send, record.

    Stateless and idempotent: overlapping ticks race only on the sent-log
    claim (one winner), a skipped tick just widens the catch-up window
    (due stays open until the class starts). Injectables (now/conf/
    send_batch/deadline_s) exist so tests can drive the clock and the
    network without touching either.
    """
    conf = conf if conf is not None else _push_conf()
    send_batch = send_batch or push_send.send_batch
    now = now or datetime.now(ZoneInfo("Asia/Kolkata"))
    t0 = time.monotonic()
    deadline = t0 + deadline_s
    local_date = now.strftime("%Y-%m-%d")
    mode = "off" if not conf["enabled"] else ("dry-run" if conf["dry_run"] else "live")
    stats = {"mode": mode, "due": 0, "claimed": 0, "sent": 0, "failed": 0,
             "dead": 0, "held": 0, "audited": 0, "skipped_deadline": 0, "orphaned": 0}
    # Crash recovery: a claim stuck without an outcome is finalized (never
    # retried — at-most-once). Fresh claims are inside their send window.
    stats["orphaned"] = push_store.finalize_stale_claims(int(time.time()) - STALE_CLAIM_S)

    subs_rows = push_store.list_subscriptions(enabled_only=True)
    groups = _push_groups({s["netid"] for s in subs_rows})
    subs = [push_calc.Sub(id=s["id"], netid=s["netid"], group_key=groups.get(s["netid"]),
                          lead_minutes=s["lead_minutes"]) for s in subs_rows]
    tt = _push_timetable(groups.values())
    sent = push_store.sent_state_for(local_date)
    due = push_calc.due_reminders(now, subs, tt, sent)
    stats["due"] = len(due)

    can_send = mode == "live" and conf["configured"]
    jobs = []
    for rem in due:
        sub_row = next(s for s in subs_rows if s["id"] == rem.sub.id)
        allowed = not conf["allow"] or rem.sub.netid.lower() in conf["allow"]
        if not can_send:
            # audit only: never claim (a dry-run/off tick must not consume
            # the reminder the real send is still going to make)
            stats["audited"] += 1
            log_with_kv(log_push, logging.INFO, "push audit",
                        mode=mode, netid=rem.sub.netid, code=rem.block.code,
                        starts=rem.block.start.strftime("%H:%M"), retry=rem.retry)
            continue
        if not allowed:
            stats["held"] += 1   # allowlist holds it; send happens on a later tick
            continue
        if time.monotonic() > deadline:
            stats["skipped_deadline"] += 1
            continue
        if rem.retry:
            if not push_store.claim_retry(rem.row_id, push_calc.MAX_ATTEMPTS):
                continue  # another tick took the retry
            row_id = rem.row_id
        else:
            if not push_store.claim_send(rem.sub.id, local_date, rem.block.start_epoch, rem.block.code):
                continue  # concurrent tick claimed first
            row_id = push_store.sent_row_id(rem.sub.id, local_date, rem.block.start_epoch, rem.block.code)
            if row_id is None:  # theoretical race with deletion
                continue
        stats["claimed"] += 1
        jobs.append({"rem": rem, "sub": sub_row, "row_id": row_id,
                     "payload": rem.message(now), "ttl": rem.ttl})

    for job in (send_batch(jobs, deadline) if jobs else []):
        oc = job.get("outcome") or {}
        row_id, sub_row, rem = job["row_id"], job["sub"], job["rem"]
        host = urlparse(sub_row["endpoint"]).netloc
        if oc.get("reason") == "deadline":
            push_store.record_send_result(row_id, push_store.STATUS_SKIPPED)
            stats["skipped_deadline"] += 1
            continue
        if oc.get("ok"):
            push_store.record_send_result(row_id, push_store.STATUS_SENT, oc.get("http_status"))
            push_store.record_subscription_result(sub_row["id"], True, oc.get("http_status"))
            stats["sent"] += 1
            status = "sent"
        elif oc.get("dead"):
            push_store.record_send_result(row_id, push_store.STATUS_FAILED, oc.get("http_status"))
            push_store.delete_subscription_by_id(sub_row["id"])
            stats["dead"] += 1
            status = "dead_cleanup"
        else:
            final = push_store.STATUS_FAILED if oc.get("retryable") else push_store.STATUS_SKIPPED
            push_store.record_send_result(row_id, final, oc.get("http_status"))
            push_store.record_subscription_result(sub_row["id"], False, oc.get("http_status"))
            stats["failed"] += 1
            status = final
        log_with_kv(log_push, logging.INFO, "push send", netid=sub_row["netid"], host=host,
                    endpoint=_endpoint_hash(sub_row["endpoint"]), http=oc.get("http_status"),
                    status=status, code=rem.block.code, ttl=job["ttl"])
    stats.pop("due_pass", None)
    push_store.prune_events(int(time.time()) - 3 * 3600)   # keep the rate table tiny
    stats["took_ms"] = int((time.monotonic() - t0) * 1000)
    log_with_kv(log_push, logging.INFO, "push tick", **stats)
    return {"ok": True, **stats}


@app.route("/internal/push/tick", methods=["POST"])
def push_tick():
    """cron-job.org fires this every minute. Secret header, no session;
    wrong/missing secret => bare 401 with no detail (nothing to probe)."""
    conf = _push_conf()
    got = request.headers.get(PUSH_TICK_HEADER, "")
    if not conf["tick_secret"] or not hmac.compare_digest(got, conf["tick_secret"]):
        log_with_kv(log_push, logging.WARNING, "tick auth failed", ip=_client_ip())
        return "", 401
    return _run_tick(conf=conf)


# ── Web push: user endpoints (JSON, session auth, 401 style) ──────────
# DB-backed rate limits only (process-local dicts die on serverless):
# subscribe 10/hour/netid, test push 3/hour/netid, receipts 30/hour/netid.

def _push_401():
    return {"ok": False, "error": "not logged in"}, 401


def _push_bad(msg, code=400):
    return {"ok": False, "error": msg}, code


@app.route("/api/push/status")
def push_status():
    netid = get_current_user()
    if not netid:
        return _push_401()
    conf = _push_conf()
    subs = push_store.list_subscriptions(netid=netid, enabled_only=False)
    row = subs[0] if subs else None
    return {"ok": True,
            "configured": conf["configured"],
            "enabled": conf["enabled"],
            "dry_run": conf["dry_run"],
            "allowlisted": not conf["allow"] or netid.lower() in conf["allow"],
            "vapid_public_key": conf["public"] if conf["configured"] else "",
            "endpoint_hash": _endpoint_hash(row["endpoint"]) if row else None,
            "subscription": ({"lead_minutes": row["lead_minutes"],
                              "enabled": bool(row["enabled"]),
                              "created_at": row["created_at"]} if row else None),
            "lead_choices": list(push_calc.LEAD_CHOICES)}


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    netid = get_current_user()
    if not netid:
        return _push_401()
    conf = _push_conf()
    if not conf["configured"]:
        return _push_bad("push not configured", 409)
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return _push_bad("invalid request — Content-Type must be application/json")
    endpoint, keys = d.get("endpoint"), d.get("keys")
    p256dh = keys.get("p256dh") if isinstance(keys, dict) else None
    auth = keys.get("auth") if isinstance(keys, dict) else None
    if (not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 4096
            or not isinstance(p256dh, str) or not p256dh or len(p256dh) > 512
            or not isinstance(auth, str) or not auth or len(auth) > 512):
        return _push_bad("invalid subscription")
    if push_store.count_events(netid, "subscribe", int(time.time()) - 3600) >= 10:
        return _push_bad("too many subscription updates (10/hour)", 429)
    row = push_store.upsert_subscription(netid, endpoint, p256dh, auth,
                                         str(d.get("ua_label", ""))[:64])
    push_store.record_event(netid, "subscribe", _endpoint_hash(endpoint))
    return {"ok": True, "lead_minutes": row["lead_minutes"],
            "endpoint_hash": _endpoint_hash(endpoint)}


@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    netid = get_current_user()
    if not netid:
        return _push_401()
    d = request.get_json(silent=True)
    endpoint = d.get("endpoint") if isinstance(d, dict) else None
    if not isinstance(endpoint, str) or not endpoint:
        return _push_bad("endpoint required")
    removed = push_store.remove_subscription(netid, endpoint)
    return {"ok": True, "removed": removed}


@app.route("/api/push/settings", methods=["POST"])
def push_settings():
    netid = get_current_user()
    if not netid:
        return _push_401()
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return _push_bad("invalid request — Content-Type must be application/json")
    lead, enabled = d.get("lead_minutes"), d.get("enabled")
    if lead is None and enabled is None:
        return _push_bad("nothing to update")
    if lead is not None and lead not in push_calc.LEAD_CHOICES:
        return _push_bad(f"lead_minutes must be one of {', '.join(map(str, push_calc.LEAD_CHOICES))}")
    if enabled is not None and not isinstance(enabled, bool):
        return _push_bad("enabled must be true or false")
    n = push_store.set_settings(netid, lead_minutes=lead, enabled=enabled)
    if n == 0:
        return _push_bad("no subscription for this account", 404)
    return {"ok": True, "updated": n}


@app.route("/api/push/test", methods=["POST"])
def push_test():
    """Send one real notification to this account's device (receipts prove
    arrival server-side). Rate-limited; works only when the feature is on."""
    netid = get_current_user()
    if not netid:
        return _push_401()
    conf = _push_conf()
    if not conf["configured"]:
        return _push_bad("push not configured", 409)
    if not conf["enabled"]:
        return _push_bad("reminders are disabled", 403)
    if conf["allow"] and netid.lower() not in conf["allow"]:
        return _push_bad("reminders are not enabled for your account yet", 403)
    if push_store.count_events(netid, "test_push", int(time.time()) - 3600) >= 3:
        return _push_bad("test notifications are limited to 3 per hour", 429)
    subs = push_store.list_subscriptions(netid=netid)
    if not subs:
        return _push_bad("no subscription — enable reminders first")
    test_id = secrets.token_hex(16)
    push_store.record_event(netid, "test_push", test_id)   # count BEFORE sending
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    payload = {"title": "OpenSRM test",
               "body": f"Test notification · {now:%H:%M}",
               "tag": f"test-{test_id}", "test_id": test_id, "url": "/"}
    job = push_send.send_one({"sub": subs[0], "payload": payload, "ttl": 600})
    oc = job["outcome"]
    if not oc.get("ok"):
        # audit 2026-10-07: the 3 prod push-test 502s (Oct 5 VAPID) and the
        # 410 row deletion left only "status=502 duration_ms=10" — the
        # outcome was never logged anywhere.
        log_with_kv(log_push, logging.WARNING, "push test failed",
                    netid=netid, http=oc.get("http_status"),
                    dead=bool(oc.get("dead")), err=(oc.get("error") or "")[:120])
    if oc.get("ok"):
        return {"ok": True, "test_id": test_id}
    if oc.get("dead"):
        push_store.delete_subscription_by_id(subs[0]["id"])
        return _push_bad("this device's subscription expired — turn reminders off and on again", 410)
    return _push_bad(f"push service error (http {oc.get('http_status')})", 502)


@app.route("/api/push/receipt", methods=["POST"])
def push_receipt():
    """The SW posts this when a test notification actually displayed —
    Navya's server-side proof of device delivery (esp. iOS)."""
    netid = get_current_user()
    if not netid:
        return _push_401()
    d = request.get_json(silent=True)
    test_id = d.get("test_id") if isinstance(d, dict) else None
    if not isinstance(test_id, str) or not re.fullmatch(r"[0-9a-f]{32}", test_id):
        return _push_bad("invalid test_id")
    if push_store.count_events(netid, "receipt", int(time.time()) - 3600) >= 30:
        return _push_bad("too many receipts (30/hour)", 429)
    push_store.record_event(netid, "receipt", test_id)
    return {"ok": True}


@app.route("/logout")
def logout():
    # incident 2026-10-10: this was a state-changing GET and prod sits behind
    # Cloudflare Speed Brain's conservative speculation rules (/*), so the
    # browser could fire GET /logout on mere link intent (touch-start/hover)
    # with no navigation at all — session died mid-use. Speculative requests
    # carry Sec-Purpose/Purpose prefetch|prerender: ignore them entirely.
    # no-store is required: if the user's intent then completes into a real
    # click, the ignored 302 must NOT be served from the prefetch cache or
    # the genuine logout would silently no-op.
    spec = (request.headers.get("Sec-Purpose", "") + " " +
            request.headers.get("Purpose", "")).lower()
    if "prefetch" in spec or "prerender" in spec:
        log_with_kv(log_auth, logging.INFO, "logout ignored",
                    reason="speculation", ip=_client_ip())
        resp = make_response(redirect("/login"))
        resp.headers["Cache-Control"] = "no-store"
        return resp
    token = request.cookies.get("srm_session")
    netid = None
    if token:
        c = db()
        row = c.execute("SELECT netid FROM cookies WHERE token=?", (token,)).fetchone()
        netid = row["netid"] if row else None
        c.execute("DELETE FROM cookies WHERE token=?", (token,))
        c.commit(); c.close()
    # incident logging: real logouts previously left no auth line at all —
    # attribution had to be reconstructed from HTTP 302s + cookie joins.
    log_with_kv(log_auth, logging.INFO, "logout ok", netid=netid or "-",
                ip=_client_ip())
    resp = make_response(redirect("/login"))
    # audit F2 fix: same flags on the clearing path — recon saw a bare
    # 'Secure; Path=/' Set-Cookie here because delete_cookie didn't inherit them
    resp.delete_cookie("srm_session", secure=_cookie_secure(), httponly=True, samesite="Lax")
    return resp

# Pre-warm ddddocr on import so the first real scrape isn't +3s cold.
threading.Thread(target=get_solver, daemon=True, name="srm-captcha-prewarm").start()

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

