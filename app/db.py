"""One way to touch the database.

connect() is the raw sqlite3 connection — the A6 policy (10s lock wait, the
busy_timeout PRAGMA twin, journal_mode set explicitly on every connect so an
env flip lands on the next boot). Callers that own their connection close it
themselves: boot code, push_store.get_conn(), scripts.

db() is the connection everything else gets: an in-flight transaction()'s, the
request's (opened lazily, closed by close_db at teardown), or — outside a
request (scripts, tests, background threads) — a fresh caller-owned one, the
contract the old module-level app.app.db() had.

transaction() is the atomic unit: commit on success, roll back on error. On
the shared request connection it runs as a SAVEPOINT, so a unit that fails
mid-way rolls back alone instead of riding into a later commit on the same
connection; on a fresh connection it is the whole transaction (closed here).
The ContextVar lets repo calls inside a block join that block's connection,
even outside a request.

Repo functions below own every SQL statement the request paths run — call
sites never open or close a connection. Two deliberate exceptions keep their
own statements on connections these primitives manage: the one-time legacy
timetable importer (app.py boot path) and push_store.py, whose portable-SQL
boundary opens via connect() and closes itself. Background threads get no
request context, so every connection they take is fresh and closed here.
"""
import contextvars
import itertools
import logging
import os
import sqlite3
from contextlib import contextmanager

from flask import g, has_request_context

# opensrm.db — setup_logging's "opensrm" handler catches it by propagation
log = logging.getLogger("opensrm.db")

# sqlite: every connection in the app funnels through connect() (migrations and
# push_store.get_conn() both call it). One knob pair here therefore covers
# all three connection sites. timeout is sqlite3's per-statement lock wait;
# busy_timeout is the PRAGMA twin — set both so the value holds even for
# statements sqlite3's timeout does not cover.
SQLITE_TIMEOUT_SECS = 10
_journal_mode = os.environ.get("SQLITE_JOURNAL_MODE", "delete").strip().lower()
if _journal_mode not in ("delete", "wal", "truncate", "persist", "off", "memory"):
    _journal_mode = "delete"  # unknown value -> today's default, never fail boot

_tx: contextvars.ContextVar = contextvars.ContextVar("opensrm_db_tx", default=None)
_sp = itertools.count()


def connect():
    """A raw connection: A6 pragmas, sqlite3.Row rows, caller owns/closes it.

    DB_PATH lives in app.app (env-driven DATA_DIR; tests repoint it there),
    imported per call — app.app imports this module at boot (same lazy-import
    rule push_store/http_scraper use to dodge the cycle)."""
    from .app import DB_PATH

    c = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT_SECS)
    c.row_factory = sqlite3.Row
    c.execute(f"PRAGMA busy_timeout={SQLITE_TIMEOUT_SECS * 1000}")
    # journal_mode persists in the DB file; set it explicitly on every
    # connect so an env flip (wal<->delete) takes effect on the next boot
    # without a manual sqlite3 shell session.
    mode = c.execute(f"PRAGMA journal_mode={_journal_mode}").fetchone()[0]
    if mode.lower() != _journal_mode:
        log.warning("sqlite journal_mode %r requested but active mode is %r",
                    _journal_mode, mode)
    if _journal_mode == "wal":
        c.execute("PRAGMA synchronous=NORMAL")  # WAL-safe durability trade
    return c


def db():
    """The one connection: the in-flight transaction's, the request's (closed
    by close_db at teardown), or a fresh caller-owned one — scripts and tests
    outside a request get the same open/close contract as before."""
    c = _tx.get()
    if c is not None:
        return c
    if has_request_context():
        c = getattr(g, "_db_conn", None)
        if c is None:
            c = g._db_conn = connect()
        return c
    return connect()


def close_db(_exc=None):
    """teardown_appcontext hook: close the request-scoped connection."""
    c = getattr(g, "_db_conn", None)
    if c is not None:
        g._db_conn = None
        c.close()


