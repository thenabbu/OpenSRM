#!/usr/bin/env python3
"""Unit: the app/db.py layer — one way to touch the database, no leaks.

Refactor contract (feat/refactor-db-layer):
  1. db() is request-scoped: one connection per request, reused inside it,
     closed by the teardown — including when the handler raises mid-way.
     Outside a request (scripts, tests, background threads) it stays the
     old caller-owned fresh connection.
  2. transaction() is the atomic unit: a unit that fails mid-way rolls back
     ALONE — on the shared request connection that means a SAVEPOINT, so a
     failed unit can never ride into whatever commits next on that connection.
  3. Semantics-equal proofs for the two contracts the refactor moved:
     the users upsert (login rotates the stored password, refresh preserves
     it, first fetch creates the row) and the attendance/marks preserve
     merge (an empty/absent fetch key must never clobber stored data).

Self-contained: fresh DATA_DIR, migrations run at import. No server, no
network. The leak probe counts open file descriptors pointing at srm.db —
a leaked connection is a leaked fd, visible without any hook.
"""
import os
import sys
import tempfile
import threading
import time

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="dblayer-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import app.app as A          # noqa: E402  (import runs init_db)
import app.db as D           # noqa: E402

fails = []


def check(name, cond, extra=""):
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        fails.append(name)


DB_FILE = os.path.join(os.environ["DATA_DIR"], "srm.db")


def open_db_fds():
    """Leak probe: open file descriptors pointing at srm.db right now."""
    n = 0
    for fd in os.listdir("/proc/self/fd"):
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue
        if target.endswith("srm.db"):
            n += 1
    return n


def usage_count(tag):
    c = D.connect()
    n = c.execute("SELECT COUNT(*) FROM usage_events WHERE event=?", (tag,)).fetchone()[0]
    c.close()
    return n


# ── 1. db() outside a request: the scripts/tests contract ────────────
c1 = D.db()
c2 = D.db()
check("db() outside a request is a fresh caller-owned connection", c1 is not c2)
c1.close(); c2.close()
check("caller closes it (fd released)", open_db_fds() == 0, f"fds={open_db_fds()}")

# ── 2. request scope: one connection, reused, closed at teardown ────
base = open_db_fds()
with A.app.test_request_context("/"):
    r1 = D.db()
    r2 = D.db()
    check("inside a request db() is one shared connection", r1 is r2)
    during = open_db_fds()
check("request connection closed by the teardown", open_db_fds() == base,
      f"before={base} after={open_db_fds()}")
check("it was actually open during the request", during == base + 1,
      f"base={base} during={during}")

# ── 3. exception mid-handler leaves zero open connections ───────────
@A.app.route("/__db_layer_boom")
def _db_layer_boom():
    c = D.db()
    c.execute("INSERT INTO usage_events(day, user, event) VALUES(?,?,?)",
              ("2026-10-16", "zz9999", "boom-pending"))
    raise RuntimeError("mid-handler boom")

client = A.app.test_client()
before = open_db_fds()
resp = client.get("/__db_layer_boom")
check("mid-handler exception returns 500", resp.status_code == 500, str(resp.status_code))
check("mid-handler exception leaks zero connections", open_db_fds() == before,
      f"before={before} after={open_db_fds()}")
check("the pending write was rolled back at teardown", usage_count("boom-pending") == 0,
      str(usage_count("boom-pending")))

# ── 4. transaction() outside a request: commit/rollback/close ────────
try:
    with D.transaction() as c:
        c.execute("INSERT INTO usage_events(day, user, event) VALUES(?,?,?)",
                  ("2026-10-16", "zz9999", "tx-out-fail"))
        raise RuntimeError("mid-unit")
except RuntimeError:
    pass
check("failed unit (outside request) rolls back", usage_count("tx-out-fail") == 0)
check("failed unit (outside request) closes its connection", open_db_fds() == base,
      f"fds={open_db_fds()}")
with D.transaction() as c:
    c.execute("INSERT INTO usage_events(day, user, event) VALUES(?,?,?)",
              ("2026-10-16", "zz9999", "tx-out-ok"))
check("successful unit (outside request) commits", usage_count("tx-out-ok") == 1)
check("successful unit (outside request) closes its connection", open_db_fds() == base,
      f"fds={open_db_fds()}")

