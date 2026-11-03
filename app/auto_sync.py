"""Refresh stale portal data on dashboard load, without waiting for a click.

Why this exists: `fetch_attendance` was only ever reached from `/api/refresh`
and `/api/login` — i.e. only when the user pressed the sync button. Nothing
refreshed attendance on its own, so a dashboard opened the next morning showed
yesterday's numbers and said "(8h ago)" until someone clicked.

The SCOPE blob already solved this shape (`_scope_sync_kick_if_stale`): cheap
check on visit, decrypt the credential only when work is actually due, run in a
daemon thread, single-flight per account, never block the response. This is the
same pattern for the portal path, calling the same `_refresh_core` the button
uses so the two can never drift.

`ponytail:` the staleness threshold is one env knob (``AUTO_SYNC_STALE_S``,
default 900s). 0 disables it entirely and restores click-only behaviour, which
is also what the test suites use so no suite starts hitting the portal.
"""
import logging
import os
import threading
import time

log = logging.getLogger("opensrm.autosync")

_AUTO_SYNC_STALE_DEFAULT = 900  # 15 min: dashboard opens are usually hours apart
_lock = threading.Lock()
_running = set()


def _stale_after_s():
    """AUTO_SYNC_STALE_S in seconds, read per call so ops can flip it without
    a restart. 0 or negative disables the kick."""
    raw = os.environ.get("AUTO_SYNC_STALE_S")
    if raw is None:
        return _AUTO_SYNC_STALE_DEFAULT
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return _AUTO_SYNC_STALE_DEFAULT


def auto_sync_kick_if_stale(netid):
    """Kick a background portal refresh when this account's data is old.

    Never raises and never blocks: a dashboard render must not fail because a
    background job could not be scheduled.
    """
    try:
        window = _stale_after_s()
        if window <= 0 or not netid:
            return False

        # Cheap read first: one row, no decrypt, no network.
        from .db import user_last_fetch

        row = user_last_fetch(netid)
        last = int(row["last_fetch"] or 0) if row else 0
        if last and (time.time() - last) < window:
            return False

        with _lock:
            if netid in _running:
                return False
            _running.add(netid)

        def _run():
            try:
                from .crypto import decrypt_pw
                from .db import user_password
                from .routes_sync import _refresh_core

                cred = user_password(netid)
                pw = decrypt_pw(cred["password"]) if cred else None
                if not pw:
                    log.info("auto.sync skipped netid=%s reason=no_creds", netid)
                    return
                res = _refresh_core(netid, pw, source="auto")
                log.info("auto.sync netid=%s ok=%s cached=%s",
                         netid, bool(res[0].get("ok")), bool(res[0].get("cached")))
            except Exception as e:  # a background job must never kill the worker
                log.warning("auto.sync background failed netid=%s error=%s",
                            netid, str(e)[:120])
            finally:
                with _lock:
                    _running.discard(netid)

        threading.Thread(target=_run, daemon=True, name="srm-auto-sync").start()
        return True
    except Exception as e:
        log.debug("auto.sync kick skipped netid=%s: %s", netid, str(e)[:120])
        return False
