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
