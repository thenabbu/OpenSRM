"""The portal scraper: one login, one fetch, one result.

Extracted from app/app.py (facade pump, phase 2). The persistent-browser
singletons, the captcha login loop, the rich fetch and the `fetch_attendance`
entry point move together because they share module-level browser/loop state —
splitting them across files would fork that state.

Re-exported from app.app, so `from app.app import fetch_attendance` (57 call
sites across app/ and tests/) keeps working.

Import shape: this module imports NOTHING from app.app at module level — its
needs live in app/captcha.py, app/portal_control.py, app/state.py, app/db.py
and the parsers. That keeps it below the facade and closes the
app -> scraper -> app cycle the first attempt created. The two names that
tests rebind at runtime (_fetch_rich_optimized, _portal_ok) are read through
`_live()` instead.

State note: `_browser`, `_loop`, `_pw`, `_persistent_*` are process-local
singletons guarded by `_pw_lock`; the app requires gunicorn -w 1.
"""
import asyncio
import json
import logging
import os
import re
import sys
import threading
import time

from . import metrics
from .captcha import CAPTCHA_JS, LOGIN_URL, solve_captcha_b64
from .db import set_cold_fetch, user_cold_fetch
from .errors import sync_error
from .portal.parsers.attendance import parse_attendance
from .portal.parsers.common import MONTHS, _cells
from .portal.parsers.marks import _parse_component_inner, parse_marks
from .portal.parsers.personal import parse_personal_details
from .portal_control import (
    PIPELINE_DEADLINE,
    _check_portal_budget,
    _clear_session,
    _load_session,
    _portal_fail_once,
    _pw_lock,
    _save_session,
    _scrape_admit,
    _scrape_release,
    _sync_ctx,
    _sync_queue_wait_s,
    _SyncContext,
)
from .reqctx import _client_ip
from .state import (
    _charge_rate,
    _check_rate,
    _netid_retry_text,
    _portal_cooldown_remaining,
    _set_progress,
)

log = logging.getLogger("opensrm")


def _live(name):
    """Read a mutable setting through the FACADE at call time.

    `from .app import _fetch_rich_optimized` binds a copy at import; tests and
    ops rebind the name on app.app (`A._fetch_rich_optimized = fake`), so a
    function-body global would keep calling the stale original. Only names a
    caller can rebind at runtime belong here.
    """
    return getattr(sys.modules["app.app"], name)


_LIVE_NAMES = frozenset({"_fetch_rich_optimized", "_portal_ok"})

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
            _live("_portal_ok")()
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
    elapsed = time.monotonic() - t0
    metrics.inc("opensrm_sync_total", pipeline=pipeline,
                result="ok" if ok else "error",
                # typed results carry kind (the KIND_STATUS vocabulary — that IS
                # the error class); the message-wording fallback covers bare
                # dicts/stubs that predate the typed results
                error="" if ok else (res.get("kind") or _error_class(res.get("error"))))
    metrics.observe("opensrm_sync_duration_seconds", elapsed, pipeline=pipeline)
    # The portal span of the sync: every return from fetch_attendance lands
    # here, so this is the ONE place the portal's own wall time is known.
    # Measured against the same t0 the total uses, so the dashboard can show
    # "portal is N% of the sync" without a second clock.
    metrics.observe("opensrm_sync_phase_duration_seconds", elapsed, phase="portal")
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
        helpers = {"portal_fail_once": _portal_fail_once, "portal_ok": _live("_portal_ok"),
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
        # _live(): tests swap A._fetch_rich_optimized to prove fallback serialization
        future = asyncio.run_coroutine_threadsafe(
            _live("_fetch_rich_optimized")(netid, password, cold=cold), loop)
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
