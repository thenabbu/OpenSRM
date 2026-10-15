"""POST /api/account/delete — schema-driven residue suite (N checks).

Every table/column of the LIVE schema that can hold a netid is discovered
via PRAGMA table_info (name contains "netid", plus the three name-irregular
columns whose values carry one: usage_events.user, component_tags.confirmed_by,
component_tags.tag_key's "net:<netid>|..." fallback key), seeded with the
fabricated netid zz9999 in production shape, deleted through the real
endpoint, then scanned for residue.

The suite fails when a later migration adds a netid column the deleter does
not cover: discovery re-reads the live schema, the seeder backfills any
uncovered column, and the residue scan reports it (the simulated-migration
check proves the detector actually catches such a column today).

Self-contained: temp DATA_DIR, seed and mint inside; no server, no network.
"""
import atexit
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# verify76 forbids test DBs in-tree; the dir must outlive this module's
# import (tests run after the import block) — mkdtemp + atexit, not `with`.
# Direct assignment, NOT setdefault: a stale exported DATA_DIR must not win.
_td = tempfile.mkdtemp(prefix="osrm-accdel-")
atexit.register(shutil.rmtree, _td, True)
os.environ["DATA_DIR"] = _td
from app import app as A  # noqa: E402  (import runs migrations)

NETID = "zz9999"   # fabricated — the repo is public (AGENTS.md)
OTHER = "xx0001"   # control account: must survive the delete untouched
DAY = time.strftime("%Y-%m-%d")
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# name-irregular columns whose VALUES carry a netid (writers in app/app.py:
# usage_events.user = netid, component_tags.confirmed_by = netid,
# component_tags.tag_key = "net:<netid>|…" per-student fallback key)
IRREGULAR = {"user", "confirmed_by", "tag_key"}


