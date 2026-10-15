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

v1.20.3 (migration 17) adds: cookies.token stores sha256(token) — the
browser keeps the raw token, the DB never does, so a leaked srm.db cannot
be replayed as a live session — and a before_request guard refuses
cross-site POST/PUT/PATCH/DELETE (403 + error= on the opensrm.http line).
"""
import atexit
import hashlib
import logging
import os
import secrets
import shutil
import sqlite3
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
    """30-day expiry still enforced at read time (audit 2026-09-27 contract).
    Rows are keyed by sha256(token) since migration 17, so the UPDATE and
    the count both address the digest."""
    tok = A.make_session_token("zz9999")
    digest = hashlib.sha256(tok.encode()).hexdigest()
    c = A.db()
    c.execute("UPDATE cookies SET created=? WHERE token=?",
              (int(time.time()) - A.SESSION_MAX_AGE - 60, digest))
    c.commit(); c.close()
    assert _who(tok) is None, "expired token must not authenticate"
    c = A.db()
    n = c.execute("SELECT COUNT(*) FROM cookies WHERE token=?", (digest,)).fetchone()[0]
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


def t_logout_ignored_on_cross_site():
    """audit run-1 #15: SameSite=Lax sends the cookie on a cross-site
    TOP-LEVEL GET — one attacker link/meta-refresh used to kill the session.
    Sec-Fetch-Site: cross-site (a forbidden header clients can't strip) must
    be ignored; a same-site navigation still logs out."""
    tok = A.make_session_token("zz9999")
    cl = A.app.test_client()
    cl.set_cookie("srm_session", tok)
    r = cl.get("/logout", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code in (302, 303), f"cross-site still gets the redirect, got {r.status_code}"
    assert _who(tok) == "zz9999", "cross-site logout must NOT delete the session"
    # same-site (no header / explicit same-origin) still works
    cl2 = A.app.test_client()
    cl2.set_cookie("srm_session", tok)
    r = cl2.get("/logout")
    assert r.status_code in (302, 303), r.status_code
    assert _who(tok) is None, "same-site logout must still delete the session"


def t_index_refresh_survive_mid_request_session_loss():
    """Race: the session row vanishes BETWEEN require_login's read and the
    handler's own get_current_user() re-read (logout in another tab landing
    mid-request, same cookie/token). index() must redirect to /login — not
    500 from a None netid; api_refresh must say "not logged in", not blame
    missing stored creds (review finding 2026-10-11).
    """
    tok = A.make_session_token("zz9999")
    orig = A.get_current_user
    state = {"n": 0}

    def racy():
        state["n"] += 1
        return orig() if state["n"] == 1 else None

    A.get_current_user = racy
    try:
        cl = A.app.test_client()
        cl.set_cookie("srm_session", tok)   # gotcha: Cookie header in headers= is dropped
        state["n"] = 0
        r1 = cl.get("/")
        state["n"] = 0
        r2 = cl.post("/api/refresh")
    finally:
        A.get_current_user = orig
    assert r1.status_code in (302, 303), \
        f"index must redirect when the session vanishes mid-request, got {r1.status_code}"
    j = r2.get_json()
    assert r2.status_code == 401 and j and j.get("error") == "not logged in", \
        f"api_refresh must report 'not logged in', got {r2.status_code} {j!r}"


def t_token_stored_hashed_raw_never_at_rest():
    """make_session_token still RETURNS the raw token (contract), but the DB
    row must be sha256(token): a leaked srm.db yields digests, never a value
    the /login cookie can replay. Read path hashes the presented value."""
    tok = A.make_session_token("zz9999")
    digest = hashlib.sha256(tok.encode()).hexdigest()
    c = A.db()
    row = c.execute("SELECT token FROM cookies WHERE token=?", (digest,)).fetchone()
    raw_rows = c.execute("SELECT COUNT(*) FROM cookies WHERE token=?", (tok,)).fetchone()[0]
    c.close()
    assert row is not None, f"row keyed by sha256(raw) missing — stored value is not the digest"
    assert raw_rows == 0, "raw token found verbatim in the DB — token leaked at rest"
    assert _who(tok) == "zz9999", "raw cookie must still authenticate (read path hashes to match)"


def t_pre_migration_rows_hashed_and_session_survives():
    """Pre-migration fixture: a DB exactly as prod stood BEFORE this release
    (schema v16, cookies.token holding the RAW token) must come out of
    migration 17 with the row hashed AND the browser's existing raw cookie
    still authenticating — current sessions survive the deploy."""
    import app.migrations as M
    fx = Path(_td) / "pre-migration.db"
    conn = sqlite3.connect(fx)
    saved = M._registry[:]
    try:
        # state BEFORE this release: every migration except 17 registered
        M._registry[:] = [m for m in saved if m["version"] != 17]
        M.migrate_db(conn)
        ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert ver == 16, f"fixture must stand at schema v16 before the migration, got v{ver}"
        raw = secrets.token_hex(32)   # prod-shaped: pre-17 rows held the raw token
        conn.execute("INSERT INTO cookies(token,netid,created) VALUES(?,?,?)",
                     (raw, "zz9999", int(time.time())))
        conn.commit()
    finally:
        M._registry[:] = saved
    # the deploy: migration 17 runs, in Python, over the existing rows
    M.migrate_db(conn)
    stored = conn.execute("SELECT token FROM cookies").fetchone()[0]
    assert stored == hashlib.sha256(raw.encode()).hexdigest(), \
        "migration 17 must store sha256(raw) for the pre-existing row"
    assert stored != raw, "pre-migration row still holds the raw token"
    ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert ver == 17, f"schema_version must record 17 after the migration, got {ver}"
    # the session survives: the browser still holds `raw` — it must resolve
    old_path = A.DB_PATH
    A.DB_PATH = str(fx)
    try:
        who = _who(raw)
    finally:
        A.DB_PATH = old_path
        conn.close()
    assert who == "zz9999", \
        f"session died across the deploy migration — raw cookie now resolves to {who!r}"


_CROSS = {"Sec-Fetch-Site": "cross-site"}


def t_guard_refuses_cross_site_state_changing():
    """Sec-Fetch-Site is a forbidden header (cross-site pages can neither
    strip nor forge it): cross-site and same-site POSTs must be refused with
    403 + error= before any view logic runs."""
    cl = A.app.test_client()
    for sfs in ("cross-site", "same-site"):
        r = cl.post("/api/refresh", headers={"Sec-Fetch-Site": sfs})
        j = r.get_json(silent=True)
        assert r.status_code == 403, \
            f"Sec-Fetch-Site: {sfs} POST must be 403, got {r.status_code}"
        assert j and "error" in j, f"403 must carry an error body, got {j!r}"


def t_guard_refuses_origin_mismatch():
    """Without Sec-Fetch-Site: an Origin whose host differs from the request
    host is refused (incl. the sandboxed 'null' origin — fails closed)."""
    cl = A.app.test_client()
    for origin in ("https://evil.example", "null", "http://localhost:1"):
        r = cl.post("/api/refresh", headers={"Origin": origin})
        j = r.get_json(silent=True)
        assert r.status_code == 403, f"Origin {origin!r} POST must be 403, got {r.status_code}"
        assert j and "error" in j, f"403 must carry an error body, got {j!r}"


def t_guard_allows_non_browser_and_same_origin():
    """Allowed branches: neither header (curl/cron/tests — non-browser), a
    matching Origin, Sec-Fetch-Site same-origin / none. GET is never guarded
    (state-changing methods only), even cross-site."""
    cl = A.app.test_client()
    allowed = {
        "no headers (non-browser)": cl.post("/api/refresh"),
        "Origin same host": cl.post("/api/refresh", headers={"Origin": "http://localhost"}),
        "SFS same-origin": cl.post("/api/refresh", headers={"Sec-Fetch-Site": "same-origin"}),
        "SFS none": cl.post("/api/refresh", headers={"Sec-Fetch-Site": "none"}),
        "GET cross-site": cl.get("/", headers=_CROSS),
    }
    for name, r in allowed.items():
        assert r.status_code != 403, f"{name} must pass the guard, got 403"


def t_guard_covers_put_patch_delete():
    """PUT/PATCH/DELETE are refused too — and the refusal comes from the
    guard (403), not from routing: the same PUT with clean headers is a
    plain 405 Method Not Allowed."""
    cl = A.app.test_client()
    for method in (cl.put, cl.patch, cl.delete):
        r = method("/api/refresh", headers=_CROSS)
        assert r.status_code == 403, \
            f"{method.__name__.upper()} cross-site must be 403, got {r.status_code}"
    r = cl.put("/api/refresh")
    assert r.status_code == 405, \
        f"clean PUT must reach routing (405), got {r.status_code} — guard over-blocking?"


def t_guard_exempts_push_tick():
    """POST /internal/push/tick authenticates with its own secret header, so
    the cross-site guard is exempt: it must reach the tick auth (bare 401),
    never the guard's 403."""
    cl = A.app.test_client()
    r = cl.post("/internal/push/tick", headers=_CROSS)
    assert r.status_code == 401, \
        f"push tick must reach its own secret-header auth (401), got {r.status_code}"


