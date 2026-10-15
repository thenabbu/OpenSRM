#!/usr/bin/env python3
"""Cookie helper for scripts/canary_sync.sh: mint / check / drop.

Runs inside the container by default
(`docker exec opensrm python /app/scripts/canary_cookie.py <op> <arg>`) or
locally with DATA_DIR pointed at a test DB. The netid and token are always
ARGUMENTS — nothing identity-bearing is ever committed.

  mint  <netid>   insert a session cookie, print the token
  check <netid>   exit non-zero (with the reason on stderr) unless the users
                  row holds non-empty attendance AND marks — the sync-health
                  assertion the canary exists for
  drop  <token>   delete that cookie row
"""
import json
import os
import sys

# repo root first so `app` resolves to THIS tree in any invocation cwd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# a CLI helper's own logging must not pollute the token/reason captured on
# stdout/stderr by canary_sync.sh (the app logs "logging.level=..." at INFO
# during import otherwise)
os.environ["LOG_LEVEL"] = "WARNING"


def main(argv):
    if len(argv) != 3 or argv[1] not in ("mint", "drop", "check"):
        sys.exit("usage: canary_cookie.py mint|drop|check <netid|token>")
    cmd, arg = argv[1], argv[2]
    if cmd == "mint":
        from app.app import make_session_token
        print(make_session_token(arg))
        return
    from app.app import db
    if cmd == "drop":
        # rows store sha256(token) since migration 17 — the canary holds the
        # raw token from `mint`, so hash before addressing the row
        import hashlib
        c = db()
        n = c.execute("DELETE FROM cookies WHERE token=?",
                      (hashlib.sha256(arg.encode()).hexdigest(),)).rowcount
        c.commit(); c.close()
        print(f"dropped={n}")
        return
    # check: the sync must have left non-empty attendance AND marks behind
    c = db()
    row = c.execute("SELECT attendance_json, marks_json FROM users WHERE netid=?",
                    (arg,)).fetchone()
    c.close()
    if not row:
        sys.exit(f"check failed: no user row for netid={arg}")
    try:
        att = json.loads(row[0]) if row[0] else {}
        marks = json.loads(row[1]) if row[1] else []
    except (ValueError, TypeError) as e:
        sys.exit(f"check failed: stored json unreadable: {e}")
    n_att = len(att.get("courses") or []) if isinstance(att, dict) else 0
    n_marks = len(marks) if isinstance(marks, list) else 0
    if not n_att:
        sys.exit("check failed: attendance empty after sync")
    if not n_marks:
        sys.exit("check failed: marks empty after sync")
    print(f"attendance_courses={n_att} marks={n_marks}")


if __name__ == "__main__":
    main(sys.argv)
