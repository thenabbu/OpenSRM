"""Tick endpoint spec: auth (bare 401), dry-run never claims, allowlist
hold, deadline cut-off + next-tick catch-up, idempotency, concurrent ticks."""
import json, os, sys, tempfile, threading, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="osrm-push-tick-")
os.environ["PUSH_TICK_SECRET"] = "s3kr3t-tick"

import app.app as A
from app import metrics as M
from app import push_store as S
from app.push_calc import IST

fails = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)

# ── seed: user + Monday 09:30 class + one subscription ────────────────
PERSONAL = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
            "Batch": "2025", "Semester": "III SEMESTER", "Section": "A"}
c = A.db()
c.execute("INSERT OR REPLACE INTO users(netid, password, personal_details_json, last_fetch) "
          "VALUES('zz9999', 'unused', ?, 0)", (json.dumps(PERSONAL),))
gk = A._group_key(PERSONAL)
c.execute("INSERT OR IGNORE INTO timetable_groups(group_key,program,batch,semester,section) "
          "VALUES(?, 'CSE CC', 2025, 3, 'A')", (gk,))
gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()[0]
c.execute("INSERT INTO timetable_slots(group_id,day,period,subject_code,subject_name,location) "
          "VALUES(?, 'Monday', 1, '21CSC202J', 'Operating Systems', 'Lab C-6/7')", (gid,))
c.commit(); c.close()
sub = S.upsert_subscription("zz9999", "https://fcm.googleapis.com/push/abc", "pk", "au", "Chrome")

NOW = datetime(2026, 10, 5, 9, 25, tzinfo=IST)      # Monday, 5 min before P1
CONF_LIVE = {"enabled": True, "dry_run": False, "allow": set(), "tick_secret": "s3kr3t-tick",
             "private": "PRIV", "public": "PUB", "subject": "mailto:a@b.c", "configured": True}
sent_jobs = []
def fake_batch(jobs, deadline):
    for j in jobs:
        j["outcome"] = {"ok": True, "http_status": 201, "dead": False, "retryable": False}
    sent_jobs.extend(jobs)
    return jobs

def reset_log():
    c = A.db(); c.execute("DELETE FROM push_sent_log"); c.commit(); c.close()

# ── HTTP auth ─────────────────────────────────────────────────────────
cl = A.app.test_client()
r = cl.post("/internal/push/tick")
check("no secret header -> bare 401", r.status_code == 401 and r.data == b"", f"{r.status_code} {r.data!r}")
r = cl.post("/internal/push/tick", headers={"X-Push-Tick": "wrong"})
check("wrong secret -> bare 401", r.status_code == 401 and r.data == b"", f"{r.status_code} {r.data!r}")
r = cl.post("/internal/push/tick", headers={"X-Push-Tick": "s3kr3t-tick"})
check("right secret -> 200 JSON summary", r.status_code == 200 and r.get_json().get("ok") is True
      and r.get_json().get("mode") in ("off", "dry-run", "live"), str(r.get_json()))
saved = os.environ.pop("PUSH_TICK_SECRET")
r = cl.post("/internal/push/tick", headers={"X-Push-Tick": "s3kr3t-tick"})
check("secret unset -> 401 (feature stays off)", r.status_code == 401, str(r.status_code))
os.environ["PUSH_TICK_SECRET"] = saved

# ── dry-run: computes, logs, NEVER claims ─────────────────────────────
reset_log()
res = A._run_tick(now=NOW, conf=dict(CONF_LIVE, enabled=False), send_batch=fake_batch)
check("off mode: due computed", res["mode"] == "off" and res["due"] == 1 and res["audited"] == 1, str(res))
check("off mode: nothing claimed, nothing sent", res["claimed"] == 0 and len(sent_jobs) == 0
      and S.sent_state_for("2026-10-05") == {}, str(res))
res = A._run_tick(now=NOW, conf=dict(CONF_LIVE, dry_run=True), send_batch=fake_batch)
check("dry-run mode: same, still unclaimed", res["mode"] == "dry-run" and res["due"] == 1
      and res["claimed"] == 0 and len(sent_jobs) == 0, str(res))

