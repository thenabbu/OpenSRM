"""Portal control plane: concurrency, queueing and the request budget.

Extracted from app/app.py (facade pump, phase 3). Everything the app does
around a portal call — the scrape semaphore, the login-before-refresh queue,
the per-IP/per-netid token budget, the encrypted portal-cookie cache and the
per-request sync context — moves here as one unit, because they all mutate the
same module-level state under the same lock.

Deliberately imports nothing from app.app: its needs are all in app/state.py
(rate limiter, progress tracker), app/crypto.py (cookie encryption) and app/db.py
(portal-session rows). That is what lets app/scraper.py drop its own facade
import for these names and closes the app -> scraper -> app cycle.

Re-exported from app.app, so existing callers and tests are untouched.
"""
import contextvars
import os
import threading
import time

from .crypto import encrypt_pw, get_fernet
from .db import delete_portal_session, get_portal_session, save_portal_session
from .state import _rate_lock, _set_progress, log


def _portal_fail():
    """One portal failure against the shared health breaker."""
    from .state import portal_health
    portal_health.fail()


def _sync_max_concurrency():
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
