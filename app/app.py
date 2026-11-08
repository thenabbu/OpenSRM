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
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime  # noqa: F401 — re-exported: tests pin the clock via A.datetime

# timetable_html is now defined locally (SQLite-backed)
from flask import Flask, g, make_response, redirect, render_template, request
from werkzeug.exceptions import HTTPException

from . import metrics, push_calc, push_send, push_store  # noqa: F401 — tests stub A.push_send
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
    weekly_slot_counts,  # noqa: F401 — re-exported from app.app
    write_user_sync,
)
from .logging_setup import log_with_kv, setup_logging
from .migrations import migrate_db
from .portal.parsers.attendance import parse_attendance  # noqa: F401 — re-exported from app.app
from .portal.parsers.common import (
    MONTHS,  # noqa: F401 — re-exported from app.app
    ROMAN,  # noqa: F401 — re-exported from app.app
    _cells,  # noqa: F401 — re-exported from app.app
    _class_key,
    _group_key,
    _program_short,  # noqa: F401 — re-exported from app.app
    _semester_int,  # noqa: F401 — re-exported from app.app
)
from .portal.parsers.exams import (
    parse_exam_schedule,  # noqa: F401 — re-exported from app.app
    parse_exam_timetable,  # noqa: F401 — re-exported from app.app
)
from .portal.parsers.feedback import _fb_plan
from .portal.parsers.marks import (
    _DATE_CELL_RE,  # noqa: F401 — re-exported from app.app
    _parse_component_inner,  # noqa: F401 — re-exported from app.app
    parse_marks,  # noqa: F401 — re-exported from app.app
)
from .portal.parsers.personal import parse_personal_details  # noqa: F401 — re-exported from app.app
from .portal.parsers.timetable import (
    DAY_ORDER,  # noqa: F401 — re-exported from app.app
    _tt_norm_clock,  # noqa: F401 — re-exported from app.app
    parse_timetable,  # noqa: F401 — re-exported from app.app
)
from .scope.ops import enabled_features  # noqa: F401 — re-exported from app.app
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
from .views.academics import (
    academics_view,  # noqa: F401 — re-exported from app.app
)
from .views.attendance import (
    ATTENDANCE_DECIMALS,  # noqa: F401 — re-exported from app.app
    ATTENDANCE_TARGET,  # noqa: F401 — re-exported from app.app
    ATTENDANCE_WARN,  # noqa: F401 — re-exported from app.app
    WORKING_DAYS,  # noqa: F401 — re-exported from app.app
    _absences_view,  # noqa: F401 — re-exported from app.app
    _attendance_budgets,  # noqa: F401 — re-exported from app.app
    _exam_stop,  # noqa: F401 — re-exported from app.app
    _safe_int,  # noqa: F401 — re-exported from app.app
    _status_for_pct,  # noqa: F401 — re-exported from app.app
    _title_case,  # noqa: F401 — re-exported from app.app
    _weekdays,  # noqa: F401 — re-exported from app.app
    hourwise_view,  # noqa: F401 — re-exported from app.app
)
from .views.campus import campus_view  # noqa: F401 — re-exported from app.app
from .views.fees import _fees_view  # noqa: F401 — re-exported from app.app
from .views.layout import (
    LAYOUT,  # noqa: F401 — re-exported from app.app
    WIDGETS,  # noqa: F401 — re-exported from app.app
)
from .views.marks import (
    _derive_ie,  # noqa: F401 — re-exported from app.app
    _fmt_date,  # noqa: F401 — re-exported from app.app
    _fmt_max,  # noqa: F401 — re-exported from app.app
    _fmt_score,  # noqa: F401 — re-exported from app.app
    _marks_summary,  # noqa: F401 — re-exported from app.app
    _marks_view,  # noqa: F401 — re-exported from app.app
)
from .views.profile import (  # noqa: F401 — re-exported from app.app
    merge_personal,
    scope_profile,
)
from .views.ticker import (
    _now_next_from_slots,  # noqa: F401 — re-exported from app.app
    _today_ticker,  # noqa: F401 — re-exported from app.app
)

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


from blobatar.flask import init_app as _init_blobatar

setup_logging()
log = logging.getLogger("opensrm")
log_http = logging.getLogger("opensrm.http")
log_auth = logging.getLogger("opensrm.auth")
log_portal = logging.getLogger("opensrm.portal")
log_db = logging.getLogger("opensrm.db")
log_metrics = logging.getLogger("opensrm.metrics")

