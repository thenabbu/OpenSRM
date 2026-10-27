#!/usr/bin/env python3
"""SRM Attendance — Flask app (multi-user, security-hardened, Sep 2026 audit).

Audit fixes (Sep 16 2026):
  - Passwords encrypted at rest (Fernet — FERNET_KEYS env, else /app/data/fernet.key)
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
import contextvars
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from html import escape as _hesc  # audit: escape DB values before |safe timetable HTML
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

# timetable_html is now defined locally (SQLite-backed)
from flask import Flask, current_app, g, has_app_context, has_request_context, make_response, redirect, render_template, request
from werkzeug.exceptions import HTTPException

from . import metrics, push_calc, push_send, push_store
from .config import AppConfig
from .db import (  # noqa: F401 — db + SQLITE_TIMEOUT_SECS re-exported for scripts/tests
    SQLITE_TIMEOUT_SECS,
    append_edit_log,
    clear_official_stamp,
    close_db,
    component_tags,
    connect,
    create_session,
    day_slots,
    db,
    delete_account_rows,
    delete_cookie,
    delete_portal_session,
    edit_log_entries,
    get_cookie,
    get_portal_session,
    group_id,
    group_ids_for,
    group_slots,
    group_subjects,
    insert_usage_event,
    official_times,
    ping,
    pop_cookie,
    prune_push_sent_log,
    prune_usage_events,
    replace_group_slots,
    save_portal_session,
    set_cold_fetch,
    set_fb_open,
    set_official_times,
    slots_for_groups,
    transaction,
    tt_fetched_at,
    upsert_component_tag,
    upsert_group,
    upsert_subject,
    user_cold_fetch,
    user_dashboard,
    user_feedback,
    user_last_fetch,
    user_marks,
    user_marks_personal,
    user_password,
    user_personal,
    user_scope_data,
    user_sync_state,
    users_group_keys,
    weekly_slot_counts,
    write_user_sync,
)
from .logging_setup import log_with_kv, setup_logging
from .migrations import migrate_db
from .portal.parsers.attendance import parse_attendance
from .portal.parsers.common import (
    MONTHS,
    ROMAN,  # noqa: F401 — re-exported from app.app
    _cells,
    _class_key,
    _group_key,
    _program_short,  # noqa: F401 — re-exported from app.app
    _semester_int,
)
from .portal.parsers.exams import (
    parse_exam_schedule,  # noqa: F401 — re-exported from app.app
    parse_exam_timetable,  # noqa: F401 — re-exported from app.app
)
from .portal.parsers.feedback import _fb_plan
from .portal.parsers.marks import (
    _DATE_CELL_RE,  # noqa: F401 — re-exported from app.app
    _parse_component_inner,
    parse_marks,
)
from .portal.parsers.personal import parse_personal_details
from .portal.parsers.timetable import (
    DAY_ORDER,
    _tt_norm_clock,  # noqa: F401 — re-exported from app.app
    parse_timetable,  # noqa: F401 — re-exported from app.app
)
from .scope.ops import enabled_features
from .security import require_login
from .state import (  # noqa: F401 — re-exported: tests/recipes import these from app.app
    _RATE_CAP,
    _charge_rate,
    _check_ip_rate,
    _check_rate,
    _ip_attempts,
    _ip_retry_text,
    _login_attempts,
    _login_progress,
    _netid_retry_text,
    _portal_cooldown_remaining,
    _portal_fail,
    _portal_ok,
    _preflight_ip,
    _preflight_last,
    _progress_ip,
    _rate_lock,
    _retry_text,
    _set_progress,
    portal_health,
    progress,
    rate_limiter,
)
from .views.attendance import (
    ATTENDANCE_TARGET,
    ATTENDANCE_WARN,  # noqa: F401 — re-exported from app.app
    WORKING_DAYS,  # noqa: F401 — re-exported from app.app
    _absences_view,
    _attendance_budgets,
    _exam_stop,  # noqa: F401 — re-exported from app.app
    _safe_int,
    _status_for_pct,
    _title_case,
    _weekdays,  # noqa: F401 — re-exported from app.app
    hourwise_view,
)
from .views.campus import campus_view
from .views.fees import _fees_view
from .views.layout import (
    LAYOUT,
    WIDGETS,
)
from .views.marks import (
    _derive_ie,  # noqa: F401 — re-exported from app.app
    _fmt_date,  # noqa: F401 — re-exported from app.app
    _fmt_max,  # noqa: F401 — re-exported from app.app
    _fmt_score,  # noqa: F401 — re-exported from app.app
    _marks_summary,
    _marks_view,
)
from .views.ticker import (
    _now_next_from_slots,
    _today_brief,
    _today_ticker,
    _week_updates,
)

LOGIN_URL = "https://sp.srmist.edu.in/srmiststudentportal/students/loginManager/youLogin.jsp"

# Single source of truth for the visible app version (task 16).
# Bump policy: patch = fix, minor = feature, major = breaking/user-visible redesign.
with open(os.path.join(os.path.dirname(__file__), "..", "VERSION")) as _vf:
    APP_VERSION = _vf.read().strip()

# ── Configuration ───────────────────────────────────────────────────
# The env is read ONCE into a typed AppConfig (app/config.py); create_app
# (bottom of file) consumes it and owns every boot side effect (data dir,
# secret key, migrations, OCR prewarm). The module mirrors below keep the
# old import-time contract for everything that runs OUTSIDE an app
# context: db.py's lazy `from .app import DB_PATH` fallback (scripts,
# background threads) and the DATA_DIR readers (fernet key rotation).
_default_config = AppConfig.from_env()
DATA_DIR = _default_config.data_dir
DB_PATH = _default_config.db_path


def _load_secret(secret_path):
    """One app's session-signing secret: created on first boot, read-only
    after (moved out of import time into create_app)."""
    if not os.path.exists(secret_path):
        with open(secret_path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(secret_path, 0o600)
    return open(secret_path).read().strip()


def _active_data_dir():
    """The data dir that owns the CURRENT work: the serving app's config
    when a Flask app context is active (per-app fernet keys, the legacy
    timetable import during create_app), else the module default."""
    if has_app_context():
        d = current_app.config.get("DATA_DIR")
        if d:
            return d
    return DATA_DIR

from blobatar.flask import init_app as _init_blobatar

setup_logging()
log = logging.getLogger("opensrm")
log_http = logging.getLogger("opensrm.http")
log_auth = logging.getLogger("opensrm.auth")
log_portal = logging.getLogger("opensrm.portal")
log_db = logging.getLogger("opensrm.db")
log_metrics = logging.getLogger("opensrm.metrics")

SESSION_MAX_AGE = 60 * 60 * 24 * 30          # 30 days

# ── Crypto: passwords at rest ──────────────────────────────────────
_fernet = None

def fernet_keys():
    """Key bytes get_fernet() is built from, shared with
    scripts/rotate_fernet_key.py so the tool and the app can never
    disagree about which keys are live.

    Returns (keys, from_env): FERNET_KEYS env (comma-separated, FIRST key
    is the primary/encrypting key) wins when set — rotation keeps keys off
    the data volume; otherwise the single persisted DATA_DIR/fernet.key
    (generated on first use), exactly as before."""
    from cryptography.fernet import Fernet
    parts = [k.strip().encode() for k in os.environ.get("FERNET_KEYS", "").split(",") if k.strip()]
    if parts:
        return parts, True
    key_path = os.path.join(_active_data_dir(), "fernet.key")
    if os.path.exists(key_path):
        return [open(key_path, "rb").read()], False
    key = Fernet.generate_key()
    with open(key_path, "wb") as f:
        f.write(key)
    os.chmod(key_path, 0o600)
    return [key], False

def get_fernet():
    """Lazy-init the data-at-rest cipher so restarts don't lose data.

    FERNET_KEYS set -> MultiFernet: the FIRST key encrypts, every key
    decrypts (old ciphertext stays readable during/after rotation).
    Otherwise -> single Fernet from DATA_DIR/fernet.key, default unchanged."""
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet, MultiFernet
        keys, from_env = fernet_keys()
        if from_env:
            try:
                _fernet = MultiFernet([Fernet(k) for k in keys])
            except ValueError as e:
                # config error, not corrupt data: name the env var, never echo a key
                raise RuntimeError("FERNET_KEYS contains an invalid key (%s)" % e) from None
        else:
            _fernet = Fernet(keys[0])
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
             os.path.join(_active_data_dir(), "timetable.json")]
    json_path = next((p for p in paths if os.path.exists(p)), None)
    if not json_path: return
    # audit B11: open+parse INSIDE the try — a corrupt legacy timetable.json
    # used to escape init_db() at import time and crash-loop the container
    try:
        with transaction() as c:
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
                    c.execute("INSERT OR IGNORE INTO timetable_slots(group_id,day,period,subject_code,subject_name,location,source) "
                              "VALUES(?,?,?,?,?,?,'manual')", (gid, day, per, s.get("code",""), s.get("name",""), s.get("location","")))
            # legacy rows are manual: drop any official stamp (rows+times must agree)
            c.execute("UPDATE timetable_groups SET official_times='', tt_fetched_at=0 WHERE id=?", (gid,))
        os.rename(json_path, json_path + ".bak")   # only consume on success
    except Exception:
        log.exception("legacy timetable import failed")

# sqlite: connection policy (SQLITE_TIMEOUT_SECS=10, busy_timeout,
# SQLITE_JOURNAL_MODE), the request-scoped connection, transactions and the
# repository layer all live in app/db.py — connect() is the raw factory.
# connect() resolves the DB per app (app.config["DB_PATH"] inside an app
# context) and falls back to module DB_PATH above (tests/scripts repoint it).
# db + SQLITE_TIMEOUT_SECS are re-exported for scripts and tests.

def init_db():
    c = connect()
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
    # v1.20.3 (migration 17): rows store sha256(token) — the browser keeps
    # the raw token, the DB never does, so a leaked srm.db cannot be replayed
    # as a live session. Every read/prune/delete path hashes to match.
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = get_cookie(digest)
    if row and time.time() - row["created"] > SESSION_MAX_AGE:
        # audit 2026-09-27: enforce expiry at READ time. Previously pruning
        # happened only inside make_session_token() (i.e. when that same user
        # logged in again), so a leaked srm_session cookie stayed valid
        # server-side indefinitely — the 30-day client cookie was the only cap.
        delete_cookie(digest)
        row = None
    return row["netid"] if row else None

def make_session_token(netid):
    token = secrets.token_hex(32)
    now = int(time.time())
    # incident 2026-10-10: this previously ran `DELETE FROM cookies WHERE
    # netid=?` — one session per account, globally. Every login on any device
    # silently evicted every other device's session: over Sep 22 - Oct 10 the
    # main account logged in 58 times from 13 IPs, and 41 of those 58 re-logins
    # were its OWN earlier login killing the current session (33 from a
    # different IP = cross-device). Sessions are now concurrent per account,
    # each still bounded by SESSION_MAX_AGE at read time.
    # v1.20.3: store sha256(token); the caller/browser keeps the raw token
    # (contract: make_session_token still returns it), so the value at rest
    # is useless to anyone holding the DB but not the cookie.
    create_session(hashlib.sha256(token.encode()).hexdigest(), netid, now,
                   now - SESSION_MAX_AGE)
    return token

# The shared `require_login` decorator lives in app/security.py (it guards
# views across route groups, so it belongs to neither app.py nor one
# blueprint).

# audit: Only trust CF headers when request came through Cloudflare (cf-ray present)
# audit run-1 (#18): bare cf-ray presence is client-assertable — anyone
# reaching the origin directly could choose their rate-limit identity and
# forge the cookie Secure / HSTS decisions. Trust is now an edge-injected
# shared secret the client can never see (cloudflared
# originRequest.httpHeaders, or a Worker): X-Edge-Secret must match
# CF_EDGE_SECRET. Unset -> False: peer-only identity (request.remote_addr),
# which is the fail-closed position the audit prescribed. OPS DEP step: set
# CF_EDGE_SECRET in the lab .env AND inject the same value at the tunnel
# together, or per-IP limits collapse onto the tunnel's peer address.
CF_EDGE_SECRET = os.environ.get("CF_EDGE_SECRET", "").strip()


def _behind_cf():
    return bool(CF_EDGE_SECRET) and request.headers.get("X-Edge-Secret") == CF_EDGE_SECRET

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


NETID_RE = re.compile(r"^[a-z0-9]{2,20}$")  # audit: SRM NetIDs are lowercase alnum

# ── Concurrency guard ──────────────────────────────────────────────
# audit F1 fix: threading.Lock, not asyncio.Semaphore — gunicorn gthread
# runs views in a thread pool, so the guard must be thread-safe, and it
# must be shared process-wide. Pair with gunicorn -w 1 (Dockerfile CMD)
# so counters below are also process-wide.
# A10: the binary lock became a permit pool with a bounded wait queue in
# front — callers QUEUE (login ahead of refresh, position published to the
# progress tracker) and wait up to SYNC_QUEUE_WAIT_S instead of being
# refused the instant a sync is running. SYNC_MAX_CONCURRENCY sizes the
# pool (read at import, default 1 = today's one-at-a-time); >1 lets the
# pure-HTTP pipelines overlap but is untested end-to-end — see the PR's
# what-to-watch list before raising it. The Playwright fallback ignores
# the pool size and serializes on _pw_lock (one shared browser context).
def _sync_max_concurrency():
    """SYNC_MAX_CONCURRENCY — read at import (the permit pool is sized once):
    an integer >= 1, else the default 1."""
    try:
        return max(1, int(str(os.environ.get("SYNC_MAX_CONCURRENCY") or "").strip()))
    except (TypeError, ValueError):
        return 1

SYNC_MAX_CONCURRENCY = _sync_max_concurrency()
SYNC_QUEUE_WAIT_DEFAULT = 45   # seconds a queued sync waits before today's busy 503

_scrape_lock = threading.BoundedSemaphore(max(1, SYNC_MAX_CONCURRENCY))
_pw_lock = threading.Lock()          # Playwright fallback: one browser, whatever the pool size
_queue_cond = threading.Condition()  # guards _sync_queue + handoff wakeups
_sync_queue = []                     # parked waiters, ordered: login before refresh, FIFO inside
# ponytail: SYNC_QUEUE_WAIT_S read per-request (same as SYNC_MIN_INTERVAL_S)
# so ops/tests can flip it without a boot; SYNC_MAX_CONCURRENCY is boot-time
# because the semaphore pool is sized once.
# audit run-1 (#8): total wall-clock budget for one held scrape lock — HTTP
# phases + Playwright fallback share it (see fetch_attendance)
PIPELINE_DEADLINE = 150

# ── Session cache: skip login when cookies are still valid ──────────
_SESSION_CACHE_TTL = 4 * 3600  # 4 hours

def _save_session(netid, cookies_json):
    """Persist portal cookies for session reuse — encrypted at rest with the
    same Fernet control as users.password (audit run-1 #5: live portal
    cookies sat in plaintext next to the encrypted passwords, so a stolen
    srm.db + fernet.key pair still handed over authenticated portal
    sessions)."""
    save_portal_session(netid, encrypt_pw(cookies_json), int(time.time()))

def _load_session(netid):
    """Load cached portal cookies if still valid (< TTL).

    audit run-1: decrypts rows written by _save_session; rows written before
    the encryption change (plaintext JSON) are returned as-is and become
    encrypted on their next save, so existing sessions keep working."""
    row = get_portal_session(netid)
    if not row: return None
    if time.time() - row["created"] > _SESSION_CACHE_TTL:
        _clear_session(netid)  # expired rows are useless — stop storing dead cookie blobs
        return None
    blob = row["cookies_json"]
    if not blob.startswith("gAAAA"):
        return blob  # legacy plaintext row (pre-encryption); replaced on next save
    try:
        return get_fernet().decrypt(blob.encode()).decode()
    except Exception as e:
        log.warning("stored portal session unreadable — forcing fresh login netid=%s: %r", netid, e)
        _clear_session(netid)
        return None

def _clear_session(netid):
    """Remove cached portal cookies (on failed session restore)."""
    delete_portal_session(netid)

# ── Login progress · rate limits · portal cooldown ───────────────────────────────
# A18: all of it lives in app/state.py — RateLimiter / ProgressTracker /
# PortalHealth, each behind ONE lock with TTL pruning. The old module-level
# names (_set_progress, _login_attempts, _rate_lock, ...) are re-exported
# from the import block at the top, so callers, tests and recipes are
# unchanged. audit run-1 (#13) still holds: progress is keyed by the
# unforgeable per-browser attempt token — /api/login/progress only answers
# the browser that started the flow; flows without a token publish NOTHING.

# ── Sync queue: bounded wait for a portal slot (A10) ────────────────
def _sync_queue_wait_s():
    """SYNC_QUEUE_WAIT_S in seconds, read per-request (like
    SYNC_MIN_INTERVAL_S): how long a queued sync waits for a free portal
    slot before returning the busy 503. 0 = refuse instantly (old
    behaviour); a non-integer falls back to the default."""
    raw = os.environ.get("SYNC_QUEUE_WAIT_S")
    if raw is None:
        return SYNC_QUEUE_WAIT_DEFAULT
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return SYNC_QUEUE_WAIT_DEFAULT


class _QueueWaiter:
    """One parked sync. Identity equality so list.index() finds ME, not a
    same-priority neighbour with an identical prio."""
    __slots__ = ("prio",)

    def __init__(self, prio):
        self.prio = prio


def _sync_queue_depth():
    """How many syncs are parked waiting for a slot — the preflight
    refusal signal (a single running sync no longer refuses preflight;
    the runner thread's non-blocking try covers that case)."""
    with _queue_cond:
        return len(_sync_queue)


def _scrape_admit(prio, attempt, netid, wait_s):
    """Take one portal-pipeline slot, waiting up to wait_s in the queue
    instead of refusing the instant a sync is running (A10: bounded wait).
    Order: login (prio 0) ahead of refresh (prio 1), FIFO inside a
    priority — a wall of refreshes can never starve a login. Each parked
    waiter publishes its position through the login progress map
    ('Waiting for N ahead…'); flows without an attempt token publish
    nothing (same contract as _set_progress's other callers). True =
    admitted — the caller must _scrape_release(); False = the wait timed
    out, nothing held, caller answers busy 503.
    ponytail: SYNC_MAX_CONCURRENCY > 1 admits overlap but is untested
    end-to-end; the Playwright fallback serializes on _pw_lock anyway."""
    deadline = time.monotonic() + wait_s
    me = _QueueWaiter(prio)
    with _queue_cond:
        idx = 0
        while idx < len(_sync_queue) and _sync_queue[idx].prio <= prio:
            idx += 1
        _sync_queue.insert(idx, me)  # higher prio jumps ahead; equal prio stays FIFO
        try:
            while True:
                # only the head of the queue may claim a slot — that is what
                # keeps admission in queue order when a slot frees up
                if _sync_queue[0] is me and _scrape_lock.acquire(blocking=False):
                    _sync_queue.remove(me)
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _sync_queue.remove(me)
                    return False
                if attempt:
                    # ahead = waiters in front + the slot-holder blocking the
                    # head (a queued waiter never exists without a holder)
                    pos = _sync_queue.index(me)
                    _set_progress(attempt, f"Waiting for {pos + 1} ahead…", 1, netid=netid)
                # 1s wake cap: a release that bypasses _scrape_release (a test
                # poking the semaphore directly) is still picked up promptly
                _queue_cond.wait(min(remaining, 1.0))
        finally:
            _queue_cond.notify_all()  # my insert/remove renumbered everyone


def _scrape_release():
    """Hand a slot back and wake the queue. EVERY _scrape_lock release must
    come through here — a bare release() leaves waiters parked until their
    next wake cap."""
    with _queue_cond:
        _scrape_lock.release()
        _queue_cond.notify_all()

# ── Portal budget (aggregate egress cap) ───────────────────────────────
# A18: the per-netid / per-IP attempt windows and the preflight admission
# moved to app/state.py (RateLimiter). The _rate_lock imported at the top
# IS the RateLimiter's lock — this budget code keeps holding the same lock
# object, so cross-structure admission order is unchanged. The two limits:
#   per-netid scrape limit — portal-friendliness (each scrape = real SRM login)
#   per-IP login limit    — brute-force protection (netid rotation-proof)
# audit 2026-09-27: AGGREGATE cap on outbound portal-bound work. Per-netid and
# per-IP limits don't bind an attacker rotating source IPs: N IPs => N*10
# attempts/hour through OUR single egress IP — which is exactly how the portal
# rate-limits/bans the server and takes every user down with it. Counts jobs
# that actually reach the pipeline (sync + preflight), not rejected requests.
# audit run-1 (HIGH): the window is split so rotation cannot lock everyone out —
# unauthenticated work (login/preflight) is capped at CAP-FLOOR tokens and one
# source IP holds at most _PORTAL_IP_CAP of them; the floor stays reserved for
# authenticated owner refreshes, which can never be pre-spent by outsiders.
# A10: the aggregate splits into three named buckets — full login,
# session-reuse refresh, preflight — so one kind of work can be counted (and
# capped) on its own. The TOTALS are unchanged: aggregate 30, unauth
# (login + preflight) 20, refresh floor 10, one IP at most 6; the preflight
# bucket's own 10/10min share is the one new number (it was only ever bound
# by the shared 20 before, and its route already caps 10/IP).
_portal_attempts = []        # full-login syncs (unauth), 10-min window
_portal_attempts_auth = []   # session-reuse refreshes (owner), 10-min window
_portal_attempts_pf = []     # login preflights (unauth warm-logins), 10-min window
_portal_ip = {}              # ip -> [unauth timestamps, ...] (same window)
_PORTAL_CAP = 30             # across all clients, all netids, all buckets
_PORTAL_IP_CAP = 6           # one source IP holds at most 6 of the unauth tokens
_PORTAL_AUTH_FLOOR = 10      # tokens unreachable for unauth work (refresh reserve)
_PORTAL_PREFLIGHT_CAP = 10   # preflight's own share of the unauth pool


def _check_portal_budget(ip=None, authorized=False, bucket="login"):
    now = time.time()
    with _rate_lock:
        _portal_attempts[:] = [t for t in _portal_attempts if now - t < 600]
        _portal_attempts_auth[:] = [t for t in _portal_attempts_auth if now - t < 600]
        _portal_attempts_pf[:] = [t for t in _portal_attempts_pf if now - t < 600]
        if authorized:
            if len(_portal_attempts) + len(_portal_attempts_auth) + len(_portal_attempts_pf) >= _PORTAL_CAP:
                return False
            _portal_attempts_auth.append(now)
            return True
        # unauth: never spend the reserved floor (audit run-1 #1); preflight
        # additionally stops at its own share so warm-logins can't drain the
        # full-logins pool
        if bucket == "preflight" and len(_portal_attempts_pf) >= _PORTAL_PREFLIGHT_CAP:
            return False
        if len(_portal_attempts) + len(_portal_attempts_pf) >= _PORTAL_CAP - _PORTAL_AUTH_FLOOR:
            return False
        if ip is not None:
            hold = [t for t in _portal_ip.get(ip, []) if now - t < 600]
            if len(hold) >= _PORTAL_IP_CAP:
                return False   # rejected WITHOUT spending a shared token
            _portal_ip[ip] = hold + [now]
        if bucket == "preflight":
            _portal_attempts_pf.append(now)
        else:
            _portal_attempts.append(now)
        return True


# -- Portal cooldown ------------------------------------------------
# When the SRM portal silently rejects logins (rate-limiting our IP),
# pause ALL login attempts to avoid worsening the block. A18: the state
# itself (cooldown timestamp + consecutive-fail counter, lock-guarded) is
# app.state.PortalHealth; the per-sync guard below stays here because it
# rides a ContextVar owned by the sync flow.


class _SyncContext:
    """Per-sync mutable state. The 'counted one portal fail already' flag
    used to be a module global (_request_fail_counted): two overlapping
    syncs shared it, so one sync's counted fail latched the other's flag
    and its cooldown could never arm (or the reset raced mid-flight).
    The object rides a ContextVar — the calling thread's context for the
    pure-HTTP path, carried into the Playwright coroutine scheduled from
    it — so every stage of ONE sync shares the flag and no other sync
    sees it."""
    __slots__ = ("fail_counted",)

    def __init__(self):
        self.fail_counted = False   # one portal-fail per request, not per retry


_sync_ctx: contextvars.ContextVar = contextvars.ContextVar("opensrm_sync_ctx", default=None)


def _portal_fail_once():
    """Count ONE fail per login request, not one per captcha retry inside it.
    Guarded by the caller's _SyncContext; a call with no sync context (any
    caller outside fetch_attendance) never arms the cooldown."""
    ctx = _sync_ctx.get()
    if ctx is None or ctx.fail_counted:
        return
    ctx.fail_counted = True
    _portal_fail()

def _client_ip():
    # Only trust CF-Connecting-IP when request came through Cloudflare.
    # Direct access spoofing the header would bypass rate limiting otherwise.
    # audit run-1: background/test callers (no active request) must not crash —
    # no request means no asserted identity.
    if not has_request_context():
        return "?"
    if _behind_cf():
        return request.headers.get("CF-Connecting-IP") or request.remote_addr or "?"
    return request.remote_addr or "?"


# ── Persistent browser + event-loop singletons (speed warm-up, Sep 2026) ──
# Launch Chromium ONCE and reuse it across requests via a dedicated worker
# event loop. Each scrape gets a FRESH context (isolated cookies); we close
# only the context, never the shared browser. This removes ~2.5-3s of
# per-request browser launch and ~3s ddddocr cold start.
# Requires gunicorn -w 1 (singletons are process-local). Thread-safe: all
# browser access serializes through _pw_lock in fetch_attendance's
# Playwright fallback (A10 — whatever SYNC_MAX_CONCURRENCY is set to).
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

def _pw_login_done(ok, err, attempts):
    """Record captcha attempts-per-login for the Playwright pipeline, return
    the (ok, err) passthrough. attempts=0 when rejected before any submit."""
    metrics.observe("opensrm_captcha_attempts_per_login", attempts, pipeline="playwright")
    return ok, err


async def _do_login(page, ctx, netid, password):
    """Perform login with captcha retry. Returns (ok, fail) — fail is a
    sync_error() result (typed kind + byte-identical message) or None."""
    _sc = _sync_ctx.get()
    if _sc is not None:
        _sc.fail_counted = False  # one portal-fail per request, not per retry
    # Check global portal cooldown before attempting
    cooldown = _portal_cooldown_remaining()
    if cooldown > 0:
        return _pw_login_done(False, sync_error("portal_cooldown",
                                 f"SRM portal temporarily rate-limiting our server. "
                                 f"Try again in {int(cooldown / 60) + 1} minutes.",
                                 retry_after=int(cooldown)), 0)

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
            return _pw_login_done(False, sync_error("portal_down", "captcha image failed to load — portal may be slow"), _ca + 1)
        captcha = solve_captcha_b64(b64)
        if not captcha:
            log.warning("playwright login netid=%s abort=ocr_empty", netid)
            return _pw_login_done(False, sync_error("internal", "captcha OCR returned empty"), _ca + 1)
        await page.click('input[name="captcha"]')
        await page.type('input[name="captcha"]', captcha, delay=10)
        await page.mouse.move(300, 200, steps=3)
        await page.click('button:has-text("Login")')
        try:
            await page.wait_for_url(lambda url: "HRDSystem" in url, timeout=8000)
            _portal_ok()
            return _pw_login_done(True, None, _ca + 1)
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
                    return _pw_login_done(False, sync_error("bad_credentials", "invalid credentials — check your NetID/password"), _ca + 1)
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
            return _pw_login_done(False, sync_error("bad_credentials",
                                     f"login failed after {MAX_CAPTCHA_RETRIES} attempts — last: {last_err}"), _ca + 1)
    # All retries exhausted via silent-rejection continues
    return _pw_login_done(False, sync_error("bad_credentials",
                             f"login failed after {MAX_CAPTCHA_RETRIES} attempts — last: {last_err or 'silent rejection'}"), _ca + 1)

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
            ok, fail = await _do_login(page, ctx, netid, password)
            if not ok:
                return fail
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
            ok, fail = await _do_login(page, ctx, netid, password)
            if not ok:
                return fail
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
            metrics.inc("opensrm_parse_empty_total", page="attendance", pipeline="playwright")
            raw = await page.evaluate(
                '() => (document.getElementById("divMainDetails")||document.body).innerText || ""')
            if "ABC ID" in raw or "Aadhaar" in raw:
                return sync_error("markup_changed", "Portal requires ABC ID Generation first — "
                                                    "log in at sp.srmist.edu.in and complete the "
                                                    "Aadhaar/ABC ID form, then try again.")
            return sync_error("portal_down", "Attendance page did not load (portal returned no "
                                             "course table). The portal may be slow or your "
                                             "account may be restricted.")

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
        if cold and not personal:
            metrics.inc("opensrm_parse_empty_total", page="personal", pipeline="playwright")

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
        if cold and not courses:
            metrics.inc("opensrm_parse_empty_total", page="courses", pipeline="playwright")

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
        if not marks:
            metrics.inc("opensrm_parse_empty_total", page="marks", pipeline="playwright")

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

def _error_class(err):
    """Low-cardinality failure class for opensrm_sync_total's error label —
    enough to tell 'the portal changed' (parse) from 'our user typed wrong'
    (auth) from 'we are rate-limited' (rate) without unbounded cardinality."""
    e = (err or "").lower()
    if "captcha" in e:
        return "captcha"
    if "invalid credentials" in e or "login failed" in e:
        return "auth"
    if "too many" in e or "rate-limit" in e:
        return "rate"
    if "deadline" in e:
        return "deadline"
    if "in progress" in e:
        return "busy"
    if "did not load" in e or "no course table" in e or "abc id" in e:
        return "parse"
    if "server-side" in e:
        return "server"
    return "other"


def _sync_result(pipeline, res, t0):
    """Record one finished sync (outcome counter + duration timer) and pass
    the result through unchanged — every fetch_attendance return goes here."""
    if not isinstance(res, dict):
        # never seen today; keep the counters total instead of crashing a sync
        res = sync_error("internal", "pipeline returned a non-dict result")
    ok = bool(res.get("ok"))
    metrics.inc("opensrm_sync_total", pipeline=pipeline,
                result="ok" if ok else "error",
                # typed results carry kind (the KIND_STATUS vocabulary — that IS
                # the error class); the message-wording fallback covers bare
                # dicts/stubs that predate the typed results
                error="" if ok else (res.get("kind") or _error_class(res.get("error"))))
    metrics.observe("opensrm_sync_duration_seconds", time.monotonic() - t0,
                    pipeline=pipeline)
    return res


def _pw_fallback_enabled():
    """The Playwright fallback pipeline is archived off by default (Oct 2026:
    prod's HTTP pipeline had never fallen back once). Ops opts in with
    PLAYWRIGHT_FALLBACK=enabled — read per request, like the other knobs
    (TIMETABLE_EDITOR, SCOPE_FEATURES)."""
    return os.environ.get("PLAYWRIGHT_FALLBACK", "").strip().lower() in ("enabled", "1", "true")


def fetch_attendance(netid, password, authorized=False, attempt=None):
    t_sync = time.monotonic()   # observability: sync outcome + duration anchor
    loop = future = None  # except block references both; may not be reached
    pw_held = False       # Playwright fallback lock; released in finally below
    # audit 2026-09-30: admission comes FIRST. _check_rate() used to run above
    # it, so a busy/cooldown/budget rejection still consumed one of the
    # account's 3 syncs per 10 minutes while reaching the portal zero times —
    # three "Sync in progress" clicks locked an account that never synced out
    # for 10 minutes (prod 2026-09-30 16:45–16:53). Only count a sync once we
    # know it can actually run.
    # audit F1 fix: acquire in the worker thread; no try/except race.
    # A10: the acquire is now a BOUNDED QUEUE WAIT — a click waits up to
    # SYNC_QUEUE_WAIT_S for the running sync to finish instead of being
    # refused instantly; a waiter that outstays the wait gets today's busy
    # 503 (still free: it returns before _check_rate/_check_portal_budget).
    # Queue priority: login (authorized=False, /api/login) ahead of refresh
    # (authorized=True, /api/refresh) — FIFO inside each.
    if not _scrape_admit(1 if authorized else 0, attempt, netid, _sync_queue_wait_s()):
        metrics.inc("opensrm_scrape_lock_rejections_total", op="sync")
        return sync_error("busy", "Sync in progress. Try again in about a minute.", retry_after=60)
    try:
        # audit 2026-09-27: reset HERE (one pipeline at a time, under its own
        # sync context). Previously the flag was only reset inside Playwright's
        # _do_login, so in the normal pure-HTTP path the first counted fail
        # latched it True forever and _portal_fail_once() became a no-op — the
        # portal cooldown could never arm and we'd keep hammering a
        # rate-limiting portal. A10: the flag lives on this per-sync
        # _SyncContext (module global was a race once two syncs can overlap).
        _sync_ctx.set(_SyncContext())
        # audit run-1 (HIGH #1/#6): FREE gates first, budget charged LAST — a
        # cooldown or quota rejection must never spend a shared portal token,
        # and unauth wrong-password guesses must never spend the victim's
        # per-netid sync quota (charged only in _charge_rate on success below).
        cooldown = _portal_cooldown_remaining()
        if cooldown > 0:
            return sync_error("portal_cooldown",
                              f"SRM portal temporarily rate-limiting our server. "
                              f"Try again in {int(cooldown / 60) + 1} minutes.",
                              retry_after=int(cooldown))
        if not _check_rate(netid):
            return sync_error("rate_limited",
                              f"Too many sync attempts for this account. Try again in {_netid_retry_text(netid)}.")
        if not _check_portal_budget(_client_ip(), authorized=authorized):
            return sync_error("rate_limited", "Too many portal requests from the server "
                                              "(rate-limit protection). Try again in 10 minutes.",
                              retry_after=600)
        # audit run-1 (#8): ONE wall-clock budget for the whole critical
        # section — HTTP phases check it between phases, the Playwright
        # fallback gets only what's left (150s total matches its documented
        # 5-retry worst case; the HTTP side is additionally bounded
        # per-response by http_scraper._MAX_READ_SECS).
        deadline = time.monotonic() + PIPELINE_DEADLINE
        # ── New pipeline: pure-HTTP first ─────────────────────────────
        def _progress_pub(_who, step, pct):
            # audit run-1 (#13): publish only under this flow's attempt token;
            # no token -> nothing lands in the unauthenticated progress map
            if attempt:
                _set_progress(attempt, step, pct, netid=netid)
        helpers = {"portal_fail_once": _portal_fail_once, "portal_ok": _portal_ok,
                   "save_session": _save_session, "load_session": _load_session,
                   "clear_session": _clear_session, "set_progress": _progress_pub}
        # Hot/cold split: cold data (personal/courses) re-fetched only when
        # stale >24h; hot (attendance/marks) always.
        row = user_cold_fetch(netid)
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
                if attempt:
                    _set_progress(attempt, "Connecting to SRM portal…", 5, netid=netid)
                res = http_scraper.fetch(netid, password, helpers, cold=cold,
                                         prepared=prepared, deadline=deadline)
                if res.get("ok"):
                    # audit run-1 (#6): the per-netid sync quota is spent only
                    # when the sync actually succeeded — a failed unauth guess
                    # can no longer pre-spend a chosen victim's quota
                    _charge_rate(netid)
                if res.get("ok") and cold:
                    try:
                        set_cold_fetch(netid, int(time.time()))
                    except Exception as e:
                        log.debug("cold_fetch update failed err=%r", e)
                return _sync_result("http", res, t_sync)
            except http_scraper.HttpScraperError as e:
                _portal_fail_once()
                if not _pw_fallback_enabled():
                    log.warning("http pipeline failed (%r) — playwright fallback archived "
                                "(PLAYWRIGHT_FALLBACK unset)", e)
                    return _sync_result("http", sync_error("portal_down",
                                        "SRM portal is not responding — try again in a few minutes."),
                                        t_sync)
                log.warning("http pipeline failed (%r) — falling back to playwright", e)
            except Exception as e:
                _portal_fail_once()
                if not _pw_fallback_enabled():
                    log.warning("http pipeline crashed (%r) — playwright fallback archived "
                                "(PLAYWRIGHT_FALLBACK unset)", e)
                    return _sync_result("http", sync_error("internal",
                                        "Scrape failed server-side — check the server log, then try again."),
                                        t_sync)
                log.warning("http pipeline crashed (%r) — falling back to playwright", e)
        # ── Fallback: Playwright (archived — opt in with PLAYWRIGHT_FALLBACK=enabled) ──
        # With the knob unset the only way to reach this block is http_scraper
        # failing to import — every pipeline failure returned in its except
        # branch above.
        if not _pw_fallback_enabled():
            return _sync_result("http", sync_error("internal",
                                "Scrape failed server-side — check the server log, then try again."),
                                t_sync)
        # An image built WITH_PLAYWRIGHT=0 has no playwright package: say so
        # loudly instead of failing deep inside the submitted coroutine.
        try:
            import playwright.async_api  # noqa: F401
        except ImportError:
            log.error("PLAYWRIGHT_FALLBACK=enabled but the playwright package is not installed in this "
                      "image — rebuild with --build-arg WITH_PLAYWRIGHT=1")
            return _sync_result("playwright", sync_error("internal",
                                "Scrape failed server-side — check the server log, then try again."),
                                t_sync)
        # A10: the browser pipeline stays serialized whatever
        # SYNC_MAX_CONCURRENCY says — one shared persistent context cannot
        # drive two logins. Held through the zombie cleanup in the except
        # block (released in finally), so a fallback never overlaps another.
        if not _pw_lock.acquire(timeout=max(1, int(deadline - time.monotonic()))):
            metrics.inc("opensrm_scrape_lock_rejections_total", op="sync")
            return _sync_result("playwright",
                                sync_error("busy", "Sync in progress. Try again in about a minute.",
                                           retry_after=60),
                                t_sync)
        pw_held = True
        loop = _ensure_loop()
        future = asyncio.run_coroutine_threadsafe(_fetch_rich_optimized(netid, password, cold=cold), loop)
        # 5 captcha retries w/ backoffs ≈ 90s worst case; 60s caused guaranteed
        # TimeoutError + zombie retries — bounded by the remaining pipeline
        # budget instead of a fresh 150s (audit run-1 #8: one deadline total)
        pw_res = future.result(timeout=max(1, min(150, deadline - time.monotonic())))
        if isinstance(pw_res, dict) and pw_res.get("ok"):
            _charge_rate(netid)  # audit run-1: same success-only quota charge as the HTTP path
        return _sync_result("playwright", pw_res, t_sync)
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
        return _sync_result("playwright",
                            sync_error("internal", "Scrape failed server-side — check the server log, then try again."),
                            t_sync)
    finally:
        if pw_held:
            _pw_lock.release()
        _scrape_release()   # return the slot + wake the queue (A10)

# ── View model ─────────────────────────────────────────────────────

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


def _weekly_slots(group_key):
    """w = weekly slot count per subject_code, scoped to THIS user's group [F4].
    Precedent: _day_slots / timetable_html / /api/timetable all scope by group_id."""
    return weekly_slot_counts(group_key)


def _norm_subject(s):
    """Join key: upper / strip / squash whitespace (spec §4.3)."""
    return " ".join(str(s or "").upper().split())


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
def _bare(code, reason):
    """Deliberately bare response body (nothing for a prober to read — used
    by the internal endpoints' auth); the reason still lands on the status
    line via _log_request's g._log_reason fallback, so every >=400 line in
    opensrm.log carries an error= (the logging-gap rule)."""
    g._log_reason = reason
    return "", code

def _log_request_start():
    request._start_time = time.monotonic()

def _log_request(resp):
    duration_ms = int((time.monotonic() - getattr(request, "_start_time", time.monotonic())) * 1000)
    # audit 2026-10-07: 86% of the log file was the docker healthcheck's
    # urllib GET pair (66,003 of 76,857 lines) — synthetic traffic now logs
    # at DEBUG. Real 4xx responses log at WARNING with the error body, 5xx at
    # ERROR (NtfyHandler pages on ERROR/5xx, never on routine 4xx) — every
    # failure carries its cause on the request line itself.
    ua = request.headers.get("user-agent", "")
    # the compose healthcheck polls /healthz every 30s: same demotion as the
    # Python-urllib UA so probe traffic can never fill opensrm.log again.
    # A real fault still page: 5xx stays ERROR whatever the path or UA.
    probe = ua.startswith("Python-urllib") or request.path == "/healthz"
    if resp.status_code >= 400:
        kv = dict(method=request.method, path=request.path,
                  status=resp.status_code, duration_ms=duration_ms)
        body = resp.get_json(silent=True)
        err = (body or {}).get("error") if isinstance(body, dict) else None
        if not err:
            err = getattr(g, "_log_reason", None)   # bare bodies (_bare())
        if not err:
            # framework errors (404/405/413) carry no JSON body — the status
            # class IS the reason; every >=400 line must stay greppable
            err = f"http_{resp.status_code}"
        kv["error"] = str(err)[:120]
        # 5xx is a real fault: ALWAYS ERROR (NtfyHandler pages on ERROR/5xx),
        # even from a urllib monitor — healthcheck 4xx noise stays DEBUG.
        lvl = (logging.ERROR if resp.status_code >= 500
               else logging.WARNING if not probe
               else logging.DEBUG)
        log_with_kv(log_http, lvl, "request", **kv)
    else:
        lvl = logging.DEBUG if probe else logging.INFO
        log_with_kv(log_http, lvl, "request",
                    method=request.method, path=request.path,
                    status=resp.status_code, duration_ms=duration_ms)
    return resp

# ── Cross-site request guard ───────────────────────────────────────────────
# v1.20.3: state-changing methods arriving from another site are refused
# (403 + error= on the opensrm.http line) instead of trusting SameSite=Lax
# alone. Sec-Fetch-Site is a forbidden header — a cross-site page can neither
# strip nor forge it — so it leads; Origin covers older browsers. Neither
# header present = non-browser client (curl, cron, tests) -> allowed.
# /internal/push/tick authenticates with its own secret header -> exempt.
_CROSS_SITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
# session-authenticated POSTs served through the tunnel (see above);
# the push tick is secret-header auth, same exemption for the same reason.
_CROSS_SITE_EXEMPT = ("/internal/push/tick", "/marks/tag")

def _cross_site_guard():
    if request.method not in _CROSS_SITE_METHODS:
        return None
    # exempt: POSTs that authenticate with the session cookie and are served
    # through the Cloudflare tunnel — the tunnel rewrites the browser's
    # same-origin fetch metadata (Sec-Fetch-Site/Origin no longer match the
    # origin host once cloudflared fronts the POST), so a same-site user form
    # would false-403 behind the tunnel while passing locally.
    if request.path in _CROSS_SITE_EXEMPT:
        return None
    sfs = request.headers.get("Sec-Fetch-Site")
    if sfs is not None and sfs.lower() not in ("same-origin", "none"):
        return {"error": "cross-site request refused (Sec-Fetch-Site)"}, 403
    origin = request.headers.get("Origin")
    if origin is not None and urlparse(origin).netloc.lower() != request.host.lower():
        return {"error": "cross-site request refused (Origin)"}, 403
    return None


# ── Security headers ───────────────────────────────────────────────
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

def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; worker-src 'self'; manifest-src 'self'")
    resp.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    # audit: HSTS only when the request came through the VERIFIED CF edge
    # (audit run-1 #18: bare cf-ray is client-assertable) — plain-HTTP local
    # dev and direct-origin requests must never receive it
    if _behind_cf():
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

# usage_events retention: env-configurable (USAGE_EVENTS_RETENTION_DAYS,
# default 365), pruned at most once a day by the next event — no background
# thread, no per-tick work (the old every-push-tick 90d prune moved here).
_usage_prune_lock = threading.Lock()
_usage_prune_last = 0.0


def _usage_retention_days():
    try:
        return max(1, int(os.environ.get("USAGE_EVENTS_RETENTION_DAYS", "365")))
    except ValueError:
        return 365


def _prune_usage_events(now=None):
    """Delete usage_events older than the retention window; at most once per
    day per process (claimed under the lock BEFORE the delete). Returns rows
    deleted, or -1 when the slot was already used this day / the delete failed.
    ponytail: runs on the next _track, so a fully idle process simply prunes
    on its next event — rows only grow when events are written anyway."""
    global _usage_prune_last
    now = time.time() if now is None else now
    with _usage_prune_lock:
        if now - _usage_prune_last < 86400:
            return -1
        _usage_prune_last = now
    days = _usage_retention_days()
    try:
        n = prune_usage_events(int(now) - days * 86400)
    except Exception as e:
        log.info("usage_events prune failed error=%r", e)
        return -1
    # pruned count logged every time the slot runs, so retention is countable
    log.info("usage_events pruned rows=%d retention_days=%d", n, days)
    return n


def _track(event, target="", detail="", user=""):
    """One usage-event row: page views, syncs, feature usage. Closed
    vocabulary (usage_events), no PII — user is the netid already stored
    in the DB; never passwords, tokens, or portal payloads. ponytail:
    plain INSERT, no batching — a few rows/day at this scale."""
    try:
        insert_usage_event(time.strftime("%Y-%m-%d"), user, event, target, detail)
        _prune_usage_events()   # at most once a day (no-op otherwise)
    except Exception as e:
        # INFO, not debug: a permanently broken usage_events table (lock
        # errors, missed migration on a restored backup) used to fail forever
        # with zero trace at prod LOG_LEVEL=INFO — the silent-failure class
        # the reliability audit outlawed. Telemetry failing must stay visible;
        # telemetry working stays quiet.
        log.info("usage track failed event=%s error=%r", event, e)

# ── Routes ─────────────────────────────────────────────────
def _hourwise_data(netid, group_key):
    """SCOPE hour rows + the join inputs for this user, or None when ANY leg
    is missing — feature 'hourwise' in SCOPE_FEATURES, a group with slots,
    and a non-empty getHourwiseAttendance — so a missing leg leaves today's
    Absences card untouched (zero regression by construction). Nothing
    cached: scope_json may be hours old, it is history and still renders.
    """
    if "hourwise" not in enabled_features() or not group_key:
        return None
    gid = group_id(group_key)
    slots = day_slots(group_key)
    if gid is None or not slots:
        return None
    row = user_scope_data(netid)
    try:
        stored = json.loads(row["scope_json"] or "{}") if row else {}
    except (ValueError, TypeError):
        stored = {}
    hw = stored.get("getHourwiseAttendance") or {} if isinstance(stored, dict) else {}
    rows = hw.get("data") if isinstance(hw, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    # custom subjects keep the state but lose the name (join spec: never invent)
    custom = {r[0] for r in group_subjects(gid) if r[3] and r[0]}
    ts = hw.get("ts") if isinstance(hw, dict) else None
    ts = int(ts) if isinstance(ts, (int, float)) and ts else 0
    return rows, slots, custom, ts, \
        (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)) if ts else "never")


