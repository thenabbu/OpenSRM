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


def scope_cold_sync(netid, password):
    """Fetch every enabled op into users.scope_json[<op>] = {"data": <parsed
    response>, "ts": <epoch>}; scope_fetched_at stamped once at the end.
    Returns {"ok", "skipped", "ops", "aborted"} for callers/tests."""
    with _lock_for(netid):
        session = ensure_scope_session(netid, password)
        ops = ops_for(enabled_features())
        stored = _stored(netid)
        ok = skipped = 0
        aborted = False
        for i, op in enumerate(ops):
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
        write_scope_data(netid, json.dumps(stored, ensure_ascii=False), int(time.time()))
        log.info("scope.sync netid=%s ops=%d ok=%d skipped=%d aborted=%s stored=%d",
                 netid, len(ops), ok, skipped, aborted, len(stored))
        return {"ok": ok, "skipped": skipped, "ops": len(ops), "aborted": aborted}
