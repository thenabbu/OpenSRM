"""Versioned database migration system for OpenSRM.

Usage:
    from migrations import migrate_db
    migrate_db(conn)  # runs all pending migrations

Adding a new migration:
    from migrations import migration

    @migration(version=5, description="add exam_scores column")
    def m005_exam_scores(conn):
        conn.execute("ALTER TABLE users ADD COLUMN exam_scores TEXT DEFAULT '[]'")
"""
import logging
import sqlite3
import time
from typing import Callable

log = logging.getLogger("opensrm.migrations")

_registry: list[dict] = []


def migration(version: int, description: str):
    """Decorator to register a migration function."""
    def decorator(fn: Callable[[sqlite3.Connection], None]):
        _registry.append({"version": version, "description": description, "fn": fn})
        return fn
    return decorator


def _ensure_version_table(conn: sqlite3.Connection):
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (datetime('now')),
        description TEXT NOT NULL,
        duration_ms INTEGER NOT NULL DEFAULT 0
    )""")
    conn.commit()


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
    return row[0] if row else 0


def migrate_db(conn: sqlite3.Connection):
    """Run all pending migrations. Called once at startup."""
    _ensure_version_table(conn)
    current = _current_version(conn)
    pending = [m for m in sorted(_registry, key=lambda m: m["version"]) if m["version"] > current]

    if not pending:
        log.info("db.schema version=%d — no pending migrations", current)
        return

    log.info("db.schema version=%d — %d migration(s) pending", current, len(pending))

    for m in pending:
        v, desc, fn = m["version"], m["description"], m["fn"]
        t0 = time.monotonic()
        try:
            log.info("db.migrate apply version=%d desc='%s'", v, desc)
            fn(conn)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            conn.execute(
                "INSERT INTO schema_version(version, description, duration_ms) VALUES(?,?,?)",
                (v, desc, elapsed_ms))
            conn.commit()
            log.info("db.migrate done version=%d desc='%s' duration_ms=%d", v, desc, elapsed_ms)
        except Exception:
            log.exception("db.migrate FAILED version=%d desc='%s'", v, desc)
            raise

    final = _current_version(conn)
    log.info("db.schema version=%d — all migrations complete", final)


# ── Migrations ──────────────────────────────────────────────────────

@migration(version=1, description="base tables: users, cookies")
def m001_base(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS users(
        netid TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        attendance_json TEXT,
        last_fetch INTEGER DEFAULT 0
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS cookies(
        token TEXT PRIMARY KEY,
        netid TEXT NOT NULL,
        created INTEGER NOT NULL
    )""")

@migration(version=2, description="add personal_details_json, photo_b64 to users")
def m002_personal(conn):
    try:
        conn.execute("ALTER TABLE users ADD COLUMN personal_details_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN photo_b64 TEXT")
    except sqlite3.OperationalError:
        pass

@migration(version=3, description="add timetable tables")
def m003_timetable(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS timetable_groups (
        id INTEGER PRIMARY KEY, group_key TEXT UNIQUE NOT NULL,
        program TEXT, batch INTEGER, semester INTEGER, section TEXT,
        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS timetable_slots (
        id INTEGER PRIMARY KEY,
        group_id INTEGER NOT NULL REFERENCES timetable_groups(id) ON DELETE CASCADE,
        day TEXT NOT NULL, period INTEGER NOT NULL,
        subject_code TEXT, subject_name TEXT, location TEXT DEFAULT '',
        UNIQUE(group_id, day, period))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS timetable_subjects (
        id INTEGER PRIMARY KEY,
        group_id INTEGER NOT NULL REFERENCES timetable_groups(id) ON DELETE CASCADE,
        code TEXT NOT NULL, name TEXT NOT NULL, credits INTEGER DEFAULT 0,
        is_custom INTEGER DEFAULT 0, UNIQUE(group_id, code))""")

@migration(version=4, description="add marks_json, subjects_json to users")
def m004_marks(conn):
    try:
        conn.execute("ALTER TABLE users ADD COLUMN marks_json TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN subjects_json TEXT DEFAULT '{}'")
    except sqlite3.OperationalError:
        pass