def _hourwise_section(netid, group_key, monthly):
    """The Detailed attendance section's context, or None to keep the Absences
    card. Month rows follow the portal's own monthly list (its `MMM / YYYY`
    label, its bar %), and a month only SCOPE knows about still renders."""
    hw = _hourwise_data(netid, group_key)
    if not hw:
        return None
    rows_hw, slots_hw, custom_hw, ts_hw, full_hw = hw
    grid = hourwise_view(rows_hw, slots_hw, custom_hw,
                         {m["label"]: m for m in monthly})
    if not grid["months"]:
        return None
    grid["ts"] = ts_hw
    grid["full"] = full_hw
    return grid


@require_login
def index():
    netid = get_current_user()
    if not netid:
        # race: require_login validated, then the row vanished before this
        # re-read (logout in another tab mid-request) — redirect, not 500.
        return redirect("/login")
    # one row read: marks/faculty live on the same users row (was three queries)
    row = user_dashboard(netid)
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

    # Fees tab: server-rendered from the cold SCOPE blob (marks-tab pattern;
    # no new DB columns). Feature 'fees' off or no fee/finance rows -> None
    # -> the template renders no navbar item and no panel (empty=hidden,
    # DESIGN §4.12 — same self-hide rule as empty cards).
    srow = user_scope_data(netid)
    fees = _fees_view(_jload(srow["scope_json"] if srow else None, {}),
                      enabled_features())

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
    # ARCHIVED while the portal's feedback window is closed (fb_open=0 — now
    # learned by EVERY sync's probe, not just the daily cold one, plus the
    # fill endpoint's portal-confirmed self-heal): empty plan -> the CTA and
    # the modal both vanish (empty=hidden, DESIGN §4.12) and come back
    # automatically on the next sync that finds the window open again. The
    # Teachers list itself is historical data and stays.
    fb_open = row["fb_open"] if row and row["fb_open"] is not None else 1
    fb_plan = _fb_plan(faculty_map) if fb_open else []

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
    # Detailed attendance (SCOPE hourwise × timetable): replaces the Absences
    # card when the feature, the group's timetable and the stored hour rows
    # are all present; otherwise the card above renders exactly as on main.
    hourwise = _hourwise_section(netid, group_key, monthly)
    if hourwise:
        monthly_abs = []
    else:
        monthly_abs = monthly
    dash = {
        # institute mail is NetID@srmist.edu.in (the portal login page states
        # it verbatim) — the personal Gmail from the profile is NOT shown here
        "email": f"{netid}@srmist.edu.in",
        "reg_no": personal_data.get("Register No.", ""),
        "today": _today_brief(group_key),
        "week": _week_updates(data.get("daily_absent", {})),
        "absent_today": any(
            r.get("date") == datetime.now().strftime("%d-%m-%Y")
            for rows in (data.get("daily_absent") or {}).values() for r in rows),
    }
    # week widget's second block: components the portal entered this Mon–Sun
    dash["week"]["marks"] = _week_marks(marks_raw)

    # card/widget engine: layout registry + derived widget data (route-side
    # joins — partials consume flat dicts only). Cards whose `when` context
    # vars are ALL empty are dropped here so no orphan shell renders.
    _wctx = {"marks_summary": marks_summary, "exams": exams,
             "budgets": _budget_rows(courses),
             "teach_groups": _teacher_groups(faculty_view)}
    layout = [c for c in LAYOUT
              if not c.get("when") or any(_wctx.get(n) for n in c["when"])]
    # Campus tab: shape-driven SCOPE cards off the same row (scope_json).
    # Each card builds ONLY when its feature slug is on and it has rows, so
    # every card self-hides — and with none left the tab is never registered
    # (alive-empty = no UI, never an error). Scope toggles are a request-time
    # knob, so the feature set is read per request like every other gate.
    campus = campus_view(_jload(row["scope_json"] if row else None, {}),
                         enabled_features())
    return render_template(
        "dashboard.html", netid=netid, courses=courses, monthly=monthly_abs,
        hourwise=hourwise,
        days_left_90=next((c["days_left_90"] for c in courses if c["days_left_90"] is not None), None),
        stop=next((c["stop"] for c in courses if c["stop"] is not None), None),
        days_left_exam=next((c["days_left_exam"] for c in courses if c["days_left_exam"] is not None), None),
        last=last, last_epoch=last_epoch, hours_old=hours_old, has_budgets=has_budgets,
        student_name=student_name, dash=dash, marks=marks_view, marks_summary=marks_summary,
        fees=fees,
        exams=exams, faculty=faculty_view, fb_plan=fb_plan,
        # card/widget engine: layout registry + derived widget data (route-side
        # joins — partials consume flat dicts only)
        layout=layout, widget_specs=WIDGETS, notices=NOTICES,
        ticker=_today_ticker(group_key), budgets=_wctx["budgets"],
        teach_groups=_wctx["teach_groups"],
        version=APP_VERSION,
        timetable=timetable_html(group_key, attendance),
        tt_fetched_at=_tt_fetched_at(group_key),
        tt_editor_enabled=_tt_editor_enabled(),
        personal=personal_data,
        campus=campus,
        tools=_tools_entries(netid))

