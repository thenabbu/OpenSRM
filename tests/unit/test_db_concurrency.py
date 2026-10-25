#!/usr/bin/env python3
"""Unit: db() connection policy — busy timeout + SQLITE_JOURNAL_MODE knob.

Under gunicorn gthread (1 worker, 8 threads) concurrent requests share one
SQLite file; a slow uncommitted write used to starve the next writer past
python's 5s default busy timeout and surface as `database is locked`.
connect() (app/db.py) is the single connection factory — migrations boot and
push_store.get_conn() both route through it — so this suite pins its policy:

  1. every connection waits up to 10s for a lock (old default: 5s)
  2. a 6s held write lock no longer fails a second writer (red baseline:
     a raw sqlite3.connect(timeout=5) writer DOES fail against the same
     hold — proving the 5s default was the defect)
  3. thread stress: writers on usage_events + readers on cookies, zero
     locked errors
  4. SQLITE_JOURNAL_MODE env: default delete (today's prod mode); wal ->
     WAL + synchronous=NORMAL; flip back works (journal_mode persists in
     the file, so db() sets it explicitly on every connect); invalid
     value falls back to delete, never fails boot

Self-contained: fresh DATA_DIR, migrations run at import. No server,
no network.
"""
import os
import subprocess
import sys
import tempfile
import threading
import time

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="dbconc-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.app import SQLITE_TIMEOUT_SECS, db  # noqa: E402  (import runs init_db)
import app.push_store as push_store  # noqa: E402

fails = []

def check(name, cond, extra=""):
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        fails.append(name)

def child_pragmas(data_dir, journal_env):
    """Boot the app in a child process with the given env; print its PRAGMAs.

    Children are used because the journal mode is read once at import —
    a same-process reload would re-run module side effects.
    """
    env = dict(os.environ)
    env["DATA_DIR"] = data_dir
    if journal_env is None:
        env.pop("SQLITE_JOURNAL_MODE", None)
    else:
        env["SQLITE_JOURNAL_MODE"] = journal_env
    code = (
        "import os, sys; sys.path.insert(0, " + repr(os.path.join(os.path.dirname(__file__), "..", "..")) + ");"
        "import app.app as A;"
        "c = A.db();"
        "print(c.execute('PRAGMA journal_mode').fetchone()[0],"
        "      c.execute('PRAGMA synchronous').fetchone()[0])"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, timeout=120)
    line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    return line, out.returncode

# ── 1. the timeout knob ────────────────────────────────────────────────
check("db() constant is 10s", SQLITE_TIMEOUT_SECS == 10, str(SQLITE_TIMEOUT_SECS))
c = db()
bt = c.execute("PRAGMA busy_timeout").fetchone()[0]
check("db() busy_timeout = 10000ms", bt == 10000, str(bt))
c.close()
pbt = push_store.get_conn().execute("PRAGMA busy_timeout").fetchone()[0]
check("push_store.get_conn() busy_timeout = 10000ms (routes through connect())",
      pbt == 10000, str(pbt))

# ── 2. deterministic red test: 6s held write lock ───────────────
# The lock holder owns its connection inside its own thread (sqlite3
# objects are thread-bound by default): open, uncommitted INSERT (holds
# the write lock), signal, sleep 6s, commit, close.
DB_FILE = os.path.join(os.environ["DATA_DIR"], "srm.db")
def hold_lock(acquired, hold_s, tag):
    c = sqlite3.connect(DB_FILE, timeout=5)
    c.execute("INSERT INTO usage_events(day, user, event) VALUES(?,?,?)",
              ("2026-10-15", "zz9999", tag))
    acquired.set()
    time.sleep(hold_s)
    c.commit()
    c.close()

