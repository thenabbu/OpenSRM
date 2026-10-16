"""State-classes suite — RateLimiter / ProgressTracker / PortalHealth (A18).

Offline, no server, no portal, no DB rows: everything under test is
in-memory state in app/state.py. Self-contained: temp DATA_DIR here.

Contract pinned (block A18 PROOF):
  * TTL pruning on every structure: login/ip attempt maps drop stale keys
    at the cap sweep, preflight dicts evict on admission, the progress map
    prunes abandoned flows on WRITE (old code only dropped the same key on
    a later read — an abandoned login leaked its entry forever), the
    progress read cap drains its own ip buckets
  * thread safety (stress): the per-IP login cap admits EXACTLY 10 under
    8-thread contention (the old unlocked check-then-act over-admits),
    charges are not lost, progress writes don't clobber each other, the
    portal fail counter increments exactly
  * the old module-level names are the SAME objects the classes mutate
    (tests/recipes poke them directly and every method sees the poke)
  * PortalHealth semantics: 3 fails arm a 5-min cooldown, doubling, capped
    at 30; ok() resets; cooldown_remaining clamps at 0
Runner style: check(name, fn) + dynamic TOTAL (test_metrics).
"""
import atexit
import os
import shutil
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

TMP = tempfile.mkdtemp(prefix="osrm-state-")
os.environ["DATA_DIR"] = TMP   # verify76: no test DBs in-tree
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

from app import app as A           # noqa: E402
from app import state as S         # noqa: E402

FAILS = []
TOTAL = [0]


def check(name, fn):
    TOTAL[0] += 1
    try:
        fn()
        print(f"  ok  {name}")
    except AssertionError as e:
        FAILS.append(name)
        print(f"FAIL  {name}: {e}")
    except Exception as e:
        FAILS.append(name)
        print(f"FAIL  {name}: raised {type(e).__name__}: {e}")


# ── 1. aliases: the old module-level names ARE the class-held objects ──────
def t_aliases_are_the_objects():
    assert A._login_attempts is S.rate_limiter.login_attempts
    assert A._ip_attempts is S.rate_limiter.ip_attempts
    assert A._preflight_last is S.rate_limiter.preflight_last
    assert A._preflight_ip is S.rate_limiter.preflight_ip
    assert A._login_progress is S.progress.entries
    assert A._progress_ip is S.progress.reads
    assert A._rate_lock is S.rate_limiter.lock, "budget code must keep the SAME lock object"
    # a direct poke through the alias is seen by the class methods
    A._login_attempts["zzpoke"] = [time.time()] * 3
    assert A._check_rate("zzpoke") is False, "3 charged syncs must deny the 4th"
    assert len(A._login_attempts["zzpoke"]) == 3, "denied admission must not append"
    assert A._check_rate("zzpoke2") is True, "fresh netid must be admitted"
    A._login_attempts.clear()


# ── 2. TTL pruning ─────────────────────────────────────────────────────────
def t_login_map_prunes_at_cap():
    now = time.time()
    stale = {f"zz{i:04d}": [now - 900] for i in range(S._RATE_CAP + 5)}
    A._login_attempts.clear()
    A._login_attempts.update(stale)
    assert A._check_rate("zzfresh") is True
    left = [k for k in A._login_attempts if k.startswith("zz")]
    assert not left, f"stale keys must be pruned at the cap sweep, {len(left)} left"
    A._login_attempts.clear()


def t_ip_map_prunes_at_cap():
    now = time.time()
    stale = {f"10.0.{i // 250}.{i % 250}": [now - 4000] for i in range(S._RATE_CAP + 5)}
    A._ip_attempts.clear()
    A._ip_attempts.update(stale)
    assert A._check_ip_rate("1.2.3.4") is True
    left = [k for k in A._ip_attempts if k != "1.2.3.4"]
    assert not left, f"stale ip keys must be pruned at the cap sweep, {len(left)} left"
    A._ip_attempts.clear()