def all_tables(c):
    return [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def netid_columns(c):
    """Every (table, column) of the live schema that can hold a netid."""
    out = []
    for t in all_tables(c):
        for col in c.execute('PRAGMA table_info("%s")' % t):
            name = col[1]
            if "netid" in name.lower() or name.lower() in IRREGULAR:
                out.append((t, name))
    return out


def scan_hits(c, cols):
    """[(table, column, rows)] still carrying the fabricated netid."""
    hits = []
    for t, col in cols:
        n = c.execute(
            'SELECT COUNT(*) FROM "%s" WHERE "%s" LIKE ?' % (t, col),
            ("%" + NETID + "%",)).fetchone()[0]
        if n:
            hits.append((t, col, n))
    return hits


def broad_cols(c):
    return [(t, col[1]) for t in all_tables(c)
            for col in c.execute('PRAGMA table_info("%s")' % t)]


def backfill(c, cols, covered):
    """Seed one production-shaped netid row per discovered-but-uncovered
    (table, column) — this is what makes a FUTURE migration's netid column
    fail the suite instead of slipping past an unmaintained hard-coded list."""
    for t, col in sorted({tc for tc in cols if tc not in covered}):
        val = f"net:{NETID}|21A|IE-1" if (t, col) == ("component_tags", "tag_key") else NETID
        info = c.execute('PRAGMA table_info("%s")' % t).fetchall()
        names, vals = [], []
        for _, name, typ, notnull, default, pk in info:
            if name == col:
                names.append(name); vals.append(val)
            elif (notnull and default is None) or (pk and "INT" not in (typ or "").upper()):
                # NOT NULL without default (or TEXT PK): fill so the insert sticks
                names.append(name)
                vals.append(1 if "INT" in (typ or "").upper() else
                            (0.0 if "REAL" in (typ or "").upper() else "seed"))
        sql = 'INSERT OR IGNORE INTO "%s" (%s) VALUES (%s)' % (
            t, ",".join('"%s"' % n for n in names), ",".join("?" * len(vals)))
        c.execute(sql, vals)
    c.commit()


def seed_realistic(c):
    """Production-shaped rows for both accounts + shared rows the delete
    must NOT touch (shared timetable groups, class-scoped tags)."""
    for net in (NETID, OTHER):
        c.execute("INSERT OR REPLACE INTO users(netid, password) VALUES(?, 'pw')", (net,))
        c.execute("INSERT INTO portal_sessions(netid, cookies_json, created) VALUES(?, '[]', ?)",
                  (net, int(time.time())))
        c.execute("""INSERT INTO push_subscriptions(netid, endpoint, p256dh, auth, created_at)
                     VALUES(?, ?, 'dh', 'au', ?)""",
                  (net, f"https://push.example/{net}", int(time.time())))
        sub = c.execute("SELECT id FROM push_subscriptions WHERE endpoint=?",
                        (f"https://push.example/{net}",)).fetchone()[0]
        c.execute("""INSERT INTO push_sent_log(subscription_id, local_date, block_start,
                     subject_code, status, claimed_at) VALUES(?, ?, 0, '21A', 'sent', ?)""",
                  (sub, DAY, int(time.time())))
        c.execute("INSERT INTO push_events(netid, kind, key, created_at) VALUES(?, 'receipt', 'k', ?)",
                  (net, int(time.time())))
        c.execute("INSERT INTO usage_events(day, user, event) VALUES(?, ?, 'page_view')", (DAY, net))
    # shared timetable group (portal-synced; the delete must leave it alone)
    cur = c.execute("""INSERT INTO timetable_groups(group_key, program, batch, semester, section)
                       VALUES('2025|CSE|3|A', 'CSE', 2025, 3, 'A')""")
    gid = cur.lastrowid
    c.execute("INSERT INTO timetable_slots(group_id, day, period, subject_code) VALUES(?, 'Monday', 1, '21A')",
              (gid,))
    c.execute("""INSERT INTO timetable_edit_log(group_id, editor_netid, editor_name, changes_json)
                 VALUES(?, ?, 'Aarav Mehta', '[]')""", (gid, NETID))
    # component_tags: one SHARED row both students confirmed (class-scoped,
    # no netid in the key) + NETID's own per-student fallback-key row
    c.execute("""INSERT INTO component_tags(tag_key, role, raw_max, scaled_max, confirmed_by)
                 VALUES('2025|CSE|3|A|21A|IE-1', 'IE-1', 50.0, 50.0, ?)""", (OTHER,))
    c.execute("""INSERT INTO component_tags(tag_key, role, raw_max, scaled_max, confirmed_by)
                 VALUES('2025|CSE|3|A|21A|IE-1b', 'IE-1', 50.0, 50.0, ?)""", (NETID,))
    c.execute("""INSERT INTO component_tags(tag_key, role, raw_max, scaled_max, confirmed_by)
                 VALUES(?, 'IE-2', 60.0, 60.0, ?)""", (f"net:{NETID}|21A|IE-2", NETID))
    c.commit()


def count(c, sql, *args):
    return c.execute(sql, args).fetchone()[0]


# ── 1. discovery from the live schema ────────────────────────────────
c = A.db()
cols = netid_columns(c)
expected = {("users", "netid"), ("cookies", "netid"), ("portal_sessions", "netid"),
            ("push_subscriptions", "netid"), ("push_events", "netid"),
            ("timetable_edit_log", "editor_netid"), ("usage_events", "user"),
            ("component_tags", "confirmed_by"), ("component_tags", "tag_key")}
check("discovery: every known netid-capable column of the live schema",
      expected <= set(cols), f"missing={sorted(expected - set(cols))} found={len(cols)}")

# ── 2. seed production-shaped rows for both accounts ─────────────────
seed_realistic(c)
# other account's session (mint inserts the digest row, hash-aware world)
A.make_session_token(OTHER)
# NETID: two real sessions + one legacy RAW-token row (pre-migration-17 shape)
tok1 = A.make_session_token(NETID)
A.make_session_token(NETID)
c.execute("INSERT INTO cookies(token, netid, created) VALUES('legacy-raw-token', ?, ?)",
          (NETID, int(time.time())))
c.commit()
cookie_rows = count(c, "SELECT COUNT(*) FROM cookies WHERE netid=?", NETID)
c.close()
check("seed: 3 cookie rows for the account (2 digest sessions + 1 legacy raw)",
      cookie_rows == 3, f"rows={cookie_rows}")

# coverage: a discovered column with no netid row yet (a future migration's)
# gets a generic production-shaped seed so its residue IS observable below.
c = A.db()
cols_now = netid_columns(c)
covered = {tc for tc in cols_now
           if count(c, 'SELECT COUNT(*) FROM "%s" WHERE "%s" LIKE ?' % tc,
                    "%" + NETID + "%")}
backfill(c, cols_now, covered)
unseeded = [(t, col) for t, col in netid_columns(c)
            if count(c, 'SELECT COUNT(*) FROM "%s" WHERE "%s" LIKE ?' % (t, col),
                     "%" + NETID + "%") == 0]
check("seed: every discovered column holds a netid before the delete",
      not unseeded, f"unseeded={unseeded}")

# ── 3. login required / method / rate limit ──────────────────────────
cl = A.app.test_client()
r = cl.post("/api/account/delete")
check("login required: anonymous POST redirects to /login",
      r.status_code == 302 and r.headers.get("Location", "").endswith("/login"),
      f"{r.status_code} {r.headers.get('Location')}")
r = cl.get("/api/account/delete")
check("GET /api/account/delete is 405 (POST only)", r.status_code == 405, str(r.status_code))

cl.set_cookie("srm_session", tok1)
A._delete_attempts[NETID] = [time.time()] * 3          # window already full
r = cl.post("/api/account/delete")
c = A.db()
still = count(c, "SELECT COUNT(*) FROM users WHERE netid=?", NETID)
c.close()
check("rate limited: 429 after 3 attempts/hour and nothing deleted",
      r.status_code == 429 and r.get_json().get("ok") is False and still == 1,
      f"status={r.status_code} ok={r.get_json().get('ok')} users={still}")
A._delete_attempts.clear()

# ── 4. the auth line (exactly one opensrm.auth line with counts) ─────
class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.recs = []

    def emit(self, record):
        self.recs.append(record)


cap = _Cap()
A.log_auth.addHandler(cap)
r = cl.post("/api/account/delete")
A.log_auth.removeHandler(cap)
deletes = [rec for rec in cap.recs if rec.getMessage() == "account delete ok"]
kv = getattr(deletes[0], "kv", {}) if deletes else {}
check("one opensrm.auth line with per-table counts",
      len(deletes) == 1 and r.status_code == 200 and r.get_json().get("ok") is True
      and "users=1" in str(kv.get("counts", "")) and "cookies=3" in str(kv.get("counts", "")),
      f"lines={len(deletes)} status={r.status_code} counts={kv.get('counts')}")

# ── 5. what must be GONE ─────────────────────────────────────────────
c = A.db()
gone = {
    "users": count(c, "SELECT COUNT(*) FROM users WHERE netid=?", NETID),
    "cookies (digest rows)": count(c, "SELECT COUNT(*) FROM cookies WHERE netid=?", NETID),
    "cookies (legacy raw token)": count(c, "SELECT COUNT(*) FROM cookies WHERE token='legacy-raw-token'"),
    "portal_sessions": count(c, "SELECT COUNT(*) FROM portal_sessions WHERE netid=?", NETID),
    "push_subscriptions": count(c, "SELECT COUNT(*) FROM push_subscriptions WHERE netid=?", NETID),
    "push_sent_log (NETID's sent row gone, OTHER's stays)": (
        0 if count(c, "SELECT COUNT(*) FROM push_sent_log") == 1 else 1),
    "push_events (receipts)": count(c, "SELECT COUNT(*) FROM push_events WHERE netid=?", NETID),
    "usage_events": count(c, "SELECT COUNT(*) FROM usage_events WHERE user=?", NETID),
    "timetable_edit_log": count(c, "SELECT COUNT(*) FROM timetable_edit_log WHERE editor_netid=?", NETID),
    "component_tags (per-student key)": count(
        c, "SELECT COUNT(*) FROM component_tags WHERE tag_key LIKE 'net:' || ? || '|%'", NETID),
}
check("every contract table erased for the netid", all(v == 0 for v in gone.values()),
      str({k: v for k, v in gone.items() if v}))

# ── 6. what must STAY ────────────────────────────────────────────────
shared = {
    "timetable_groups": count(c, "SELECT COUNT(*) FROM timetable_groups"),
    "timetable_slots": count(c, "SELECT COUNT(*) FROM timetable_slots"),
    "component_tags shared rows": count(
        c, "SELECT COUNT(*) FROM component_tags WHERE tag_key LIKE '2025|CSE|3|A|%'"),
    "shared tag confirmed_by scrubbed": count(
        c, "SELECT COUNT(*) FROM component_tags WHERE tag_key='2025|CSE|3|A|21A|IE-1b' "
           "AND confirmed_by='' AND role='IE-1'"),
}
check("shared timetable groups/slots and class-wide tags stay; netid attribution scrubbed",
      shared == {"timetable_groups": 1, "timetable_slots": 1,
                 "component_tags shared rows": 2, "shared tag confirmed_by scrubbed": 1},
      str(shared))

other_rows = {
    "users": count(c, "SELECT COUNT(*) FROM users WHERE netid=?", OTHER),
    "cookies": count(c, "SELECT COUNT(*) FROM cookies WHERE netid=?", OTHER),
    "portal_sessions": count(c, "SELECT COUNT(*) FROM portal_sessions WHERE netid=?", OTHER),
    "push_subscriptions": count(c, "SELECT COUNT(*) FROM push_subscriptions WHERE netid=?", OTHER),
    "push_events": count(c, "SELECT COUNT(*) FROM push_events WHERE netid=?", OTHER),
    "usage_events": count(c, "SELECT COUNT(*) FROM usage_events WHERE user=?", OTHER),
    "component_tags confirmed_by": count(
        c, "SELECT COUNT(*) FROM component_tags WHERE confirmed_by=?", OTHER),
}
check("control account xx0001 completely untouched",
      all(v == 1 for v in other_rows.values()), str(other_rows))

# ── 7. residue: every discovered column, then the whole schema ───────
disc_hits = scan_hits(c, netid_columns(c))
check("residue: zero in every discovered netid-capable column", not disc_hits, str(disc_hits))
broad_hits = scan_hits(c, broad_cols(c))
check("residue: zero in EVERY column of EVERY table (broad sweep)", not broad_hits, str(broad_hits))

# ── 8. the session itself is dead: replay redirects to /login ────────
c.close()
cl.set_cookie("srm_session", tok1)     # row was deleted: cookie now resolves nowhere
r = cl.post("/api/account/delete")
check("replay after delete redirects to /login (session gone)",
      r.status_code == 302 and r.headers.get("Location", "").endswith("/login"),
      f"{r.status_code} {r.headers.get('Location')}")

# ── 9. simulated later migration: the detector FAILS an uncovered column ──
# A future @migration that adds a netid column the deleter does not clear
# must turn this suite red. Prove the detector catches one TODAY: add the
# column, leave the deleter ignorant of it, scan -> residue must be found,
# then clean up and re-scan -> zero (the green state the suite ends in).
c = A.db()
c.execute("ALTER TABLE usage_events ADD COLUMN future_netid TEXT DEFAULT ''")
c.execute("INSERT INTO usage_events(day, user, event, future_netid) VALUES(?, '', 'simulated', ?)",
          (DAY, NETID))
c.commit()
future = scan_hits(c, [tc for tc in netid_columns(c) if tc[1] == "future_netid"])
check("detector: an uncovered future netid column FAILS the residue scan (simulated migration)",
      future == [("usage_events", "future_netid", 1)], str(future))
c.execute("DELETE FROM usage_events WHERE event='simulated'")
c.execute("ALTER TABLE usage_events DROP COLUMN future_netid")
c.commit()
final = scan_hits(c, broad_cols(c))
check("after simulated-migration cleanup: broad sweep zero again", not final, str(final))
c.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} PASS")
sys.exit(1 if fails else 0)
