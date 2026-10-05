"""User endpoints spec: 401 style, config/status, subscribe validation +
DB rate limits, settings validation, test-push gating/rate/dead-cleanup,
receipts. pywebpush is mocked (no network)."""
import json, os, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="osrm-push-api-")

import app.app as A
from app import push_store as S

fails = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)

PERSONAL = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
            "Batch": "2025", "Semester": "III SEMESTER", "Section": "A"}
c = A.db()
for n in ("ng2776", "aa1111", "bb2222"):
    c.execute("INSERT OR REPLACE INTO users(netid, password, personal_details_json, last_fetch) "
              "VALUES(?, 'unused', ?, 0)", (n, json.dumps(PERSONAL)))
c.commit(); c.close()

cl = A.app.test_client()
TOK = {n: A.make_session_token(n) for n in ("ng2776", "aa1111", "bb2222")}
def as_user(n): cl.set_cookie("srm_session", TOK[n])
SUB_OK = {"endpoint": "https://fcm.googleapis.com/push/one", "keys": {"p256dh": "BKx", "auth": "au"},
          "ua_label": "Chrome Android"}

# ── 1) auth: every endpoint 401s when logged out ──────────────────────
for path, meth in (("/api/push/status", "GET"), ("/api/push/subscribe", "POST"),
                   ("/api/push/unsubscribe", "POST"), ("/api/push/settings", "POST"),
                   ("/api/push/test", "POST"), ("/api/push/receipt", "POST")):
    r = cl.open(path, method=meth, json={})
    check(f"{path} 401 when logged out", r.status_code == 401 and r.get_json() == {"ok": False, "error": "not logged in"}, str(r.get_json()))

# ── 2) status before configuration ────────────────────────────────────
as_user("ng2776")
r = cl.get("/api/push/status").get_json()
check("unconfigured: says so, no key, not allowlisted flag wrongness",
      r["configured"] is False and r["vapid_public_key"] == "" and r["subscription"] is None, str(r))
r = cl.post("/api/push/subscribe", json=SUB_OK)
check("subscribe while unconfigured -> 409", r.status_code == 409, str(r.get_json()))

# ── 3) configure (fake keys — no real send happens, sender is mocked) ─
os.environ.update({"VAPID_PUBLIC_KEY": "PUBKEY", "VAPID_PRIVATE_KEY": "PRIVKEY",
                   "VAPID_SUBJECT": "mailto:x@y.z", "PUSH_ENABLED": "1"})
r = cl.get("/api/push/status").get_json()
check("configured status exposes public key", r["configured"] is True and r["vapid_public_key"] == "PUBKEY", str(r))
check("status lead choices", r["lead_choices"] == [5, 10, 15, 30], str(r["lead_choices"]))

# ── 4) subscribe: validation + happy path ─────────────────────────────
r = cl.post("/api/push/subscribe", data="not json", content_type="text/plain")
check("non-JSON body -> 400", r.status_code == 400, str(r.status_code))
r = cl.post("/api/push/subscribe", json={"endpoint": "ftp://x", "keys": {"p256dh": "a", "auth": "b"}})
check("non-https endpoint -> 400", r.status_code == 400, str(r.get_json()))
r = cl.post("/api/push/subscribe", json={"endpoint": "https://x"})
check("missing keys -> 400", r.status_code == 400, str(r.status_code))
r = cl.post("/api/push/subscribe", json=SUB_OK)
j = r.get_json()
check("valid subscribe -> ok + endpoint_hash", r.status_code == 200 and j["ok"] and len(j["endpoint_hash"]) == 12, str(j))
r = cl.get("/api/push/status").get_json()
check("status shows subscription + matching hash",
      r["subscription"] is not None and r["endpoint_hash"] == j["endpoint_hash"]
      and r["subscription"]["enabled"] is True and r["subscription"]["lead_minutes"] == 10, str(r))

# ── 5) subscribe DB rate limit (10/hour) ──────────────────────────────
as_user("aa1111")
codes = []
for i in range(11):
    codes.append(cl.post("/api/push/subscribe",
                         json={"endpoint": f"https://fcm.googleapis.com/push/{i}",
                               "keys": {"p256dh": "a", "auth": "b"}}).status_code)
check("10 allowed, 11th -> 429", codes == [200] * 10 + [429], str(codes))

