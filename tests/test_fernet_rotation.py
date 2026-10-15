#!/usr/bin/env python3
"""Fernet key rotation contract: FERNET_KEYS env + scripts/rotate_fernet_key.py.

Phases (fabricated keys, generated in-process, never committed):
  1. file mode (no FERNET_KEYS) unchanged: plain Fernet, key file 0600
  2. FERNET_KEYS -> MultiFernet; first key encrypts
  3. rotation point: old-key rows still decrypt, wrong key -> "" (the
     stored-credentials-unreadable path), bad env names FERNET_KEYS w/o echo
  4. script: dry run default, refuses unreadable rows with a count (exit 1,
     DB untouched), --skip-unreadable leaves them alone, re-encryption lands
     under the new primary only, already-primary bytes untouched
  5. clean apply: exit 0, committed in one transaction, idempotent re-run
  6. no key material, plaintext or netids in any script output
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile

# worktree root first: the shared venv must import THIS tree's app/ package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# temp DB before importing app.app (migrations run at import)
_tmp = tempfile.mkdtemp(prefix="osrm-fernet-")
os.environ["DATA_DIR"] = _tmp
os.environ.pop("FERNET_KEYS", None)
atexit.register(shutil.rmtree, _tmp, ignore_errors=True)

from cryptography.fernet import Fernet, MultiFernet  # noqa: E402

import app.app as A  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "rotate_fernet_key.py")
FAILS = []
TOTAL = 0
OUTPUTS = []

K_OLD, K_NEW, K_WRONG = (Fernet.generate_key() for _ in range(3))


def check(desc, cond, detail=""):
    global TOTAL
    TOTAL += 1
    print(("PASS " if cond else "FAIL ") + desc + ("" if cond else "  -> " + str(detail)))
    if not cond:
        FAILS.append(desc)


def _diag(got, want):
    """check() detail that classifies a mismatch WITHOUT the value - a
    decrypt result must never reach print (CodeQL clear-text-logging)."""
    if got == want:
        return ""
    return "unreadable (empty)" if got == "" else "value mismatch"


def use_keys(*keys):
    os.environ["FERNET_KEYS"] = ",".join(k.decode() for k in keys)
    A._fernet = None


def use_file_mode():
    os.environ.pop("FERNET_KEYS", None)
    A._fernet = None


def _can(f, blob):
    try:
        f.decrypt(blob.encode())
        return True
    except Exception:
        return False


def put_user(netid, pw, key=None):
    """Insert users.password encrypted under `key`, or under the live cipher."""
    blob = (Fernet(key) if key else A.get_fernet()).encrypt(pw.encode()).decode()
    c = A.db()
    c.execute("INSERT OR REPLACE INTO users(netid, password) VALUES(?, ?)", (netid, blob))
    c.commit()
    c.close()
    return blob


def get_blob(netid):
    c = A.db()
    row = c.execute("SELECT password FROM users WHERE netid=?", (netid,)).fetchone()
    c.close()
    return row["password"] if row else None


def run_script(*args):
    p = subprocess.run([sys.executable, SCRIPT, *args],
                       capture_output=True, text=True, cwd=ROOT)
    out = p.stdout + p.stderr
    OUTPUTS.append(out)
    return p.returncode, out


# ── phase 1: file mode (default) unchanged ─────────────────────────
use_file_mode()
f1 = A.get_fernet()
check("file mode returns a plain Fernet (default unchanged)",
      type(f1) is Fernet and not isinstance(f1, MultiFernet), repr(type(f1)))
kpath = os.path.join(A.DATA_DIR, "fernet.key")
check("file-mode key generated at DATA_DIR/fernet.key", os.path.exists(kpath))
check("key file mode is 0600",
      (os.stat(kpath).st_mode & 0o777) == 0o600, oct(os.stat(kpath).st_mode & 0o777))
FILE_KEY = open(kpath, "rb").read()
blob_f = put_user("zz9991", "file-mode-pw")
_got = A.decrypt_pw(blob_f)
check("file-mode round trip", _got == "file-mode-pw", _diag(_got, "file-mode-pw"))
rc, out = run_script()
check("file-mode dry run exits 0", rc == 0, "rc=%d %s" % (rc, out[-300:]))
check("file-mode dry run reports nothing to do", "to re-encrypt: 0" in out, out)
check("file-mode key source line", "key source: DATA_DIR/fernet.key (1 key)" in out, out)
check("file-mode dry run never writes", get_blob("zz9991") == blob_f)

# ── phase 2: FERNET_KEYS env -> MultiFernet ────────────────────────
use_keys(K_OLD)
f2 = A.get_fernet()
check("FERNET_KEYS set -> MultiFernet", isinstance(f2, MultiFernet), repr(type(f2)))
blob_old = put_user("zz9992", "old-key-pw")
_got = A.decrypt_pw(blob_old)
check("env-mode round trip", _got == "old-key-pw", _diag(_got, "old-key-pw"))

# ── phase 3: rotation point ────────────────────────────────────────
use_keys(K_NEW, K_OLD)
_got = A.decrypt_pw(blob_old)
check("old-key row still decrypts after the primary changes",
      _got == "old-key-pw", _diag(_got, "old-key-pw"))
blob_new = put_user("zz9993", "new-key-pw")
check("first key encrypts: new primary can decrypt",
      _can(Fernet(K_NEW), blob_new), blob_new[:20])
check("first key encrypts: old key cannot",
      not _can(Fernet(K_OLD), blob_new), blob_new[:20])
use_keys(K_WRONG)
_got = A.decrypt_pw(blob_old)
check("wrong key -> decrypt_pw returns '' (stored-credentials-unreadable path)",
      _got == "", _diag(_got, ""))
use_keys(b"not-a-fernet-key")
try:
    A.get_fernet()
    got = ""
except RuntimeError as e:
    got = str(e)
check("invalid FERNET_KEYS raises naming the env var", "FERNET_KEYS" in got, got)
check("invalid-key error never echoes the key material",
      "not-a-fernet-key" not in got, got)
use_keys(K_NEW, K_OLD)

# ── phase 4: script with mixed + unreadable rows ───────────────────
# live keys: K_NEW (primary), K_OLD. Rows: zz9991 = file key (unreadable),
# zz9992 = old key (re-encrypt), zz9993 = new key (already primary)
rc, out = run_script()
check("unreadable row -> dry run refuses with exit 1", rc == 1, "rc=%d" % rc)
check("dry run prints the unreadable count", "unreadable: 1" in out, out)
check("dry run counts mixed rows (1 to re-encrypt, 1 already primary)",
      "to re-encrypt: 1" in out and "already under primary: 1" in out, out)
check("dry run names the skip flag", "--skip-unreadable" in out, out)
check("dry run left zz9991 untouched", get_blob("zz9991") == blob_f)
rc, out = run_script("--apply")
check("apply without --skip-unreadable refuses (exit 1)", rc == 1, "rc=%d" % rc)
check("refused apply wrote nothing", get_blob("zz9992") == blob_old)
rc, out = run_script("--apply", "--skip-unreadable")
check("apply --skip-unreadable exits 0", rc == 0, "rc=%d %s" % (rc, out[-300:]))
_b = get_blob("zz9992")
check("rotation landed: zz9992 decrypts under the NEW primary alone",
      _can(Fernet(K_NEW), _b) and not _can(Fernet(K_OLD), _b),
      "new-key:%s old-key:%s" % (_can(Fernet(K_NEW), _b), _can(Fernet(K_OLD), _b)))
_got = A.decrypt_pw(get_blob("zz9992"))
check("old key no longer needed for zz9992", _got == "old-key-pw",
      _diag(_got, "old-key-pw"))
check("already-primary row bytes untouched", get_blob("zz9993") == blob_new)
check("skipped unreadable row untouched", get_blob("zz9991") == blob_f)
check("apply verifies every readable row before commit",
      "verified: 2/3 rows decrypt" in out, out)  # 3rd row is the refused one
check("apply reports the skip", "skipped: 1 unreadable row(s) left untouched" in out, out)
rc, out = run_script()
check("re-run is idempotent: nothing left to re-encrypt", "to re-encrypt: 0" in out, out)

# ── phase 5: clean apply (all rows readable) ───────────────────────
c = A.db()
c.execute("DELETE FROM users WHERE netid='zz9991'")  # operator restores the file key
c.commit(); c.close()
blob_mix = put_user("zz9994", "mixed-pw", key=K_OLD)
rc, out = run_script()
check("clean dry run exits 0", rc == 0, "rc=%d %s" % (rc, out[-300:]))
check("clean dry run reports the one stale row", "to re-encrypt: 1" in out, out)
check("clean dry run did not write", _can(Fernet(K_OLD), get_blob("zz9994")))
rc, out = run_script("--apply")
check("clean apply exits 0", rc == 0, "rc=%d %s" % (rc, out[-300:]))
_b = get_blob("zz9994")
check("clean apply rotated zz9994 under the primary",
      _can(Fernet(K_NEW), _b) and not _can(Fernet(K_OLD), _b),
      "new-key:%s old-key:%s" % (_can(Fernet(K_NEW), _b), _can(Fernet(K_OLD), _b)))
check("clean apply committed in one transaction", "committed in one transaction" in out, out)
rc, out = run_script()
check("final dry run: 0 to re-encrypt", "to re-encrypt: 0" in out, out)

# ── no key material / plaintext / netids in any script output ──────
leaks = []
for k in (K_OLD, K_NEW, K_WRONG, FILE_KEY):
    if any(k.decode() in o for o in OUTPUTS):
        leaks.append("key-material")
if any(s in o for o in OUTPUTS
       for s in ("file-mode-pw", "old-key-pw", "new-key-pw", "mixed-pw")):
    leaks.append("plaintext-pw")
if any("zz999" in o for o in OUTPUTS):
    leaks.append("netid")
check("script output carries no key material, plaintext or netids",
      not leaks, leaks)

print()
print("%d/%d passed" % (TOTAL - len(FAILS), TOTAL))
raise SystemExit(1 if FAILS else 0)
