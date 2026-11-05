"""Health and metrics endpoints: /healthz and /internal/metrics.

Extracted from app/app.py (facade pump, cycle F). Split from the push routes
they sit next to, because these describe the PROCESS and the DB — not the push
feature — and a future metrics change should not touch push code.

/internal/metrics authenticates with the X-Metrics-Token secret header
(METRICS_SECRET, 600-mode secret file; ops stack in ops/observability).
"""
import hmac
import logging
import os
import time

from flask import request

from . import db as dbmod
from . import metrics
from .db import ping
from .logging_setup import log_with_kv

log_http = logging.getLogger("opensrm.http")


def _db_path():
    """The live DB path. app.DB_PATH is a mutable global (tests repoint it), so
    read it from the facade at call time rather than importing a copy."""
    from .app import DB_PATH
    return DB_PATH
from .reqctx import _client_ip
from .views.attendance import _bare

log_metrics = logging.getLogger("opensrm.metrics")


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
    # Close visits that have gone idle so their span is counted even when the
    # student simply stopped (no later tick to notice the gap). One scrape per
    # 30s is exactly the right cadence for a 30-minute idle threshold.
    try:
        sweep_idle_visits()
    except Exception:
        pass
    return metrics.render(), 200, {"Content-Type": "text/plain; version=0.0.4"}


# ── metric callbacks (moved from the push area: they measure the PROCESS
# and the DB, not push) ──────────────


_PUSH_TICK_LAST_OK = {"ts": 0.0}


def _push_tick_last_ok_ts():
    return _PUSH_TICK_LAST_OK["ts"]


metrics.gauge("opensrm_push_tick_last_success_timestamp_seconds", _push_tick_last_ok_ts)


# ── Process and storage gauges ────────────────────────────────────────────
# Everything here is a RENDER-TIME callback (metrics.gauge runs it once per
# scrape, ~1/30s), so it must stay cheap and never raise. The whole block
# answers "is this process healthy and is the data growing" — the questions
# the existing sync/push counters cannot see at all.

