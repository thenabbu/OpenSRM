"""Shared test seed: self-contained user + timetable data for DUT runs.

DATA_DIR decides which DB; same DATA_DIR must be given to the gunicorn
under test so seed + server share one file.
"""
import json, os, sys, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

PAYLOAD = '<img src=x onerror="window.__xss=1"><script>window.__xss2=1</script>'
PERSONAL = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
            "Batch": "2025", "Semester": "III SEMESTER", "Section": "A"}


def seed(with_payload=True):
    from app import app as A
    c = A.db()
    c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json, last_fetch)
                 VALUES('ng2776', 'unused-by-tests', ?, ?)""",
              (json.dumps(PERSONAL), int(time.time())))
    gid = None
    if with_payload:
        gk = A._group_key(PERSONAL)
        c.execute("""INSERT OR IGNORE INTO timetable_groups(group_key, program, batch, semester, section)
                     VALUES(?, 'CSE Cloud Computing', 2025, 3, 'A')""", (gk,))
        gid = c.execute("SELECT id FROM timetable_groups WHERE group_key=?", (gk,)).fetchone()[0]
        # UNIQUE(group_id,day,period): replace whatever sits at Monday p6
        c.execute("DELETE FROM timetable_slots WHERE group_id=? AND day='Monday' AND period=6", (gid,))
        c.execute("""INSERT INTO timetable_slots(group_id, day, period, subject_code, subject_name, location)
                     VALUES(?, 'Monday', 6, ?, ?, 'Test Hall')""", (gid, PAYLOAD, PAYLOAD))
    c.commit(); c.close()


def mint_token():
    from app.app import make_session_token
    return make_session_token('ng2776')
