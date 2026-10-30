"""SCOPE cold sync — session handling + paced op fetch into users.scope_json.

Import surface (stable for later PRs): app.scope.sync.ensure_scope_session /
app.scope.sync.scope_cold_sync. Everything imported here lives in
app.scope.* or app.db — nothing touches app.app (same no-circular-import
rule http_scraper follows; app.app will import THIS module lazily when the
cold-sync hook lands in the UI PRs).

Discipline (mission contract):
  preserve-if-empty — a failing op NEVER deletes its stored scope_json key
  (log + skip); an alive-empty answer ({Status, Data:""}) IS data, stored
  as-is. ScopeAuthError -> ONE relogin + retry of THAT op, never a loop.
  ScopeTransportError -> break the run, keep what landed, one ERROR line.
"""
import json
import logging
import threading
import time

from app.db import save_scope_session, user_scope, user_scope_data, write_scope_data
from app.scope.client import ScopeAuthError, ScopeError, ScopeTransportError, data_op, login
from app.scope.ops import enabled_features, ops_for

log = logging.getLogger("opensrm.scope")

PACE_S = 0.5  # courtesy pacing between ops (backend runs 4-8s/op)

# A full pass is ~15 ops x 4-8s upstream = 1-2 minutes, so the backend's
# slots are the scarce resource: re-fetch an op only when its payload is
# missing or older than this. 30 min matches the app's own sync cadence.
SCOPE_TTL_S = 1800

# ponytail: one in-process lock per netid — ceiling = sync throughput per
# account inside one process; upgrade path = per-account file locks if this
# ever runs multi-worker.
_locks: dict = {}
_locks_guard = threading.Lock()


def _lock_for(netid):
    with _locks_guard:
        if netid not in _locks:
            _locks[netid] = threading.Lock()
        return _locks[netid]


def _login_and_persist(netid, password):
    res = login(netid, password)
    save_scope_session(netid, res["sid"], res["studentid"])
    return {"sid": res["sid"], "studentid": res["studentid"]}


def ensure_scope_session(netid, password):
    """The stored scope_sid if the row has one, else a fresh login
    (persisted before returning)."""
    row = user_scope(netid)
    if row and row["scope_sid"]:
        return {"sid": row["scope_sid"], "studentid": row["scope_studentid"]}
    return _login_and_persist(netid, password)


def _stored(netid):
    row = user_scope_data(netid)
    try:
        stored = json.loads(row["scope_json"]) if row and row["scope_json"] else {}
    except ValueError:
        stored = {}
    return stored if isinstance(stored, dict) else {}


def _pending_ops(stored, ops, now, force=False):
    """The ops that actually need a fetch: missing, or older than the TTL.

    Fresh ops are kept as-is — each op is a 4-8s upstream call, so re-fetching
    a fresh one is pure waste (and burns the backend's slots).
    """
    if force:
        return list(ops)
    out = []
    for op in ops:
        e = stored.get(op) if isinstance(stored, dict) else None
        ts = e.get("ts") if isinstance(e, dict) else None
        if isinstance(ts, (int, float)) and ts and (now - int(ts)) < SCOPE_TTL_S:
            continue
        out.append(op)
    return out


def scope_needs_sync(netid, force=False):
    """True when any enabled op is missing or stale. One users-row read.

    The dashboard uses this as its cheap "is a sync due?" check — it must not
    log in, fetch, or touch the network.
    """
    ops = ops_for(enabled_features())
    if not ops:
        return False
    return bool(_pending_ops(_stored(netid), ops, int(time.time()), force))


def scope_cold_sync(netid, password, force=False):
    """Fetch the MISSING/STALE enabled ops into users.scope_json[<op>] =
    {"data": <parsed response>, "ts": <epoch>}; scope_fetched_at stamped at
    the end ONLY when the run completed (an aborted run is not fresh).
    Returns {"ok", "skipped", "fresh", "ops", "aborted"} for callers/tests.

    Incremental by design: fresh ops are never re-fetched, a per-op failure
    keeps that op's stored payload+ts, and a transport fault aborts the run
    with what landed preserved.
    """
    t_scope = time.monotonic()
    with _lock_for(netid):
        ops = ops_for(enabled_features())
        stored = _stored(netid)
        pending = _pending_ops(stored, ops, int(time.time()), force)
        if not pending:
            log.info("scope.sync netid=%s nothing stale (%d op(s) fresh)", netid, len(ops))
            _record_sync_phase("scope", time.monotonic() - t_scope, 0)
            return {"ok": 0, "skipped": 0, "fresh": len(ops), "ops": len(ops), "aborted": False}
        session = ensure_scope_session(netid, password)
        ok = skipped = 0
        aborted = False
        for i, op in enumerate(pending):
            if i:
                time.sleep(PACE_S)
            try:
                data = data_op(op, session["sid"])
            except ScopeAuthError:
                # credential fault: ONE relogin + retry of THIS op, never a loop
                try:
                    session = _login_and_persist(netid, password)
                    data = data_op(op, session["sid"])
                except ScopeTransportError as e:
                    log.error("scope.sync op=%s transport fault after relogin: %s — aborting run", op, e)
                    aborted = True
                    break
                except ScopeError as e:
                    log.warning("scope.sync op=%s still failing after one relogin, skipped (stored key preserved): %s", op, e)
                    skipped += 1
                    continue
            except ScopeTransportError as e:
                log.error("scope.sync op=%s transport fault: %s — aborting run, %d stored op(s) kept", op, e, len(stored))
                aborted = True
                break
            except ScopeError as e:
                log.warning("scope.sync op=%s failed, skipped (stored key preserved): %s", op, e)
                skipped += 1
                continue
            stored[op] = {"data": data, "ts": int(time.time())}
            ok += 1
        # an aborted run must NOT claim freshness — keep whatever stamp the row
        # already had. (user_scope_data SELECTs scope_fetched_at, not the row.)
        prev = user_scope_data(netid)
        prev_at = (prev["scope_fetched_at"] or 0) if prev else 0
        stamp = prev_at if aborted else int(time.time())
        write_scope_data(netid, json.dumps(stored, ensure_ascii=False), stamp)
        log.info("scope.sync netid=%s pending=%d ok=%d skipped=%d aborted=%s stored=%d",
                 netid, len(pending), ok, skipped, aborted, len(stored))
        _record_sync_phase("scope", time.monotonic() - t_scope, len(pending))
        return {"ok": ok, "skipped": skipped, "fresh": len(ops) - len(pending),
                "ops": len(ops), "aborted": aborted}


def _record_sync_phase(phase, seconds, ops):
    """One sync span into metrics, split by data source.

    The dashboard's whole point here is proportionality: "the sync takes 40s"
    is useless, "31s of it is the portal and 2s is SCOPE" is actionable. Phase
    is a literal ('portal' | 'scope' | 'persist'), so cardinality is three.
    """
    try:
        from .. import metrics
        metrics.observe("opensrm_sync_phase_duration_seconds", seconds, phase=phase)
        metrics.inc("opensrm_sync_phase_ops_total", phase=phase,
                    bucket="0" if ops == 0 else "1-3" if ops <= 3 else "4+")
    except Exception:
        pass