@contextmanager
def transaction():
    """Atomic unit: commit on success, roll back on error, never leaks a
    half-written unit into whatever commits next on a shared connection.

    fresh (no transaction, no request): its own connection — committed and
    closed here. Shared (request / outer block): SAVEPOINT, so rollback is
    scoped to this unit. Repo writes all run inside one of these."""
    fresh = _tx.get() is None and not has_request_context()
    c = connect() if fresh else db()
    token = _tx.set(c)
    try:
        if fresh:
            try:
                yield c
            except BaseException:
                c.rollback()
                raise
            else:
                c.commit()
        else:
            sp = "u%d" % next(_sp)
            c.execute(f"SAVEPOINT {sp}")
            try:
                yield c
            except BaseException:
                c.execute(f"ROLLBACK TO {sp}")
                c.execute(f"RELEASE {sp}")
                raise
            else:
                c.execute(f"RELEASE {sp}")
    finally:
        _tx.reset(token)
        if fresh:
            c.close()


def ping():
    """healthz: one fresh connection, SELECT 1, closed — never the request's."""
    c = connect()
    try:
        c.execute("SELECT 1").fetchone()
    finally:
        c.close()
    return True


def _read(sql, args=(), one=False):
    """SELECT through db(): closes only a connection it opened itself."""
    c = db()
    owned = _tx.get() is None and not has_request_context()
    try:
        cur = c.execute(sql, args)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        if owned:
            c.close()


# ── repository: users ────────────────────────────────────────────────

def user_cold_fetch(netid):
    """hot/cold split state — cold data re-fetched only when stale >24h."""
    return _read("SELECT cold_fetch FROM users WHERE netid=?", (netid,), one=True)


def set_cold_fetch(netid, ts):
    with transaction() as c:
        c.execute("UPDATE users SET cold_fetch=? WHERE netid=?", (ts, netid))


def user_dashboard(netid):
    """one row read: marks/faculty live on the same users row (was three queries)"""
    return _read("SELECT attendance_json, last_fetch, personal_details_json, "
                 "exam_schedule_json, marks_json, faculty_map_json, fb_open "
                 "FROM users WHERE netid=?", (netid,), one=True)


def user_sync_state(netid):
    """persist_sync's pre-merge read (the columns _merge_fetch_result keys)."""
    return _read("SELECT personal_details_json, subjects_json, exam_schedule_json, "
                 "marks_json, faculty_map_json, fb_open, attendance_json "
                 "FROM users WHERE netid=?", (netid,), one=True)


def write_user_sync(netid, pw_blob, attendance_json, fetched, personal_json,
                    marks_json, subjects_json, exams_json, faculty_json, fb_open):
    """The users upsert persist_sync runs: pw_blob None = refresh (UPDATE in
    place, stored password untouched); set = login (INSERT ... ON CONFLICT:
    first fetch creates the row, later logins rotate the stored password).

    photo_b64 dropped: write-only since photo scraping was removed Sep 25 2026.
    audit run-1: attendance goes through the preserve merge (was
    json.dumps(res["data"]) — wholesale wipe on partial responses);
    subjects_json was ALSO discarded here despite the merge (R1)."""
    with transaction() as c:
        if pw_blob is None:
            c.execute("UPDATE users SET attendance_json=?, last_fetch=?, "
                      "personal_details_json=?, marks_json=?, subjects_json=?, "
                      "exam_schedule_json=?, faculty_map_json=?, fb_open=? WHERE netid=?",
                      (attendance_json, fetched, personal_json, marks_json,
                       subjects_json, exams_json, faculty_json, fb_open, netid))
        else:
            c.execute("INSERT INTO users(netid,password,attendance_json,last_fetch,personal_details_json,marks_json,subjects_json,exam_schedule_json,faculty_map_json,fb_open) VALUES(?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(netid) DO UPDATE SET password=excluded.password, attendance_json=excluded.attendance_json, marks_json=excluded.marks_json, subjects_json=excluded.subjects_json, "
                      "last_fetch=excluded.last_fetch, personal_details_json=excluded.personal_details_json, exam_schedule_json=excluded.exam_schedule_json, faculty_map_json=excluded.faculty_map_json, fb_open=excluded.fb_open",
                      (netid, pw_blob, attendance_json, fetched, personal_json,
                       marks_json, subjects_json, exams_json, faculty_json, fb_open))