# ── Timetable (SQLite-backed, per-group) ─────────────────────────
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

# The portal's published time row is WRONG (verified live 2026-10-12): its
# morning block runs -60 min and its afternoon block -40 min against real
# campus hours (08:30 shown, classes start 09:30; its lunch is mis-sized the
# same way). These per-period offsets are DERIVED so official+OFFSET == the
# SLOTS grid above exactly for p1-6 (tests/test_official_tt pins it). Legacy
# p7 (16:00-16:50) has no portal counterpart: a first official sync drops
# stored p7 rows (whole-group DELETE+replace is the design), and a future
# 7-period portal capture gets offset 0 via .get(p, 0) -> corrected overlap
# -> whole-group SLOTS fallback (safe, log.debug only).
# ponytail: re-derive the table + SLOTS edge if a 7-period capture exists.
# When the portal fixes its clock: set every value to 0 AND refresh the
# tests/fixtures/timetable_form10.html capture to the corrected portal output
# (test_official_tt pins raw fixture + offset == SLOTS). Nothing else in the
# code depends on these values.
TIMETABLE_TIME_OFFSETS = {1: 60, 2: 60, 3: 60, 4: 60, 5: 40, 6: 40}

# Where the rendered grid comes from: "official" = portal timetable when the
# group has one (legacy SLOTS as per-group fallback); "manual" = always the
# legacy SLOTS/manual rows — the ops escape hatch if a published official
# timetable is ever wrong beyond a clock offset.
TIMETABLE_SOURCE = "official"