# ── per-type pref: notify_reminders=0 drops the account before due-calc ──
S.set_settings("zz9999", notify_reminders=False)
res = A._run_tick(now=NOW, conf=CONF_LIVE, send_batch=fake_batch)
check("muted reminders: account excluded (0 due/claimed)",
      res["due"] == 0 and res["claimed"] == 0 and len(sent_jobs) == 0
      and S.sent_state_for("2026-10-05") == {}, str(res))
S.set_settings("zz9999", notify_reminders=True)
res = A._run_tick(now=NOW, conf=CONF_LIVE, send_batch=fake_batch)
check("unmuted: due returns", res["due"] == 1, str(res))
reset_log(); sent_jobs.clear()

# ── live: claim + send + record, then idempotent ──────────────────────
reset_log(); sent_jobs.clear()
res = A._run_tick(now=NOW, conf=CONF_LIVE, send_batch=fake_batch)
check("live: due/claimed/sent", res["due"] == 1 and res["claimed"] == 1 and res["sent"] == 1, str(res))
st = S.sent_state_for("2026-10-05")
check("sent row recorded with 201", list(st.values())[0][0] == "sent", str(st))
check("payload has real countdown + room",
      "in 5 min" in sent_jobs[0]["payload"]["body"] and sent_jobs[0]["payload"]["body"].endswith(" · Lab C-6/7"),
      str(sent_jobs[0]["payload"]))
check("ttl is real seconds to start", sent_jobs[0]["ttl"] == 300, str(sent_jobs[0]["ttl"]))
res2 = A._run_tick(now=NOW, conf=CONF_LIVE, send_batch=fake_batch)
check("second tick: idempotent (0 due, 0 sent)", res2["due"] == 0 and res2["claimed"] == 0 and res2["sent"] == 0, str(res2))

# ── allowlist: held without claiming, sends once allowed ──────────────
reset_log(); sent_jobs.clear()
res = A._run_tick(now=NOW, conf=dict(CONF_LIVE, allow={"zz9990"}), send_batch=fake_batch)
check("not allowlisted -> held, unclaimed", res["held"] == 1 and res["claimed"] == 0 and not sent_jobs
      and S.sent_state_for("2026-10-05") == {}, str(res))
res = A._run_tick(now=NOW, conf=dict(CONF_LIVE, allow={"zz9999"}), send_batch=fake_batch)
check("allowlisted -> sent (held tick did not consume it)", res["sent"] == 1 and len(sent_jobs) == 1, str(res))

# ── deadline: skip without claiming -> next tick catches up ───────────
reset_log(); sent_jobs.clear()
res = A._run_tick(now=NOW, conf=CONF_LIVE, send_batch=fake_batch, deadline_s=-1)
check("deadline passed -> skipped, NOT claimed", res["skipped_deadline"] == 1 and res["claimed"] == 0
      and S.sent_state_for("2026-10-05") == {}, str(res))
res = A._run_tick(now=NOW, conf=CONF_LIVE, send_batch=fake_batch)
check("next tick picks it up (catch-up window open)", res["sent"] == 1, str(res))

# ── concurrent ticks: exactly one send ────────────────────────────────
reset_log(); sent_jobs.clear()
gate = threading.Event()
def slow_batch(jobs, deadline):
    for j in jobs:
        j["outcome"] = {"ok": True, "http_status": 201, "dead": False, "retryable": False}
    sent_jobs.extend(jobs)
    gate.wait(5)          # hold tick A mid-send while tick B runs
    return jobs
out_a = {}
def tick_a(): out_a["res"] = A._run_tick(now=NOW, conf=CONF_LIVE, send_batch=slow_batch)
t = threading.Thread(target=tick_a); t.start()
for _ in range(100):      # wait until A has claimed (inside send_batch)
    if sent_jobs: break
    time.sleep(0.05)