def user_marks(netid):
    return _read("SELECT marks_json FROM users WHERE netid=?", (netid,), one=True)


def user_marks_personal(netid):
    return _read("SELECT marks_json, personal_details_json FROM users WHERE netid=?",
                 (netid,), one=True)


def user_feedback(netid):
    return _read("SELECT faculty_map_json, fb_open FROM users WHERE netid=?",
                 (netid,), one=True)


def user_password(netid):
    return _read("SELECT password FROM users WHERE netid=?", (netid,), one=True)


def user_personal(netid):
    return _read("SELECT personal_details_json FROM users WHERE netid=?",
                 (netid,), one=True)


def user_last_fetch(netid):
    return _read("SELECT last_fetch FROM users WHERE netid=?", (netid,), one=True)


def users_group_keys(netids):
    """netid -> stored personal details, one query (push group resolution)."""
    q = ",".join("?" * len(netids))
    return _read(f"SELECT netid, personal_details_json FROM users WHERE netid IN ({q})",
                 list(netids))


def delete_account_rows(netid):
    """Erase every stored row keyed by this account (docs/privacy.md) — one
    transaction, counts returned for the opensrm.auth line.

    cookies: EVERY session of this account (all devices). Rows hold
    sha256(token) since migration 17, so the key is the netid — never the
    presented raw token, which matches nothing at rest.
    push_sent_log references subscriptions, not netids: drop the sent
    log first (per-subscription), then the subscriptions themselves.
    timetable_edit_log: this editor's entries go; the shared timetable
    groups/slots they edited have no netid and stay.
    component_tags is class-scoped (no netid by design): a per-student
    fallback key (net:<netid>|...) is private to the account and dies;
    a shared row keeps the class-wide confirmation but loses this
    student's confirmed_by attribution."""
    counts = {}
    with transaction() as c:
        counts["cookies"] = c.execute("DELETE FROM cookies WHERE netid=?",
                                      (netid,)).rowcount
        counts["portal_sessions"] = c.execute(
            "DELETE FROM portal_sessions WHERE netid=?", (netid,)).rowcount
        counts["push_sent_log"] = c.execute(
            "DELETE FROM push_sent_log WHERE subscription_id IN "
            "(SELECT id FROM push_subscriptions WHERE netid=?)", (netid,)).rowcount
        counts["push_subscriptions"] = c.execute(
            "DELETE FROM push_subscriptions WHERE netid=?", (netid,)).rowcount
        counts["push_events"] = c.execute(
            "DELETE FROM push_events WHERE netid=?", (netid,)).rowcount
        counts["usage_events"] = c.execute(
            "DELETE FROM usage_events WHERE user=?", (netid,)).rowcount
        counts["timetable_edit_log"] = c.execute(
            "DELETE FROM timetable_edit_log WHERE editor_netid=?",
            (netid,)).rowcount
        counts["component_tags"] = c.execute(
            "DELETE FROM component_tags WHERE tag_key LIKE 'net:' || ? || '|%'",
            (netid,)).rowcount
        counts["component_tags"] += c.execute(
            "UPDATE component_tags SET confirmed_by='' WHERE confirmed_by=?",
            (netid,)).rowcount
        counts["users"] = c.execute("DELETE FROM users WHERE netid=?",
                                    (netid,)).rowcount
    return counts


# ── repository: cookies (web sessions) ───────────────────────────────

def get_cookie(digest):
    """Row for a sha256(token) digest (migration 17): netid + created."""
    return _read("SELECT netid, created FROM cookies WHERE token=?",
                 (digest,), one=True)


def delete_cookie(digest):
    with transaction() as c:
        c.execute("DELETE FROM cookies WHERE token=?", (digest,))


def create_session(digest, netid, created, prune_before):
    """Mint one session: prune expired rows, then insert — one transaction.

    incident 2026-10-10: the prune used to be `DELETE ... WHERE netid=?`
    (one session per account, globally). Sessions are now concurrent per
    account, each still bounded by SESSION_MAX_AGE at read time; the value
    at rest is the digest, useless to anyone holding the DB but not the
    cookie (contract: make_session_token still returns the raw token)."""
    with transaction() as c:
        c.execute("DELETE FROM cookies WHERE created < ?", (prune_before,))
        c.execute("INSERT INTO cookies(token,netid,created) VALUES(?,?,?)",
                  (digest, netid, created))