# The timetable is fully portal-owned: the manual editor entry + save API are
# archived (no user input — see the Oct 2026 "portal publishes formId 10"
# decision). Escape hatch if the portal's copy ever breaks: TIMETABLE_EDITOR
# =enabled (read per-request so tests can flip it live; restart not needed).
def _tt_editor_enabled():
    return os.environ.get("TIMETABLE_EDITOR", "archived") == "enabled"


# Release notices, newest first (append at release time). The New badge rides
# the head entry only — release notes verbatim from the real CHANGELOG.
NOTICES = [
    {"ver": "v2.2.0", "date": "27 Oct", "title": "Fees, without the digging",
     "body": "A Fees tab shows what you still owe, and once nothing is due it opens "
             "straight into what you have paid, grouped by academic year with the "
             "date first and the amount on the right. The full receipt history sits "
             "in a collapsed ledger you can open when you actually need a voucher "
             "number."},
    {"ver": "v2.1.0", "date": "26 Oct", "title": "Attendance, hour by hour",
     "body": "The absences list turns into a real attendance view: open any month "
             "and each date drops down as a row of periods showing P, A or OD, "
             "joined to your timetable so hovering a cell tells you which subject "
             "that hour actually was."},
    {"ver": "v2.0.0", "date": "27 Oct", "title": "SRM's own app backend, and a Tools tab",
     "body": "OpenSRM now talks to the same backend the official SRM SCOPE student app uses, "
             "so fee records, exam results, library loans, hostelling and placement "
             "details can come from the source the college itself ships with. This "
             "release is the groundwork: the connection, the feature switches and this "
             "Tools tab. The cards for each of those arrive over the next updates — "
             "phones also get a tidier bar, with refresh on the left of the logo and "
             "settings on the right, and Settings' place in the bottom bar goes to Tools."},
    {"ver": "v1.32.0", "date": "26 Oct", "title": "A cleaner edge",
     "body": "The empty strip along the right side is gone, and the scrollbar "
             "is now a thin bar that only appears while you are using it — it "
             "floats over the page instead of pushing it around. The top bar "
             "runs edge to edge and stays put while you scroll."},
    {"ver": "v1.31.1", "date": "26 Oct", "title": "The page stays put",
     "body": "A refresh used to nudge the cards in from the left edge and "
             "down from the menu after every sync. They now stay exactly "
             "where they were."},
    {"ver": "v1.31.0", "date": "24 Oct", "title": "Leaner under the hood",
     "body": "The server got a much smaller update package, so future "
             "updates download faster. Nothing you can see changes — same "
             "app, lighter behind the scenes."},
    {"ver": "v1.30.0", "date": "20 Oct", "title": "Swipe to refresh",
     "body": "Pull down from the top on your phone to refresh \u2014 the "
             "same gesture you know from apps, right inside OpenSRM."},
    {"ver": "v1.29.0", "date": "20 Oct", "title": "Kind to weak phones",
     "body": "The animated avatar now rests when it is off screen, and "
             "weak devices get a calm version automatically \u2014 less "
             "battery and smoother scrolling for everyone."},
    {"ver": "v1.28.0", "date": "20 Oct", "title": "Feels like an app",
     "body": "Taps now respond instantly, tabs glide instead of snapping, "
             "and dialogs slide up from the bottom on phones \u2014 the "
             "small motion touches that make it feel native."},
    {"ver": "v1.27.2", "date": "20 Oct", "title": "Security upkeep",
     "body": "A routine security update of the tools the server uses "
             "under the hood. Nothing changes in how the app looks or "
             "works."},
    {"ver": "v1.27.1", "date": "20 Oct", "title": "Smarter feedback button",
     "body": "The auto-fill feedback option now checks the portal before "
             "showing itself: while the mid-sem feedback form is closed on "
             "the portal, the button hides itself automatically and returns "
             "on its own when the form opens again — no more dead buttons."},
    {"ver": "v1.27.0", "date": "20 Oct", "title": "Refresh without the flash",
     "body": "Refreshing now updates your numbers right where they are "
             "— no more white flash, lost scroll position or "
             "re-loading of the page after a sync."},
    {"ver": "v1.26.3", "date": "20 Oct", "title": "Instant repeat visits",
     "body": "The app now remembers its own files: styles and scripts "
             "that have not changed are no longer re-downloaded on every "
             "launch, so opening the dashboard again is much faster and "
             "uses less data. New versions still arrive automatically "
             "right after each update."},
    {"ver": "v1.26.2", "date": "19 Oct", "title": "Faster first paint",
     "body": "The app's stylesheet is now built ahead of time and served "
             "straight from this server, instead of each phone compiling "
             "CSS in the browser on every launch. The page shows sooner, "
             "works with no third-party requests, and nothing changes in "
             "how it looks."},
    {"ver": "v1.26.1", "date": "19 Oct", "title": "Under-the-hood tidy-up",
     "body": "A defensive fix so an unusually long subject code in the Today "
             "widget can never push the page sideways on a phone — the code "
             "truncates instead. Nothing changes with normal timetables. Also "
             "adds the measuring tools used for the upcoming performance work."},
    {"ver": "v1.26.0", "date": "18 Oct", "title": "Self-checking reminders",
     "body": "The job that sends class-reminder pushes now reports its own "
             "health on the server's metrics page, so if it ever stops "
             "running, the server itself raises an alarm instead of the "
             "reminders just quietly not arriving. Nothing changes in how "
             "reminders look on your end."},
    {"ver": "v1.25.0", "date": "15 Oct", "title": "Delete my data",
     "body": "Settings now has a \"Delete my data\" row: it opens an explainer "
             "listing exactly what is erased (your account, login sessions, "
             "reminder subscriptions, usage rows, your edit attributions) and "
             "what is never touched — the SRM portal itself, shared timetables "
             "and other students' accounts. Nothing is removed until you "
             "confirm, and afterwards you are signed out back to the login page."},
    {"ver": "v1.24.0", "date": "15 Oct", "title": "Server health check + hardening",
     "body": "The server now answers a small health endpoint that is checked "
             "every 30 seconds, so a broken server is noticed immediately "
             "instead of timing out in your dashboard. The app also runs in a "
             "locked-down container (no root, read-only filesystem, capped "
             "memory and process limits), so a fault inside it stays inside "
             "it. Nothing changes in how you use the app."},
    {"ver": "v1.23.0", "date": "15 Oct", "title": "Syncs wait in line instead of failing",
     "body": "Clicking sync while another sync is already running no longer fails with "
             "\"Sync in progress\" — it waits up to 45 seconds for its turn (logins go "
             "ahead of refreshes, and the progress bar shows how many syncs are ahead) "
             "and only gives the busy error if the wait runs out."},
    {"ver": "v1.22.1", "date": "15 Oct", "title": "Sessions hardened at rest",
     "body": "Session tokens are now stored in the database only as SHA-256 "
             "digests, so a copied database file can no longer be used to log "
             "in as you — and your existing session keeps working across this "
             "update. Requests that try to change your data from another "
             "website are also refused now."},
    {"ver": "v1.22.0", "date": "15 Oct", "title": "Smarter syncs — no wasted portal visits",
     "body": "Syncing twice in a row no longer hits the portal twice: a refresh within "
             "5 minutes of your last sync is answered from the data you already have, "
             "and refreshes started while one is already running now wait for and "
             "share that sync instead of showing a \"Sync in progress\" error."},

    {"ver": "v1.21.0", "date": "15 Oct", "title": "Clearer sync errors + sync health monitoring",
     "body": "A failed sync now says exactly what went wrong (wrong password, "
             "portal busy, or the portal changed) instead of a generic error. "
             "We also track sync success, timing and portal failures "
             "server-side — with a one-command canary check — so a portal "
             "change is caught before it reaches your dashboard."},
    {"ver": "v1.20.2", "date": "15 Oct", "title": "Fewer database-is-locked errors",
     "body": "Concurrent requests used to hit SQLite's 5-second lock wait "
             "limit and show a database-is-locked error; the app now waits "
             "up to 10 seconds, and operators can switch to WAL journaling "
             "with the SQLITE_JOURNAL_MODE setting for smoother concurrent "
             "access. Nothing changes for existing installs by default."},
    {"ver": "v1.20.1", "date": "14 Oct", "title": "Refresh keeps your subjects",
     "body": "A refresh whose marks page failed to parse used to blank the "
             "subjects already stored on your account. Stored subjects, marks, "
             "exam schedule, faculty and attendance are now kept whenever the "
             "fresh value comes back empty, and every kept value is logged "
             "instead of being written silently."},
    {"ver": "v1.20.0", "date": "14 Oct", "title": "Dashboard layout fixes",
     "body": "Uniform 15px spacing everywhere (no more 30px gaps or mystery "
             "19px right gutter); cards no longer scroll when their widgets "
             "fit; attendance shows subject names with +skip/-attend margins; "
             "freshly entered marks are faintly highlighted and show up in "
             "This Week; the profile blobatar is bigger now."},
    {"ver": "v1.19.0", "date": "13 Oct", "title": "Feedback button follows the portal",
     "body": "Auto-fill hides itself while the portal's mid-sem feedback service is "
             "closed and comes back when it reopens; the dashboard now fits your "
             "screen without scrolling on desktop; every release ships a notice here."},
    {"ver": "v1.18.0", "date": "12 Oct", "title": "Official timetable from the portal",
     "body": "Timetable syncs straight from the portal's published grid (manual "
             "editing archived); syncs now keep your session through a mid-scrape relogin."},
    {"ver": "v1.17.0", "date": "12 Oct", "title": "Settings tab",
     "body": "Personal details, notification preferences and log out consolidated "
             "into one Settings tab."},
    {"ver": "v1.16.0", "date": "11 Oct", "title": "Card dashboard + notices",
     "body": "Dashboard rebuilt as cards and widgets: class ticker, skip "
             "glance, subject-grouped teachers and this notices panel."},
    {"ver": "v1.15.4", "date": "10 Oct", "title": "Institute email + marks fixes",
     "body": "Profile shows your @srmist.edu.in address; marks list every "
             "subject, stale entries flagged, trailing zeroes trimmed."},
]