def _capture(logger_name):
    """Attach a collecting handler to a named logger; returns (handler, detach)."""
    h = logging.Handler()
    h.setLevel(logging.DEBUG)
    h.emit = lambda rec: h.records.append(rec)  # type: ignore[attr-defined]
    h.records = []  # type: ignore[attr-defined]
    lg = logging.getLogger(logger_name)
    lg.addHandler(h)
    return h, lambda: lg.removeHandler(h)


def t_guard_403_logged_with_error():
    """A refusal must be countable from logs: the opensrm.http request line
    carries status=403 and error= (v1.15.x 4xx-on-one-line contract)."""
    h, detach = _capture("opensrm.http")
    try:
        A.app.test_client().post("/api/refresh", headers=_CROSS)
    finally:
        detach()
    # log_with_kv renders kv on the record (the formatter prints them as
    # `status=403 … error=…`); getMessage() alone is just "request".
    seen = [(r.getMessage(), getattr(r, "kv", {})) for r in h.records]
    hit = [(m, kv) for m, kv in seen if str(kv.get("status")) == "403"]
    assert hit, f"no status=403 record on opensrm.http for the refusal; got: {seen!r}"
    assert hit[0][1].get("error"), \
        f"403 record must carry error=, got kv={hit[0][1]!r}"


