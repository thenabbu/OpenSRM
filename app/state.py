"""In-memory rate-limit, login-progress and portal-health state (A18).

Three small classes replace the loose module-level dicts/scalars that used
to live in app/app.py. Each owns ONE threading.Lock and prunes expired keys
on access, so no structure can grow without bound:

  RateLimiter     netid/ip attempt windows + preflight admission state
  ProgressTracker login-progress map (attempt token -> stage) + its read cap
  PortalHealth    portal cooldown timestamp + consecutive-fail counter

The old module-level names (_login_attempts, _ip_attempts, _preflight_*,
_login_progress, _progress_ip, _rate_lock, ...) stay as ALIASES to the very
objects the classes mutate — tests and ops recipes poke them directly and
every class method sees the poke. Rebinding a scalar alias
(``_portal_cooldown_until = ...``) no longer works; set the attribute
(``portal_health.cooldown_until``) instead.

Memory bound (docs: SECURITY.md "Memory exhaustion guard"): every
admission/write prunes expired keys first (O(live keys), once per request);
when a map still exceeds _RATE_CAP keys it drops only stale entries, and a
>2x blowout clears that ONE map. Worst case per map: ~2x10,000 keys, each
holding only its window's timestamps (<=10); the progress map additionally
TTL-prunes on every write, so an abandoned login flow leaks nothing.
PortalHealth holds two scalars - nothing accumulates there to prune.
"""
import logging
import threading
import time

from . import metrics

log = logging.getLogger(__name__)

_RATE_CAP = 10000  # ponytail: memory exhaustion guard; upgrade to LRU if throughput matters