def _budget_rows(courses):
    """Attendance widget: (subject name, signed margin, risk) per subject in
    COURSES order (already sorted pct-ascending = risk-first). Value is the
    MARGIN-SIGNED form of the same _bunk_counts numbers the attendance tab's
    Margin column shows: `-N` = N classes short of 75% (attend N), `+N` = N in
    surplus (can skip N), `0` = exactly at the line — one sign language across
    tab and glance. Names go through _title_case (codes read as jargon on
    the dashboard; custom mixed-case names keep their casing).
    (None, None) rows (nothing held) are dropped, never faked as 0.
    """
    rows = []
    for c in courses:
        skip, attend = c.get("skip_now"), c.get("attend_now")
        if attend is None and skip is None:
            continue
        name = _title_case(c.get("description") or c.get("code", ""))
        if attend is not None:
            rows.append((name, f"-{attend}", 0))
        elif skip:
            rows.append((name, f"+{skip}", 2))
        else:
            rows.append((name, "0", 1))
    return rows


# ── Tools tab (SCOPE-sourced surfaces) ──────────────────────────────
# One entry per SCOPE surface. A row renders ONLY when its feature slug is
# enabled AND its representative op landed a non-empty answer; nothing
# qualifying = empty list = no entry, no tab (zero footprint — the mission
# toggle contract, and the same self-hiding rule the dashboard widgets obey).
# `tab` is the panel that surface's own PR mounts: the row navigates there
# when that panel exists today and renders inert otherwise, so this stays a
# landing surface for the SCOPE rotation instead of a duplicate of it.
TOOLS = [
    ("fees", "Fees", "Dues, payments and receipts", "getFeeDetails"),
    # gates on the RELEASED-results op: the provisional/revaluation endpoints
    # are empty outside their window, so keying the entry on them left Academics
    # hidden even with a full grade history (caught in review).
    ("academics", "Academics", "Results, grades and credits",
     "getExamDetails"),
    ("library", "Library", "Issued books, due dates, fines",
     "getLibraryTransaction"),
    ("campus", "Hostel & transport", "Room, mess and bus route",
     "getHostelDetails"),
    ("campus", "Notifications", "Campus notices and circulars",
     "getViewNotificationListJson"),
    ("placement", "Placement", "Offers, eligibility, registration",
     "getStudentAllOfferedJobs"),
]


def _tools_entries(netid):
    """Rows for the Tools panel: [{"slug","label","hint","op"}].

    Two gates, both required: SCOPE_FEATURES enables the slug (the ops
    contract) and the cold blob holds a non-empty answer for the op (an
    enabled surface with nothing behind it must not advertise itself).
    Costs one users-row read, and only when a feature is enabled at all.
    """
    from app.scope.ops import enabled_features  # lazy: app.scope imports app.db
    on = enabled_features()
    if not on:
        return []
    row = user_scope_data(netid)
    # shape guard on both levels: a corrupt/foreign scope_json must degrade to
    # "no tools", never 500 the dashboard (same rule as _stored in scope.sync
    # and _jload's wrong-shape branch — audit B10).
    blob = _jload(row["scope_json"] if row else None, {})
    rows = []
    for feat, label, hint, op in TOOLS:
        if feat not in on:
            continue
        entry = blob.get(op)
        if isinstance(entry, dict) and entry.get("data"):
            rows.append({"slug": feat, "label": label, "hint": hint, "op": op})
    return rows


def _teacher_groups(faculty):
    """Faculty rows -> flat teacher-group dicts for the Teachers widget
    (subject-first grouping is the widget's whole view; initials derived
    HERE, not in the template). faculty == _faculty_view output."""
    out = []
    for f in faculty:
        staff = []
        for _sid, tname, kind in f["staff"]:
            # portal writes "Dr.Priyanka" with no space — normalise for display
            tname = re.sub(r"^(Dr|Mr|Ms|Mrs|Prof)\.(?=\S)", r"\1. ", tname)
            parts = tname.split()
            given = parts[0] if parts else ""
            # honorifics are not initials: "Dr.Priyanka Gupta" -> PG, not DG
            m = re.match(r"^(?:Dr|Mr|Ms|Mrs|Prof)\.?(.*)$", given, re.I)
            if m:
                given = m.group(1) or (parts[1] if len(parts) > 1 else given)
            sur = parts[-1] if len(parts) > 1 else ""
            ini = (given[:1] + sur[:1]) if given else ""
            staff.append({"name": tname, "mode": kind, "ini": ini.upper()})
        out.append({"code": f["code"], "name": f["name"], "staff": staff})
    return out


def _day_slots(group_key):
    """group_key -> {day: {period: slot}} or None when no timetable exists."""
    return day_slots(group_key)

def _tt_grid(group_key):
    """Resolved weekly TIME grid for a group — same row shape SLOTS has
    (class rows + period-0 break dividers), so ticker/push/panel consumers
    swap SLOTS -> _tt_grid(group_key) without other changes.

    official mode (default): the group's RAW published time row
    (timetable_groups.official_times) + TIMETABLE_TIME_OFFSETS; gaps >= 10 min
    between corrected periods become dividers (the official page has none —
    break/lunch exist only as gaps). Fallback to legacy SLOTS whenever there
    is no official data to trust: group missing, never published, raw JSON
    corrupt, offsets producing overlap — any anomaly degrades to the grid we
    know instead of failing the render.

    TIMETABLE_SOURCE = "manual" is the ops escape hatch: always SLOTS."""
    if TIMETABLE_SOURCE != "official":
        return SLOTS
    raw_txt = official_times(group_key)
    if not raw_txt:
        return SLOTS
    try:
        raw = json.loads(raw_txt)
        parsed = []
        for k in raw:
            p = int(k)
            sm, em = raw[k].split("-")
            s = int(sm.split(":")[0]) * 60 + int(sm.split(":")[1]) + TIMETABLE_TIME_OFFSETS.get(p, 0)
            e = int(em.split(":")[0]) * 60 + int(em.split(":")[1]) + TIMETABLE_TIME_OFFSETS.get(p, 0)
            if e <= s:
                raise ValueError("inverted period %d after offset" % p)
            parsed.append((p, s, e))
        parsed.sort(key=lambda t: t[1])
        if any(parsed[i][1] < parsed[i - 1][2] for i in range(1, len(parsed))):
            raise ValueError("corrected periods overlap")
    except Exception as ex:
        log.debug("timetable grid: official_times unusable (%r) — SLOTS fallback", ex)
        return SLOTS
    out = []
    for i, (p, s, e) in enumerate(parsed):
        if i:
            gap = s - parsed[i - 1][2]
            if gap >= 10:
                out.append({"period": 0, "start": "%02d:%02d" % divmod(parsed[i - 1][2], 60),
                            "end": "%02d:%02d" % divmod(s, 60), "type": "break",
                            "name": "Lunch" if gap >= 30 else "Break"})
        out.append({"period": p, "start": "%02d:%02d" % divmod(s, 60),
                    "end": "%02d:%02d" % divmod(e, 60), "type": "class"})
    return out


def _tt_fetched_at(group_key):
    """Epoch of the last official timetable sync for this group (0 = never)."""
    v = tt_fetched_at(group_key)
    return int(v) if v else 0

def _save_timetable_group(netid, res):
    """Upsert the student's timetable group + scraped subjects, then persist the
    official portal timetable (formId 10). Own transaction, warn-only — a
    timetable write must never fail a sync.

    Called from /api/login AND /api/refresh (refresh had no group/subject
    upsert before, so subjects and the official grid would only ever update on
    a fresh login; hot syncs skip formId 17 so the group key comes from stored
    cold data there).

    Preserve contract: no "timetable" grid in res (section unpublished, shape
    drift, dead JSP) -> no slot writes, stored rows untouched. A published grid
    is an atomic whole-group replace stamped source='official' (UNIQUE
    group/day/period means one source at a time per group — the archived
    editor does the same replace stamped 'manual'). Locations typed into the
    editor carry forward: the portal publishes no rooms."""
    try:
        personal = dict(res.get("personal") or {})
        if not personal:
            prow = user_personal(netid)
            try:
                personal = json.loads(prow[0]) if prow and prow[0] else {}
            except Exception:
                personal = {}
        gk = _group_key(personal)
        if not gk:
            return
        with transaction():
            upsert_group(gk, personal.get("Program", ""), int(personal.get("Batch", 0) or 0),
                         _semester_int(personal.get("Semester", "")), personal.get("Section", ""))
            gid = group_id(gk)
            for sub in res.get("courses") or []:
                upsert_subject(gid, sub["code"], sub["name"], sub["credits"], 0)
            tt = res.get("timetable")
            if isinstance(tt, dict) and tt.get("grid"):
                old_loc = {(r[0], r[1]): (r[2], r[4]) for r in group_slots(gid) if r[4]}
                known = {r[0]: r[1] for r in group_subjects(gid)}
                legend = tt.get("legend") or {}
                rows = []
                for day, slots in tt["grid"].items():
                    for p, code in slots.items():
                        if not code:
                            continue
                        # same rule as the editor path (app.py:~3020): carry the
                        # room forward only while the slot's CODE is unchanged —
                        # a swapped subject drops the old room (review #3)
                        prev = old_loc.get((day, int(p)))
                        loc = prev[1] if prev and prev[0] == code else ""
                        rows.append((day, int(p), code,
                                     legend.get(code) or known.get(code) or code, loc))
                replace_group_slots(gid, rows, "official")
                set_official_times(gk, json.dumps({str(k): v for k, v in sorted(tt["times"].items())}),
                                   int(time.time()))
                log.debug("timetable official save netid=%s group=%s rows=%d", netid, gk, len(rows))
    except Exception as e:
        log.warning("timetable group/subject save failed netid=%s: %r", netid, e, exc_info=True)


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
    gid = group_id(group_key)
    if gid is None:
        return ("<div class=\"tt-wrap\"><div class=\"tt-hero\">"
                ""
                "<div><strong>No timetable set</strong>"
                "<div class=\"tt-hero-sub\">Your group has no timetable. Use the editor to build one.</div></div></div></div>")
    day_slots = {}
    # attendance join (spec §4): custom short-circuits BEFORE any name match —
    # a custom subject typed with a portal-matching name must never join.
    custom_codes = set()
    if attendance:
        for r in group_subjects(gid):
            if r[3] and r[0]:
                custom_codes.add(r[0])
    for r in group_slots(gid):
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
    grid = _tt_grid(group_key)
    last_cls = -1
    for i, s in enumerate(grid):
        if s["type"] == "class" and today in day_slots and s["period"] in day_slots[today]:
            last_cls = i
    today_slots = []
    for i, s in enumerate(grid):
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
        present = [s["type"] == "class" and s["period"] in day_slots.get(d, {}) for s in grid]
        last_cls = max((i for i, p in enumerate(present) if p), default=-1)
        rows = []
        for i, s in enumerate(grid):
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
            # Navya 2026-10-12: Soon retired — only the live class carries "Now"
            # (the hero repeats it; the badge marks the row itself).
            badge = "<span class=tt-badge>Now</span>" if hl == "current" else ""
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


@require_login
def api_marks():
    netid = get_current_user()
    if not netid:
        return {"ok": False, "error": "not logged in"}, 401
    row = user_marks(netid)
    marks = _jload(row["marks_json"] if row else None, [])
    return {"ok": True, "marks": marks}

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
    row = user_feedback(netid)
    # archived while the window is closed: refuse BEFORE any portal contact
    # (a stale open flag would otherwise burn a session rebuild + login just
    # to be told "Service closed" by the portal).
    if row and row["fb_open"] is not None and not row["fb_open"]:
        log_with_kv(log_portal, logging.INFO, "feedback fill refused (window closed)",
                    netid=netid, error="fb_open=0")
        return {"ok": False,
                "error": "the mid-sem feedback window is closed on the portal — nothing was submitted"}, 409
    fmap = _jload(row["faculty_map_json"] if row else None, {})
    plan = _fb_plan(fmap)
    if not plan:
        return {"ok": False, "error": "no feedback data yet — sync first"}, 400
    cookies = _load_session(netid)
    if not cookies:
        return {"ok": False, "error": "portal session expired — sync first"}, 400
    # audit run-1 (#3): this path reaches the portal like every other — it used
    # to run with ZERO gates and no scrape lock (92 portal requests fired while
    # a sync held the lock, budget untouched). Same free gates first, budget
    # last; the lock is held for the whole submit so fills serialize against
    # in-flight syncs. Fill is bounded by budget+cooldown+lock; the per-netid
    # sync quota stays reserved for actual syncs (no charge here).
    if _portal_cooldown_remaining() > 0:
        return {"ok": False,
                "error": "SRM portal temporarily rate-limiting our server — try again in a few minutes."}, 429
    if not _check_rate(netid):
        return {"ok": False,
                "error": f"Too many sync attempts for this account. Try again in {_netid_retry_text(netid)}."}, 429
    if not _scrape_lock.acquire(blocking=False):
        metrics.inc("opensrm_scrape_lock_rejections_total", op="feedback")
        return {"ok": False, "error": "Sync in progress — try again in about a minute."}, 503
    try:
        if not _check_portal_budget(_client_ip(), authorized=True):
            return {"ok": False,
                    "error": "Too many portal requests from the server — try again in 10 minutes."}, 429
        from . import http_scraper
        t0 = time.monotonic()
        try:
            res = http_scraper.fill_feedback(netid, plan, cookies)
        except http_scraper.HttpScraperError as e:
            # full detail goes to the log + telemetry only: exception text must
            # never reach the response body (CWE-209, CodeQL
            # py/stack-trace-exposure) — it can embed nested exception reprs.
            # audit run-1 (#17): reachable only from pre-loop failures now —
            # mid-loop failures return partial res via the success path below.
            log_with_kv(log_portal, logging.WARNING, "feedback fill error", netid=netid, error=str(e)[:80])
            _track("feedback_fill_fail", detail=str(e)[:60], user=netid)
            return {"ok": False, "error": "feedback submission failed — nothing was submitted"}, 502
        if "error" in res:
            # fill_feedback's own portal-state refusal: a literal it built
            # itself, so it is safe to hand to the student verbatim.
            log_with_kv(log_portal, logging.WARNING, "feedback fill refused", netid=netid, error=res["error"][:80])
            _track("feedback_fill_fail", detail=res["error"][:60], user=netid)
            if res.get("closed"):
                # self-heal (2026-10-20): the portal itself just confirmed the
                # window is shut — archive the CTA NOW so the stale button
                # disappears on the next dashboard load instead of waiting
                # for the next sync's probe. Closed refusals read as 409,
                # same as the fb_open=0 pre-contact guard above.
                try:
                    set_fb_open(netid, 0)
                    log_with_kv(log_portal, logging.INFO, "feedback CTA archived (portal-confirmed closed)",
                                netid=netid)
                except Exception as e:
                    log_with_kv(log_portal, logging.WARNING, "fb_open self-heal write failed",
                                netid=netid, error=str(e)[:80])
                return {"ok": False, "error": res["error"]}, 409
            return {"ok": False, "error": res["error"]}, 502
        ms = int((time.monotonic() - t0) * 1000)
        log_with_kv(log_portal, logging.INFO, "feedback fill done",
                    netid=netid, filled=len(res.get("filled", [])), already=len(res.get("already", [])),
                    failed=len(res.get("failed", [])), total_ms=ms)
        _track("feedback_fill_ok", detail=f"{ms}ms", user=netid)
        return {"ok": True, **res}
    finally:
        _scrape_release()   # A10: hand back through the queue-aware release


