"""push_store spec: migration on a fresh DATA_DIR, portable-SQL enforcement
(AST-based: docstrings/comments excluded, real string literals scanned),
claim/retry/orphan semantics, rebind, rate events."""
import ast, os, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="osrm-push-store-")

import app.app as A                    # runs migrations on the fresh DATA_DIR
from app import migrations, push_store as S

fails = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)

# 1) fresh-DB migration reaches v11 with the three tables
c = A.db()
ver = c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
c.close()
check("fresh DATA_DIR migrates to v12", ver == 12, str(ver))  # v12 = usage_events
check("push tables exist", {"push_subscriptions", "push_sent_log", "push_events"} <= tables, str(sorted(tables)))

# 2) portable SQL: scan REAL string literals (skip docstrings) of the
#    storage module and migration 11 for SQLite-only syntax
FORBIDDEN = ["insert or ignore", "rowid", "pragma", "autoincrement", "last_insert_rowid"]
def code_strings(src):
    tree = ast.parse(src)
    skip = {id(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]
store_src = (REPO / "app" / "push_store.py").read_text()
mig_tree = ast.parse((REPO / "app" / "migrations.py").read_text())
m11_src = ast.get_source_segment((REPO / "app" / "migrations.py").read_text(),
                                 [n for n in ast.walk(mig_tree)
                                  if isinstance(n, ast.FunctionDef) and n.name == "m011_push"][0])
for label, blob in (("push_store", " ".join(code_strings(store_src))),
                    ("migration 11", " ".join(code_strings(m11_src)))):
    hits = [t for t in FORBIDDEN if t in blob.lower()]
    check(f"{label}: portable SQL only", not hits, str(hits))

# 3) subscribe + endpoint rebinding (shared phone follows the newest user)
sub = S.upsert_subscription("aa1111", "https://push.example/ep-1", "pk", "au", "Chrome Android")
sub2 = S.upsert_subscription("bb2222", "https://push.example/ep-1", "pk2", "au2", "Chrome Android")
check("insert works", sub["netid"] == "aa1111" and sub["lead_minutes"] == 10, str(sub)[:120])
check("same endpoint rebinds netid, keeps id", sub2["id"] == sub["id"] and sub2["netid"] == "bb2222", str(sub2["netid"]))
check("one row per endpoint", len(S.list_subscriptions(enabled_only=False)) == 1, "")

# 4) settings + unsubscribe
check("disable by netid", S.set_settings("bb2222", enabled=False) == 1, "")
check("disabled subs hidden", S.list_subscriptions() == [], "")
check("re-enable + lead", S.set_settings("bb2222", enabled=True, lead_minutes=15) == 1
      and S.list_subscriptions()[0]["lead_minutes"] == 15, "")
check("unsubscribe needs matching netid", S.remove_subscription("aa1111", "https://push.example/ep-1") is False
      and S.remove_subscription("bb2222", "https://push.example/ep-1") is True, "")

# 5) claim semantics (at-most-once)
sub = S.upsert_subscription("cc3333", "https://push.example/ep-2", "pk", "au", "Safari iOS")
sid, today, start = sub["id"], "2026-10-05", int(time.time()) + 600
check("first claim wins", S.claim_send(sid, today, start, "21CSC202J") is True, "")
check("second claim loses", S.claim_send(sid, today, start, "21CSC202J") is False, "")
state = S.sent_state_for(today)
check("sent_state exposes (status, attempts, row_id)",
      state[(sid, today, start, "21CSC202J")][0] == "claimed" and state[(sid, today, start, "21CSC202J")][1] == 1,
      str(state))

# 6) failure/retry/orphan lifecycle
row_id = state[(sid, today, start, "21CSC202J")][2]
S.record_send_result(row_id, S.STATUS_FAILED, http_status=503)
st_fail = S.sent_state_for(today)[(sid, today, start, "21CSC202J")]
check("failed row stays visible to due-calc for retry",
      st_fail[0] == "failed" and st_fail[1] == 1 and st_fail[2] == row_id, str(st_fail))
check("retry claim 1 (attempts 1->2)", S.claim_retry(row_id, 3) is True, "")
check("retry claim 2 (attempts 2->3)", S.claim_retry(row_id, 3) is True, "")
check("attempt cap stops further retries", S.claim_retry(row_id, 3) is False, "")
S.record_send_result(row_id, S.STATUS_SENT, http_status=201)
check("sent row never retried", S.claim_retry(row_id, 3) is False
      and S.sent_state_for(today)[(sid, today, start, "21CSC202J")][0] == "sent", "")

# stale claim -> orphaned (age-gated!)
sub3 = S.upsert_subscription("dd4444", "https://push.example/ep-3", "pk", "au", "Firefox")
S.claim_send(sub3["id"], today, start, "21MAB206T")
check("fresh claim NOT orphaned", S.finalize_stale_claims(int(time.time()) - 100) == 0, "")
n = S.finalize_stale_claims(int(time.time()) + 100)
st = S.sent_state_for(today)[(sub3["id"], today, start, "21MAB206T")]
check("aged claim becomes orphaned, never retried", n == 1 and st[0] == "orphaned", str(st))

# 7) rate-limit events + receipts
now = int(time.time())
for _ in range(3):
    S.record_event("cc3333", "test_push", "evt")
check("window count", S.count_events("cc3333", "test_push", now - 60) == 3, "")
check("other kind/netid isolated", S.count_events("cc3333", "receipt", now - 60) == 0
      and S.count_events("zz9999", "test_push", now - 60) == 0, "")
check("empty window -> 0", S.count_events("cc3333", "test_push", now + 60) == 0, "")
S.record_event("cc3333", "test_push", "evt", data={"test_id": "abc"})
S.prune_events(now + 1)
check("prune drops old events", S.count_events("cc3333", "test_push", 0) == 0, "")

print("ok  push store" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