def t_preflight_dicts_evict_on_admission():
    now = time.time()
    A._preflight_last.clear(); A._preflight_ip.clear()
    A._preflight_last["zzold"] = now - 700
    A._preflight_ip["9.9.9.9"] = [now - 700]
    admit = S.rate_limiter.preflight_admit("zznew", "1.2.3.4", busy=False)
    assert admit is None, f"fresh admission must pass, got {admit!r}"
    assert "zzold" not in A._preflight_last, "stale netid keys must be evicted"
    assert "9.9.9.9" not in A._preflight_ip, "drained ip buckets must be evicted"
    assert S.rate_limiter.preflight_charge("zznew", "1.2.3.4") is None
    assert S.rate_limiter.preflight_charge("zznew", "1.2.3.4") == "cooldown", \
        "second charge inside the 30s per-netid cooldown must be a no-op"
    A._preflight_last.clear(); A._preflight_ip.clear()


def t_progress_write_prunes_abandoned_flows():
    # OLD BUG: entries were only dropped when the SAME key was read again
    # after 10 min — a browser that started a login and never polled leaked
    # its entry forever. Every write now sweeps expired entries.
    old = time.time() - 700
    A._login_progress.clear()
    A._login_progress["deadtoken"] = {"step": "x", "ts": int(old), "pct": 1, "netid": "-"}
    S.progress.set("livetoken", "Reading captcha…", 60, netid="zz9999")
    assert "deadtoken" not in A._login_progress, "abandoned flow must be pruned on write"
    assert A._login_progress["livetoken"]["step"] == "Reading captcha…"
    # the read path still prunes a stale key for its own reader
    A._login_progress["deadtoken2"] = {"step": "x", "ts": int(old), "pct": 1, "netid": "-"}
    assert S.progress.read("deadtoken2") == ("", 0)
    assert "deadtoken2" not in A._login_progress, "stale key must be pruned on read"
    assert S.progress.read("livetoken") == ("Reading captcha…", 60)
    A._login_progress.clear()


def t_progress_read_cap_drains_buckets():
    A._progress_ip.clear()
    assert S.progress.read_ok("5.5.5.5") is True
    A._progress_ip["6.6.6.6"] = [time.time() - 120]   # drained bucket, older window
    assert S.progress.read_ok("5.5.5.5") is True
    assert "6.6.6.6" not in A._progress_ip, "drained ip buckets must be pruned"
    A._progress_ip["7.7.7.7"] = [time.time()] * 30
    assert S.progress.read_ok("7.7.7.7") is False, "30 reads in 60s must be capped"
    A._progress_ip.clear()


# ── 3. thread safety (stress) ──────────────────────────────────────────────
def t_ip_cap_exact_under_contention():
    # 8 threads race check_ip on ONE ip: exactly 10 may be admitted. The
    # pre-refactor unlocked check-then-act (get -> rewrite -> append) loses
    # updates and over-admits; sys.setswitchinterval(1e-6) forces GIL
    # preemption mid-sequence so the race is actually exercised (with the
    # default 5ms interval the critical section is too short to interleave).
    ip = "stress.ip.cap"
    A._ip_attempts.pop(ip, None)
    admitted = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)
    old_iv = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)

    def worker():
        barrier.wait()
        for _ in range(20):
            ok = A._check_ip_rate(ip)
            with lock:
                admitted.append(ok)

    try:
        threads = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
    finally:
        sys.setswitchinterval(old_iv)
    got = sum(1 for x in admitted if x)
    assert got == 10, f"per-IP cap must admit exactly 10 under contention, got {got}"
    assert len(A._ip_attempts[ip]) == 10, f"bucket must hold 10, got {len(A._ip_attempts[ip])}"
    A._ip_attempts.pop(ip, None)