out_b = A._run_tick(now=NOW, conf=CONF_LIVE, send_batch=fake_batch)
gate.set(); t.join(5)
check("tick B sees the claim -> 0 due", out_b["due"] == 0 and out_b["claimed"] == 0, str(out_b))
check("exactly ONE push sent overall", len(sent_jobs) == 1, str(len(sent_jobs)))
check("tick A completed", out_a.get("res", {}).get("sent") == 1, str(out_a))

# ── dead-man metrics: opensrm_push_tick_total + last-success gauge ──────
# (the observability stack scrapes these; no PII may ever enter a label)
M.reset()
A._PUSH_TICK_LAST_OK["ts"] = 0.0

# a successful authenticated tick bumps outcome=ok and stamps the gauge
r = cl.post("/internal/push/tick", headers={"X-Push-Tick": "s3kr3t-tick"})
got_ok = M.get("opensrm_push_tick_total", outcome="ok")
check("tick ok -> opensrm_push_tick_total{outcome=ok} counted",
      r.status_code == 200 and got_ok == 1, f"{r.status_code} count={got_ok}")
check("tick ok -> last-success gauge stamped (>0)",
      A._PUSH_TICK_LAST_OK["ts"] > 0, str(A._PUSH_TICK_LAST_OK["ts"]))

# an unauthenticated (wrong secret) tick must NOT move the dead-man signal:
# an outside prober could otherwise fake scheduler liveness
before_ok, before_ts = got_ok, A._PUSH_TICK_LAST_OK["ts"]
r = cl.post("/internal/push/tick", headers={"X-Push-Tick": "wrong"})
check("wrong-secret tick leaves counter AND gauge untouched",
      r.status_code == 401
      and M.get("opensrm_push_tick_total", outcome="ok") == before_ok
      and A._PUSH_TICK_LAST_OK["ts"] == before_ts,
      f"{r.status_code} ok={M.get('opensrm_push_tick_total', outcome='ok')} ts={A._PUSH_TICK_LAST_OK['ts']}")

# a tick whose _run_tick raises counts outcome=error and does not stamp
real_run, A._PUSH_TICK_LAST_OK["ts"] = A._run_tick, 0.0
def _boom(**kw):
    raise RuntimeError("tick exploded")
A._run_tick = _boom
try:
    import werkzeug.serving  # noqa: F401
    r = cl.post("/internal/push/tick", headers={"X-Push-Tick": "s3kr3t-tick"})
finally:
    A._run_tick = real_run
got_err = M.get("opensrm_push_tick_total", outcome="error")
check("raising tick -> outcome=error counted, gauge NOT stamped",
      r.status_code == 500 and got_err == 1 and A._PUSH_TICK_LAST_OK["ts"] == 0.0,
      f"{r.status_code} error={got_err} ts={A._PUSH_TICK_LAST_OK['ts']}")

# the gauge renders through /internal/metrics (what Prometheus scrapes)
os.environ["METRICS_SECRET"] = "s3kr3t-metrics"
try:
    M.reset()
    M.inc("opensrm_push_tick_total", outcome="ok")
    A._PUSH_TICK_LAST_OK["ts"] = 1792250000.0
    r = cl.get("/internal/metrics", headers={"X-Metrics-Token": "s3kr3t-metrics"})
    body = r.data.decode() if r.status_code == 200 else ""
    check("/internal/metrics exposes the tick counter + gauge",
          r.status_code == 200
          and 'opensrm_push_tick_total{outcome="ok"} 1' in body
          and "opensrm_push_tick_last_success_timestamp_seconds 1792250000.0" in body,
          f"{r.status_code} {body[:200]!r}")
    check("tick metrics carry no PII label (outcome only)",
          'opensrm_push_tick_total{' in body
          and "netid" not in body and "user=" not in body and "ip=" not in body,
          "body contains netid/user/ip")
finally:
    os.environ.pop("METRICS_SECRET", None)
    A._PUSH_TICK_LAST_OK["ts"] = 0.0

print("ok  push tick" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
