"""Push notifications: config, the cron tick, and the subscription API.

Extracted from app/app.py (facade pump, cycle F). One feature, one file:

  config     VAPID keys / allow-list / dry-run, read per call so ops flips them
             without a reboot, and _endpoint_hash so a capability URL is never
             logged in full.
  the tick   _run_tick: claim due subscriptions, send, record outcomes. Driven
             by POST /internal/push/tick from a hosted cron, not by a scheduler
             inside the app.
  the API    subscribe/unsubscribe/status/settings/test/receipt for the browser.

The metric probes next to it (_push_tick_last_ok_ts, _proc_*, _db_stat) are NOT
here: they are observability and live in app/observability.py.
"""
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import request

from . import metrics, push_calc, push_send, push_store
from .auth import get_current_user
from .db import (
    group_ids_for,
    prune_push_sent_log,
    slots_for_groups,
    users_group_keys,
)
from .logging_setup import log_with_kv
from .observability import _PUSH_TICK_LAST_OK
from .portal.parsers.common import _group_key
from .reqctx import _client_ip
from .views.attendance import _bare

log = logging.getLogger("opensrm")


def _db_path():
    """The live DB path. app.DB_PATH is a mutable global (tests repoint it),
    so read it from the facade at call time rather than importing a copy."""
    from .app import DB_PATH
    return DB_PATH


PUSH_TICK_HEADER = "X-Push-Tick"
TICK_DEADLINE_S = 20.0       # cron-job.org's hard budget is ~30s; keep 10s margin
STALE_CLAIM_S = 120          # claims older than this with no outcome -> orphaned
log_push = logging.getLogger("opensrm.push")


def _push_conf():
    env_b = lambda k: os.environ.get(k, "").strip().lower() in ("1", "true", "yes")
    priv = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    pub = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    sub = os.environ.get("VAPID_SUBJECT", "").strip()
    return {
        "enabled": env_b("PUSH_ENABLED"),
        "dry_run": env_b("PUSH_DRY_RUN"),
        "allow": {n.strip().lower() for n in os.environ.get("PUSH_ALLOW_NETIDS", "").split(",") if n.strip()},
        "tick_secret": os.environ.get("PUSH_TICK_SECRET", ""),
        "private": priv, "public": pub, "subject": sub,
        "configured": bool(priv and pub and sub),
    }


def _endpoint_hash(endpoint):
    """Capability URL must never be logged in full — short hash prefix only."""
    return hashlib.sha256(endpoint.encode()).hexdigest()[:12]


def _push_groups(netids):
    """netid -> group_key from stored personal details (one query)."""
    if not netids:
        return {}
    out = {}
    for r in users_group_keys(netids):
        try:
            pd = json.loads(r[1]) if r[1] else {}
        except (ValueError, TypeError):
            pd = {}
        out[r[0]] = _group_key(pd)
    return out


def _push_timetable(group_keys):
    """{group_key: {day: {period: {code,name,location}}}} for the given groups."""
    group_keys = [g for g in group_keys if g]
    if not group_keys:
        return {}
    gids = group_ids_for(group_keys)
    out = {}
    if gids:
        for r in slots_for_groups(list(gids)):
            day = out.setdefault(gids[r[0]], {}).setdefault(r[1], {})
            day[r[2]] = {"code": r[3] or "", "name": r[4] or "", "location": r[5] or ""}
    return out