def _load_component_tags(class_key, marks):
    """Confirmed IE tags for this class's components -> {(code, name): row}.
    Keys carry no netid on purpose: one student's confirmation applies to the
    whole class (and is later reused by the GPA predictor)."""
    wanted = {f"{class_key}|{s.get('code', '')}|{c.get('name', '')}":
              (s.get("code", ""), c.get("name", ""))
              for s in marks for c in s.get("components", [])}
    if not wanted:
        return {}
    rows = component_tags(wanted)
    return {wanted[r[0]]: {"role": r[1], "raw_max": r[2], "scaled_max": r[3]} for r in rows}


def _week_marks(marks):
    """Week widget: components whose portal 'Entered on' falls in the current
    Mon–Sun week (IST server date) — `code · name · date` rows, newest first.
    The week column's second job: what got ADDED this week, next to what got
    missed. Empty list = the block stays hidden (empty=hidden, DESIGN §8)."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    out = []
    for m in marks or []:
        for cpt in m.get("components", []):
            try:
                d = datetime.strptime(cpt.get("entered", "") or "", "%d/%b/%Y").date()
            except (ValueError, TypeError):
                continue
            if monday <= d <= today:
                out.append({"code": m.get("code", ""), "name": cpt.get("name", ""),
                            "_d": d, "date": d.strftime("%d %b")})
    out.sort(key=lambda r: r["_d"], reverse=True)
    for r in out:
        del r["_d"]
    return out

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
    subs = [s for s in subs if s["notify_exams"]]   # per-type pref
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


def static_no_cache(filename):
    from flask import send_from_directory
    # audit: was hardcoded "/app/app/static" — only worked inside the container
    # (local runs 404'd). Derive from __file__ like every other path here.
    resp = send_from_directory(os.path.join(os.path.dirname(__file__), "static"), filename)
    # Cache policy (DESIGN §10.16 rule 2):
    #  - versioned URLs (?v=<content hash> from asset()) are
    #    content-addressed — the bytes under the URL can never change — so
    #    they cache immutable for a year. This is what makes warm repeat
    #    visits move zero CSS/JS bytes.
    #  - sw.js revalidates every load so worker updates land on the next
    #    navigation instead of after up to 1h (audit run-1 R1).
    #  - manifest stays cacheable (3600), other unversioned statics stay
    #    no-store (a deploy must never leave a stale shell).
    if filename == "sw.js":
        resp.headers["Cache-Control"] = "no-cache"
        # audit 2026-09-27: without this header a scope of "/" is rejected
        # (default max scope = the script's directory, /static/) and
        # registration fails — swallowed by .catch(), so the PWA silently
        # never worked. Registration now lives in login.js/dash.js (external
        # files pass script-src 'self').
        resp.headers["Service-Worker-Allowed"] = "/"
    elif request.args.get("v"):
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif filename.endswith('.json'):
        resp.headers["Cache-Control"] = "public, max-age=3600"
    elif filename.endswith('.js'):
        resp.headers["Cache-Control"] = "no-cache"
    else:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


# ── Versioned asset URLs (?v=<content-hash>, DESIGN §10.16 rule 2) ────
# Templates reference CSS/JS through asset(); Phase 3 makes static_no_cache
# serve these URLs immutable, so the browser never re-downloads an unchanged
# file. Cache key = mtime_ns; a rebuild changes the hash automatically.
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_asset_cache = {}


def asset(name):
    """Versioned /static/ URL: /static/<name>?v=<sha256[:10]>."""
    path = os.path.join(_STATIC_DIR, name)
    st = os.stat(path)
    hit = _asset_cache.get(name)
    if not hit or hit[0] != st.st_mtime_ns:
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()[:10]
        hit = (st.st_mtime_ns, digest)
        _asset_cache[name] = hit
    return "/static/%s?v=%s" % (name, hit[1])

# ── Typed sync results ─────────────────────────────────────────────────
# A failed sync carries a `kind`; its HTTP status comes from this table —
# the replacement for the old status classifier, which substring-matched
# the message text (wrong password vs captcha failure was told apart by
# wording). 401 auth · 429 rate/cooldown · 503 busy/portal/internal.
# Every status and user-visible string is byte-identical to the old
# mapping; tests/test_login_reject.py runs the old classifier against the
# new table over every {'ok': False} producer in app.py + http_scraper.py.
KIND_STATUS = {
    "bad_credentials": 401,
    "rate_limited": 429,
    "portal_cooldown": 429,
    "busy": 503,
    "portal_down": 503,
    "markup_changed": 503,
    "internal": 503,
}

def sync_error(kind, user_message, retry_after=None):
    """One failed sync result (the SyncError result type): typed kind, the
    byte-identical user-visible message, optional retry seconds — filled in
    only where the window is already computed (the portal cooldown),
    None otherwise. Routes rebuild the response as {ok, error}, so kind and
    retry_after never reach the client."""
    return {"ok": False, "error": user_message, "kind": kind, "retry_after": retry_after}

def sync_status(res):
    """HTTP status for a failed sync — from its kind, never from message
    text. A failure without a kind (a bare test stub) keeps the old
    fallback: 503."""
    return KIND_STATUS.get(res.get("kind"), 503)

def login():
    if get_current_user(): return redirect("/")
    return render_template("login.html", version=APP_VERSION)

def _merge_fetch_result(existing, res, netid=None):
    """preserve-if-empty merge shared by /api/login and /api/refresh (audit B6).

    An absent/empty fetch key must never clobber stored data: parse failures
    return marks=[] / personal={} with ok=True. The two routes had separate
    copies of this contract and drifted — refresh was missing the subjects
    preserve, so a hot-only refresh wiped stored subjects_json on the exact
    marks-page failure that preserved marks_json (R1). One copy now.
    `existing` = current users row (dict row, or None on first fetch).
    Returns (personal_json, marks_json, subjects_json, exams_json,
    faculty_json, fb_open, exam_events, attendance_json). attendance_json follows
    the same absent/empty-equals-preserve contract (audit run-1), with daily_absent
    merged per month. Any column kept because the fresh payload was empty/absent
    is logged once as `preserve kept stored data netid=… columns=…` (INFO) so
    keeps are visible in opensrm.auth instead of silent.
    """
    preserved = []  # columns kept from `existing` because fresh was empty/absent

    def _pres(col):
        if col not in preserved:
            preserved.append(col)

    def _col(key, col):
        if res.get(key):
            return json.dumps(res[key])
        if existing and existing[col]:
            _pres(col)
            return existing[col]   # transition events read PRE-write rows
        return json.dumps({"personal": {}, "subjects": {}}[key])
    personal_json = _col("personal", "personal_details_json")
    subjects_json = _col("subjects", "subjects_json")
    # attendance: same absent-equals-preserve contract as every sibling (audit
    # run-1): a partial portal response (missing cumulative table, failed
    # drilldown months, junk first tbody) must never wipe stored monthly rows,
    # absence history or the period anchor. Fresh non-empty fields win; empty
    # fresh fields keep stored; daily_absent merges per month.
    if res.get("data"):
        att = dict(res["data"])
        stored_att = {}
        raw_att = (existing["attendance_json"]
                   if existing and "attendance_json" in existing.keys() else None)
        if raw_att:
            try:
                stored_att = json.loads(raw_att) or {}
            except (ValueError, TypeError):
                stored_att = {}
        if isinstance(stored_att, dict):
            for f in ("courses", "monthly", "period"):
                if not att.get(f) and stored_att.get(f):
                    att[f] = stored_att[f]
                    _pres("attendance_json")
            fresh_daily = att.get("daily_absent") or {}
            if stored_att.get("daily_absent") or fresh_daily:
                att["daily_absent"] = {**stored_att.get("daily_absent", {}), **fresh_daily}
            if stored_att.get("daily_absent") and not fresh_daily:
                _pres("attendance_json")
        attendance_json = json.dumps(att)
    elif existing and "attendance_json" in existing.keys() and existing["attendance_json"]:
        _pres("attendance_json")
        attendance_json = existing["attendance_json"]   # key absent = preserve
    else:
        attendance_json = json.dumps({"courses": [], "monthly": [], "period": None, "daily_absent": {}})
    # marks: preserve-if-empty (B6) AND flag the preserved rows `stale=True`
    # — the dashboard widget highlights chips whose numbers come from an
    # earlier sync instead of the latest one (Oct 2026). A real fetch writes
    # portal rows as-is, which clears any previous flag.
    if res.get("marks"):
        marks_json = json.dumps(res["marks"])
    elif existing and existing["marks_json"]:
        _pres("marks_json")
        marks_json = existing["marks_json"]
        try:
            stored = json.loads(marks_json)
            if isinstance(stored, list):
                for m in stored:
                    if isinstance(m, dict):
                        m["stale"] = True
                marks_json = json.dumps(stored)
        except (ValueError, TypeError):  # corrupt row: keep the bytes (B1-B4)
            pass
    else:
        marks_json = "[]"
    # exams: key absent (probe unreliable / Playwright fallback) -> preserve stored
    if "exams" in res:
        exams_json = json.dumps(res["exams"])
        exam_events = _exam_events(existing["exam_schedule_json"] if existing else None,
                                   res["exams"])
    else:
        exams_json = (existing["exam_schedule_json"] if existing and existing["exam_schedule_json"] else "[]")
        if existing and existing["exam_schedule_json"]:
            _pres("exam_schedule_json")
        exam_events = []
    # faculty map: key absent (window closed / harvest failed) -> preserve stored
    if "faculty" in res:
        faculty_json = json.dumps(res["faculty"])
    else:
        faculty_json = (existing["faculty_map_json"] if existing and existing["faculty_map_json"] else "{}")
        if existing and existing["faculty_map_json"]:
            _pres("faculty_map_json")
    # fb_open (feedback window availability): same preserve contract — only a
    # cold sync that actually classified it (1 open / 0 Service closed) writes;
    # hot syncs and unknown failures keep the stored flag. Absent row/column
    # (pre-v16 restore, hand-made test row) = optimistic 1, matching the
    # column DEFAULT — never let a missing key 500 the login path.
    if "fb_open" in res:
        fb_open = res["fb_open"]
    else:
        fb_open = 1
        if existing:
            try:
                v = existing["fb_open"]
            except (IndexError, KeyError):
                v = None
            fb_open = v if v is not None else 1
    if preserved and netid:
        # visibility: a keep because the fresh payload was empty is otherwise
        # silent — the subjects wipe (R1) shipped with no trace in the logs
        log_with_kv(log_auth, logging.INFO, "preserve kept stored data",
                    netid=netid, columns=",".join(preserved))
    return personal_json, marks_json, subjects_json, exams_json, faculty_json, fb_open, exam_events, attendance_json


def persist_sync(netid, res, password=None):
    """Persist one sync — the single copy of what /api/login and /api/refresh
    each did: users upsert through _merge_fetch_result, then (post-commit) the
    exam-event thread, the timetable group and the sync_ok telemetry row.
    Login passes the password (INSERT ... ON CONFLICT: first fetch creates the
    row, later logins rotate the stored password); refresh passes None
    (UPDATE in place, stored password untouched). Ordering and the
    post-commit thread start are kept from both routes.
    """
    existing = user_sync_state(netid)
    (personal_json, marks_json, subjects_json, exams_json, faculty_json,
     fb_open, exam_events, attendance_json) = _merge_fetch_result(existing, res, netid=netid)
    write_user_sync(netid, encrypt_pw(password) if password is not None else None,
                    attendance_json, res["fetched"], personal_json, marks_json,
                    subjects_json, exams_json, faculty_json, fb_open)
    # one-shot exam pushes (official release / room allotment): post-commit,
    # background thread — detection already read pre-write rows, and the
    # single gunicorn worker must not wait on a push round-trip
    if exam_events:
        threading.Thread(target=_notify_exam_events, args=(netid, exam_events),
                         daemon=True, name="srm-exam-evt").start()
    # timetable group/subjects + official grid (non-critical, separate tx)
    _save_timetable_group(netid, res)
    _track("sync_ok", user=netid)


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
    # audit run-1 (#13): this browser's progress token — keying progress by
    # it (instead of netid) makes /api/login/progress unreadable to anyone
    # who merely guesses the account name
    attempt = str(d.get("attempt") or "").strip()
    if not attempt.isalnum() or len(attempt) > 64:
        attempt = None

    # audit 2026-09-27: count the per-IP budget AFTER validation (was before).
    # Previously 11 trivial `{}` POSTs (valid JSON dict, no credentials) burned
    # the 10/hour budget and 429'd the rest of the hour — a cheap self-DoS on
    # shared campus NAT that never even reached the portal.
    if not _check_ip_rate(_client_ip()):
        log_with_kv(log_auth, logging.WARNING, "login ip limited", ip=_client_ip())
        return {"ok": False, "error": f"Too many login attempts from this device (10/hour). Try again in {_ip_retry_text(_client_ip())}."}, 429

    login_t0 = time.monotonic()
    res = fetch_attendance(netid, password, attempt=attempt)
    login_ms = int((time.monotonic() - login_t0) * 1000)
    if not res["ok"]:
        log_with_kv(log_auth, logging.WARNING, "login failed", netid=netid, ip=_client_ip(),
                    error=res["error"][:80], duration_ms=login_ms)
        _track("login_fail", detail=res["error"][:60], user=netid)
        # audit F4: auth failures are 401; busy/rate are 429/503
        code = sync_status(res)
        return {"ok": False, "error": res["error"]}, code
    log_with_kv(log_auth, logging.INFO, "login ok", netid=netid, ip=_client_ip(),
                duration_ms=login_ms, subjects=len(res.get("marks", [])))
    _track("login_ok", detail=f"{login_ms}ms", user=netid)
    # Hot/cold + audit B6: empty/absent fetch keys preserve stored cold data
    # (single shared contract — see _merge_fetch_result); the one copy of
    # the upsert now lives in persist_sync, password passed so the row is
    # created/rotated exactly as before
    persist_sync(netid, res, password=password)

    token = make_session_token(netid)
    resp = make_response({"ok": True})
    resp.set_cookie("srm_session", token, max_age=SESSION_MAX_AGE, httponly=True,
                    samesite="Lax", secure=_cookie_secure())
    return resp

# ── Sync cache window + per-netid single flight ──────────────────────
# A refresh answered from the last sync never reaches the portal, so it
# spends neither the account's 3-in-10-min quota (only _charge_rate spends
# that) nor the aggregate portal budget. A second refresh for an account
# already syncing waits for that sync and returns ITS result instead of
# "Sync in progress" — joiners never enter fetch_attendance either, so the
# per-netid limit still moves only once, by the runner.
#
# SYNC_MIN_INTERVAL_S default = 300s, chosen from the durable log: 212
# completed syncs / 9 accounts (opensrm.log 2026-10-08..15, `http scrape
# complete netid=`) give 203 per-account consecutive-sync gaps — p10 299s,
# p25 2009s, median 9852s; a 300s window absorbs 21/203 (10.3% — the
# double-click / reload bursts) while 89.7% of real syncs sit further apart
# than the window and pass through untouched. Maintainer decision: 0 keeps
# always-sync; 900 would absorb 18.2% but also answers the dashboard's
# 600s background auto-sync from cache.
SYNC_MIN_INTERVAL_DEFAULT = 300

# ponytail: a joiner waits at most one pipeline deadline + slack, then
# falls back to today's busy 503 — raise only if queued multi-account
# syncs ever outlive it (leader time is bounded by PIPELINE_DEADLINE only
# once it holds the scrape lock; queue time behind other syncs is not).
_SYNC_FLIGHT_WAIT_S = PIPELINE_DEADLINE + 30
_sync_flights = {}   # netid -> {"done": Event, "res": dict|None} (res = the runner's full result)
_flights_lock = threading.Lock()


def _sync_min_interval_s():
    """SYNC_MIN_INTERVAL_S in seconds, read per-request (like
    TIMETABLE_EDITOR, so tests/ops can flip it without a restart):
    0 or negative disables the cache window; a non-integer value falls
    back to the data-derived default."""
    raw = os.environ.get("SYNC_MIN_INTERVAL_S")
    if raw is None:
        return SYNC_MIN_INTERVAL_DEFAULT
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return SYNC_MIN_INTERVAL_DEFAULT


def _last_sync_age(netid):
    """Seconds since the last completed sync (users.last_fetch, written by
    persist_sync from the fetch completion time). None = never synced or
    unreadable → no cache, always sync."""
    try:
        row = user_last_fetch(netid)
        fetched = int(row["last_fetch"] or 0) if row else 0
    except Exception as e:
        log.debug("last_fetch read failed netid=%s err=%r", netid, e)
        return None
    if fetched <= 0:
        return None
    return max(0.0, time.time() - fetched)


def _cached_sync_answer(netid, window):
    """The cached-refresh response when the last sync is younger than the
    window, else None. Single emit point: every cached answer logs one
    key=value line, bumps opensrm_sync_cached_total and records a
    sync_cached usage event, so the portal traffic actually saved stays
    observable (/internal/metrics + usage_events + opensrm.auth)."""
    if window <= 0:
        return None
    age = _last_sync_age(netid)
    if age is None or age >= window:
        return None
    metrics.inc("opensrm_sync_cached_total")
    log_with_kv(log_auth, logging.INFO, "sync cached",
                netid=netid, age_s=int(age), window_s=window)
    _track("sync_cached", user=netid)
    return {"ok": True, "cached": True, "age_s": int(age)}


@require_login
def api_refresh():
    netid = get_current_user()
    if not netid:
        return {"ok": False, "error": "not logged in"}, 401
    row = user_password(netid)
    if not row:
        log_with_kv(log_auth, logging.WARNING, "refresh blocked", netid=netid, reason="no_stored_creds")
        return {"ok": False, "error": "no stored creds"}, 401
    password = decrypt_pw(row["password"])  # audit: was plaintext, now Fernet
    if not password:
        log_with_kv(log_auth, logging.WARNING, "refresh blocked", netid=netid, reason="unreadable_creds")
        return {"ok": False, "error": "stored credentials unreadable — log in again"}, 401
    # single flight: join the sync already running for this account, or
    # become its runner (only the runner ever reaches fetch_attendance, so
    # joiners cost nothing against the per-netid limit)
    with _flights_lock:
        flight = _sync_flights.get(netid)
        leader = flight is None
        if leader:
            flight = _sync_flights[netid] = {"done": threading.Event(),
                                             "res": None}
    if not leader:
        metrics.inc("opensrm_sync_joined_total")
        t_join = time.monotonic()
        shared = flight["done"].wait(_SYNC_FLIGHT_WAIT_S) and flight["res"] is not None
        log_with_kv(log_auth, logging.INFO, "sync joined", netid=netid,
                    waited_ms=int((time.monotonic() - t_join) * 1000),
                    outcome="shared" if shared else "timeout")
        if shared:
            # the runner's exact result: success/cached payloads verbatim,
            # failures rebuilt {ok, error} with the same typed status — kind
            # and retry_after stay server-side (routes never expose them)
            jr = flight["res"]
            if jr.get("ok"):
                return jr
            return {"ok": False, "error": jr["error"]}, sync_status(jr)
        # runner outlived the join wait — today's busy answer, also free
        err = sync_error("busy", "Sync in progress. Try again in about a minute.", retry_after=60)
        return {"ok": False, "error": err["error"]}, sync_status(err)
    try:
        # cache window: inside SYNC_MIN_INTERVAL_S of the last completed
        # sync nothing can be new — answer from it, portal untouched.
        # (A joiner that raced this runner's completion shares its answer
        # or, after the flight drops, runs one ordinary sync — the window
        # re-check under leadership keeps that gap at sub-millisecond.)
        cached = _cached_sync_answer(netid, _sync_min_interval_s())
        if cached is not None:
            flight["res"] = cached
            return cached
        res = fetch_attendance(netid, password, authorized=True)  # owner session: draws the reserved auth floor
        if not res["ok"]:
            # audit 2026-09-30: refresh failures were invisible — prod 07:43 logged
            # only "status=503" with no reason anywhere, so the failure class could
            # not be diagnosed after the fact. Same KV line as /api/login.
            log_with_kv(log_auth, logging.WARNING, "refresh failed", netid=netid,
                        error=res["error"][:80])
            _track("sync_fail", detail=res["error"][:60], user=netid)
            # audit F4: match /api/login's status-code discipline
            flight["res"] = res   # typed result — joiners rebuild {ok, error} + typed status
            return {"ok": False, "error": res["error"]}, sync_status(res)
        # same single persistence path as login — no password arg: refresh
        # never rotates the stored credential
        persist_sync(netid, res)
        flight["res"] = {"ok": True}
        return {"ok": True}
    finally:
        # publish the result before the flight leaves the map: a joiner
        # holding this flight while it finished still shares the answer
        with _flights_lock:
            _sync_flights.pop(netid, None)
        flight["done"].set()

# ── Login preflight: browser fires this when the user focuses the
#    password field — warms the portal session + solves the captcha
#    while they finish typing. Consumed by /api/login via fetch_attendance.
# A18: _preflight_last/_preflight_ip (and the progress read cap) live in
# app/state.py — RateLimiter.preflight_* and ProgressTracker.read_ok.

def _run_preflight(netid):
    # audit run-1 (#7): the detached body used to fire portal work + OCR with
    # no lock — concurrent with an in-flight sync driving the same portal. It
    # now serializes through the scrape lock (busy -> skip, the warm login is
    # an optimization, not a requirement).
    if not _scrape_lock.acquire(blocking=False):
        log.debug("preflight skipped netid=%s — scrape lock busy", netid)
        metrics.inc("opensrm_preflight_total", outcome="busy")
        return
    try:
        from . import http_scraper
        http_scraper.preflight(netid)
    except Exception as e:
        # audit 2026-10-07: warm-login loss was DEBUG-only — now visible at WARNING
        log.warning("preflight failed netid=%s err=%r", netid, e)
        metrics.inc("opensrm_preflight_total", outcome="failed")
    finally:
        _scrape_release()   # A10: queue-aware handoff (wakes parked syncs)

def api_login_preflight():
    d = request.get_json(silent=True)
    netid = ((d.get("netid") or "").strip().lower().split("@")[0]
             if isinstance(d, dict) and isinstance(d.get("netid"), str) else "")
    if not netid or not NETID_RE.match(netid):
        return {"ok": False, "error": "invalid netid"}, 400
    ip = _client_ip()
    # audit run-1 (#7): the whole admission (ip cap + per-netid cooldown) is
    # one atomic read-modify-write inside RateLimiter.preflight_admit — the
    # old unlocked check-then-act let two gthread workers double-spend the
    # same admission; TTL eviction of both dicts happens there too. Log AFTER
    # releasing. A10: busy = queue DEPTH > 0, not a held lock — one running
    # sync no longer 503s the warm-login; a backed-up queue does.
    admission = rate_limiter.preflight_admit(
        netid, ip,
        busy=_portal_cooldown_remaining() > 0 or _sync_queue_depth() > 0)
    if admission == "limited":
        log_with_kv(log_auth, logging.WARNING, "preflight ip limited", netid=netid, ip=ip)
        return {"ok": False, "error": "rate"}, 429
    if admission == "cooldown":
        # identical response to a fresh start — no per-netid discriminator
        # leaks to an unauthenticated caller (audit run-1 #14)
        return {"ok": True}
    if admission == "busy":
        log_with_kv(log_auth, logging.WARNING, "preflight busy", netid=netid, ip=ip)
        return {"ok": False, "error": "portal busy"}, 503
    if not _check_portal_budget(ip, bucket="preflight"):  # audit: aggregate egress cap (takes _rate_lock — must run outside the admission above)
        return {"ok": False, "error": "rate"}, 429
    raced = rate_limiter.preflight_charge(netid, ip)  # atomic charge, re-validated — closes the admission race
    if raced == "cooldown":
        return {"ok": True}
    if raced == "limited":
        return {"ok": False, "error": "rate"}, 429
    threading.Thread(target=_run_preflight, args=(netid,), daemon=True,
                     name="srm-preflight").start()
    log_with_kv(log_auth, logging.DEBUG, "preflight start", netid=netid, ip=ip)
    return {"ok": True}

def api_login_progress():
    # audit: GET put netid in the URL (access logs, history, referrers).
    # Mid-login, session auth can't apply — the body keeps it out of logs.
    # audit run-1 (#13): reads are keyed by the unforgeable attempt token
    # minted in this browser's login form, not the bare netid — guessing an
    # account name now yields 400/empty, never presence or stage. The read
    # path is also per-IP capped (30/60s) like preflight.
    data = request.get_json(silent=True) or {}
    attempt = str(data.get("attempt", "")).strip()
    if not attempt or not attempt.isalnum() or len(attempt) > 64:
        return {"step": "", "pct": 0, "error": "invalid attempt token"}, 400
    if not progress.read_ok(_client_ip()):   # 30 reads/60s per IP (was unlocked)
        return {"step": "", "pct": 0, "error": "rate"}, 429
    step, pct = progress.read(attempt)   # prunes the key when stale
    return {"step": step, "pct": pct}

# ── Timetable API ───────────────────────────────────────────────
def _load_personal(netid):
    """personal_details_json for a netid; corrupt/missing row -> {}.

    One shared decode — was copy-pasted (with a different comment) across the
    three timetable routes."""
    try:
        r = user_personal(netid)
        v = json.loads(r[0]) if r and r[0] else {}
        return v if isinstance(v, dict) else {}
    except Exception as e:  # corrupt/unreadable row → proceed with empty personal details
        log.warning("corrupt personal_details_json netid=%s: %r", netid, e)
        return {}


def api_get_timetable():
    netid = get_current_user()
    if not netid: return {"ok": False, "error": "not logged in"}, 401
    personal = _load_personal(netid)
    gk = _group_key(personal)
    if not gk: return {"ok": True, "slots": {}, "subjects": [], "group_key": None}
    gid = group_id(gk)
    if gid is None: return {"ok": True, "slots": {}, "subjects": [], "group_key": gk}
    slots = {}
    for r in group_slots(gid):
        slots[str(r[0]) + "-" + str(r[1])] = {"code": r[2], "name": r[3], "location": r[4] or ""}
    subjects = [{"code":r[0], "name":r[1], "credits":r[2], "custom":bool(r[3])}
                for r in group_subjects(gid)]
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

def api_timetable_history():
    """Edit log for the caller's own group (classmates share group_key)."""
    netid = get_current_user()
    if not netid: return {"ok": False, "error": "not logged in"}, 401
    personal = _load_personal(netid)
    gk = _group_key(personal)
    if not gk: return {"ok": True, "entries": []}
    gid = group_id(gk)
    if gid is None: return {"ok": True, "entries": []}
    entries = []
    for r in edit_log_entries(gid):
        try:
            changes = json.loads(r[3] or "[]")
        except Exception as e:
            log.warning("corrupt timetable edit changes_json: %r", e)
            changes = []
        entries.append({"netid": r[0], "name": r[1] or "", "at": r[2], "changes": changes})
    return {"ok": True, "entries": entries}