def t_charges_not_lost_under_contention():
    # 8 threads x 25 charges on distinct netids: no lost updates.
    nets = [f"zzc{i:02d}" for i in range(8)]
    A._login_attempts.clear()
    barrier = threading.Barrier(8)

    def worker(n):
        barrier.wait()
        for _ in range(25):
            A._charge_rate(n)

    threads = [threading.Thread(target=worker, args=(n,)) for n in nets]
    [t.start() for t in threads]
    [t.join() for t in threads]
    for n in nets:
        assert len(A._login_attempts[n]) == 25, \
            f"lost charges for {n}: {len(A._login_attempts[n])} != 25"
    A._login_attempts.clear()


def t_progress_writes_no_clobber():
    # 6 threads writing distinct keys + 4 threads hammering ONE key: every
    # distinct key survives with its own value, the shared key exists once.
    barrier = threading.Barrier(10)

    def distinct(i):
        barrier.wait()
        for j in range(20):
            S.progress.set(f"tok{i}_{j}", f"step {i}", j)

    def shared():
        barrier.wait()
        for j in range(50):
            S.progress.set("tokshared", "shared", j)

    A._login_progress.clear()
    threads = [threading.Thread(target=distinct, args=(i,)) for i in range(6)]
    threads += [threading.Thread(target=shared) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(A._login_progress) == 6 * 20 + 1, \
        f"entries lost/clobbered: {len(A._login_progress)} != 121"
    assert A._login_progress["tokshared"]["step"] == "shared"
    A._login_progress.clear()


def t_portal_fail_counter_exact():
    # 8 threads x 3 fails: the counter must land on exactly 24 (a racy
    # += 1 loses increments and delays the cooldown arm).
    ph = A.portal_health
    ph.ok()
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        for _ in range(3):
            ph.fail()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert ph.consecutive_fails == 24, f"fail counter lost increments: {ph.consecutive_fails} != 24"
    ph.ok()


# ── 4. PortalHealth semantics (unchanged escalation, now lock-guarded) ─────
def t_cooldown_escalation_and_reset():
    ph = A.portal_health
    ph.ok()
    assert ph.cooldown_remaining() == 0.0
    ph.fail(); ph.fail()
    assert ph.cooldown_remaining() == 0.0, "2 fails must not arm the cooldown"
    ph.fail()
    rem = ph.cooldown_remaining()
    assert 290 <= rem <= 300, f"3 fails must arm a 5-min cooldown, got {rem}"
    ph.ok()
    assert ph.cooldown_remaining() == 0.0 and ph.consecutive_fails == 0, "ok() resets both fields"
    for _ in range(6):   # 5 -> 10 -> 20 -> 30 (cap) -> 30 (cap)
        ph.fail()
    rem = ph.cooldown_remaining()
    assert 1790 <= rem <= 1800, f"cooldown must cap at 30 min, got {rem}"
    ph.ok()
    assert A._portal_cooldown_remaining() == 0.0, "wrapper reads through to the class"


for name, fn in [
    ("old module-level names are the same objects the classes mutate", t_aliases_are_the_objects),
    ("login-attempt map prunes stale keys at the cap sweep", t_login_map_prunes_at_cap),
    ("ip-attempt map prunes stale keys at the cap sweep", t_ip_map_prunes_at_cap),
    ("preflight dicts evict stale entries on admission; charge closes the race",
     t_preflight_dicts_evict_on_admission),
    ("progress map prunes abandoned flows on WRITE (old: never)", t_progress_write_prunes_abandoned_flows),
    ("progress read cap prunes drained ip buckets", t_progress_read_cap_drains_buckets),
    ("per-IP login cap admits exactly 10 under 8-thread contention", t_ip_cap_exact_under_contention),
    ("charges are not lost under 8-thread contention", t_charges_not_lost_under_contention),
    ("progress writes never clobber distinct keys (stress)", t_progress_writes_no_clobber),
    ("portal fail counter increments exactly under contention", t_portal_fail_counter_exact),
    ("cooldown escalation 5->30min cap + ok() reset, lock-guarded", t_cooldown_escalation_and_reset),
]:
    check(name, fn)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("ok  state-classes suite")