def pop_cookie(digest):
    """Read + delete in one transaction (logout): the netid, or None."""
    with transaction() as c:
        row = c.execute("SELECT netid FROM cookies WHERE token=?",
                        (digest,)).fetchone()
        c.execute("DELETE FROM cookies WHERE token=?", (digest,))
    return row["netid"] if row else None


# ── repository: portal_sessions (cached portal cookie jars) ──────────

def save_portal_session(netid, blob, created):
    """blob is Fernet-encrypted by the caller (crypto lives in app.app)."""
    with transaction() as c:
        c.execute("INSERT OR REPLACE INTO portal_sessions(netid, cookies_json, created) VALUES(?, ?, ?)",
                  (netid, blob, created))


def get_portal_session(netid):
    return _read("SELECT cookies_json, created FROM portal_sessions WHERE netid=?",
                 (netid,), one=True)


def delete_portal_session(netid):
    with transaction() as c:
        c.execute("DELETE FROM portal_sessions WHERE netid=?", (netid,))


# ── repository: timetable (groups / slots / subjects / edit log) ─────

def group_id(group_key):
    r = _read("SELECT id FROM timetable_groups WHERE group_key=?",
              (group_key,), one=True)
    return r[0] if r else None


def upsert_group(group_key, program, batch, semester, section):
    with transaction() as c:
        c.execute("INSERT INTO timetable_groups(group_key,program,batch,semester,section) "
                  "VALUES(?,?,?,?,?) ON CONFLICT(group_key) DO UPDATE SET updated_at=excluded.updated_at",
                  (group_key, program, batch, semester, section))


def upsert_subject(gid, code, name, credits, is_custom):
    with transaction() as c:
        c.execute("INSERT INTO timetable_subjects(group_id,code,name,credits,is_custom) "
                  "VALUES(?,?,?,?,?) ON CONFLICT(group_id,code) DO UPDATE SET name=excluded.name",
                  (gid, code, name, credits, is_custom))


def group_slots(gid):
    return _read("SELECT day,period,subject_code,subject_name,location "
                 "FROM timetable_slots WHERE group_id=?", (gid,))


def group_subjects(gid):
    return _read("SELECT code,name,credits,is_custom FROM timetable_subjects "
                 "WHERE group_id=?", (gid,))


def replace_group_slots(gid, rows, source):
    """Atomic whole-group replace: DELETE every slot, re-insert rows.
    rows = (day, period, code, name, location); source stamps 'official'
    (portal sync) or 'manual' (archived editor) — UNIQUE group/day/period
    means one source at a time per group."""
    with transaction() as c:
        c.execute("DELETE FROM timetable_slots WHERE group_id=?", (gid,))
        c.executemany("INSERT INTO timetable_slots(group_id,day,period,subject_code,subject_name,location,source) "
                      "VALUES(?,?,?,?,?,?,?)",
                      [(gid, r[0], r[1], r[2], r[3], r[4], source) for r in rows])


def set_official_times(group_key, times_json, fetched_at):
    """Rows and official stamp are written together — they never disagree."""
    with transaction() as c:
        c.execute("UPDATE timetable_groups SET official_times=?, tt_fetched_at=? WHERE group_key=?",
                  (times_json, fetched_at, group_key))


def clear_official_stamp(gid):
    """Manual/legacy rows: drop the official stamp in the same transaction."""
    with transaction() as c:
        c.execute("UPDATE timetable_groups SET official_times='', tt_fetched_at=0 WHERE id=?",
                  (gid,))


def official_times(group_key):
    r = _read("SELECT official_times FROM timetable_groups WHERE group_key=?",
              (group_key,), one=True)
    return r[0] if r else None


def tt_fetched_at(group_key):
    r = _read("SELECT tt_fetched_at FROM timetable_groups WHERE group_key=?",
              (group_key,), one=True)
    return r[0] if r else None