def api_save_timetable():
    netid = get_current_user()
    if not netid: return {"ok": False, "error": "not logged in"}, 401
    if not _tt_editor_enabled():
        return {"ok": False, "error": "timetable editor is archived — the portal "
                "owns the timetable (set TIMETABLE_EDITOR=enabled to re-enable)"}, 403
    data = request.get_json(silent=True) or {}
    slots = data.get("slots", {})
    custom = data.get("custom_subjects", [])
    personal = _load_personal(netid)
    gk = _group_key(personal)
    if not gk: return {"ok": False, "error": "could not determine group"}, 400
    with transaction():
        upsert_group(gk, personal.get("Program", ""), int(personal.get("Batch", 0)),
                     _semester_int(personal.get("Semester", "")), personal.get("Section", ""))
        gid = group_id(gk)
        for sub in custom:
            upsert_subject(gid, sub["code"], sub["name"], 0, 1)
        # audit feature: diff old vs new BEFORE the delete-and-replace so the
        # shared timetable's edit log records exactly who changed what.
        old_rows = {f"{r[0]}-{r[1]}": {"code": r[2] or "", "name": r[3] or "",
                                       "location": r[4] or ""}
                    for r in group_slots(gid)}
        old_slots = {k: {"code": v["code"], "name": v["name"]} for k, v in old_rows.items()}
        new_slots = {}
        for key, val in slots.items():
            if val and len(key.rsplit("-", 1)) == 2:
                new_slots[key] = {"code": str(val.get("code", "")), "name": str(val.get("name", ""))}
        changes = _tt_diff(old_slots, new_slots)
        rows = []
        for key, val in new_slots.items():
            day, period = key.rsplit("-", 1)
            # fix 2026-10-05: the editor has no location field, so a blind
            # delete+re-insert used to wipe `location` for the WHOLE group on
            # every save (proved: 'Test Hall' -> ''). Carry the room forward
            # while the slot's subject CODE is unchanged; a swapped subject
            # drops the old room (it belonged to the old class).
            prev = old_rows.get(key)
            loc = prev["location"] if prev and prev["code"] == val["code"] else ""
            rows.append((day, int(period), val["code"], val["name"], loc))
        replace_group_slots(gid, rows, "manual")
        # rows and official_times must never disagree: these rows are manual, so
        # drop the official stamp (next sync rewrites rows+stamp together)
        clear_official_stamp(gid)
        if changes:  # no-op saves stay out of the log
            append_edit_log(gid, netid, str(personal.get("Student Name", "")),
                            json.dumps(changes, ensure_ascii=False))
    return {"ok": True}

def marks_tag():
    """Confirm (or refuse) the IE-1/IE-2 tag of one component. Server-side only:
    the scaled max comes from the live portal row, never from the form.
    The tag key is class-scoped, so one student's confirmation applies to the
    whole class — persisted for the future GPA predictor. Redirects back to the
    marks tab (#marks restores it)."""
    netid = get_current_user()
    if not netid:
        return redirect("/login")
    # fetch callers (dash.js soft refresh) ask for JSON and morph in place;
    # a plain form POST keeps the redirect round-trip as the no-JS fallback
    wants_json = request.accept_mimetypes.best == "application/json"
    def _back(err=None):
        if wants_json:
            return {"ok": not err, **({"error": err} if err else {})}
        return redirect("/#marks")
    form = request.form
    code = (form.get("code") or "").strip()[:32]
    name = (form.get("component") or "").strip()[:32]
    role = form.get("role")
    if role not in ("IE-1", "IE-2", "none") or not code or not name:
        return _back("Invalid component")
    row = user_marks_personal(netid)
    try:
        marks = json.loads(row[0]) if row and row[0] else []
        personal = json.loads(row[1]) if row and row[1] else {}
    except (ValueError, TypeError):
        marks, personal = [], {}
    scaled = next((cp.get("max", 0.0) for s in marks if s.get("code") == code
                   for cp in s.get("components", []) if cp.get("name") == name), 0.0)
    if not scaled:
        return _back("Component not found")
    # raw_max: the marks the component stands for on paper (50 / 60); 'none'
    # keeps it NULL — the row exists either way, which is what 'confirmed' means.
    raw = {"IE-1": 50.0, "IE-2": 60.0}.get(role)
    key = f"{_class_key(personal, netid)}|{code}|{name}"
    upsert_component_tag(key, role, raw, scaled, netid, int(time.time()))
    return _back()

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
    out = {}
    for r in users_group_keys(netids):
        try:
            pd = json.loads(r[1]) if r[1] else {}
        except (ValueError, TypeError):
            pd = {}
        out[r[0]] = _group_key(pd)
    return out