def _run_tick(now=None, conf=None, send_batch=None, deadline_s=TICK_DEADLINE_S):
    """One tick: compute due from LIVE data, claim, send, record.

    Stateless and idempotent: overlapping ticks race only on the sent-log
    claim (one winner), a skipped tick just widens the catch-up window
    (due stays open until the class starts). Injectables (now/conf/
    send_batch/deadline_s) exist so tests can drive the clock and the
    network without touching either.
    """
    conf = conf if conf is not None else _push_conf()
    send_batch = send_batch or push_send.send_batch
    now = now or datetime.now(ZoneInfo("Asia/Kolkata"))
    t0 = time.monotonic()
    deadline = t0 + deadline_s
    local_date = now.strftime("%Y-%m-%d")
    mode = "off" if not conf["enabled"] else ("dry-run" if conf["dry_run"] else "live")
    stats = {"mode": mode, "due": 0, "claimed": 0, "sent": 0, "failed": 0,
             "dead": 0, "held": 0, "audited": 0, "skipped_deadline": 0, "orphaned": 0}
    # Crash recovery: a claim stuck without an outcome is finalized (never
    # retried — at-most-once). Fresh claims are inside their send window.
    stats["orphaned"] = push_store.finalize_stale_claims(int(time.time()) - STALE_CLAIM_S)

    subs_rows = push_store.list_subscriptions(enabled_only=True)
    # per-type pref: a muted account is dropped before due-calc (its classes
    # are never computed, so a mute can't leak into stats or claims)
    subs_rows = [s for s in subs_rows if s["notify_reminders"]]
    groups = _push_groups({s["netid"] for s in subs_rows})
    subs = [push_calc.Sub(id=s["id"], netid=s["netid"], group_key=groups.get(s["netid"]),
                          lead_minutes=s["lead_minutes"]) for s in subs_rows]
    tt = _push_timetable(groups.values())
    sent = push_store.sent_state_for(local_date)
    due = push_calc.due_reminders(now, subs, tt, sent)
    stats["due"] = len(due)

    can_send = mode == "live" and conf["configured"]
    jobs = []
    for rem in due:
        sub_row = next(s for s in subs_rows if s["id"] == rem.sub.id)
        allowed = not conf["allow"] or rem.sub.netid.lower() in conf["allow"]
        if not can_send:
            # audit only: never claim (a dry-run/off tick must not consume
            # the reminder the real send is still going to make)
            stats["audited"] += 1
            log_with_kv(log_push, logging.INFO, "push audit",
                        mode=mode, netid=rem.sub.netid, code=rem.block.code,
                        starts=rem.block.start.strftime("%H:%M"), retry=rem.retry)
            continue
        if not allowed:
            stats["held"] += 1   # allowlist holds it; send happens on a later tick
            continue
        if time.monotonic() > deadline:
            stats["skipped_deadline"] += 1
            continue
        if rem.retry:
            if not push_store.claim_retry(rem.row_id, push_calc.MAX_ATTEMPTS):
                continue  # another tick took the retry
            row_id = rem.row_id
        else:
            if not push_store.claim_send(rem.sub.id, local_date, rem.block.start_epoch, rem.block.code):
                continue  # concurrent tick claimed first
            row_id = push_store.sent_row_id(rem.sub.id, local_date, rem.block.start_epoch, rem.block.code)
            if row_id is None:  # theoretical race with deletion
                continue
        stats["claimed"] += 1
        jobs.append({"rem": rem, "sub": sub_row, "row_id": row_id,
                     "payload": rem.message(now), "ttl": rem.ttl})

    for job in (send_batch(jobs, deadline) if jobs else []):
        oc = job.get("outcome") or {}
        row_id, sub_row, rem = job["row_id"], job["sub"], job["rem"]
        host = urlparse(sub_row["endpoint"]).netloc
        if oc.get("reason") == "deadline":
            push_store.record_send_result(row_id, push_store.STATUS_SKIPPED)
            stats["skipped_deadline"] += 1
            continue
        if oc.get("ok"):
            push_store.record_send_result(row_id, push_store.STATUS_SENT, oc.get("http_status"))
            push_store.record_subscription_result(sub_row["id"], True, oc.get("http_status"))
            stats["sent"] += 1
            status = "sent"
        elif oc.get("dead"):
            push_store.record_send_result(row_id, push_store.STATUS_FAILED, oc.get("http_status"))
            push_store.delete_subscription_by_id(sub_row["id"])
            stats["dead"] += 1
            status = "dead_cleanup"
        else:
            final = push_store.STATUS_FAILED if oc.get("retryable") else push_store.STATUS_SKIPPED
            push_store.record_send_result(row_id, final, oc.get("http_status"))
            push_store.record_subscription_result(sub_row["id"], False, oc.get("http_status"))
            stats["failed"] += 1
            status = final
        log_with_kv(log_push, logging.INFO, "push send", netid=sub_row["netid"], host=host,
                    endpoint=_endpoint_hash(sub_row["endpoint"]), http=oc.get("http_status"),
                    status=status, code=rem.block.code, ttl=job["ttl"])
    stats.pop("due_pass", None)
    push_store.prune_events(int(time.time()) - 3 * 3600)   # keep the rate table tiny
    # audit R1: push_sent_log retention — 30d covers the window the dashboards
    # read. usage_events retention moved to _prune_usage_events (env-config,
    # default 365d, at most once a day) so a per-minute tick stops paying it.
    try:
        # Retention is relative to the tick's OWN clock, not wall-clock: the
        # tick already takes `now`, and a row's local_date comes from that same
        # clock. Pruning against time.time() made the horizon drift away from
        # the rows the tick itself writes, which is what turned the push_tick
        # suite into a 30-day time bomb (rows dated NOW fell outside a horizon
        # computed from today).
        _horizon = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        prune_push_sent_log(_horizon)
    except Exception as e:
        log_push.warning("log retention prune failed: %r", e)
    stats["took_ms"] = int((time.monotonic() - t0) * 1000)
    log_with_kv(log_push, logging.INFO, "push tick", **stats)
    return {"ok": True, **stats}


