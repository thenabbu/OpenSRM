#!/usr/bin/env python3
"""Re-encrypt users.password under the primary Fernet key (key rotation).

Runbook: SECURITY.md "Key rotation". After FERNET_KEYS has been set to
<new-key>,<old-key>,... run this to rewrite every users.password under the
PRIMARY (first) key, so the old key can be dropped from the env later.

Keys are read exactly the way the app reads them (app.app.fernet_keys), so
the tool and the running app can never disagree about which keys are live.

Behaviour:
  - dry run by default; --apply writes
  - one transaction: every UPDATE + the verification read commit together
    or not at all
  - verifies by decrypting EVERY row before committing
  - refuses to continue if any row is unreadable (exit 1, count printed)
    unless --skip-unreadable; skipped rows are left untouched
  - never prints key material, ciphertext, plaintext or netids - counts only

Snapshot the DB before --apply (runbook step 1).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.fernet import Fernet  # noqa: E402


def _count_unreadable(c, fernet):
    """Decrypt every users.password row; return how many fail."""
    n = 0
    for row in c.execute("SELECT password FROM users").fetchall():
        try:
            fernet.decrypt(row["password"].encode())
        except Exception:
            n += 1
    return n


def _scan(c, fernet, primary):
    """Classify every users.password row.

    Returns (under_primary, todo, unreadable): todo holds (netid, new_blob)
    pairs already encrypted under the primary key, ready to write."""
    under = unreadable = 0
    todo = []
    for row in c.execute("SELECT netid, password FROM users").fetchall():
        try:
            plain = fernet.decrypt(row["password"].encode())
        except Exception:
            unreadable += 1
            continue
        try:
            primary.decrypt(row["password"].encode())  # already under the primary key? leave bytes alone
            under += 1
            continue
        except Exception:
            pass
        # .decode(): the column is TEXT - storing bytes would land a BLOB
        # the app's decrypt_pw() could never read back
        todo.append((row["netid"], fernet.encrypt(plain).decode()))
    return under, todo, unreadable


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Re-encrypt users.password under the primary Fernet key "
                    "(dry run by default; see SECURITY.md key-rotation runbook)")
    ap.add_argument("--apply", action="store_true",
                    help="write the re-encrypted rows (default: dry run)")
    ap.add_argument("--skip-unreadable", action="store_true",
                    help="continue even if some rows cannot be decrypted "
                         "(those rows are left untouched)")
    args = ap.parse_args(argv)

    try:
        from app.app import db, fernet_keys, get_fernet, reset_fernet
        keys, from_env = fernet_keys()
        fernet = get_fernet()
        primary = Fernet(keys[0])
    except Exception as e:  # config error (bad FERNET_KEYS) - message never carries key material
        print("error: cannot load key material: %s" % e, file=sys.stderr)
        return 1

    print("rotate_fernet_key: re-encrypt users.password under the primary key")
    print("mode: %s" % ("apply" if args.apply else "dry run (no writes)"))
    print("key source: %s (%d key%s)"
          % ("FERNET_KEYS" if from_env else "DATA_DIR/fernet.key",
             len(keys), "" if len(keys) == 1 else "s"))

    c = db()
    try:
        under, todo, unreadable = _scan(c, fernet, primary)
        total = under + len(todo) + unreadable
        print("rows: %d" % total)
        print("already under primary: %d" % under)
        print("to re-encrypt: %d" % len(todo))
        print("unreadable: %d" % unreadable)

        if unreadable and not args.skip_unreadable:
            print("refusing: %d unreadable row(s) - rerun with "
                  "--skip-unreadable to leave them untouched" % unreadable,
                  file=sys.stderr)
            return 1
        if not args.apply:
            print("dry run complete - no changes written; rerun with --apply")
            return 0

        # one transaction: the implicit BEGIN lands on the first UPDATE and
        # commit() below covers the verification read too - all or nothing
        for netid, blob in todo:
            c.execute("UPDATE users SET password=? WHERE netid=?", (blob, netid))
        bad = _count_unreadable(c, fernet)  # verify: decrypt every row pre-commit
        if bad > unreadable:
            c.rollback()
            print("verification FAILED: %d row(s) unreadable after "
                  "re-encrypt (%d before) - rolled back" % (bad, unreadable),
                  file=sys.stderr)
            return 1
        c.commit()
        print("re-encrypted: %d" % len(todo))
        print("verified: %d/%d rows decrypt under the live keys"
              % (total - bad, total))
        if unreadable:
            print("skipped: %d unreadable row(s) left untouched" % unreadable)
        print("committed in one transaction")
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