import sqlite3
acq = threading.Event()
hold = threading.Thread(target=hold_lock, args=(acq, 6, "hold"))
hold.start()
acq.wait(10)
t0 = time.monotonic()
try:
    w = db()  # the guarded path: must wait out the 6s hold
    w.execute("INSERT INTO usage_events(day, user, event) VALUES(?,?,?)",
              ("2026-10-15", "zz9999", "writer"))
    w.commit()
    w.close()
    wait_s = time.monotonic() - t0
    check("second writer succeeds against a 6s lock hold", True)
    check("it waited past the old 5s default (> 5s)", wait_s > 5, f"waited {wait_s:.2f}s")
except Exception as e:
    check("second writer succeeds against a 6s lock hold", False, repr(e))
    check("it waited past the old 5s default (> 5s)", False, "writer failed")
hold.join()

# red baseline against the SAME hold shape: python’s old 5s default fails.
acq = threading.Event()
hold = threading.Thread(target=hold_lock, args=(acq, 6, "hold2"))
hold.start()
acq.wait(10)
try:
    raw = sqlite3.connect(DB_FILE, timeout=5)
    raw.execute("INSERT INTO usage_events(day, user, event) VALUES(?,?,?)",
                ("2026-10-15", "xx0001", "raw"))
    raw.commit()
    raw.close()
    check("raw 5s-default writer still fails against the same hold (defect baseline)", False, "raw writer unexpectedly succeeded")
except sqlite3.OperationalError as e:
    check("raw 5s-default writer still fails against the same hold (defect baseline)",
          "locked" in str(e), repr(e))
hold.join()

# ── 3. thread stress: writers on usage_events, readers on cookies ─────
errors = []
NWR, NRD, INS, SEL = 6, 4, 12, 40
def writer(i):
    try:
        c = db()
        for n in range(INS):
            c.execute("INSERT INTO usage_events(day, user, event) VALUES(?,?,?)",
                      ("2026-10-15", "zz9999", f"stress-{i}-{n}"))
            c.commit()
        c.close()
    except Exception as e:
        errors.append(("writer", i, repr(e)))
def reader(i):
    try:
        c = db()
        for _ in range(SEL):
            c.execute("SELECT COUNT(*) FROM cookies").fetchone()
        c.close()
    except Exception as e:
        errors.append(("reader", i, repr(e)))
threads = [threading.Thread(target=writer, args=(i,)) for i in range(NWR)] + \
          [threading.Thread(target=reader, args=(i,)) for i in range(NRD)]
for t in threads: t.start()
for t in threads: t.join()
locked = [e for e in errors if "locked" in e[2]]
check("thread stress: zero locked errors", not locked, str(locked[:3]))
check("thread stress: zero other errors", not errors, str(errors[:3]))
c = db()
n = c.execute("SELECT COUNT(*) FROM usage_events WHERE event LIKE 'stress-%'").fetchone()[0]
c.close()
check("all stress writes committed", n == NWR * INS, str(n))

# ── 4. SQLITE_JOURNAL_MODE knob ───────────────────────────────────────
fresh = tempfile.mkdtemp(prefix="dbconc-mode-")
line, rc = child_pragmas(fresh, None)
check("default boot: journal delete, synchronous FULL (2)",
      rc == 0 and line == "delete 2", f"rc={rc} line={line!r}")

line, rc = child_pragmas(fresh, "wal")
check("env wal: journal wal, synchronous NORMAL (1)",
      rc == 0 and line == "wal 1", f"rc={rc} line={line!r}")

# journal_mode persists in the file: an explicit set on connect is what
# flips it back — unset env must return the same file to delete.
line, rc = child_pragmas(fresh, None)
check("flip back: unset env returns the wal file to delete",
      rc == 0 and line == "delete 2", f"rc={rc} line={line!r}")

line, rc = child_pragmas(tempfile.mkdtemp(prefix="dbconc-bogus-"), "bogus-mode")
check("invalid env value falls back to delete (boot never fails)",
      rc == 0 and line == "delete 2", f"rc={rc} line={line!r}")

passed = 14 - len(fails)
print(f"db concurrency: {passed}/14" if not fails else f"db concurrency: FAILED: {fails}")
sys.exit(1 if fails else 0)

