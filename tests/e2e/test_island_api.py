#!/usr/bin/env python3
"""The 3 island read endpoints added in P7 (marks/timetable/tools).

Why these three exist at all: /api/marks (app.py:741) serves raw stored JSON
from before the island contract, and /api/timetable (blueprints/timetable.py)
is the GET+POST the user WRITES the grid through. Neither can feed the cache
path, which needs the exact payload the island's zod schema validates. So the
island feeds get their own paths: /api/<panel>/island.

Contract under test (identical to the four P50 endpoints):
  * anonymous -> 401 JSON, never a 302 to /login HTML
  * success   -> {"ok": true, "data": {...}}
  * no data   -> 404 {"ok": false, "error": ...}
  * Cache-Control: no-store (PII)

Run against the shared CI server (scripts/ci_e2e_http.sh) with a full seed.
"""
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.environ.get("DUT_BASE", os.environ.get("BASE_URL", "http://127.0.0.1:18181")).rstrip("/")
DATA_DIR = os.environ.get("DATA_DIR", "")

PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def get(path, token=None):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Cookie", f"srm_session={token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace"), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), {k.lower(): v for k, v in e.headers.items()}


def json_of(body):
    try:
        return json.loads(body)
    except Exception:
        return None


ISLAND_PATHS = ["/api/marks/island", "/api/timetable/island", "/api/tools/island"]


def check_anonymous():
    print("\n-- anonymous: 401 JSON, not a redirect --")
    for p in ISLAND_PATHS:
        st, body, hdr = get(p)
        doc = json_of(body)
        chk(f"{p} -> 401 JSON", st == 401 and doc is not None and doc.get("ok") is False,
            f"{st} {body[:80]}")
        chk(f"{p} not a 302 to /login", st != 302)


def check_authenticated(token, label):
    """For each island endpoint: 200 with the island-shaped payload, or a
    documented 404. Never a 500, never a shape we did not expect."""
    print(f"\n-- authenticated as {label} --")
    expectations = {
        "/api/marks/island": ("subjects",),
        "/api/timetable/island": ("days",),
        "/api/tools/island": ("rows",),
    }
    for p, (key,) in expectations.items():
        st, body, hdr = get(p, token)
        doc = json_of(body)
        chk(f"{p} not a 500", st != 500, f"{st} {body[:120]}")
        if st == 200:
            chk(f"{p} ok:true", bool(doc and doc.get("ok") is True), body[:100])
            data = (doc or {}).get("data")
            chk(f"{p} data has '{key}'", isinstance(data, dict) and key in data,
                f"keys={sorted(data) if isinstance(data, dict) else type(data).__name__}")
            chk(f"{p} Cache-Control: no-store",
                hdr.get("cache-control", "") == "no-store", hdr.get("cache-control"))
        elif st == 404:
            chk(f"{p} 404 carries ok:false", bool(doc and doc.get("ok") is False), body[:100])
        else:
            chk(f"{p} status is 200 or 404", False, f"got {st}")


def find_db(data_dir):
    """The DB that actually holds sessions. Do not assume a filename: the
    real store here is srm.db, and an empty opensrm.sqlite3 also exists in the
    same dir, so pick by table presence, not by name."""
    for cand in sorted(os.listdir(data_dir)):
        path = os.path.join(data_dir, cand)
        if not cand.endswith((".sqlite3", ".db")):
            continue
        try:
            conn = sqlite3.connect(path)
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            conn.close()
        except sqlite3.Error:
            continue
        if "cookies" in names and "users" in names:
            return path
    raise RuntimeError(f"no session DB found under {data_dir}")


def mint_token(netid):
    """Insert a session row whose digest matches a raw token we hold."""
    import hashlib
    token = f"p7-island-test-{netid}"
    digest = hashlib.sha256(token.encode()).hexdigest()
    db = find_db(DATA_DIR)
    import time
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM cookies WHERE token=?", (digest,))
    # created MUST be now: get_current_user() deletes any row older than
    # SESSION_MAX_AGE at READ time, so created=0 made the token expire before
    # the first request and every authenticated call 401'd.
    conn.execute("INSERT INTO cookies(token,netid,created) VALUES(?,?,?)",
                 (digest, netid, int(time.time())))
    conn.commit()
    conn.close()
    return token


def main():
    check_anonymous()
    if DATA_DIR and os.path.isdir(DATA_DIR):
        try:
            token = mint_token("zz9999")
            check_authenticated(token, "zz9999")
        except Exception as e:  # noqa: BLE001 - report, never crash the suite
            chk("authenticated leg ran", False, repr(e))
    else:
        print("\n  [SKIP] authenticated leg — DATA_DIR not set")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