def weekly_slot_counts(group_key):
    """w = weekly slot count per subject_code, scoped to THIS user's group [F4].
    Precedent: _day_slots / timetable_html / /api/timetable all scope by group_id."""
    if not group_key:
        return {}
    gid = group_id(group_key)
    if not gid:
        return {}
    return {r[0]: r[1] for r in _read(
        "SELECT subject_code, COUNT(*) FROM timetable_slots "
        "WHERE group_id=? AND subject_code IS NOT NULL AND subject_code != '' "
        "GROUP BY subject_code", (gid,))}


def day_slots(group_key):
    """group_key -> {day: {period: slot}} or None when no timetable exists."""
    if not group_key:
        return None
    gid = group_id(group_key)
    if gid is None:
        return None
    day_slots = {}
    for r in group_slots(gid):
        if r[0] not in day_slots:
            day_slots[r[0]] = {}
        day_slots[r[0]][r[1]] = {"code": r[2], "name": r[3], "location": r[4] or ""}
    return day_slots


def edit_log_entries(gid, limit=50):
    return _read("SELECT editor_netid,editor_name,created_at,changes_json "
                 "FROM timetable_edit_log WHERE group_id=? ORDER BY id DESC LIMIT ?",
                 (gid, limit))


def append_edit_log(gid, editor_netid, editor_name, changes_json, keep=200):
    """One log entry + the spam ceiling, one transaction.
    ponytail: keep the last 200 entries per group; raise the LIMIT if
    sections start legitimately editing that often."""
    with transaction() as c:
        c.execute("INSERT INTO timetable_edit_log(group_id,editor_netid,editor_name,changes_json) "
                  "VALUES(?,?,?,?)",
                  (gid, editor_netid, editor_name, changes_json))
        c.execute("DELETE FROM timetable_edit_log WHERE group_id=? AND id NOT IN "
                  "(SELECT id FROM timetable_edit_log WHERE group_id=? ORDER BY id DESC LIMIT ?)",
                  (gid, gid, keep))


# ── repository: usage_events ─────────────────────────────────────────

def insert_usage_event(day, user, event, target, detail):
    """ponytail: plain INSERT, no batching — a few rows/day at this scale."""
    with transaction() as c:
        c.execute("INSERT INTO usage_events(day, user, event, target, detail) VALUES(?,?,?,?,?)",
                  (day, user, event, target[:64], detail[:64]))


def prune_usage_events(before_ts):
    with transaction() as c:
        return c.execute("DELETE FROM usage_events WHERE ts < ?", (before_ts,)).rowcount


# ── repository: component_tags / push_sent_log ───────────────────────

def component_tags(tag_keys):
    q = ",".join("?" * len(tag_keys))
    return _read(f"SELECT tag_key, role, raw_max, scaled_max FROM component_tags "
                 f"WHERE tag_key IN ({q})", list(tag_keys))


def upsert_component_tag(tag_key, role, raw_max, scaled_max, confirmed_by, updated_at):
    with transaction() as c:
        c.execute("""INSERT INTO component_tags(tag_key, role, raw_max, scaled_max, confirmed_by, updated_at)
                     VALUES(?,?,?,?,?,?)
                     ON CONFLICT(tag_key) DO UPDATE SET role=excluded.role, raw_max=excluded.raw_max,
                     scaled_max=excluded.scaled_max, confirmed_by=excluded.confirmed_by,
                     updated_at=excluded.updated_at""",
                  (tag_key, role, raw_max, scaled_max, confirmed_by, updated_at))


def prune_push_sent_log(local_date):
    with transaction() as c:
        c.execute("DELETE FROM push_sent_log WHERE local_date < ?", (local_date,))


def group_ids_for(group_keys):
    """{gid: group_key} for a batch — push tick resolves slots by id."""
    q = ",".join("?" * len(group_keys))
    return {r[0]: r[1] for r in _read(
        f"SELECT id, group_key FROM timetable_groups WHERE group_key IN ({q})",
        list(group_keys))}


def slots_for_groups(gids):
    q = ",".join("?" * len(gids))
    return _read(f"SELECT group_id, day, period, subject_code, subject_name, location "
                 f"FROM timetable_slots WHERE group_id IN ({q})", list(gids))