# ── Crypto: passwords at rest ──────────────────────────────────────
# Moved to app/crypto.py (leaf module: it imports nothing from app.py), so
# extracted modules can encrypt/decrypt without importing this facade.
from .crypto import (  # noqa: E402,F401 — re-exported
    _active_data_dir,
    _load_secret,
    decrypt_pw,
    encrypt_pw,
    fernet_keys,
    get_fernet,
    reset_fernet,
)

_MISSING = object()  # sentinel: distinguishes 'absent' from 'bound to None'


class _FacadeModule(sys.modules[__name__].__class__):
    """Make the facade's mutable globals proxies for their real homes.

    A `from .crypto import _fernet` is a one-time copy: `app._fernet = None`
    would rebind only THIS module's name while crypto.get_fernet() kept its own
    cached cipher — the test suite's reset idiom silently stopped working
    (caught by test_fernet_rotation: 25/39). Proxying the attribute keeps
    `app._fernet = None` meaningful no matter which side sets it.

    The same copy problem hits every mutable name that moved to an extracted
    module and is still rebound by tests/ops on `app`, so they all live here:

      _fernet        -> app.crypto          (cipher cache reset)
      CF_EDGE_SECRET -> app.auth            (edge-trust flag)
      _scrape_lock   -> app.portal_control  (permit pool size in tests)

    Rule for the next extraction: if a name is MUTABLE and a caller might
    rebind it on `app`, it belongs in _PROXY. Immutable constants and
    functions do not — a copy of a constant is harmless.
    """

    _PROXY = {
        "_fernet": "app.crypto",
        "CF_EDGE_SECRET": "app.auth",
        "_scrape_lock": "app.portal_control",
        "TIMETABLE_SOURCE": "app.static_data",
        # The seam every sync test stubs: `A.fetch_attendance = fake` must reach
        # app/scraper.py (where it is defined) and app/routes_sync.py (which
        # calls it). Proxying keeps those in step whichever side is written.
        "fetch_attendance": "app.scraper",
    }

    def __getattr__(cls, name):
        target = cls._PROXY.get(name)
        if target:
            import sys as _s
            return getattr(_s.modules[target], name)
        raise AttributeError(f"module {cls.__name__!r} has no attribute {name!r}")

    def __setattr__(cls, name, value):
        """Rebind a facaded name EVERYWHERE it is bound.

        `A._SYNC_FLIGHT_WAIT_S = 0.2` in a test used to update only app.app's
        dict, so the moved reader kept the old value and exercised the wrong
        path (test_sync_cache: the joiner never timed out). Setting the facade
        name now fans out to every loaded app module holding that binding, so
        one idiom works for every extracted name without a per-name list. That
        is the fix for the whole class, not the sixth instance of it.
        """
        target = cls._PROXY.get(name)
        if target:
            import sys as _s
            setattr(_s.modules[target], name, value)
            return
        super().__setattr__(name, value)
        if not name.startswith("__"):
            cls._fanout(name, value)

    def _fanout(cls, name, value):
        """Copy a facade rebind into every loaded app module that holds it.

        Only re-exported names are copied, and never module objects. `A.db = fake`
        used to reach app.db and overwrite its db() function — a semantic change
        from HEAD that no test exercises today but that would bite a future one.
        Restricting to the re-export set is what makes that safe, because a type
        test cannot: app.db.db is a function, exactly like A._run_tick.

        Known ceiling: a module imported AFTER the rebind does not receive it
        (ponytail: late-import hole — the modules that need rebinds are all
        imported by app.py before the facade exists, so nothing hits it today).
        """
        import sys as _s
        import types as _t
        if isinstance(value, _t.ModuleType):
            return
        for modname, mod in list(_s.modules.items()):
            if mod is None or not modname.startswith("app") or modname == __name__:
                continue
            d = getattr(mod, "__dict__", None)
            if d is None or d.get(name, _MISSING) is _MISSING:
                continue
            # Never fan into app/db.py: `from .db import db` re-exports the db()
            # FUNCTION, so a type test cannot distinguish it from A._run_tick.
            # On main `A.db = X` left app.db.db alone (verified against
            # origin/main); keeping that exact behaviour is the whole point.
            if modname == "app.db" and name == "db":
                continue
            if isinstance(d[name], _t.ModuleType):
                continue
            # Only names the facade actually RE-EXPORTS are fanned out.
            # A name that merely happens to also exist in another module is
            # left alone — that is what makes `A.db = fake` safe: app.db has a
            # db() FUNCTION (not a module), so a type test cannot tell it from
            # A._run_tick, but it is not in _PROXY or any re-export block.
            if name not in cls._FANNED and name not in cls._PROXY:
                # _FANNED = re-exported names; _PROXY = mutable globals. A name
                # that is neither is not facade state, so leave every module
                # alone (`A.something = x` must not reach into a submodule).
                return
            d[name] = value


