"""Usage telemetry: which surfaces get used, and by whom.

Extracted from app/app.py (facade pump, cycle D). _track() is called from seven
places across the app, so it lives below them rather than inside the facade. The
retention prune runs inside _track() (self rate-limited to once/24h) — there is
no scheduler for it by design.

Imports app.db + app.metrics only; re-exported from app.app.
"""
import hashlib
import logging
import os
import threading
import time

from . import metrics
from .db import insert_usage_event, prune_usage_events

log = logging.getLogger("opensrm")


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
    plain INSERT, no batching — a few rows/day at this scale.

    Also mirrors the event into the in-process metric registry, so the
    dashboard can chart activity live instead of only querying SQLite.
    `user` reaches the metric ONLY as `_user_label(user)`: a truncated
    sha256, never the netid — this repo is public and its dashboards are
    served on the LAN, so a raw identifier in a label would leak it.
    """
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
    # Metric mirror runs whatever the DB did: a locked DB must not blind the
    # live charts too. Label cardinality is bounded by design — at this
    # scale (a student body, not a web audience) one series per active user
    # per event is fine; revisit past a few thousand users.
    try:
        u = _user_label(user)
        # label is `uid`, NOT `user`: the observability asset guard bans a
        # `user` label outright because a raw netid there would leak PII into
        # a LAN-served dashboard. Keeping the banned name and weakening the
        # guard to fit a hashed value would remove the guard's whole point;
        # `uid` reads as an opaque handle and cannot be mistaken for a netid.
        metrics.inc("opensrm_events_total", event=event, uid=u,
                    target=(target or "none")[:24])
        if user:
            metrics.inc("opensrm_active_users_total", uid=u)
    except Exception:
        pass


def _user_label(user):
    """Stable, non-reversible handle for a netid: 'u' + sha256[:10].

    Returns 'anonymous' for an empty user so logged-out traffic has its own
    series instead of vanishing. Truncated to 10 hex chars — enough to
    correlate one user's activity across panels, far too little to recover
    the netid, and short enough to keep legends readable.
    """
    if not user:
        return "anonymous"
    return "u" + hashlib.sha256(str(user).encode()).hexdigest()[:10]
