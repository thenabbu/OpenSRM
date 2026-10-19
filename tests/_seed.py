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
                 VALUES('zz9999', 'unused-by-tests', ?, ?)""",
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
    return make_session_token('zz9999')


def seed_rich(with_payload=True):
    """Full-fidelity seed: base user + realistic attendance/marks/exams/
    faculty payloads so EVERY dashboard card and tab renders (grid, ticker,
    budgets, estimates, absences, marks widget, exams card, teachers list,
    feedback plan, personal-details groups). Shared by test_dash_fit.py and
    scripts/perf_baseline.py — add payload keys HERE, never per-suite: one
    canonical rich dataset keeps before/after captures comparable."""
    seed(with_payload)
    from app import app as A
    personal = {**PERSONAL, "Student Name": "Test Student",
                "Register No.": "RA2500000000"}
    att = {"courses": [
        {"code": "21CSC201J", "description": "DATA STRUCTURES AND ALGORITHMS", "max_hours": "46", "attended": "45", "absent": "1"},
        {"code": "21CSC202J", "description": "OPERATING SYSTEMS", "max_hours": "44", "attended": "30", "absent": "14"},
        {"code": "21CSC203P", "description": "ADVANCED PROGRAMMING PRACTICE", "max_hours": "55", "attended": "30", "absent": "25"},
        {"code": "21CSS201T", "description": "COMPUTER ORGANIZATION AND ARCHITECTURE", "max_hours": "45", "attended": "43", "absent": "2"},
        {"code": "21DCS201P", "description": "DESIGN THINKING AND METHODOLOGY", "max_hours": "30", "attended": "26", "absent": "4"},
        {"code": "21LEM201T", "description": "PROFESSIONAL ETHICS", "max_hours": "11", "attended": "10", "absent": "1"},
        {"code": "21MAB206T", "description": "NUMERICAL METHODS AND ANALYSIS", "max_hours": "44", "attended": "38", "absent": "6"},
        {"code": "CL", "description": "CLASS IN CHARGE", "max_hours": "4", "attended": "2", "absent": "2"}],
        "period": {"from": "20/Jul/2026", "to": "13/Oct/2026"},
        "monthly": [{"month": "OCT / 2026", "present": "19", "absent": "5",
                     "od_present": "0", "od_absent": "0", "ml": "0"}],
        "daily_absent": {"OCT / 2026": [{"date": "01-10-2026", "hours": "1"},
                                        {"date": "06-10-2026", "hours": "2"}]}}
    marks = [{"code": "21CSS201T", "title": "COMPUTER ORGANIZATION AND ARCHITECTURE",
              "components": [{"name": "FT-I", "entered": "04/Sep/2026", "scored": 4.5, "max": 5.0}],
              "scored_total": 4.5, "max_total": 5.0},
             {"code": "21MAB206T", "title": "NUMERICAL METHODS AND ANALYSIS",
              "components": [{"name": "FT-I", "entered": "21/Sep/2026", "scored": 5.0, "max": 5.0}],
              "scored_total": 5.0, "max_total": 5.0}]
    exams = [{"code": "21CSC201J", "name": "DATA STRUCTURES AND ALGORITHMS", "date": "25-11-2026", "session": "FN", "month": "11", "year": "2026"},
             {"code": "21CSC202J", "name": "OPERATING SYSTEMS", "date": "28-11-2026", "session": "AN", "month": "11", "year": "2026"}]
    faculty = {"DATA STRUCTURES AND ALGORITHMS": {"subject_id": "90001", "staff": [["50001", "Dr.Test Alpha-Theory"], ["50002", "Dr.Test Beta-Theory"]]},
               "OPERATING SYSTEMS": {"subject_id": "90004", "staff": [["50004", "Dr.Test Delta-Theory"]]},
               "ADVANCED PROGRAMMING PRACTICE": {"subject_id": "90005", "staff": [["50005", "Dr.Test Epsilon-Practical"]]},
               "COMPUTER ORGANIZATION AND ARCHITECTURE": {"subject_id": "90006", "staff": [["50006", "Dr.Test Zeta-Theory"]]},
               "DESIGN THINKING AND METHODOLOGY": {"subject_id": "90007", "staff": [["50007", "Dr.Test Eta-Practical"]]},
               "PROFESSIONAL ETHICS": {"subject_id": "90002", "staff": [["50003", "Dr.Test Gamma-Practical"]]},
               "NUMERICAL METHODS AND ANALYSIS": {"subject_id": "90008", "staff": [["50008", "Dr.Test Theta-Theory"]]}}
    c = A.db()
    c.execute("""UPDATE users SET personal_details_json=?, attendance_json=?, marks_json=?,
                 exam_schedule_json=?, faculty_map_json=?, fb_open=?, last_fetch=?
                 WHERE netid='zz9999'""",
              (json.dumps(personal), json.dumps(att), json.dumps(marks),
               json.dumps(exams), json.dumps(faculty), 1, int(time.time())))
    c.commit(); c.close()


# ---- phantom-verdict guard: the server under test must be THIS worktree ----
def _listener_pid(port):
    """PID of whatever LISTENS on `port`. ss/lsof are absent on this host:
    /proc/net/tcp{,6} state 0A -> socket inode -> /proc/*/fd owner."""
    ino = None
    needle = f":{port:04X}"
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = open(path).read().splitlines()[1:]
        except OSError:
            continue
        for ln in rows:
            f = ln.split()
            if len(f) > 9 and f[1].upper().endswith(needle) and f[3] == "0A":
                ino = f[9]
                break
        if ino:
            break
    if not ino:
        return None
    tgt = f"socket:[{ino}]"
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            fds = os.listdir(f"/proc/{d}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(f"/proc/{d}/fd/{fd}") == tgt:
                    return int(d)
            except OSError:
                pass
    return None


def _served_hash_matches(base, rel="static/sw.js"):
    """Fallback used ONLY when the listener's cwd is unreadable (foreign uid):
    sha256 of the served file vs this tree's file."""
    import hashlib
    import urllib.request
    try:
        remote = urllib.request.urlopen(f"{base}/{rel}", timeout=10).read()
        with open(os.path.join(REPO, "app", rel), "rb") as fh:
            local = fh.read()
    except Exception:
        return False
    return hashlib.sha256(remote).hexdigest() == hashlib.sha256(local).hexdigest()


def _proc_env(pid):
    try:
        raw = open(f"/proc/{pid}/environ", "rb").read().decode(errors="replace")
    except OSError:
        return {}
    return dict(kv.split("=", 1) for kv in raw.split("\0") if "=" in kv)


def require_own_server(*bases):
    """FAIL (exit 1, before any browser or login work) unless every base is
    served by THIS worktree's own gunicorn. Kills phantom verdicts: a foreign
    server holding a default port gets graded as your code (Oct 2026: 7/7, 9/9,
    16/16 "verified" against another worktree; also the 6/7 that became 7/7
    from DUT_BASE alone).

    Identity = listener's boot cwd vs REPO (the tree owning this test file) —
    a served-vs-tree sha256 alone is insufficient: the incident's foreign sw.js
    hash-matched. DATA_DIR is checked too (seed/mint must land in the DB the
    server reads). ponytail: Linux local gunicorn only (needs /proc, same uid);
    a container/prod target would need a served-byte marker endpoint instead.
    """
    from urllib.parse import urlsplit
    wt = os.path.realpath(REPO)
    for base in bases:
        port = urlsplit(base).port
        if not port:
            sys.exit(f"FAIL[guard]: no port in {base!r} — pass e.g. "
                     f"DUT_BASE=http://127.0.0.1:18177")
        pid = _listener_pid(port)
        if pid is None:
            sys.exit(f"FAIL[guard]: nothing listening on port {port} ({base}) — "
                     f"boot gunicorn from {wt}, then re-run with DUT_BASE={base} inline")
        try:
            cwd = os.path.realpath(f"/proc/{pid}/cwd")
        except OSError:
            cwd = None
        if cwd != wt and not (cwd is None and _served_hash_matches(base)):
            sys.exit(f"FAIL[guard]: {base} is served by pid {pid} cwd={cwd} — NOT this "
                     f"worktree ({wt}). Phantom verdict: another agent's server would be "
                     f"graded as yours. Boot gunicorn from this worktree and re-run with "
                     f"DUT_BASE={base} inline.")
        mine = os.environ.get("DATA_DIR")
        if mine:
            theirs = _proc_env(pid).get("DATA_DIR")
            if theirs != mine:
                sys.exit(f"FAIL[guard]: {base} server DATA_DIR={theirs!r} != this run's "
                         f"DATA_DIR={mine!r} — seed/mint land in a DB the server never reads "
                         f"(vacuous positive controls / lost cookies). Re-boot with "
                         f"DATA_DIR={mine} and pass it inline.")