def _build_fanned_names():
    """Names the facade re-exports from app submodules — the ONLY ones whose
    rebind is fanned out. Derived by parsing this file, so adding an extraction
    cannot silently shrink the set.

    `from . import db` / `from . import metrics` are EXCLUDED: they bind a
    module, and `A.db = fake` must never reach app.db's own db() function.
    Only `from .X import name` (an explicit name pulled out of a submodule)
    counts.
    """
    import ast as _a
    names = set()
    for node in _a.walk(_a.parse(open(__file__).read())):
        if isinstance(node, _a.ImportFrom) and node.level and node.module:
            for al in node.names:
                if al.name != "*":
                    names.add(al.asname or al.name)
    return frozenset(names)


_FacadeModule._FANNED = _build_fanned_names()

sys.modules[__name__].__class__ = _FacadeModule

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

# Portal constants + captcha solver: app/captcha.py (leaf). Re-exported.
# Session identity lives in app/auth.py (get_current_user has 18 consumers —
# it belongs under this facade, not inside it). Re-exported for callers.
from .auth import (  # noqa: E402,F401 — re-exported
    # CF_EDGE_SECRET is deliberately NOT imported: a copy would land in this
    # module's __dict__ and shadow the _FacadeModule proxy, so
    # `A.CF_EDGE_SECRET = x` would rebind the copy and _behind_cf() would keep
    # reading the old value. The proxy in _FacadeModule forwards it to auth.
    SESSION_MAX_AGE,
    _behind_cf,
    _cookie_secure,
    get_current_user,
    make_session_token,
)
from .captcha import CAPTCHA_JS, LOGIN_URL, get_solver, solve_captcha_b64  # noqa: E402,F401

# Request identity lives in app/reqctx.py. Re-exported for callers.
from .reqctx import _client_ip  # noqa: E402,F401 — re-exported

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

# ── Portal control plane ────────────────────────────────────────────
# Queue, scrape semaphore, portal token budget, cookie session cache and
# the per-request sync context all live in app/portal_control.py.
from .portal_control import (  # noqa: E402,F401 — re-exported
    _PORTAL_AUTH_FLOOR,
    _PORTAL_CAP,
    _PORTAL_IP_CAP,
    _PORTAL_PREFLIGHT_CAP,
    _SESSION_CACHE_TTL,
    PIPELINE_DEADLINE,
    SYNC_MAX_CONCURRENCY,
    SYNC_QUEUE_WAIT_DEFAULT,
    _check_portal_budget,
    _clear_session,
    _load_session,
    _portal_attempts,
    _portal_attempts_auth,
    _portal_attempts_pf,
    _portal_fail_once,
    _portal_ip,
    _pw_lock,
    _queue_cond,
    _QueueWaiter,
    _save_session,
    _scrape_admit,
    _scrape_lock,
    _scrape_release,
    _sync_ctx,
    _sync_max_concurrency,
    _sync_queue,
    _sync_queue_depth,
    _sync_queue_wait_s,
    _SyncContext,
)

# (portal scraper import moved to the bottom of this file — it needs the
# names defined below to exist first; see the end of the module.)
# ── View model ─────────────────────────────────────────────────────
# ── Attendance view model ───────────────────────────────────────────
# Row shaping for the attendance page lives in app/views/attendance.py.
from .views.attendance import (  # noqa: E402,F401 — re-exported
    _BAND_BAR,
    _attendance_index,
    _bare,
    _bunk_counts,
    _bunk_line,
    _course_view,
    _join_attendance,
    _month_view,
    _norm_subject,
    _pct_trunc,
    _weekly_slots,
)


def _log_request_start():
    request._start_time = time.monotonic()

def _route_label():
    """Bounded label for the request metric: the matched rule's pattern
    ('/api/marks/<netid>') rather than the raw path, so cardinality is the
    route table (~26 rules), not one series per netid. Unmatched requests
    fall back to the status class + 'unmatched' — a bot spray of random URLs
    must not create a series each."""
    rule = request.url_rule
    if rule is None:
        return "<unmatched>"
    return str(rule.rule)