def push_tick():
    """The every-minute tick scheduler (the Hermes cron job opensrm-push-tick;
    cron-job.org is the kept alternative scheduler, see docs/push.md) fires
    this. Secret header, no session; wrong/missing secret => bare 401 with
    no detail (nothing to probe)."""
    conf = _push_conf()
    got = request.headers.get(PUSH_TICK_HEADER, "")
    # audit run-1 (#16): hmac.compare_digest raises TypeError on non-ASCII
    # str — one byte >= 0x80 in the header turned the documented bare 401
    # into an unauthenticated 500 + ERROR alert. Compare UTF-8 bytes: a
    # non-ASCII header can never equal an ASCII secret; a lone surrogate
    # raises UnicodeEncodeError -> mismatch (fail closed).
    try:
        tick_ok = hmac.compare_digest(got.encode("utf-8"),
                                       conf["tick_secret"].encode("utf-8"))
    except UnicodeEncodeError:
        tick_ok = False
    if not conf["tick_secret"] or not tick_ok:
        log_with_kv(log_push, logging.WARNING, "tick auth failed", ip=_client_ip())
        return _bare(401, "push tick auth failed — secret missing or wrong")
    # auth-failed ticks deliberately do NOT touch the dead-man signal: an
    # unauthenticated prober must never be able to move a metric.
    try:
        res = _run_tick(conf=conf)
    except Exception:
        metrics.inc("opensrm_push_tick_total", outcome="error")
        raise
    metrics.inc("opensrm_push_tick_total", outcome="ok")
    _PUSH_TICK_LAST_OK["ts"] = time.time()
    return res


def _push_401():
    return {"ok": False, "error": "not logged in"}, 401


def _push_bad(msg, code=400):
    return {"ok": False, "error": msg}, code


# audit run-1 (#4): client-supplied push endpoints are fetched server-side by
# pywebpush — scheme+length validation alone made that an SSRF + upstream-status
# oracle. Known push-service host suffixes only; re-enforced at send time.
_PUSH_HOST_SUFFIXES = ("fcm.googleapis.com", "web.push.apple.com",
                       "updates.push.services.mozilla.com")
MAX_PUSH_SUBSCRIPTIONS = 8   # per netid — one account, a handful of devices


def _push_endpoint_allowed(endpoint):
    from urllib.parse import urlparse
    host = (urlparse(endpoint).hostname or "").lower()
    # suffix check only: a DNS pre-check adds latency + a TOCTOU gap and
    # blocks nothing the suffix list doesn't (attackers can't own a suffix)
    return any(host == s or host.endswith("." + s) for s in _PUSH_HOST_SUFFIXES)


def push_status():
    netid = get_current_user()
    if not netid:
        return _push_401()
    conf = _push_conf()
    subs = push_store.list_subscriptions(netid=netid, enabled_only=False)
    row = subs[0] if subs else None
    return {"ok": True,
            "configured": conf["configured"],
            "enabled": conf["enabled"],
            "dry_run": conf["dry_run"],
            "allowlisted": not conf["allow"] or netid.lower() in conf["allow"],
            "vapid_public_key": conf["public"] if conf["configured"] else "",
            "endpoint_hash": _endpoint_hash(row["endpoint"]) if row else None,
            "subscription": ({"lead_minutes": row["lead_minutes"],
                              "enabled": bool(row["enabled"]),
                              "notify_reminders": bool(row["notify_reminders"]),
                              "notify_exams": bool(row["notify_exams"]),
                              "created_at": row["created_at"]} if row else None),
            "lead_choices": list(push_calc.LEAD_CHOICES)}


def push_subscribe():
    netid = get_current_user()
    if not netid:
        return _push_401()
    conf = _push_conf()
    if not conf["configured"]:
        return _push_bad("push not configured", 409)
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return _push_bad("invalid request — Content-Type must be application/json")
    endpoint, keys = d.get("endpoint"), d.get("keys")
    p256dh = keys.get("p256dh") if isinstance(keys, dict) else None
    auth = keys.get("auth") if isinstance(keys, dict) else None
    if (not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 4096
            or not isinstance(p256dh, str) or not p256dh or len(p256dh) > 512
            or not isinstance(auth, str) or not auth or len(auth) > 512):
        return _push_bad("invalid subscription")
    if not _push_endpoint_allowed(endpoint):
        # audit run-1 (#4): the server would POST to whatever host this names
        return _push_bad("invalid subscription — not a known push service")
    if push_store.count_events(netid, "subscribe", int(time.time()) - 3600) >= 10:
        return _push_bad("too many subscription updates (10/hour)", 429)
    if push_store.count_subscriptions(netid) >= MAX_PUSH_SUBSCRIPTIONS:
        # audit run-1 (#11): per-account row cap — N rows = N duplicate sends
        return _push_bad(f"too many registered devices ({MAX_PUSH_SUBSCRIPTIONS})", 429)
    row = push_store.upsert_subscription(netid, endpoint, p256dh, auth,
                                         str(d.get("ua_label", ""))[:64])
    push_store.record_event(netid, "subscribe", _endpoint_hash(endpoint))
    return {"ok": True, "lead_minutes": row["lead_minutes"],
            "endpoint_hash": _endpoint_hash(endpoint)}


