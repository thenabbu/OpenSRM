"""Sending side: pywebpush behind one bounded pool per tick.

No module-level state that outlives a request (serverless rule): the pool
is created and drained inside send_batch(). Every push is an encrypted
RFC 8291 POST with VAPID (RFC 8292) to the subscription endpoint; this
module never logs the endpoint itself — callers hash it.
"""
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from pywebpush import WebPushException, webpush

log = logging.getLogger("opensrm.push")

SEND_TIMEOUT = 5.0          # seconds per push-service POST
DEFAULT_WORKERS = 8         # matches gunicorn --threads 8; period-boundary burst


def send_one(job):
    """One push. `job` = {sub: subscription row, payload: dict, ttl: int, ...}.
    Returns the job with `outcome` attached: {ok, http_status, dead, retryable}."""
    sub = job["sub"]
    try:
        resp = webpush(
            subscription_info={"endpoint": sub["endpoint"],
                               "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
            data=json.dumps(job["payload"]),
            vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY", ""),
            vapid_claims={"sub": os.environ.get("VAPID_SUBJECT", "")},
            ttl=int(job["ttl"]),
            headers={"Urgency": "high"},
            timeout=SEND_TIMEOUT)
        code = getattr(resp, "status_code", None)
        job["outcome"] = {"ok": bool(code and 200 <= code < 300), "http_status": code,
                          "dead": False, "retryable": not (code and 200 <= code < 300)}
    except WebPushException as ex:
        code = getattr(ex, "status_code", None)
        if code is None and ex.response is not None:
            code = ex.response.status_code
        # 404/410 = subscription is dead, delete it. Other 4xx won't improve
        # on retry (bad request/VAPID) — 5xx/429/timeouts are retryable.
        job["outcome"] = {"ok": False, "http_status": code,
                          "dead": code in (404, 410),
                          "retryable": code is None or code >= 500 or code == 429}
    except Exception as ex:  # timeout / DNS / connection reset — retryable
        job["outcome"] = {"ok": False, "http_status": None, "dead": False,
                          "retryable": True, "error": type(ex).__name__}
    return job


def send_batch(jobs, deadline, workers=DEFAULT_WORKERS):
    """Send `jobs` in a bounded pool; no send STARTS after `deadline`
    (time.monotonic) — whatever is still pending belongs to the next tick.
    Returns jobs with `outcome` attached (deadline-skips get reason=deadline)."""
    done, futures = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for job in jobs:
            if time.monotonic() > deadline:
                job["outcome"] = {"ok": False, "reason": "deadline"}
                done.append(job)
                continue
            futures.append(pool.submit(send_one, job))
        for f in futures:
            done.append(f.result())
    return done
