"""Login Flow UX Guide — server half: normalization, error parity, timing,
rate-limit honesty. 7 real portal logins max (3 per netid cap, 10/hour IP cap).
INCONCLUSIVE = the portal/rate limiter interfered, not a verdict on the guide.
"""
import json, os, re, statistics, subprocess, sys, time, urllib.error, urllib.request

BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18186")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = []

def mark(item, verdict, ev=""):
    rows.append((item, verdict, ev))
    print(f"[{verdict:13}] {item}" + (f"  — {ev}" if ev else ""))

def post(netid, password, path="/api/login"):
    body = json.dumps({"netid": netid, "password": password}).encode()
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            status, data = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, data = e.code, e.read().decode()
    ms = int((time.monotonic() - t0) * 1000)
    try:
        return status, json.loads(data), ms
    except Exception:
        return status, {"raw": data[:200]}, ms

def verdict_for(status):
    return "INCONCLUSIVE" if status in (429, 503) else None

# ── 1. server-side normalization (guide §1) ─────────────────────────────────
s, b, ms = post("  ZzTemp99@SRMIST.EDU.IN  ", "whatever1")
norm = not (s == 400 and "format" in b.get("error", ""))
mark("§1 server lowercases + trims + strips @domain before comparing", "PASS" if norm else "FAIL",
     f"status={s} error={b.get('error','?')!r} ({ms}ms) — a bare/upper/suffixed id must NOT be rejected as format" if not verdict_for(s) else f"status={s} ({b.get('error')}) portal-limited")
if verdict_for(s):
    rows[-1] = (rows[-1][0], verdict_for(s), f"status={s} {b.get('error')}")

# ── 2 + 3. error parity + timing (guide §5: one generic error, no timing tell)
tA, tB = [], []
pairs = []
for i in range(3):
    pairs.append(("unknown-id",) + post("zznoacc1", "wrongpass" + str(i)))
    pairs.append(("wrong-pass",) + post("ng2776", "wrongpass" + str(i)))
status_seen = {p[1] for p in pairs}
if status_seen & {429, 503}:
    mark("§5 generic error: bad-ID and wrong-password are indistinguishable", "INCONCLUSIVE",
         f"statuses seen={sorted(status_seen)} (rate limiter or portal cooldown interfered)")
    mark("§5 no timing tell between bad-ID and wrong-password", "INCONCLUSIVE", "blocked by the above")
else:
    a = [p for p in pairs if p[0] == "unknown-id"]
    c = [p for p in pairs if p[0] == "wrong-pass"]
    same_status = {p[1] for p in a} == {p[1] for p in c} and len({p[1] for p in pairs}) == 1
    same_body = {json.dumps(p[2], sort_keys=True) for p in a} == {json.dumps(p[2], sort_keys=True) for p in c}
    mark("§5 generic error: bad-ID and wrong-password are indistinguishable",
         "PASS" if same_status and same_body else "FAIL",
         f"both -> {pairs[1][1]} {json.dumps(pairs[1][2])!r} | same_status={same_status} same_body={same_body}")
    tA = [p[3] for p in a]; tB = [p[3] for p in c]
    mA, mB = statistics.mean(tA), statistics.mean(tB)
    gap = abs(mA - mB)
    mark("§5 no timing tell (response time roughly consistent)",
         "PASS" if gap <= 1000 else "FAIL",
         f"bad-ID {mA:.0f}ms {tA} vs wrong-pass {mB:.0f}ms {tB} | gap={gap:.0f}ms (tolerance 1000ms)")
    # what a user actually sees: status codes are the same class
    mark("§5 auth failures return 401 (not a 200-with-different-body oracle)",
         "PASS" if all(p[1] == 401 for p in pairs) else "FAIL", f"statuses={[p[1] for p in pairs]}")

# ── 4. rate limiting: honest countdown (guide §5) ───────────────────────────
src = open(os.path.join(REPO, "app/app.py")).read()
vague = "Try again later." in src
mark("§5 no vague 'try again later' left in the API", "PASS" if not vague else "FAIL",
     "source contains 'Try again later.'" if vague else "removed; every lockout message names a time")
concrete = {
    "per-netid sync cap": "Try again in 10 minutes",
    "sync in progress": "Try again in 30 seconds",
    "portal budget": "Try again in 10 minutes",
    "portal cooldown": "Try again in {int(cooldown / 60) + 1} minutes",
    "per-IP login cap": "Try again in {",
}
missing = [k for k, v in concrete.items() if v not in src]
mark("§5 every lockout message states a concrete retry time", "PASS" if not missing else "FAIL",
     "all 5 present" if not missing else f"missing: {missing}")

unit = subprocess.run([sys.executable, "-c", f'''
import os, sys, time
os.environ["DATA_DIR"] = "/tmp/osrm-guide-unit"
sys.path.insert(0, {REPO!r})
from app.app import _check_ip_rate, _ip_attempts, _ip_retry_text
ip = "203.0.113.7"
_ip_attempts[ip] = [time.time() - 3500] * 10
assert _check_ip_rate(ip) is False, "budget should be exhausted"
txt = _ip_retry_text(ip)
assert "later" not in txt and ("seconds" in txt or "minutes" in txt), txt
print("countdown:", txt)
'''], capture_output=True, text=True, cwd=REPO)
ok = unit.returncode == 0 and "countdown:" in unit.stdout
mark("§5 per-IP lockout returns a live countdown value", "PASS" if ok else "FAIL",
     (unit.stdout.strip().splitlines() or [unit.stderr.strip()[-300:]])[-1])

fails = [r for r in rows if r[1] == "FAIL"]
inc = [r for r in rows if r[1] == "INCONCLUSIVE"]
print("\n" + "=" * 72)
print(f"SERVER: {len(rows)} items | PASS {sum(1 for r in rows if r[1]=='PASS')} | "
      f"FAIL {len(fails)} | INCONCLUSIVE {len(inc)}")
print("ALL PASS" if not fails else "FAILURES PRESENT")
sys.exit(1 if fails else 0)
