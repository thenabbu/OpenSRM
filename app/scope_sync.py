"""SCOPE background sync: kick a stale SCOPE fetch, track whether one is running.

Extracted from app/app.py (facade pump, cycle D). Three functions and one lock;
it reads the stored password, decrypts it and starts a daemon thread — the only
scheduler-shaped thing in the app, and it is per-request, not a cron.

Imports app.crypto + app.db only; re-exported from app.app.
"""
import logging
import threading

from .crypto import decrypt_pw
from .db import user_password

log = logging.getLogger("opensrm")


_scope_sync_lock = threading.Lock()
_scope_sync_running: set = set()


def _scope_sync_trigger(netid, password):
    """Start the SCOPE sync in the background. Never blocks the response.

    Single-flight per account: a trigger while a run is already in flight is
    dropped, not queued — two concurrent batches would double the upstream
    load for no benefit.

    No-ops when SCOPE is off (SCOPE_FEATURES unset/"off"/no ops). That is the
    single gate every caller routes through, so a test or a deployment with
    the integration disabled never makes an outbound call — test_canary_sync
    boots a real server and asserts no network, and used to reach the live
    SCOPE backend through /api/refresh.
    """
    if not netid or not password:
        return
    from app.scope.ops import enabled_features, ops_for
    from app.scope.sync import scope_cold_sync
    if not ops_for(enabled_features()):
        return
    with _scope_sync_lock:
        if netid in _scope_sync_running:
            return
        _scope_sync_running.add(netid)

    def _run():
        try:
            scope_cold_sync(netid, password)
        except Exception as e:  # a background job must never kill the worker
            log.warning("scope.sync background failed netid=%s error=%s", netid, str(e)[:120])
        finally:
            with _scope_sync_lock:
                _scope_sync_running.discard(netid)

    threading.Thread(target=_run, daemon=True, name="srm-scope-sync").start()


def _scope_sync_kick_if_stale(netid):
    """Dashboard visit: kick the sync when the blob is missing or stale.

    The cheap check runs first (one row read, no network, no login); the
    stored credential is only decrypted when a sync is actually due.
    """
    try:
        from app.scope.sync import scope_needs_sync
        if not scope_needs_sync(netid):
            return
        row = user_password(netid)
        if not row:
            return
        pw = decrypt_pw(row["password"])
        if pw:
            _scope_sync_trigger(netid, pw)
    except Exception as e:
        log.debug("scope.sync dashboard kick skipped: %s", str(e)[:120])


def _scope_sync_state(netid):
    """'off' | 'stale' | 'running' | 'complete' — the dashboard's one-shot
    reload signal. No payload, no credentials, no cross-user data."""
    try:
        from app.scope.ops import enabled_features, ops_for
        from app.scope.sync import scope_needs_sync
        if not ops_for(enabled_features()):
            return "off"
        with _scope_sync_lock:
            if netid in _scope_sync_running:
                return "running"
        return "stale" if scope_needs_sync(netid) else "complete"
    except Exception:
        return "off"
