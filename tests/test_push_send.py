"""Sender spec with pywebpush mocked (no network): outcomes, dead-endpoint
cleanup signals, retryability, VAPID/TTL/Urgency kwargs, deadline cut-off."""
import os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="osrm-push-send-"))

from pywebpush import WebPushException

from app import push_send as PS

fails = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)

SUB = {"id": 5, "netid": "ng2776", "endpoint": "https://fcm.googleapis.com/x/y",
       "p256dh": "BKx", "auth": "au"}
def job():
    return {"sub": SUB, "row_id": 9, "payload": {"title": "t", "body": "b"}, "ttl": 600}

class Resp:
    def __init__(self, code): self.status_code = code

# 1) success path + exact kwargs the RFCs require
seen = {}
def fake_ok(subscription_info, data, vapid_private_key=None, vapid_claims=None,
            ttl=None, headers=None, timeout=None, **kw):
    seen.update({"info": subscription_info, "data": data, "key": vapid_private_key,
                 "claims": vapid_claims, "ttl": ttl, "headers": headers, "timeout": timeout})
    return Resp(201)
PS.webpush = fake_ok
os.environ["VAPID_PRIVATE_KEY"] = "FAKEPRIV"
os.environ["VAPID_SUBJECT"] = "mailto:navya@example.com"
out = PS.send_one(job())["outcome"]
check("2xx -> ok", out == {"ok": True, "http_status": 201, "dead": False, "retryable": False}, str(out))
check("endpoint + keys passed", seen["info"]["endpoint"].startswith("https://") and seen["info"]["keys"]["p256dh"] == "BKx", str(seen["info"]))
check("TTL forwarded", seen["ttl"] == 600, str(seen["ttl"]))
check("Urgency: high", seen["headers"] == {"Urgency": "high"}, str(seen["headers"]))
check("per-send timeout", seen["timeout"] == PS.SEND_TIMEOUT, str(seen["timeout"]))
check("VAPID sub is a mailto", seen["claims"]["sub"].startswith("mailto:"), str(seen["claims"]))
check("VAPID private key from env", seen["key"] == "FAKEPRIV", str(seen["key"]))
check("payload is the message JSON", '"title"' in seen["data"], seen["data"][:80])

# 2) dead subscription (410) -> delete signal, NOT retryable
class DeadExc(WebPushException):
    status_code = 410
def fake_410(**kw): raise DeadExc("gone")
PS.webpush = fake_410
out = PS.send_one(job())["outcome"]
check("410 -> dead cleanup, no retry", out["dead"] is True and out["retryable"] is False and out["http_status"] == 410, str(out))

# 3) 503 -> retryable
class SvExc(WebPushException):
    status_code = 503
def fake_503(**kw): raise SvExc("unavailable")
PS.webpush = fake_503
out = PS.send_one(job())["outcome"]
check("503 -> retryable, not dead", out["retryable"] is True and out["dead"] is False, str(out))

# 4) 429 -> retryable; other 4xx -> not retryable.
# WebPushException.status_code is a read-only property on the instance, so
# the code rides as a CLASS attribute (same trick as DeadExc/SvExc above).
def _exc(code):
    return type(f"E{code}", (WebPushException,), {"status_code": code})("bad")
PS.webpush = lambda **kw: (_ for _ in ()).throw(_exc(429))
check("429 -> retryable", PS.send_one(job())["outcome"]["retryable"] is True, "")
PS.webpush = lambda **kw: (_ for _ in ()).throw(_exc(400))
check("400 -> not retryable", PS.send_one(job())["outcome"]["retryable"] is False, "")

# 5) transport error (timeout) -> retryable
def fake_timeout(**kw): raise TimeoutError("slow")
PS.webpush = fake_timeout
out = PS.send_one(job())["outcome"]
check("timeout -> retryable with error name", out["retryable"] and out.get("error") == "TimeoutError", str(out))

# 6) send_batch honors the deadline without calling send_one
called = []
PS.send_one = lambda j: called.append(j) or j
res = PS.send_batch([job(), job()], deadline=-1)
check("deadline passed -> all skipped", len(res) == 2 and all(r["outcome"]["reason"] == "deadline" for r in res), str([r["outcome"] for r in res]))
check("deadline passed -> send_one never called", called == [], str(len(called)))
import time as _t
res = PS.send_batch([job()], deadline=_t.monotonic() + 5)
check("deadline open -> send_one invoked", len(called) == 1, str(len(called)))

print("ok  push send" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)


def test_subject_bare_email_is_prefixed():
    """Regression: a bare (non-URI) VAPID_SUBJECT must be normalized to
    mailto: before it reaches py_vapid, else signing dies with
    "Missing 'sub'" before any HTTP (prod incident 2026-10-05)."""
    saved = os.environ.get("VAPID_SUBJECT")
    try:
        os.environ["VAPID_SUBJECT"] = "128571614+dev@example.com"
        job = {"sub": {"endpoint": "https://fcm.example/x", "p256dh": "B", "auth": "a"},
               "payload": {"title": "t", "body": "b"}, "ttl": 60}
        sent = []
        push_send.webpush = lambda **kw: (sent.append(kw), FakeResp())[1]
        push_send.send_one(job)
        assert sent[0]["vapid_claims"]["sub"] == "mailto:128571614+dev@example.com", \
            sent[0]["vapid_claims"]
        # already-mailto stays untouched (idempotent)
        os.environ["VAPID_SUBJECT"] = "mailto:kept@example.com"
        sent.clear()
        push_send.send_one(job)
        assert sent[0]["vapid_claims"]["sub"] == "mailto:kept@example.com", \
            sent[0]["vapid_claims"]
        # .env whitespace is stripped
        os.environ["VAPID_SUBJECT"] = "mailto:spaced@example.com  \n"
        sent.clear()
        push_send.send_one(job)
        assert sent[0]["vapid_claims"]["sub"] == "mailto:spaced@example.com", \
            sent[0]["vapid_claims"]
    finally:
        if saved is None:
            os.environ.pop("VAPID_SUBJECT", None)
        else:
            os.environ["VAPID_SUBJECT"] = saved
