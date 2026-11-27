"""`GET /api/data/state` — the answer the dashboard now asks for instead of
reading `data-ts` out of its own markup.

Three properties, and each one is a way this route could have gone wrong:

  * an anonymous caller is refused, so it can never be a probe for somebody
    else's freshness;
  * the verdict is the SAME window `/api/refresh` caches on, so a check and a
    reload can never disagree;
  * it answers, it starts nothing — the whole point of moving the decision to
    the server is that a page can ask cheaply and often.

Run:  .venv/bin/python tests/unit/test_data_state_route.py
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="osrm-datastate-"))
os.environ.setdefault("AUTO_SYNC_STALE_S", "0")      # never touch the portal
os.environ.setdefault("SCOPE_FEATURES", "off")

import app.app as A  # noqa: E402  (import boots create_app)
from app import db  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


NETID = "t_datastate"
client = A.app.test_client()

# `require_login` sends an anonymous caller to /login — the same gate every
# other signed-in route has, so this route leaks nothing to a stranger.
anon = client.get("/api/data/state")
check("anonymous caller is refused",
      anon.status_code == 302 and "/login" in anon.headers.get("Location", ""),
      f"status={anon.status_code} to={anon.headers.get('Location')}")

# An account that has synced, and one that never has.
with db.transaction() as c:
    c.execute("INSERT OR REPLACE INTO users(netid, password, attendance_json, last_fetch)"
              " VALUES(?,?,?,?)", (NETID, "x", "{}", int(time.time())))

# A real session cookie: `make_session_token` stores sha256(token) and the
# browser keeps the raw one, so the client has to send the raw string back.
client.set_cookie("srm_session", A.make_session_token(NETID))

r = client.get("/api/data/state")
body = r.get_json() or {}
check("a signed-in caller gets a verdict", r.status_code == 200 and body.get("ok") is True,
      f"status={r.status_code} body={body}")
check("just-synced data is fresh", body.get("stale") is False, f"age_s={body.get('age_s')}")
check("the verdict carries the window it judged", isinstance(body.get("window_s"), int))

# Older than the window: the same comparison /api/refresh caches on.
with db.transaction() as c:
    c.execute("UPDATE users SET last_fetch=? WHERE netid=?",
              (int(time.time()) - body["window_s"] - 60, NETID))
r = client.get("/api/data/state")
body = r.get_json() or {}
check("older than the window is stale", body.get("stale") is True, f"age_s={body.get('age_s')}")

# Never synced: no age at all, and that is stale, not an error.
with db.transaction() as c:
    c.execute("UPDATE users SET last_fetch=0 WHERE netid=?", (NETID,))
r = client.get("/api/data/state")
body = r.get_json() or {}
check("never synced is stale with no age", body.get("stale") is True and body.get("age_s") is None,
      f"body={body}")

failed = sum(1 for _, ok in results if not ok)
print(f"\nDATA STATE ROUTE: {len(results)} items | PASS {len(results) - failed} | FAIL {failed}")
sys.exit(1 if failed else 0)
