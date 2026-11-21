"""The reminder card's first paint — the server states must not say "Loading…".

The bug this pins: app/templates/settings.html shipped the literal
"Loading…" and left it there. With public/js blocked (or before push.js ran)
the Settings page showed a loading line forever, while the very same state was
already decidable on the server: no VAPID keys, PUSH_ENABLED off, or a netid
outside PUSH_ALLOW_NETIDS. Only the browser can answer the remaining states
(permission, subscription), so those keep the placeholder.

Self-contained: temp DATA_DIR, seeded row + minted cookie, no server, no
network, fabricated netid (repo is public).
"""
import atexit
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

_td = tempfile.mkdtemp(prefix="osrm-pushssr-")
atexit.register(shutil.rmtree, _td, True)
os.environ["DATA_DIR"] = _td
os.environ["OCR_PREWARM"] = "0"

from app import app as A  # noqa: E402

NETID = "zz9999"                      # fabricated — repo is public
DB = os.path.join(_td, "srm.db")
PERSONAL = {"Student Name": "TEST STUDENT", "Register No.": "RA0000000000000",
            "Program": "B.Tech. Computer Science", "Batch": "2025",
            "Semester": "III SEMESTER", "Section": "A"}
VAPID = {"VAPID_PRIVATE_KEY": "priv", "VAPID_PUBLIC_KEY": "pub",
         "VAPID_SUBJECT": "mailto:test@example.com"}
PUSH_ENV = ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT",
            "PUSH_ENABLED", "PUSH_ALLOW_NETIDS")

NOT_SET_UP = "Class reminders are not set up on this server yet."
SWITCHED_OFF = "Class reminders are switched off on the server for now."
ROLLING_OUT = "Class reminders are rolling out"


def _seed():
    import sqlite3
    c = sqlite3.connect(DB)
    c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
                 attendance_json, last_fetch) VALUES(?,?,?,?,?)""",
              (NETID, "pw", json.dumps(PERSONAL), json.dumps({"courses": []}),
               int(time.time())))
    c.commit()
    c.close()


def _settings_html(env):
    """GET /settings with exactly `env` set among the push knobs."""
    old = {k: os.environ.get(k) for k in PUSH_ENV}
    for k in PUSH_ENV:
        os.environ.pop(k, None)
    os.environ.update(env)
    try:
        cl = A.app.test_client()
        cl.set_cookie("srm_session", A.make_session_token(NETID))
        return cl.get("/settings").get_data(as_text=True)
    finally:
        for k, v in old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def _state_line(html):
    """Text inside #push-state — the line push.js overwrites."""
    m = re.search(r'id="push-state">([^<]*)<', html)
    return None if m is None else m.group(1)


def t_no_vapid_renders_not_set_up():
    _seed()
    line = _state_line(_settings_html({}))
    assert line == NOT_SET_UP, line
    assert "Loading" not in (line or ""), line


def t_vapid_without_push_enabled_renders_switched_off():
    line = _state_line(_settings_html(VAPID))
    assert line == SWITCHED_OFF, line


def t_allowlist_miss_renders_rolling_out():
    line = _state_line(_settings_html({**VAPID, "PUSH_ENABLED": "1",
                                       "PUSH_ALLOW_NETIDS": "someoneelse"}))
    assert line.startswith(ROLLING_OUT), line
    assert NETID.upper() not in line, line


def t_decidable_by_the_browser_only_keeps_loading():
    line = _state_line(_settings_html({**VAPID, "PUSH_ENABLED": "1"}))
    assert line == "Loading…", line


TESTS = [
    ("no VAPID -> 'not set up' is server-painted", t_no_vapid_renders_not_set_up),
    ("VAPID but PUSH_ENABLED off -> 'switched off'", t_vapid_without_push_enabled_renders_switched_off),
    ("netid outside PUSH_ALLOW_NETIDS -> 'rolling out'", t_allowlist_miss_renders_rolling_out),
    ("browser-only state keeps 'Loading…'", t_decidable_by_the_browser_only_keeps_loading),
]


def main():
    failed = 0
    for name, fn in TESTS:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    total = len(TESTS)
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