def push_unsubscribe():
    netid = get_current_user()
    if not netid:
        return _push_401()
    d = request.get_json(silent=True)
    endpoint = d.get("endpoint") if isinstance(d, dict) else None
    if not isinstance(endpoint, str) or not endpoint:
        return _push_bad("endpoint required")
    removed = push_store.remove_subscription(netid, endpoint)
    return {"ok": True, "removed": removed}


def push_settings():
    netid = get_current_user()
    if not netid:
        return _push_401()
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return _push_bad("invalid request — Content-Type must be application/json")
    lead = d.get("lead_minutes")
    enabled = d.get("enabled")
    n_rem, n_exm = d.get("notify_reminders"), d.get("notify_exams")
    if lead is None and enabled is None and n_rem is None and n_exm is None:
        return _push_bad("nothing to update")
    if lead is not None and lead not in push_calc.LEAD_CHOICES:
        return _push_bad(f"lead_minutes must be one of {', '.join(map(str, push_calc.LEAD_CHOICES))}")
    if enabled is not None and not isinstance(enabled, bool):
        return _push_bad("enabled must be true or false")
    if n_rem is not None and not isinstance(n_rem, bool):
        return _push_bad("notify_reminders must be true or false")
    if n_exm is not None and not isinstance(n_exm, bool):
        return _push_bad("notify_exams must be true or false")
    n = push_store.set_settings(netid, lead_minutes=lead, enabled=enabled,
                                notify_reminders=n_rem, notify_exams=n_exm)
    if n == 0:
        return _push_bad("no subscription for this account", 404)
    return {"ok": True, "updated": n}


def push_test():
    """Send one real notification to this account's device (receipts prove
    arrival server-side). Rate-limited; works only when the feature is on."""
    netid = get_current_user()
    if not netid:
        return _push_401()
    conf = _push_conf()
    if not conf["configured"]:
        return _push_bad("push not configured", 409)
    if not conf["enabled"]:
        return _push_bad("reminders are disabled", 403)
    if conf["allow"] and netid.lower() not in conf["allow"]:
        return _push_bad("reminders are not enabled for your account yet", 403)
    if push_store.count_events(netid, "test_push", int(time.time()) - 3600) >= 3:
        return _push_bad("test notifications are limited to 3 per hour", 429)
    subs = push_store.list_subscriptions(netid=netid)
    if not subs:
        return _push_bad("no subscription — enable reminders first")
    test_id = secrets.token_hex(16)
    push_store.record_event(netid, "test_push", test_id)   # count BEFORE sending
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    payload = {"title": "OpenSRM test",
               "body": f"Test notification · {now:%H:%M}",
               "tag": f"test-{test_id}", "test_id": test_id, "url": "/"}
    job = push_send.send_one({"sub": subs[0], "payload": payload, "ttl": 600})
    oc = job["outcome"]
    if not oc.get("ok"):
        # audit 2026-10-07: the 3 prod push-test 502s (Oct 5 VAPID) and the
        # 410 row deletion left only "status=502 duration_ms=10" — the
        # outcome was never logged anywhere.
        log_with_kv(log_push, logging.WARNING, "push test failed",
                    netid=netid, http=oc.get("http_status"),
                    dead=bool(oc.get("dead")), err=(oc.get("error") or "")[:120])
    if oc.get("ok"):
        return {"ok": True, "test_id": test_id}
    if oc.get("dead"):
        push_store.delete_subscription_by_id(subs[0]["id"])
        return _push_bad("this device's subscription expired — turn reminders off and on again", 410)
    # audit run-1 (#4): upstream status code must not be reflected — it turns
    # the server into a status oracle for whatever endpoint was stored.
    # Full detail goes to the log line above.
    return _push_bad("push service error — try again later", 502)


def push_receipt():
    """The SW posts this when a test notification actually displayed —
    Navya's server-side proof of device delivery (esp. iOS)."""
    netid = get_current_user()
    if not netid:
        return _push_401()
    d = request.get_json(silent=True)
    test_id = d.get("test_id") if isinstance(d, dict) else None
    if not isinstance(test_id, str) or not re.fullmatch(r"[0-9a-f]{32}", test_id):
        return _push_bad("invalid test_id")
    if push_store.count_events(netid, "receipt", int(time.time()) - 3600) >= 30:
        return _push_bad("too many receipts (30/hour)", 429)
    push_store.record_event(netid, "receipt", test_id)
    return {"ok": True}