class RateLimiter:
    """Attempt windows + preflight admission, all under ONE lock.

    audit: check-and-append is atomic only under one lock shared by gthread
    workers. The lock object is exported as ``_rate_lock`` so the portal
    budget code in app.app keeps holding the SAME lock (cross-structure
    admission order unchanged).
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.login_attempts = {}   # netid -> [ts, ...]  (scrapes, 10-min window)
        self.ip_attempts = {}      # ip -> [ts, ...]     (login POSTs, 1-hour window)
        self.preflight_last = {}   # netid -> ts         (30s per-netid cooldown)
        self.preflight_ip = {}     # ip -> [ts, ...]     (10 per 10 min per IP)

    def check(self, netid):
        """Sync-quota ADMISSION (check-only, audit run-1 #6): >=3 successful
        syncs in the 10-min window rejects; rejected requests never append,
        and the charge only happens in charge() when a sync actually succeeds
        — so unauth wrong-password guesses can never pre-spend a chosen
        victim's quota."""
        now = time.time()
        with self.lock:
            if len(self.login_attempts) > _RATE_CAP:
                # audit: drop only stale keys — a flood must not reset the
                # cap for every account (the old clear() did)
                for k in [k for k, v in self.login_attempts.items()
                          if not v or now - max(v) >= 600]:
                    self.login_attempts.pop(k, None)   # prune expired netids
                if len(self.login_attempts) > _RATE_CAP * 2:  # ponytail: blowout guard
                    self.login_attempts.clear()
            kept = [t for t in self.login_attempts.get(netid, []) if now - t < 600]
            if kept:
                self.login_attempts[netid] = kept
            else:
                # never materialize an empty key: a denied admission must leave
                # the counter state exactly as it was (test_login_reject pins it)
                self.login_attempts.pop(netid, None)
            return len(kept) < 3

    def charge(self, netid):
        """Spend one sync token — called only when a sync really succeeded."""
        now = time.time()
        with self.lock:
            self.login_attempts[netid] = [t for t in self.login_attempts.get(netid, [])
                                          if now - t < 600]
            self.login_attempts[netid].append(now)

    def check_ip(self, ip):
        now = time.time()
        with self.lock:
            if len(self.ip_attempts) > _RATE_CAP:
                # audit: same as login_attempts — prune stale keys, don't reset everyone
                for k in [k for k, v in self.ip_attempts.items()
                          if not v or now - max(v) >= 3600]:
                    self.ip_attempts.pop(k, None)      # prune expired ip keys
                if len(self.ip_attempts) > _RATE_CAP * 2:  # ponytail: blowout guard
                    self.ip_attempts.clear()
            attempts = self.ip_attempts.get(ip, [])
            self.ip_attempts[ip] = [t for t in attempts if now - t < 3600]
            if len(self.ip_attempts[ip]) >= 10:
                return False
            self.ip_attempts[ip].append(now)
            return True

    def oldest(self, key, which="netid"):
        """Oldest in-window timestamp behind a countdown text — reads the
        SAME window the checker prunes against, so the promise can't drift
        from what the limit will actually allow."""
        with self.lock:
            m = self.login_attempts if which == "netid" else self.ip_attempts
            return min(m.get(key) or [time.time()])

    def preflight_admit(self, netid, ip, busy):
        """Atomic preflight admission (audit run-1 #7): the old unlocked
        check-then-act let two gthread workers double-spend one admission.
        Returns "limited" (route answers 429), "cooldown" (route answers
        {ok: true} — identical to a fresh start, no per-netid discriminator
        leaks to an unauthenticated caller, audit run-1 #14), "busy" (route
        answers 503; A10: refused by QUEUE DEPTH, not a held lock) or None
        (admitted — the route must charge() after the portal-budget check).
        ``busy`` is the caller's call: the portal cooldown and the sync
        queue are not this object's state. Both dicts get aggregate eviction
        here so neither can grow without bound."""
        now = time.time()
        with self.lock:
            for k in [k for k, t in self.preflight_last.items() if now - t > 600]:
                self.preflight_last.pop(k, None)          # expire cooled-down netids
            for k in [k for k, v in self.preflight_ip.items()
                      if not [t for t in v if now - t < 600]]:
                self.preflight_ip.pop(k, None)            # expire drained ip buckets
            hits = [t for t in self.preflight_ip.get(ip, []) if now - t < 600]
            if len(hits) >= 10:  # ponytail: preflight is unauthenticated — cap hard
                return "limited"
            if now - self.preflight_last.get(netid, 0) < 30:
                return "cooldown"
            if busy:
                return "busy"
            self.preflight_ip[ip] = hits
            return None

    def preflight_charge(self, netid, ip):
        """Atomic charge, re-validated — closes the admission race (audit
        run-1 #7). "cooldown"/"limited" = the window closed while the portal
        budget check ran; None = charged, spawn the warm login."""
        now = time.time()
        with self.lock:
            if now - self.preflight_last.get(netid, 0) < 30:
                return "cooldown"
            hits = [t for t in self.preflight_ip.get(ip, []) if now - t < 600]
            if len(hits) >= 10:
                return "limited"
            self.preflight_ip[ip] = hits + [now]
            self.preflight_last[netid] = now
            return None


class ProgressTracker:
    """Login-progress map (attempt token -> stage) + its per-IP read cap.

    Writes used to run unlocked and an entry was only dropped when the SAME
    key was read again after 10 min — an abandoned login flow leaked its
    entry forever. Every write now prunes expired entries under the lock;
    the per-IP read cap (audit #13: 30 reads/60s) was likewise mutated
    unlocked and never pruned drained buckets.
    ponytail: one shared lock — a ~5-30s flow publishing ~1 step/s never
    contends; per-key locks if throughput matters."""

    _TTL = 600   # same window the old read-path purge used; fine for a ~5-30s flow

    def __init__(self):
        self.lock = threading.Lock()
        self.entries = {}   # attempt -> {"step", "ts", "pct", "netid"}
        self.reads = {}     # ip -> [ts, ...] (30 reads/60s per IP)

    def set(self, key, step, pct, netid=None):
        now = time.time()
        with self.lock:
            for k in [k for k, v in self.entries.items() if now - v["ts"] > self._TTL]:
                self.entries.pop(k, None)   # prune abandoned flows, not just this key
            self.entries[key] = {"step": step, "ts": int(now), "pct": pct,
                                 "netid": netid or "-"}

    def read(self, key):
        """(step, pct) for this attempt token; ("", 0) when unknown or stale."""
        now = time.time()
        with self.lock:
            p = self.entries.get(key)
            if p and now - p["ts"] > self._TTL:
                self.entries.pop(key, None)
                p = None
            return (p["step"], p["pct"]) if p else ("", 0)

    def read_ok(self, ip):
        """One progress-read token (30/60s per IP); drains its own bucket."""
        now = time.time()
        with self.lock:
            for k in [k for k, v in self.reads.items()
                      if not [t for t in v if now - t < 60]]:
                self.reads.pop(k, None)     # prune drained ip buckets
            hits = [t for t in self.reads.get(ip, []) if now - t < 60]
            if len(hits) >= 30:
                return False
            self.reads[ip] = hits + [now]
            return True


class PortalHealth:
    """Portal cooldown + consecutive-fail counter (was two module globals
    mutated without a lock). Both fields are scalars — nothing accumulates,
    so there is nothing to prune; the cooldown timestamp self-expires on
    read. ponytail: the cooldown itself is still GLOBAL — per-user
    isolation needs per-netid counters, add when multi-user load is real."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cooldown_until = 0.0   # unix timestamp; 0 = no cooldown
        self.consecutive_fails = 0

    def fail(self):
        with self.lock:
            self.consecutive_fails += 1
            if self.consecutive_fails >= 3:
                minutes = min(30, 5 * (2 ** (self.consecutive_fails - 3)))
                self.cooldown_until = time.time() + minutes * 60
                log.warning("portal cooldown %d min after %d consecutive fails",
                            minutes, self.consecutive_fails)

    def ok(self):
        with self.lock:
            self.consecutive_fails = 0
            self.cooldown_until = 0.0

    def cooldown_remaining(self):
        with self.lock:
            return max(0.0, self.cooldown_until - time.time())


# ── instances + module-level aliases (tests/recipes poke the same objects) ──
rate_limiter = RateLimiter()
progress = ProgressTracker()
portal_health = PortalHealth()

_rate_lock = rate_limiter.lock      # same lock object the portal-budget code holds
_login_attempts = rate_limiter.login_attempts
_ip_attempts = rate_limiter.ip_attempts
_preflight_last = rate_limiter.preflight_last
_preflight_ip = rate_limiter.preflight_ip
_login_progress = progress.entries
_progress_ip = progress.reads


# ── thin wrappers under the old function names (app.app re-exports them) ──
def _check_rate(netid):
    return rate_limiter.check(netid)


def _charge_rate(netid):
    rate_limiter.charge(netid)


def _check_ip_rate(ip):
    return rate_limiter.check_ip(ip)


def _retry_text(oldest, window):
    """Guide §5 core: honest countdown from a window's oldest entry, so the
    promise can't drift from what the matching checker will actually allow."""
    left = max(1, int(window - (time.time() - oldest)))
    return f"{left} seconds" if left < 90 else f"{(left + 59) // 60} minutes"


def _netid_retry_text(netid):
    """Per-netid sync cap countdown. The old message promised a flat
    \"10 minutes\" while the sliding window could have <2 minutes left."""
    return _retry_text(rate_limiter.oldest(netid), 600)


def _ip_retry_text(ip):
    """Guide §5: an honest lockout message names the remaining time instead
    of \"try again later\"."""
    return _retry_text(rate_limiter.oldest(ip, which="ip"), 3600)


def _set_progress(key, step, pct, netid=None):
    progress.set(key, step, pct, netid)


def _portal_fail():
    portal_health.fail()


def _portal_ok():
    portal_health.ok()


def _portal_cooldown_remaining():
    return portal_health.cooldown_remaining()


# observability: live cooldown state for GET /internal/metrics (0 = armed off)
metrics.gauge("opensrm_portal_cooldown_seconds",
              lambda: float(portal_health.cooldown_remaining()))