def _log_request(resp):
    duration_s = time.monotonic() - getattr(request, "_start_time", time.monotonic())
    duration_ms = int(duration_s * 1000)
    # every request counts, including the healthcheck: the compose probe is
    # 66k lines of log noise but it is a REAL latency sample, and the metric
    # path is cheap (one dict increment behind a lock).
    metrics.inc("opensrm_http_requests_total",
                route=_route_label(), method=request.method,
                status_class=f"{resp.status_code // 100}xx")
    metrics.observe("opensrm_http_request_duration_seconds", duration_s,
                    route=_route_label(), method=request.method)
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

# Edge/proxy trust (Origin host check + X-Forwarded-Host) lives in app/edge.py.
from .edge import (  # noqa: E402,F401 — re-exported
    _origin_host_guard,
    _origin_matches_host,
    _origin_matches_public,
    _public_host,
)


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
    if origin is not None and not (
            _origin_matches_host(origin, _public_host())
            or _origin_matches_public(origin)):
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

# Faculty/_hourwise view helpers are re-exported with the rest of the
# dashboard view model below (one import block, not two: a second
# early import of dashboard.py half-initialises it and cycles).


from .db import jload as _jload  # noqa: E402 — generic stored-JSON reader

# ── Routes ─────────────────────────────────────────────────
# ── SCOPE background sync ─────────────────────────────────────────────
# The SCOPE surfaces self-hide when their op holds no data, and NOTHING in
# the app ever called scope_cold_sync — so prod carried scope_json={} for
# every user and the whole SCOPE rotation was invisible in the browser.
# The fetch is background work (each SOAP op is 4-8s upstream), so it never
# runs inside a login/refresh HTTP response: it is kicked off after a
# successful login/refresh and on an authenticated dashboard visit that finds
# the blob missing or stale.
# Moved to app/scope_sync.py. Re-exported so existing importers are unchanged.
from .scope_sync import (  # noqa: E402,F401
    _scope_sync_kick_if_stale,
    _scope_sync_lock,
    _scope_sync_running,
    _scope_sync_state,
    _scope_sync_trigger,
)

# ── Timetable (SQLite-backed, per-group) ─────────────────────────
# Declarative tables (timetable slots, Tools panel) live in
# app/static_data.py — pure data, imported by the views. Re-exported.
from .static_data import (  # noqa: E402,F401 — re-exported
    SLOTS,
    TIMETABLE_TIME_OFFSETS,
    TOOLS,
)

# usage_events retention: env-configurable (USAGE_EVENTS_RETENTION_DAYS,
# default 365), pruned at most once a day by the next event — no background
# thread, no per-tick work (the old every-push-tick 90d prune moved here).
# Moved to app/usage_metrics.py. Re-exported so existing importers are unchanged.
from .usage_metrics import (  # noqa: E402,F401
    _prune_usage_events,
    _track,
    _usage_prune_last,  # noqa: F401 — mutable global, tests rebind via A
    _usage_prune_lock,
    _usage_retention_days,
    _user_label,
)

# The dashboard page (route + its view model) lives in app/views/dashboard.py.
from .views.dashboard import (  # noqa: E402,F401 — re-exported
    APP_VERSION,
    _exams_view,
    _faculty_view,
    _hourwise_data,
    _hourwise_section,
    _load_component_tags,
    _week_marks,
    index,
    panel_data,
)

# The timetable is fully portal-owned: the manual editor entry + save API are
# archived (no user input — see the Oct 2026 "portal publishes formId 10"
# decision). Escape hatch if the portal's copy ever breaks: TIMETABLE_EDITOR
# =enabled (read per-request so tests can flip it live; restart not needed).
# ── Timetable view model ────────────────────────────────────────────
# Grid, NOW hero, empty state and the rendered HTML live in
# app/views/timetable.py (with the write side, _save_timetable_group).
from .views.timetable import (  # noqa: E402,F401 — re-exported
    _budget_rows,
    _day_slots,
    _save_timetable_group,
    _teacher_groups,
    _tools_entries,
    _tt_att_sig,
    _tt_countdown,
    _tt_editor_enabled,
    _tt_empty,
    _tt_fetched_at,
    _tt_grid,
    _tt_hero,
    _tt_sig_phrase,
    timetable_html,
)


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




# ── exam event pushes (one-shot) ───────────────────────────────────────────
EXAM_EVT_TTL = 12 * 3600  # offline phones: deliver for 12 h, then drop


# Moved to app/routes_sync.py. Re-exported so existing importers are unchanged.
from .routes_sync import (  # noqa: E402,F401
    _exam_events,
    _notify_exam_events,
)


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