def _push_timetable(group_keys):
    """{group_key: {day: {period: {code,name,location}}}} for the given groups."""
    group_keys = [g for g in group_keys if g]
    if not group_keys:
        return {}
    gids = group_ids_for(group_keys)
    out = {}
    if gids:
        for r in slots_for_groups(list(gids)):
            day = out.setdefault(gids[r[0]], {}).setdefault(r[1], {})
            day[r[2]] = {"code": r[3] or "", "name": r[4] or "", "location": r[5] or ""}
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
    # per-type pref: a muted account is dropped before due-calc (its classes
    # are never computed, so a mute can't leak into stats or claims)
    subs_rows = [s for s in subs_rows if s["notify_reminders"]]
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
    # audit R1: push_sent_log retention — 30d covers the window the dashboards
    # read. usage_events retention moved to _prune_usage_events (env-config,
    # default 365d, at most once a day) so a per-minute tick stops paying it.
    try:
        prune_push_sent_log(time.strftime("%Y-%m-%d", time.gmtime(time.time() - 30 * 86400)))
    except Exception as e:
        log_push.warning("log retention prune failed: %r", e)
    stats["took_ms"] = int((time.monotonic() - t0) * 1000)
    log_with_kv(log_push, logging.INFO, "push tick", **stats)
    return {"ok": True, **stats}


# observability: dead-man signal for the tick scheduler. The gauge stamps
# the epoch of the last SUCCESSFUL tick (0 = never); Prometheus alerts when
# it goes >5m stale (OpenSRMPushTickStale), which is what closes the
# runbook's dead-man gap — a dead Hermes cron job is otherwise silent from
# inside the app. Counter by outcome pairs with it: ok should sit at ~1/min,
# error means _run_tick raised (the 5xx chain already pages on that).
_PUSH_TICK_LAST_OK = {"ts": 0.0}


def _push_tick_last_ok_ts():
    return _PUSH_TICK_LAST_OK["ts"]


metrics.gauge("opensrm_push_tick_last_success_timestamp_seconds", _push_tick_last_ok_ts)


def push_tick():
    """The every-minute tick scheduler (the Hermes cron job opensrm-push-tick;
    cron-job.org is the kept alternative scheduler, see docs/push.md) fires
    this. Secret header, no session; wrong/missing secret => bare 401 with
    no detail (nothing to probe)."""
    conf = _push_conf()
    got = request.headers.get(PUSH_TICK_HEADER, "")
    # audit run-1 (#16): hmac.compare_digest raises TypeError on non-ASCII
    # str — one byte >= 0x80 in the header turned the documented bare 401
    # into an unauthenticated 500 + ERROR alert. Compare UTF-8 bytes: a
    # non-ASCII header can never equal an ASCII secret; a lone surrogate
    # raises UnicodeEncodeError -> mismatch (fail closed).
    try:
        tick_ok = hmac.compare_digest(got.encode("utf-8"),
                                       conf["tick_secret"].encode("utf-8"))
    except UnicodeEncodeError:
        tick_ok = False
    if not conf["tick_secret"] or not tick_ok:
        log_with_kv(log_push, logging.WARNING, "tick auth failed", ip=_client_ip())
        return _bare(401, "push tick auth failed — secret missing or wrong")
    # auth-failed ticks deliberately do NOT touch the dead-man signal: an
    # unauthenticated prober must never be able to move a metric.
    try:
        res = _run_tick(conf=conf)
    except Exception:
        metrics.inc("opensrm_push_tick_total", outcome="error")
        raise
    metrics.inc("opensrm_push_tick_total", outcome="ok")
    _PUSH_TICK_LAST_OK["ts"] = time.time()
    return res


# ── Internal metrics (Prometheus text, secret-header auth) ──────────
METRICS_HEADER = "X-Metrics-Token"

def healthz():
    """Container healthcheck probe: DB round-trip only.

    No session, no portal contact — a probe that touched the portal would
    spend login attempts and log noise every interval (the 2026-10-07 audit
    found healthcheck traffic was 86% of opensrm.log). The compose
    healthcheck and scripts/post_deploy.sh both point here; _log_request
    demotes it to DEBUG alongside the Python-urllib UA for the same reason.
    Body stays two words: it is served through the tunnel too.
    """
    try:
        ping()
    except Exception as exc:            # pragma: no cover - failure arm below
        log_with_kv(log_http, logging.ERROR, "healthz failed", error=type(exc).__name__)
        return {"status": "error"}, 503
    return {"status": "ok"}


def internal_metrics():
    """In-process sync/portal counters as Prometheus text (app/metrics.py).

    Same auth contract as /internal/push/tick: METRICS_SECRET unset -> the
    endpoint is OFF; wrong/missing/non-ASCII header -> bare 401 with nothing
    to probe (hmac.compare_digest over UTF-8 bytes, fail closed)."""
    secret = os.environ.get("METRICS_SECRET", "").strip()
    got = request.headers.get(METRICS_HEADER, "")
    try:
        tok_ok = hmac.compare_digest(got.encode("utf-8"), secret.encode("utf-8"))
    except UnicodeEncodeError:
        tok_ok = False
    if not secret or not tok_ok:
        log_with_kv(log_metrics, logging.WARNING, "metrics auth failed", ip=_client_ip())
        return _bare(401, "metrics auth failed — secret missing or wrong")
    return metrics.render(), 200, {"Content-Type": "text/plain; version=0.0.4"}


# ── Web push: user endpoints (JSON, session auth, 401 style) ──────────
# DB-backed rate limits only (process-local dicts die on serverless):
# subscribe 10/hour/netid, test push 3/hour/netid, receipts 30/hour/netid.

def _push_401():
    return {"ok": False, "error": "not logged in"}, 401


def _push_bad(msg, code=400):
    return {"ok": False, "error": msg}, code


# audit run-1 (#4): client-supplied push endpoints are fetched server-side by
# pywebpush — scheme+length validation alone made that an SSRF + upstream-status
# oracle. Known push-service host suffixes only; re-enforced at send time.
_PUSH_HOST_SUFFIXES = ("fcm.googleapis.com", "web.push.apple.com",
                       "updates.push.services.mozilla.com")
MAX_PUSH_SUBSCRIPTIONS = 8   # per netid — one account, a handful of devices


def _push_endpoint_allowed(endpoint):
    from urllib.parse import urlparse
    host = (urlparse(endpoint).hostname or "").lower()
    # suffix check only: a DNS pre-check adds latency + a TOCTOU gap and
    # blocks nothing the suffix list doesn't (attackers can't own a suffix)
    return any(host == s or host.endswith("." + s) for s in _PUSH_HOST_SUFFIXES)


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
                              "notify_reminders": bool(row["notify_reminders"]),
                              "notify_exams": bool(row["notify_exams"]),
                              "created_at": row["created_at"]} if row else None),
            "lead_choices": list(push_calc.LEAD_CHOICES)}


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
    if not _push_endpoint_allowed(endpoint):
        # audit run-1 (#4): the server would POST to whatever host this names
        return _push_bad("invalid subscription — not a known push service")
    if push_store.count_events(netid, "subscribe", int(time.time()) - 3600) >= 10:
        return _push_bad("too many subscription updates (10/hour)", 429)
    if push_store.count_subscriptions(netid) >= MAX_PUSH_SUBSCRIPTIONS:
        # audit run-1 (#11): per-account row cap — N rows = N duplicate sends
        return _push_bad(f"too many registered devices ({MAX_PUSH_SUBSCRIPTIONS})", 429)
    row = push_store.upsert_subscription(netid, endpoint, p256dh, auth,
                                         str(d.get("ua_label", ""))[:64])
    push_store.record_event(netid, "subscribe", _endpoint_hash(endpoint))
    return {"ok": True, "lead_minutes": row["lead_minutes"],
            "endpoint_hash": _endpoint_hash(endpoint)}


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


def push_settings():
    netid = get_current_user()
    if not netid:
        return _push_401()
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return _push_bad("invalid request — Content-Type must be application/json")
    lead = d.get("lead_minutes")
    enabled = d.get("enabled")
    n_rem, n_exm = d.get("notify_reminders"), d.get("notify_exams")
    if lead is None and enabled is None and n_rem is None and n_exm is None:
        return _push_bad("nothing to update")
    if lead is not None and lead not in push_calc.LEAD_CHOICES:
        return _push_bad(f"lead_minutes must be one of {', '.join(map(str, push_calc.LEAD_CHOICES))}")
    if enabled is not None and not isinstance(enabled, bool):
        return _push_bad("enabled must be true or false")
    if n_rem is not None and not isinstance(n_rem, bool):
        return _push_bad("notify_reminders must be true or false")
    if n_exm is not None and not isinstance(n_exm, bool):
        return _push_bad("notify_exams must be true or false")
    n = push_store.set_settings(netid, lead_minutes=lead, enabled=enabled,
                                notify_reminders=n_rem, notify_exams=n_exm)
    if n == 0:
        return _push_bad("no subscription for this account", 404)
    return {"ok": True, "updated": n}


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
    # audit run-1 (#4): upstream status code must not be reflected — it turns
    # the server into a status oracle for whatever endpoint was stored.
    # Full detail goes to the log line above.
    return _push_bad("push service error — try again later", 502)


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


# ── Account deletion ─────────────────────────────────────────────────
# Ephemeral per-netid window (3/hour, same shape as _login_attempts): the
# route needs no portal contact, so memory is the whole limiter — entries
# exist only for accounts that POSTed a delete. ponytail: a stale entry is
# never a safety issue (success removes the account, so a later POST 401s).
_delete_attempts = {}   # netid -> [ts, ...]  account-delete POSTs, 1-hour window


def _check_delete_rate(netid):
    now = time.time()
    if len(_delete_attempts) > _RATE_CAP:   # blowout guard, same as _check_rate
        _delete_attempts.clear()
    kept = [t for t in _delete_attempts.get(netid, []) if now - t < 3600]
    if len(kept) >= 3:
        _delete_attempts[netid] = kept
        return False
    kept.append(now)
    _delete_attempts[netid] = kept
    return True


@require_login
def account_delete():
    """Erase everything this app stores about the signed-in account
    (docs/privacy.md). One opensrm.auth line with per-table counts.

    No portal contact: sessions die locally, the SRM portal is never told
    anything, and no portal attempt is spent. Schema coverage (every column
    that can hold a netid) is enforced by tests/test_account_delete.py,
    which seeds the live schema and fails when a later migration adds a
    netid column this route does not clear.
    """
    netid = get_current_user()
    if not netid:
        return {"ok": False, "error": "not logged in"}, 401
    if not _check_delete_rate(netid):
        return {"ok": False, "error": "too many delete attempts — try again later"}, 429
    counts = delete_account_rows(netid)
    log_with_kv(log_auth, logging.INFO, "account delete ok", netid=netid,
                ip=_client_ip(),
                counts=",".join(f"{k}={v}" for k, v in counts.items()))
    resp = make_response({"ok": True})
    resp.delete_cookie("srm_session", secure=_cookie_secure(),
                       httponly=True, samesite="Lax")
    return resp


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
    # audit run-1 (#15): SameSite=Lax still SENDS the cookie on a cross-site
    # TOP-LEVEL GET, so one link/meta-refresh logged the victim out. Reject
    # cross-site fetch-metadata the same way speculation is rejected;
    # absent Sec-Fetch-Site (older browsers) falls through to Lax (the
    # header is a forbidden header name — attacker pages cannot strip it).
    sfs = request.headers.get("Sec-Fetch-Site", "").lower()
    origin = request.headers.get("Origin", "")
    if sfs == "cross-site" or (origin and origin != "null"
                               and not origin.endswith(request.host)):
        log_with_kv(log_auth, logging.INFO, "logout ignored",
                    reason="cross-site", ip=_client_ip())
        resp = make_response(redirect("/login"))
        resp.headers["Cache-Control"] = "no-store"
        return resp
    token = request.cookies.get("srm_session")
    netid = None
    if token:
        digest = hashlib.sha256(token.encode()).hexdigest()
        netid = pop_cookie(digest)
    # incident logging: real logouts previously left no auth line at all —
    # attribution had to be reconstructed from HTTP 302s + cookie joins.
    log_with_kv(log_auth, logging.INFO, "logout ok", netid=netid or "-",
                ip=_client_ip())
    resp = make_response(redirect("/login"))
    # audit F2 fix: same flags on the clearing path — recon saw a bare
    # 'Secure; Path=/' Set-Cookie here because delete_cookie didn't inherit them
    resp.delete_cookie("srm_session", secure=_cookie_secure(), httponly=True, samesite="Lax")
    return resp

# ── Application factory ─────────────────────────────────────────────
# Import used to be the boot script: data dir + secret at the top, the
# Flask object right below them, migrations + OCR prewarm at the file
# bottom. All of it now lives in create_app so a second app (tests) can
# boot with its own data dir while the module-level `app` below keeps
# `gunicorn app.app:app` (Dockerfile CMD) and the set-DATA_DIR-before-
# import test contract working unchanged.

def create_app(config=None):
    """Build one OpenSRM instance end to end.

    config: an AppConfig (app/config.py); None -> AppConfig.from_env(),
    which reads the boot env exactly once per app. Side effects live
    here and only here: data-dir + secret-key creation, schema
    migrations, and the ddddocr prewarm thread (config.prewarm_ocr,
    OCR_PREWARM=0 opts out — tests take it).
    """
    if config is None:
        config = AppConfig.from_env()
    os.makedirs(config.data_dir, exist_ok=True)
    # audit 2026-09-27: Flask's built-in /static route stays disabled — it
    # registered the SAME rule as static_no_cache (whose rule now lives in
    # app/blueprints/internal.py) and won the match (registered first), so
    # that function never ran anywhere: no Service-Worker-Allowed header, no
    # intended cache policy. Nothing calls url_for('static'), so removal is
    # safe.
    a = Flask(__name__, static_folder=None)
    a.secret_key = _load_secret(config.secret_path)
    a.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # audit: bound request bodies
    # per-app resolution targets for db.py (_db_path) and _active_data_dir()
    a.config["DATA_DIR"] = config.data_dir
    a.config["DB_PATH"] = config.db_path
    # one request-scoped connection per request, closed when the app context
    # pops — including when a handler raises (app/db.py close_db).
    a.teardown_appcontext(close_db)
    _init_blobatar(a)  # GET /avatar/<name> + `blobatar` Jinja filter
    # hooks in the order the decorators used to register them
    a.before_request(_log_request_start)
    a.before_request(_cross_site_guard)
    a.errorhandler(Exception)(_unhandled_error)
    a.after_request(_log_request)
    a.after_request(_security_headers)
    # Route tables live in app/blueprints/ (auth, dashboard, marks, timetable,
    # push, feedback, internal), one module per area. The blueprints are
    # FlatBlueprints: endpoints keep their bare names (`login`, not
    # `auth.login`), so the url_map — paths, methods, endpoint names, view
    # functions — stays byte-identical to the flat pre-split app (dump:
    # scripts/url_map_dump.py; pinned: tests/test_app_factory.py). Imported
    # here because each blueprint pulls its view functions from THIS module.
    from .blueprints.auth import bp as auth_bp
    from .blueprints.dashboard import bp as dashboard_bp
    from .blueprints.feedback import bp as feedback_bp
    from .blueprints.internal import bp as internal_bp
    from .blueprints.marks import bp as marks_bp
    from .blueprints.push import bp as push_bp
    from .blueprints.timetable import bp as timetable_bp

    for _bp in (auth_bp, dashboard_bp, marks_bp, timetable_bp,
                push_bp, feedback_bp, internal_bp):
        a.register_blueprint(_bp)
    # boot the schema on THIS app's DB: the app context below is what points
    # db.connect() at config.db_path (per-app resolution in app/db.py).
    with a.app_context():
        init_db()
    if config.prewarm_ocr:
        # pre-warm ddddocr so the first real scrape isn't +3s cold (was a
        # module-level thread at import time)
        threading.Thread(target=get_solver, daemon=True, name="srm-captcha-prewarm").start()
    a.jinja_env.globals["asset"] = asset  # versioned /static/ URLs (DESIGN §10.16)
    return a


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

