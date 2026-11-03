"""Sync routes: login, refresh, preflight, progress, and the timetable API.

Extracted from app/app.py (facade pump, cycle D). These are the request
handlers that drive a portal sync and serve what it produced. They stay in one
module because they share the single-flight machinery (_sync_flights) and the
same merge contract (_merge_fetch_result) — splitting them would put one
contract in two files.

The exam-event diff/notify pair moves with them: _merge_fetch_result calls
_exam_events, and api_login calls _notify_exam_events.

Imports nothing from app.app: needs resolve to app/db.py, app/state.py,
app/portal_control.py, app/scraper.py, app/usage_metrics.py, app/scope_sync.py
and the parsers. Re-exported from app.app, so the blueprints and tests that
import these view functions by name are unchanged.
"""
import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime

from flask import make_response, request

from . import metrics, push_send, push_store
from .auth import SESSION_MAX_AGE, _cookie_secure, get_current_user, make_session_token
from .crypto import decrypt_pw, encrypt_pw
from .db import (
    append_edit_log,
    clear_official_stamp,
    edit_log_entries,
    group_id,
    group_slots,
    group_subjects,
    replace_group_slots,
    transaction,
    upsert_group,
    upsert_subject,
    user_last_fetch,
    user_password,
    user_personal,
    user_sync_state,
    write_user_sync,
)
from .errors import sync_error, sync_status
from .logging_setup import log_with_kv
from .portal.parsers.common import _group_key, _semester_int
from .portal.parsers.timetable import DAY_ORDER
from .portal_control import (
    PIPELINE_DEADLINE,
    _check_portal_budget,
    _scrape_lock,
    _scrape_release,
    _sync_queue_depth,
)
from .reqctx import _client_ip
from .scope_sync import _scope_sync_state, _scope_sync_trigger
from .security import require_login
from .state import _check_ip_rate, _ip_retry_text, _portal_cooldown_remaining, progress, rate_limiter


def _push_conf():
    """VAPID/push config from the environment, read per call (ops flips it
    without a reboot). Lives in the push area; imported here rather than
    duplicated."""
    from .app import _push_conf as _f
    return _f()


EXAM_EVT_TTL = 12 * 3600  # offline phones: deliver for 12 h, then drop
from .usage_metrics import _track
from .views.timetable import _save_timetable_group, _tt_editor_enabled


def fetch_attendance(netid, password, **kw):
    """The sync entry point, read through the module that OWNS it.

    Tests stub the facade (`A.fetch_attendance = fake`), and the facade proxies
    that name into app.scraper. Calling our import-time copy here would bypass
    the stub entirely and hit the real portal — so resolve at call time.
    """
    from . import scraper as _s
    return _s.fetch_attendance(netid, password, **kw)


log = logging.getLogger("opensrm")
log_auth = logging.getLogger("opensrm.auth")
log_push = logging.getLogger("opensrm.push")
NETID_RE = re.compile(r"^[a-z0-9]{2,20}$")  # audit: SRM NetIDs are lowercase alnum


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
    t_persist = time.monotonic()
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
    # The third span: everything this process spends writing the sync to
    # SQLite (upsert + timetable group). Portal and SCOPE are network-bound;
    # this one is disk-bound, and mixing them hides which is actually slow.
    metrics.observe("opensrm_sync_phase_duration_seconds",
                    time.monotonic() - t_persist, phase="persist")


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
    # SCOPE is BACKGROUND work (each SOAP op is 4-8s upstream) — it must never
    # sit in the login response. The dashboard reloads once when it lands.
    _scope_sync_trigger(netid, password)

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


def _refresh_core(netid, password):
    """One refresh for an ALREADY-AUTHENTICATED account.

    Split out of api_refresh so the background auto-sync can run the exact
    same single-flight + cache-window + persist path without a request
    context (and without duplicating logic that is easy to drift).
    Caller owns credential loading; this owns the portal work.
    """
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
        # same rule as login: the SCOPE fetch runs in the background, never
        # inside the refresh response
        _scope_sync_trigger(netid, password)
        flight["res"] = {"ok": True}
        return {"ok": True}
    finally:
        # publish the result before the flight leaves the map: a joiner
        # holding this flight while it finished still shares the answer
        with _flights_lock:
            _sync_flights.pop(netid, None)
        flight["done"].set()


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
    return _refresh_core(netid, password)

def api_scope_status():
    """Minimal SCOPE sync status for the dashboard's one-shot reload.

    Authenticated (the session cookie) and scoped to the CURRENT user: it
    returns a state word and an op count — never a payload, never a
    credential, never another user's data.
    """
    netid = get_current_user()
    if not netid:
        return {"ok": False, "error": "not logged in"}, 401
    try:
        from app.scope.ops import enabled_features, ops_for
        ops = ops_for(enabled_features())
    except Exception:
        ops = []
    return {"ok": True, "state": _scope_sync_state(netid), "ops": len(ops)}

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