# asset_dist() (the Vite dist/ URL mapper) lives in app/assets_dist.py to keep
# this module under its line budget — see scripts/check_architecture.py.


# ── Typed sync results ─────────────────────────────────────────────────
# A failed sync carries a `kind`; its HTTP status comes from KIND_STATUS.
# Both live in app/errors.py (pure data — no imports), so pipeline modules
# can build a failure without importing this facade. Re-exported here.
from .errors import KIND_STATUS, sync_error, sync_status  # noqa: E402,F401 — re-exported


def login():
    if get_current_user(): return redirect("/")
    return render_template("login.html", version=APP_VERSION)

# Moved to app/routes_sync.py. Re-exported so existing importers are unchanged.
from .routes_sync import (  # noqa: E402,F401
    _SYNC_FLIGHT_WAIT_S,
    SYNC_MIN_INTERVAL_DEFAULT,
    _cached_sync_answer,
    _flights_lock,
    _last_sync_age,
    _load_personal,
    _merge_fetch_result,
    _run_preflight,
    _sync_flights,
    _sync_min_interval_s,
    _tt_diff,
    _tt_sort_key,
    api_get_timetable,
    api_login,
    api_login_preflight,
    api_login_progress,
    api_refresh,
    api_save_timetable,
    api_scope_status,
    api_timetable_history,
    persist_sync,
)


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




# observability: dead-man signal for the tick scheduler. The gauge stamps
# the epoch of the last SUCCESSFUL tick (0 = never); Prometheus alerts when
# it goes >5m stale (OpenSRMPushTickStale), which is what closes the
# runbook's dead-man gap — a dead Hermes cron job is otherwise silent from
# inside the app. Counter by outcome pairs with it: ok should sit at ~1/min,
# error means _run_tick raised (the 5xx chain already pages on that).


# ── Internal metrics (Prometheus text, secret-header auth) ──────────
# ── Health + metrics ─────────────────────────────────────────────────
# Process/DB probes and the two endpoints live in app/observability.py.
from .observability import (  # noqa: E402,F401 — re-exported
    _PUSH_TICK_LAST_OK,
    METRICS_HEADER,
    _count,
    _db_size_bytes,
    _db_stat,
    _db_wal_bytes,
    _proc_rss_bytes,
    _proc_threads,
    _push_tick_last_ok_ts,
    healthz,
    internal_metrics,
    track_session_activity,
)

# ── Web push: user endpoints (JSON, session auth, 401 style) ──────────
# DB-backed rate limits only (process-local dicts die on serverless):
# subscribe 10/hour/netid, test push 3/hour/netid, receipts 30/hour/netid.
# ── Push notifications ───────────────────────────────────────────────
# Config, the cron tick and the subscription API live in app/routes_push.py.
from .routes_push import (  # noqa: E402,F401 — re-exported
    _PUSH_HOST_SUFFIXES,
    MAX_PUSH_SUBSCRIPTIONS,
    PUSH_TICK_HEADER,
    STALE_CLAIM_S,
    TICK_DEADLINE_S,
    _db_path,
    _endpoint_hash,
    _push_401,
    _push_bad,
    _push_conf,
    _push_endpoint_allowed,
    _push_groups,
    _push_timetable,
    _run_tick,
    log_push,
    push_receipt,
    push_settings,
    push_status,
    push_subscribe,
    push_test,
    push_tick,
    push_unsubscribe,
)

# ── Tab interaction beacon ───────────────────────────────────────────
# Tabs are a client-side switch (no page load), so the server cannot see
# which one a student actually reads — every dashboard load records
# target="dashboard" and stops there. dash.js posts the tab name here on
# switch so page-level usage is measurable at all.
#
# Deliberately tiny: the response is a bare 204 with no body, the caller
# ignores it, and every failure path still returns 204 — a dropped click
# beacon must never surface as an error in a student's console.
_TAB_NAMES = frozenset({"dashboard", "attendance", "timetable", "marks",
                        "campus", "academics", "fees", "tools", "settings"})

