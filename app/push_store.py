"""Web-push storage: subscriptions, sent log, rate-limit/test-receipt events.

Every push table lives behind this module so the DB can move from SQLite
to Postgres/libSQL (Vercel) by changing get_conn() alone. SQL rules —
enforced by tests/test_push_store.py:
  - ``ON CONFLICT ... DO NOTHING/UPDATE`` + rowcount checks (no ``INSERT OR IGNORE``)
  - integer epoch timestamps, no SQL-side clock functions
  - no ``rowid``, no PRAGMA, no SQLite-only syntax
The rest of the app's database (users/sessions/timetable) is NOT migrated
here — those tables keep being read through app.db() as before.
"""
import json
import time

# Sent-log statuses: claimed -> sent | failed | orphaned | skipped
#   claimed : insert won; the claimer is about to send
#   sent    : push service returned 2xx
#   failed  : retryable (non-2xx/timeout), retried while inside the window
#   orphaned: process died mid-send (row stuck at 'claimed'); finalized
#             without a retry — at-most-once by design
#   skipped : deadline passed before any send attempt
STATUS_CLAIMED, STATUS_SENT, STATUS_FAILED = "claimed", "sent", "failed"
STATUS_ORPHANED, STATUS_SKIPPED = "orphaned", "skipped"


def get_conn():
    """The single connection factory — swap this for Postgres/libSQL."""
    from .app import db  # lazy: app imports this module at boot
    return db()


# ── subscriptions ─────────────────────────────────────────────────────

def upsert_subscription(netid, endpoint, p256dh, auth, ua_label, lead_minutes=10):
    """Insert, or rebind an existing endpoint to the calling netid.

    UNIQUE(endpoint) + DO UPDATE means a shared phone always notifies the
    NEWEST user; the id (and thus sent-log idempotency) survives rebinds.
    """
    c = get_conn()
    c.execute("""INSERT INTO push_subscriptions(netid, endpoint, p256dh, auth, lead_minutes, enabled, created_at, ua_label)
                 VALUES(?,?,?,?,?,1,?,?)
                 ON CONFLICT(endpoint) DO UPDATE SET netid=excluded.netid, p256dh=excluded.p256dh,
                   auth=excluded.auth, ua_label=excluded.ua_label""",
              (netid, endpoint, p256dh, auth, int(lead_minutes), int(time.time()), ua_label))
    row = c.execute("SELECT * FROM push_subscriptions WHERE endpoint=?", (endpoint,)).fetchone()
    c.commit(); c.close()
    return dict(row) if row else None


def list_subscriptions(netid=None, enabled_only=True):
    c = get_conn()
    q = "SELECT * FROM push_subscriptions WHERE 1=1"
    args = []
    if netid is not None:
        q += " AND netid=?"; args.append(netid)
    if enabled_only:
        q += " AND enabled=1"
    rows = [dict(r) for r in c.execute(q, args).fetchall()]
    c.close()
    return rows


def set_settings(netid, lead_minutes=None, enabled=None):
    """Update the caller's subscriptions; returns rows touched."""
    c = get_conn()
    sets, args = [], []
    if lead_minutes is not None:
        sets.append("lead_minutes=?"); args.append(int(lead_minutes))
    if enabled is not None:
        sets.append("enabled=?"); args.append(1 if enabled else 0)
    n = 0
    if sets:
        args.append(netid)
        cur = c.execute(f"UPDATE push_subscriptions SET {', '.join(sets)} WHERE netid=?", args)
        n = cur.rowcount
        c.commit()
    c.close()
    return n


def remove_subscription(netid, endpoint):
    """Unsubscribe: returns True when a row was actually deleted."""
    c = get_conn()
    cur = c.execute("DELETE FROM push_subscriptions WHERE netid=? AND endpoint=?", (netid, endpoint))
    n = cur.rowcount
    c.commit(); c.close()
    return n == 1


def delete_subscription_by_id(sub_id):
    """Dead-subscription cleanup (push service answered 404/410)."""
    c = get_conn()
    cur = c.execute("DELETE FROM push_subscriptions WHERE id=?", (sub_id,))
    n = cur.rowcount
    c.commit(); c.close()
    return n == 1