def _proc_rss_bytes():
    """Resident set size from /proc/self/statm (pages * page_size).
    Linux-only by design: prod is a Linux container. On any other platform
    or a missing file the gauge renders 0 rather than raising."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return 0.0


def _proc_threads():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("Threads:"):
                    return float(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0.0


def _db_stat(fn):
    """Run one read-only DB probe for a gauge; 0 on any failure.

    Deliberately NOT using db() — a gauge must never open a request-scoped
    connection or join an in-flight transaction (it would render mid-commit
    state and could deadlock a scrape against a busy writer). A private
    short-lived connection reads the same WAL snapshot safely.
    """
    try:
        c = dbmod.connect()
        try:
            return float(fn(c))
        finally:
            c.close()
    except Exception:
        return 0.0


def _db_size_bytes(c):
    return c.execute("SELECT page_count * page_size FROM pragma_page_count(), "
                     "pragma_page_size()").fetchone()[0]


def _db_wal_bytes(c):
    """WAL file size on disk.

    PRAGMA wal_checkpoint returns (busy, log, checkpointed) where busy=-1
    means "another connection held it" — NOT a size. An earlier version
    multiplied that -1 by the page size and published a negative byte count.
    Read the file instead: it exists exactly when SQLite has a WAL.
    """
    try:
        return float(os.path.getsize(str(_db_path()) + "-wal"))
    except OSError:
        return 0.0


def _count(table):
    """Row count for one of the FIXED tables below (never user input)."""
    return lambda c: c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


metrics.gauge("opensrm_process_rss_bytes", _proc_rss_bytes)
metrics.gauge("opensrm_process_threads", _proc_threads)
metrics.gauge("opensrm_db_size_bytes", lambda: _db_stat(_db_size_bytes))
metrics.gauge("opensrm_db_wal_bytes", lambda: _db_stat(_db_wal_bytes))
# Table sizes worth watching, registered explicitly rather than in a loop so
# each series name is greppable as a literal in this file (the observability
# asset guard asserts every series an asset references exists in app/).
#   users              — growth = real adoption
#   push_subscriptions — growth without users = dead devices accumulating
#   push_sent_log      — retention-managed (30d); growth means pruning broke
#   usage_events       — retention-managed (365d); same signal
metrics.gauge("opensrm_rows_users", lambda: _db_stat(_count("users")))
metrics.gauge("opensrm_rows_push_subscriptions", lambda: _db_stat(_count("push_subscriptions")))
metrics.gauge("opensrm_rows_push_sent_log", lambda: _db_stat(_count("push_sent_log")))
metrics.gauge("opensrm_rows_usage_events", lambda: _db_stat(_count("usage_events")))


# ── Product analytics, derived from data SQLite already holds ─────────────
# Every gauge below reads a table the app has been writing since early
# migrations (users, cookies, usage_events). Each one is a RENDER-TIME query
# against a private short-lived connection (_db_stat), so a scrape costs one
# small SELECT and NEVER adds a write on a student's request path.
#
# Why gauges instead of counters: a counter accumulates from process start,
# so a restart silently resets "how many users exist" to zero and the panel
# lies for the rest of the day. These are properties of the DATABASE, not of
# this process, so they are read fresh on every scrape.
#
# All of them are plain numbers with NO per-user label, so none of them can
# leak a netid into a LAN-served dashboard (see the `uid` rule in
# app/metrics.py). Per-user breakdowns that Grafana cannot hold here without
# exploding cardinality are served as a distribution instead — see
# opensrm_user_db_bytes_bucket below.


def _distinct_users(c):
    return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def _now_sql():
    """The clock the usage queries compare against — SQLite's, in prod.

    Rows are stamped with the DB's clock, so the window must be measured with
    the SAME clock or the two drift apart under load and a user who is 1 day
    back flips across the 24h line mid-suite. Tests that seed their own
    timeline pass their own timestamp here instead of racing wall-clock.
    """
    return "strftime('%s','now')"


def _active_users_24h(c, now_sql=None):
    """Distinct people who did ANYTHING in the last 24h.

    The live counter opensrm_active_users_total{uid} answers "who is on right
    now" but resets on every deploy and double-counts an event per user, so it
    cannot answer "how many people used the app today". This reads usage_events
    directly: one row per event, one user column, a 24h floor on ts.
    """
    now_sql = now_sql or _now_sql()
    return c.execute("SELECT COUNT(DISTINCT user) FROM usage_events "
                     f"WHERE ts >= {now_sql} - 86400 "
                     "AND user != ''").fetchone()[0]


def _active_users_7d(c, now_sql=None):
    now_sql = now_sql or _now_sql()
    return c.execute("SELECT COUNT(DISTINCT user) FROM usage_events "
                     f"WHERE ts >= {now_sql} - 7*86400 "
                     "AND user != ''").fetchone()[0]


def _new_users_24h(c, now_sql=None):
    """First-time users: accounts whose EARLIEST usage event is within 24h.

    This is "first time login" in the sense the dashboard needs — the moment
    they first did anything. A user row created but never used does not count,
    and an existing account that finally opened the app DOES, which is what
    "new users came" means when reading a growth curve.
    """
    now_sql = now_sql or _now_sql()
    return c.execute(
        "SELECT COUNT(*) FROM (SELECT user, MIN(ts) AS first_ts FROM usage_events "
        f"WHERE user != '' GROUP BY user HAVING first_ts >= {now_sql} - 86400)"
    ).fetchone()[0]


def _new_users_7d(c, now_sql=None):
    now_sql = now_sql or _now_sql()
    return c.execute(
        "SELECT COUNT(*) FROM (SELECT user, MIN(ts) AS first_ts FROM usage_events "
        f"WHERE user != '' GROUP BY user HAVING first_ts >= {now_sql} - 7*86400)"
    ).fetchone()[0]


def _returning_users_24h(c, now_sql=None):
    """Active in the last 24h, but NOT first-timers: the loyalty number."""
    now_sql = now_sql or _now_sql()
    return c.execute(
        "SELECT COUNT(*) FROM (SELECT user, MIN(ts) AS first_ts FROM usage_events "
        f"WHERE user != '' GROUP BY user HAVING MAX(ts) >= {now_sql} - 86400 "
        f"AND first_ts < {now_sql} - 86400)"
    ).fetchone()[0]


def _sessions_open(c):
    """Live login sessions in the cookies table (read-time expiry, so a row
    older than SESSION_MAX_AGE is already dead even if it is still present)."""
    return c.execute("SELECT COUNT(*) FROM cookies WHERE created > strftime('%s','now') - 2592000").fetchone()[0]


def _users_with_data(c):
    """Accounts that have actually synced at least once (last_fetch set)."""
    return c.execute("SELECT COUNT(*) FROM users WHERE last_fetch > 0").fetchone()[0]


def _last_sync_age_seconds(c):
    """Seconds since ANY user last completed a sync. The stale-data alarm:
    if this climbs past a day the whole product is frozen even though the
    process looks healthy."""
    row = c.execute("SELECT MAX(last_fetch) FROM users").fetchone()
    ts = int(row[0] or 0) if row else 0
    if ts <= 0:
        return 0.0
    return float(max(0, time.time() - ts))


def _last_usage_event_age(c):
    """Seconds since the newest usage_events row. Proves telemetry is alive:
    a meter that stops moving is the difference between 'quiet' and 'broken'."""
    row = c.execute("SELECT MAX(ts) FROM usage_events").fetchone()
    ts = int(row[0] or 0) if row else 0
    if ts <= 0:
        return 0.0
    return float(max(0, time.time() - ts))


# Per-user storage is bucketed, never labelled per user: a per-account size in
# a public, LAN-served dashboard is the same PII leak as a netid label. The
# buckets answer "how big is a typical user" and "is anyone an outlier".
# Range 16KB..4MB — a synced student sits around 100-600KB (attendance + marks
# + subjects + timetable + SCOPE blobs together).
_DB_SIZE_BUCKETS = (16384, 32768, 65536, 131072, 262144, 524288,
                    1048576, 2097152, 4194304)


def _user_row_bytes_sql():
    """Bytes a single user occupies: the sum of the JSON blobs on their row.
    Every column is COALESCEd because a never-synced account has NULLs, and
    NULL + anything is NULL, which would silently drop that user from every
    bucket instead of counting them at the bottom."""
    return ("SELECT COALESCE(length(attendance_json),0) + "
            "COALESCE(length(marks_json),0) + "
            "COALESCE(length(subjects_json),0) + "
            "COALESCE(length(scope_json),0) + "
            "COALESCE(length(personal_details_json),0) + "
            "COALESCE(length(exam_schedule_json),0) + "
            "COALESCE(length(faculty_map_json),0) + "
            "COALESCE(length(photo_b64),0) FROM users")


def _user_db_bytes_buckets():
    """Cumulative count of users at-or-below each size bucket, or None.

    One full scan of `users` (one row per student) per scrape is cheaper than
    any index would be at this size, and it never touches the request path.
    """
    try:
        c = dbmod.connect()
        try:
            rows = [int(r[0] or 0) for r in c.execute(_user_row_bytes_sql())]
        finally:
            c.close()
        return [sum(1 for v in rows if v <= le) for le in _DB_SIZE_BUCKETS]
    except Exception:
        return None


metrics.gauge("opensrm_users_total", lambda: _db_stat(_distinct_users))
metrics.gauge("opensrm_users_synced_total", lambda: _db_stat(_users_with_data))
metrics.gauge("opensrm_auth_sessions_active", lambda: _db_stat(_sessions_open))
metrics.gauge("opensrm_users_active_24h", lambda: _db_stat(_active_users_24h))
metrics.gauge("opensrm_users_active_7d", lambda: _db_stat(_active_users_7d))
metrics.gauge("opensrm_users_new_24h", lambda: _db_stat(_new_users_24h))
metrics.gauge("opensrm_users_new_7d", lambda: _db_stat(_new_users_7d))
metrics.gauge("opensrm_users_returning_24h", lambda: _db_stat(_returning_users_24h))
metrics.gauge("opensrm_last_sync_age_seconds", lambda: _db_stat(_last_sync_age_seconds))
metrics.gauge("opensrm_last_usage_event_age_seconds", lambda: _db_stat(_last_usage_event_age))



# ── Visit span: how long one sitting actually lasts ───────────────────────
# Lives here, not in app.py, because app.py is line-ratcheted (see
# scripts/check_architecture.py) and this is self-contained telemetry.
# usage_events already stores one row per page view / tab view, so per-VIEW
# duration is derivable later; what it cannot say is "how long was someone
# here". A visit is a run of activity with no gap longer than SESSION_GAP_S.
# Tracking it in memory is enough: the span is only recorded when a visit
# ENDS (a gap is observed), so nothing is lost on restart except the visit in
# flight, which the restart would have truncated anyway.
SESSION_GAP_S = 1800          # 30 min idle ends a visit
VISIT_MAP_CAP = 4096          # bound on the per-netid maps, same idea as VISIT_MAP_CAP
_visit_start = {}             # netid -> monotonic ts of the first activity
_visit_last = {}              # netid -> monotonic ts of the latest activity

# usage_events already stores one row per page view / tab view, so per-VIEW
# duration is derivable later; what it cannot say is "how long was someone
# here". A visit is a run of activity with no gap longer than SESSION_GAP_S.
# Tracking it in memory is enough: the span is only recorded when a visit
# ENDS (a gap is observed), so nothing is lost on restart except the visit in
# flight, which would have been truncated by the restart anyway.


def track_session_activity(netid, now=None):
    """Fold one activity tick into the caller's current visit.

    Says nothing to Prometheus until the visit closes; closing emits the span
    into opensrm_user_session_span_seconds. Cheap: two dict reads/writes.
    """
    try:
        now = time.monotonic() if now is None else now
        last = _visit_last.get(netid)
        if last is None or now - last > SESSION_GAP_S:
            # a previous visit ended exactly here — record its span first
            if last is not None:
                start = _visit_start.get(netid, last)
                _emit_session_span(last - start)
            _visit_start[netid] = now
        # bound the maps like every other per-user limiter in this module
        if len(_visit_last) > VISIT_MAP_CAP:
            _visit_start.clear()
            _visit_last.clear()
            _visit_start[netid] = now
        _visit_last[netid] = now
    except Exception:
        pass


def _emit_session_span(seconds):
    try:
        metrics.observe("opensrm_user_session_span_seconds", max(0.0, seconds))
    except Exception:
        pass


def sweep_idle_visits(now=None):
    """Close visits that have gone quiet but never produced a new tick.

    Without this, the LAST visit of every sitting is never recorded — someone
    opens the app, reads for 4 minutes, and leaves, and nothing fires because
    a gap is only noticed on the NEXT visit. Called from the metrics render
    path (once per scrape), which is cheap and needs no scheduler.
    """
    try:
        now = time.monotonic() if now is None else now
        for netid in list(_visit_last.keys()):
            last = _visit_last[netid]
            if now - last > SESSION_GAP_S:
                start = _visit_start.get(netid, last)
                _emit_session_span(last - start)
                _visit_start.pop(netid, None)
                _visit_last.pop(netid, None)
    except Exception:
        pass

# ── Per-user storage histogram ────────────────────────────────────────────
# Registered like a gauge but rendered as a proper Prometheus histogram: the
# bucket boundaries are fixed at import, the cumulative counts are recomputed
# per scrape from the live row sizes.
metrics.histogram_provider("opensrm_user_db_bytes",
                           _user_db_bytes_buckets, _DB_SIZE_BUCKETS)