# The fixed vocabulary for "what inside a tab did they touch". A CLOSED set is
# the whole point: `item` arrives from the browser, and an open vocabulary
# would let any client mint unlimited label values into Prometheus — the exact
# cardinality explosion the label rules exist to prevent. Anything not listed
# here is dropped by the 204-always contract. Add an entry when a new
# interactive element ships; never derive these from the DOM at runtime.
_ITEM_NAMES = frozenset({
    "attendance-graph",      # attendance chart / table toggle
    "attendance-table",
    "attendance-sort",       # per-subject sort
    "timetable-day",         # week/day view switch
    "timetable-subject",     # a subject row opened
    "marks-component",       # a component's detail expanded
    "marks-semester",        # semester selector
    "fees-breakdown",
    "academics-transcript",
    "academics-credits",
    "tools-feedback",        # feedback fill flow
    "tools-push",            # reminder settings
    "profile-card",
    "sync-button",           # the manual refresh control
    "settings-device",
})
_tab_beacon_last = {}   # netid -> monotonic ts, 2s floor per user


def track_tab():
    """POST /api/track/tab  {"tab": "<name>", "item": "<key>"} -> 204 always."""
    try:
        netid = get_current_user()
        if netid:
            d = request.get_json(silent=True)
            tab = d.get("tab") if isinstance(d, dict) else None
            if isinstance(tab, str) and tab in _TAB_NAMES:
                track_session_activity(netid)
                # per-user 2s floor: a keyboard user arrowing across the tab
                # strip fires one switch per keypress, and ten rows for one
                # intentional visit pollutes the very number being measured.
                now = time.monotonic()
                if now - _tab_beacon_last.get(netid, 0.0) >= 2.0:
                    if len(_tab_beacon_last) > _RATE_CAP:
                        # blowout guard: entries older than the floor can never
                        # suppress a future beacon, so they are safe to drop
                        stale = [k for k, v in _tab_beacon_last.items()
                                 if now - v >= 2.0]
                        for k in stale:
                            _tab_beacon_last.pop(k, None)
                    _tab_beacon_last[netid] = now
                    _track("tab_view", target=tab, user=netid)
                    metrics.observe("opensrm_tab_render_duration_seconds",
                                    max(0.0, now - getattr(request, "_start_time", now)),
                                    tab=tab)
                # Item-level interaction: what INSIDE the tab people touch.
                # Same beacon, one extra optional key — the tab floor above
                # deliberately does NOT apply, because two different cards in
                # the same tab within 2s is two real interactions. `item` is
                # validated against a fixed vocabulary (see _ITEM_NAMES) so a
                # client cannot mint label values, and the 204 contract means
                # a junk value is dropped silently rather than erroring.
                item = d.get("item") if isinstance(d, dict) else None
                if isinstance(item, str) and item in _ITEM_NAMES:
                    _track("item_view", target=item, user=netid, detail=tab)
                    metrics.inc("opensrm_item_views_total", item=item, tab=tab)
    except Exception:
        pass   # telemetry must never break the UI
    return "", 204


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
    a.before_request(_origin_host_guard)
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
    from .blueprints.panels import bp as panels_bp
    from .blueprints.push import bp as push_bp
    from .blueprints.timetable import bp as timetable_bp

    for _bp in (auth_bp, dashboard_bp, marks_bp, timetable_bp,
                push_bp, feedback_bp, internal_bp, panels_bp):
        a.register_blueprint(_bp)
    # boot the schema on THIS app's DB: the app context below is what points
    # db.connect() at config.db_path (per-app resolution in app/db.py).
    with a.app_context():
        init_db()
    if config.prewarm_ocr:
        # pre-warm ddddocr so the first real scrape isn't +3s cold (was a
        # module-level thread at import time)
        threading.Thread(target=get_solver, daemon=True, name="srm-captcha-prewarm").start()
    from app.assets_dist import asset_dist  # call-time: keeps app->assets_dist a leaf edge
    a.jinja_env.globals["asset"] = asset  # versioned /static/ URLs (DESIGN §10.16)
    # P4.1 build output (content-hashed by Vite): '' when dist/ is not built yet,
    # so the page falls back to the legacy scripts + app.css
    a.jinja_env.globals["asset_dist"] = asset_dist
    return a


# ── Portal scraper ──────────────────────────────────────────────────
# The persistent browser singletons, captcha login loop, rich fetch and
# fetch_attendance live in app/scraper.py (they share browser/loop state).
from .scraper import (  # noqa: E402,F401 — re-exported
    _browser,
    _do_login,
    _ensure_loop,
    _error_class,
    _fetch_rich_optimized,
    _get_browser,
    _get_persistent_page,
    _loop,
    _loop_thread,
    _persistent_ctx,
    _persistent_owner,
    _persistent_page,
    _pw,
    _pw_fallback_enabled,
    _pw_login_done,
    _sync_result,
    fetch_attendance,
)

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