def record_subscription_result(sub_id, ok, http_status=None):
    """Per-send outcome on the subscription row (last_status/succeed/fail)."""
    c = get_conn()
    if ok:
        c.execute("""UPDATE push_subscriptions SET last_success_at=?, last_status='ok',
                     fail_count=0 WHERE id=?""", (int(time.time()), sub_id))
    else:
        c.execute("""UPDATE push_subscriptions SET last_status=?, fail_count=fail_count+1
                     WHERE id=?""", (f"http_{http_status}" if http_status else "error", sub_id))
    c.commit(); c.close()


# ── sent log (idempotency) ────────────────────────────────────────────

def sent_state_for(local_date):
    """{key: (status, attempts, row_id)} for one local date — the `sent`
    input of due_reminders (row_id lets a retry claim the same row)."""
    c = get_conn()
    rows = c.execute("""SELECT id, subscription_id, local_date, block_start, subject_code, status, attempts
                        FROM push_sent_log WHERE local_date=?""", (local_date,)).fetchall()
    c.close()
    return {(r[1], r[2], r[3], r[4]): (r[5], r[6], r[0]) for r in rows}


def claim_send(sub_id, local_date, block_start, subject_code):
    """At-most-once: True only for the caller that inserted the row."""
    c = get_conn()
    cur = c.execute("""INSERT INTO push_sent_log(subscription_id, local_date, block_start, subject_code, status, attempts, claimed_at)
                       VALUES(?,?,?,?,?,1,?)
                       ON CONFLICT(subscription_id, local_date, block_start, subject_code) DO NOTHING""",
                    (sub_id, local_date, block_start, subject_code, STATUS_CLAIMED, int(time.time())))
    n = cur.rowcount
    c.commit(); c.close()
    return n == 1


def claim_retry(row_id, max_attempts):
    """One retry slot for a FAILED row; concurrent ticks race safely."""
    c = get_conn()
    cur = c.execute("""UPDATE push_sent_log SET attempts=attempts+1
                       WHERE id=? AND status=? AND attempts<?""",
                    (row_id, STATUS_FAILED, max_attempts))
    n = cur.rowcount
    c.commit(); c.close()
    return n == 1


def sent_row_id(sub_id, local_date, block_start, subject_code):
    """Row id of an existing claim (used to record its outcome)."""
    c = get_conn()
    row = c.execute("""SELECT id FROM push_sent_log WHERE subscription_id=? AND local_date=?
                       AND block_start=? AND subject_code=?""",
                    (sub_id, local_date, block_start, subject_code)).fetchone()
    c.close()
    return row[0] if row else None


def record_send_result(row_id, status, http_status=None):
    c = get_conn()
    c.execute("UPDATE push_sent_log SET status=?, http_status=?, sent_at=? WHERE id=?",
              (status, http_status, int(time.time()), row_id))
    c.commit(); c.close()


def finalize_stale_claims(before_epoch):
    """Crash recovery: claims stuck with no outcome since before `before_epoch`
    become 'orphaned' and are never retried (at-most-once). Returns count."""
    c = get_conn()
    cur = c.execute("""UPDATE push_sent_log SET status=? WHERE status=? AND sent_at IS NULL
                       AND claimed_at<?""", (STATUS_ORPHANED, STATUS_CLAIMED, int(before_epoch)))
    n = cur.rowcount
    c.commit(); c.close()
    return n


# ── rate limits + test receipts (push_events) ─────────────────────────

def record_event(netid, kind, key, data=None):
    c = get_conn()
    c.execute("INSERT INTO push_events(netid, kind, key, created_at, data_json) VALUES(?,?,?,?,?)",
              (netid, kind, key, int(time.time()), json.dumps(data or {})))
    c.commit(); c.close()


def count_events(netid, kind, since_epoch):
    c = get_conn()
    row = c.execute("SELECT COUNT(*) FROM push_events WHERE netid=? AND kind=? AND created_at>=?",
                    (netid, kind, since_epoch)).fetchone()
    c.close()
    return int(row[0])


def prune_events(older_than_epoch):
    """Keep the events table small — drop rate rows past any window we use."""
    c = get_conn()
    c.execute("DELETE FROM push_events WHERE created_at<?", (int(older_than_epoch),))
    c.commit(); c.close()