def t_logout_emits_auth_line():
    """Session mutations keep emitting their opensrm.auth line: a real
    logout logs 'logout ok' with the netid (incident 2026-10-10 contract)."""
    tok = A.make_session_token("zz9999")
    h, detach = _capture("opensrm.auth")
    try:
        cl = A.app.test_client()
        cl.set_cookie("srm_session", tok)
        r = cl.get("/logout")
    finally:
        detach()
    assert r.status_code in (302, 303), f"logout must redirect, got {r.status_code}"
    seen = [(r.getMessage(), getattr(r, "kv", {})) for r in h.records]
    hit = [(m, kv) for m, kv in seen if m == "logout ok"]
    assert hit, f"no opensrm.auth 'logout ok' record on real logout; got: {seen!r}"
    assert hit[0][1].get("netid") == "zz9999", \
        f"logout auth record must name the netid, got kv={hit[0][1]!r}"


TESTS = [
    ("second login keeps first session (multi-device)", t_second_login_keeps_first_session),
    ("expired token pruned on read", t_expired_token_pruned_on_read),
    ("real GET /logout deletes session", t_logout_real_navigation_deletes),
    ("logout no-op on Sec-Purpose prefetch/prerender", t_logout_ignored_on_prefetch),
    ("logout no-op on cross-site fetch (audit #15)", t_logout_ignored_on_cross_site),
    ("index/refresh survive mid-request session loss", t_index_refresh_survive_mid_request_session_loss),
    ("token stored as sha256 digest, raw never at rest", t_token_stored_hashed_raw_never_at_rest),
    ("pre-migration rows hashed, session survives deploy", t_pre_migration_rows_hashed_and_session_survives),
    ("guard refuses cross-site POST (Sec-Fetch-Site)", t_guard_refuses_cross_site_state_changing),
    ("guard refuses Origin host mismatch", t_guard_refuses_origin_mismatch),
    ("guard allows non-browser/same-origin/GET", t_guard_allows_non_browser_and_same_origin),
    ("guard covers PUT/PATCH/DELETE (403, not 405)", t_guard_covers_put_patch_delete),
    ("guard exempts /internal/push/tick", t_guard_exempts_push_tick),
    ("refusal logged on opensrm.http with error=", t_guard_403_logged_with_error),
    ("real logout emits opensrm.auth line", t_logout_emits_auth_line),
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