# ── 6) settings: validation + effect ──────────────────────────────────
as_user("ng2776")
check("bad lead -> 400", cl.post("/api/push/settings", json={"lead_minutes": 7}).status_code == 400, "")
check("bad enabled -> 400", cl.post("/api/push/settings", json={"enabled": "yes"}).status_code == 400, "")
check("empty update -> 400", cl.post("/api/push/settings", json={}).status_code == 400, "")
r = cl.post("/api/push/settings", json={"lead_minutes": 15, "enabled": True})
check("valid settings -> ok", r.get_json() == {"ok": True, "updated": 1}, str(r.get_json()))
st = cl.get("/api/push/status").get_json()
check("settings visible in status", st["subscription"]["lead_minutes"] == 15, str(st["subscription"]))
as_user("bb2222")
check("settings without subscription -> 404", cl.post("/api/push/settings", json={"lead_minutes": 5}).status_code == 404, "")

# ── 7) unsubscribe ────────────────────────────────────────────────────
as_user("ng2776")
r = cl.post("/api/push/unsubscribe", json={"endpoint": "https://nope"})
check("wrong endpoint -> removed false", r.get_json()["removed"] is False, str(r.get_json()))
r = cl.post("/api/push/unsubscribe", json={"endpoint": SUB_OK["endpoint"]})
check("own endpoint -> removed true", r.get_json()["removed"] is True, str(r.get_json()))
check("status: no subscription after unsubscribe", cl.get("/api/push/status").get_json()["subscription"] is None, "")

# ── 8) test push: gating, rate, dead cleanup (sender mocked) ──────────
del os.environ["PUSH_ENABLED"]
r = cl.post("/api/push/test")
check("feature off -> 403", r.status_code == 403, str(r.get_json()))
os.environ["PUSH_ENABLED"] = "1"
os.environ["PUSH_ALLOW_NETIDS"] = "zz9999"
r = cl.post("/api/push/test")
check("not allowlisted -> 403", r.status_code == 403, str(r.get_json()))
del os.environ["PUSH_ALLOW_NETIDS"]
r = cl.post("/api/push/test")
check("no subscription -> 400", r.status_code == 400, str(r.get_json()))

as_user("ng2776")
cl.post("/api/push/subscribe", json=SUB_OK)
send_calls = []
def fake_send(job):
    send_calls.append(job)
    job["outcome"] = {"ok": True, "http_status": 201, "dead": False, "retryable": False}
    return job
A.push_send.send_one = fake_send
r = cl.post("/api/push/test")
j = r.get_json()
check("test push ok with 32-hex test_id", r.status_code == 200 and j["ok"] and len(j["test_id"]) == 32, str(j))
check("payload carries test_id + tag", send_calls[0]["payload"]["test_id"] == j["test_id"]
      and send_calls[0]["payload"]["tag"].startswith("test-"), str(send_calls[0]["payload"]))

# dead endpoint on a test push -> subscription deleted, 410
def fake_dead(job):
    job["outcome"] = {"ok": False, "http_status": 410, "dead": True, "retryable": False}
    return job
A.push_send.send_one = fake_dead
r = cl.post("/api/push/test")
check("dead endpoint -> 410 + subscription deleted", r.status_code == 410
      and cl.get("/api/push/status").get_json()["subscription"] is None, str(r.get_json()))
# re-subscribe, then hit the 3/hour cap
cl.post("/api/push/subscribe", json=SUB_OK)
A.push_send.send_one = fake_send
check("3rd test ok", cl.post("/api/push/test").status_code == 200, "")
check("4th test -> 429 (3/hour)", cl.post("/api/push/test").status_code == 429, "")

# ── 9) receipts ───────────────────────────────────────────────────────
check("bad test_id -> 400", cl.post("/api/push/receipt", json={"test_id": "xyz"}).status_code == 400, "")
good_id = "a" * 32
check("valid receipt -> ok", cl.post("/api/push/receipt", json={"test_id": good_id}).get_json() == {"ok": True}, "")
check("receipt recorded", S.count_events("ng2776", "receipt", 0) == 1, "")
for _ in range(29):
    cl.post("/api/push/receipt", json={"test_id": good_id})
check("30/hour receipt cap -> 429", cl.post("/api/push/receipt", json={"test_id": good_id}).status_code == 429, "")

print("ok  push api" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