# ── 5. transaction() on the shared request connection: SAVEPOINT ────
# the refactor's sharpest hazard: pre-refactor each call site had its own
# connection, so a failed multi-statement write vanished at close(); on one
# shared connection a failed unit MUST NOT ride into a later commit.
with A.app.test_request_context("/"):
    try:
        with D.transaction() as c:
            c.execute("INSERT INTO usage_events(day, user, event) VALUES(?,?,?)",
                      ("2026-10-16", "zz9999", "tx-sp-fail"))
            raise RuntimeError("mid-unit")
    except RuntimeError:
        pass
    with D.transaction() as c:
        c.execute("INSERT INTO usage_events(day, user, event) VALUES(?,?,?)",
                  ("2026-10-16", "zz9999", "tx-sp-ok"))
check("failed savepoint unit rolls back alone (no bleed into next commit)",
      usage_count("tx-sp-fail") == 0, str(usage_count("tx-sp-fail")))
check("later unit on the same request connection commits fine",
      usage_count("tx-sp-ok") == 1, str(usage_count("tx-sp-ok")))
check("request teardown still closes the connection", open_db_fds() == base,
      f"fds={open_db_fds()}")

# ── 6. background threads never share the request's connection ───────
with A.app.test_request_context("/"):
    req_conn = D.db()
    seen = {}

    def _worker():
        c = D.db()
        seen["same"] = c is req_conn
        c.close()  # threads open/close their own connection explicitly

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
check("a thread inside a request gets its own connection", seen.get("same") is False)

# ── 7. upsert semantics: login rotates, refresh preserves ────────────
NETID = "zz9999"
ATT1 = {"courses": [{"code": "21CSE1", "description": "Old Course",
                     "attended": 10, "total": 12}],
        "monthly": [], "period": None, "daily_absent": {}}
ATT2 = {"courses": [{"code": "21CSE2", "description": "New Course",
                     "attended": 5, "total": 8}],
        "monthly": [], "period": None, "daily_absent": {}}


def _res(fetched, **kw):
    r = {"fetched": fetched, "data": dict(ATT1)}
    r.update(kw)
    return r


A.persist_sync(NETID, _res(1000), password="login-pw-1")
row = D.user_password(NETID)
check("first login creates the users row (INSERT arm)", row is not None)
check("stored password is decryptable Fernet (not plaintext)",
      A.decrypt_pw(row["password"]) == "login-pw-1")
dash = D.user_dashboard(NETID)
check("first login writes the fetched attendance", "21CSE1" in (dash["attendance_json"] or ""))

# refresh: password=None -> UPDATE arm, stored password untouched
A.persist_sync(NETID, _res(2000, data={"courses": [], "monthly": [],
                                       "period": None, "daily_absent": {}},
                           marks=[], subjects={}), password=None)
check("refresh (password=None) preserves the stored password",
      A.decrypt_pw(D.user_password(NETID)["password"]) == "login-pw-1")

# a later login rotates the stored password (ON CONFLICT arm)
A.persist_sync(NETID, _res(3000, data=ATT2), password="login-pw-2")
check("later login rotates the stored password (ON CONFLICT arm)",
      A.decrypt_pw(D.user_password(NETID)["password"]) == "login-pw-2")
check("later login replaces attendance with the fresh parse",
      "21CSE2" in D.user_dashboard(NETID)["attendance_json"])

# ── 8. preserve contract: empty/absent fetch keys keep stored data ────
MANY_MARKS = [{"code": "21CSE2", "components": [{"name": "IE-1", "max": 30}]}]
A.persist_sync(NETID, _res(4000, data=ATT2, marks=MANY_MARKS), password="login-pw-2")
check("real marks payload stores", '"IE-1"' in D.user_marks(NETID)["marks_json"])
# partial fetch: marks key present-but-empty, attendance empty -> preserve both
A.persist_sync(NETID, _res(5000, data={"courses": [], "monthly": [],
                                       "period": None, "daily_absent": {}},
                           marks=[]), password=None)
check("empty fresh attendance preserves the stored attendance",
      "21CSE2" in D.user_dashboard(NETID)["attendance_json"])
check("empty fresh marks preserve the stored marks (B6)",
      '"IE-1"' in D.user_marks(NETID)["marks_json"])

passed = 24 - len(fails)
print(f"db layer: {passed}/24" if not fails else f"db layer: FAILED: {fails}")
sys.exit(1 if fails else 0)
