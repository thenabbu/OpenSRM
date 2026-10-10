"""Session lifecycle: logins must not kill other sessions; logout must not fire on prefetch.

Covers the 2026-10-10 prod incident — "sessions don't last, keeps asking for
creds": 78 logins across 8 accounts over Sep 22 - Oct 10 (main account: 58
logins, 13 distinct IPs). Of 70 re-logins (78 total minus 8 firsts), 44 followed
the same account's OWN earlier login (36 from a different IP = cross-device)
because make_session_token() ran `DELETE FROM cookies WHERE netid=?` on every
login — one session per account, globally; deploy smoke mints hit the same
path silently (no auth log line). 26 more followed a real /logout 302;
Cloudflare Speed Brain serves conservative speculation rules for /*, and
GET /logout was state-changing, so a touch-start-then-scroll on the logout
link can prefetch it and kill the session without any navigation.

Fix: keep sibling sessions alive (expiry still bounds them), and make
/logout a no-op for Sec-Purpose: prefetch|prerender requests.
"""
import atexit
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# verify76 forbids test DBs in-tree; the dir must outlive this module's import
# (tests run after the import block), so mkdtemp + atexit cleanup, not `with`.
_td = tempfile.mkdtemp(prefix="osrm-sessions-")
atexit.register(shutil.rmtree, _td, True)
os.environ["DATA_DIR"] = _td
from app import app as A


def _who(tok):
    with A.app.test_request_context("/", headers={"Cookie": f"srm_session={tok}"}):
        return A.get_current_user()


def t_second_login_keeps_first_session():
    """A login from device B must not evict device A's session (multi-device)."""
    tok1 = A.make_session_token("zz9999")
    tok2 = A.make_session_token("zz9999")
    assert _who(tok1) == "zz9999", \
        f"first session died on second login (tok1 now resolves to {_who(tok1)!r})"
    assert _who(tok2) == "zz9999", "second session must be valid"
    # cross-user isolation: another account's logins never touch this one
    A.make_session_token("yy8888")
    assert _who(tok1) == "zz9999", "different netid's login evicted this session"


def t_expired_token_pruned_on_read():
    """30-day expiry still enforced at read time (audit 2026-09-27 contract)."""
    tok = A.make_session_token("zz9999")
    c = A.db()
    c.execute("UPDATE cookies SET created=? WHERE token=?",
              (int(time.time()) - A.SESSION_MAX_AGE - 60, tok))
    c.commit(); c.close()
    assert _who(tok) is None, "expired token must not authenticate"
    c = A.db()
    n = c.execute("SELECT COUNT(*) FROM cookies WHERE token=?", (tok,)).fetchone()[0]
    c.close()
    assert n == 0, "expired token row must be deleted at read time"


def t_logout_real_navigation_deletes():
    """A real GET /logout (no speculation header) still kills the session."""
    tok = A.make_session_token("zz9999")
    cl = A.app.test_client()
    cl.set_cookie("srm_session", tok)   # gotcha: Cookie header in headers= is dropped
    r = cl.get("/logout")
    assert r.status_code in (302, 303), f"logout must redirect, got {r.status_code}"
    assert _who(tok) is None, "real logout must delete the session row"


def t_logout_ignored_on_prefetch():
    """Sec-Purpose: prefetch/prerender must NOT delete the session (speculation rules)."""
    tok = A.make_session_token("zz9999")
    for hdr in ({"Sec-Purpose": "prefetch"}, {"Sec-Purpose": "prerender"}):
        cl = A.app.test_client()
        cl.set_cookie("srm_session", tok)
        r = cl.get("/logout", headers=hdr)
        assert r.status_code in (302, 303), "prefetch still gets the redirect"
    assert _who(tok) == "zz9999", \
        "prefetch killed the session — state-changing GET fired without navigation"


TESTS = [
    ("second login keeps first session (multi-device)", t_second_login_keeps_first_session),
    ("expired token pruned on read", t_expired_token_pruned_on_read),
    ("real GET /logout deletes session", t_logout_real_navigation_deletes),
    ("logout no-op on Sec-Purpose prefetch/prerender", t_logout_ignored_on_prefetch),
]

if __name__ == "__main__":
    failed = 0
    for name, fn in TESTS:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
