"""One runnable check for SCOPE-only mode (PORTAL_LOGIN=off).

Diagnosed 2026-11-23: the SRM portal's WAF began answering our logins with
a rejection page ("The requested URL was rejected ... Your support ID is
..."), which the scraper correctly classified as a silent rejection and the
global breaker turned into a cooldown for EVERY account. SCOPE-only mode
stops all portal traffic while SCOPE keeps serving.

Two invariants, each of which fails silently if broken:
  1. No portal request happens — fetch_attendance returns before any portal
     work, and preflight does not reach http_scraper.preflight().
  2. A first-time account still gets a users row. Every SCOPE writer is
     UPDATE-only and write_user_sync is the sole INSERT, so without
     ensure_user_row the whole SCOPE payload lands on zero rows and the app
     looks healthy while storing nothing.

Offline: no network, no portal, own temp DB.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

_td = tempfile.TemporaryDirectory()          # test_audit_findings forbids in-tree DBs
os.environ["DATA_DIR"] = _td.name
os.environ["SCOPE_FEATURES"] = "off"         # no SCOPE network either

from app import app as A  # noqa: E402  (init_db lives here)
from app import db as D  # noqa: E402
from app import scraper as S  # noqa: E402


def _portal_touched():
    """True if the portal pipeline ran. Any portal attempt imports/uses
    http_scraper.fetch, so patch it to record and fail the test."""
    called = []
    from app import http_scraper as H
    orig = H.fetch

    def _boom(*a, **k):
        called.append(1)
        raise AssertionError("portal was called in SCOPE-only mode")

    H.fetch = _boom
    return called, lambda: setattr(H, "fetch", orig)


def test_knob_parsing():
    os.environ.pop("PORTAL_LOGIN", None)
    assert S.portal_login_enabled() is True, "unset must mean portal ON"
    for off in ("off", "OFF", "0", "false", "disabled", "no", " off "):
        os.environ["PORTAL_LOGIN"] = off
        assert S.portal_login_enabled() is False, off
    for on in ("on", "1", "true", "enabled", "", "yes"):
        os.environ["PORTAL_LOGIN"] = on
        assert S.portal_login_enabled() is True, repr(on)
    os.environ.pop("PORTAL_LOGIN", None)


def test_fetch_attendance_makes_no_portal_call():
    os.environ["PORTAL_LOGIN"] = "off"
    called, restore = _portal_touched()
    try:
        res = S.fetch_attendance("zz9999", "pw", authorized=True)
    finally:
        restore()
    os.environ.pop("PORTAL_LOGIN", None)
    assert called == [], "SCOPE-only must not reach the portal"
    assert res["ok"] is True, res
    assert res["portal_disabled"] is True, res
    # persist_sync reads res["fetched"] directly — it must exist.
    assert res["fetched"] == {}, res
    # Empty keys are what make _merge_fetch_result PRESERVE stored data.
    for key in ("data", "marks", "personal", "subjects"):
        assert not res.get(key), f"{key} must be empty so stored data is kept"


def test_ensure_user_row_creates_then_preserves():
    A.init_db()
    # row absent -> created; other columns at defaults
    assert D.user_password("ab1234") is None
    D.ensure_user_row("ab1234", "blob-1")
    assert D.user_password("ab1234")["password"] == "blob-1"

    # a second call rotates the password and must NOT wipe sync columns
    D.write_user_sync("ab1234", None, '{"pct": 90}', 123, '{"name": "x"}',
                      "[]", "[]", "[]", "{}", 0)
    D.ensure_user_row("ab1234", "blob-2")
    assert D.user_password("ab1234")["password"] == "blob-2"
    assert D.user_sync_state("ab1234")["attendance_json"] == '{"pct": 90}'
    assert D.user_sync_state("ab1234")["personal_details_json"] == '{"name": "x"}'


def test_scope_write_lands_on_a_created_row():
    """The bug this mode would have shipped: UPDATE-only SCOPE write on a
    row that does not exist is a silent no-op."""
    assert D.user_scope_data("cd5678") is None
    D.ensure_user_row("cd5678", "blob")
    D.write_scope_data("cd5678", '{"getSubjects": {"data": []}}', 999)
    row = D.user_scope_data("cd5678")
    assert row is not None, "SCOPE write vanished — ensure_user_row did not run"
    assert row["scope_fetched_at"] == 999


def test_scope_only_rejects_wrong_password():
    """SCOPE-mode login must verify the password itself. The SCOPE backend
    authenticates on NetID alone, and the portal (the only real check) is
    off, so without this every password works for every NetID."""
    A.init_db()
    from app.crypto import encrypt_pw
    D.ensure_user_row("ef9012", encrypt_pw("the-real-pw"))

    os.environ["PORTAL_LOGIN"] = "off"
    c = A.app.test_client()
    try:
        r = c.post("/api/login", json={"netid": "ef9012", "password": "wrong-pw"})
        assert r.status_code == 401, f"wrong password accepted: {r.status_code}"
        assert "invalid credentials" in r.get_json()["error"], r.get_json()

        r = c.post("/api/login", json={"netid": "ef9012", "password": "the-real-pw"})
        assert r.status_code == 200, f"correct password rejected: {r.status_code} {r.get_json()}"
    finally:
        os.environ.pop("PORTAL_LOGIN", None)


def test_scope_only_rejects_unknown_account():
    """An account with no stored credential cannot be verified without the
    portal, so it must be refused rather than handed a session."""
    from app.crypto import encrypt_pw  # noqa: F401  (documents the intent)
    A.init_db()
    os.environ["PORTAL_LOGIN"] = "off"
    c = A.app.test_client()
    try:
        r = c.post("/api/login", json={"netid": "zz0000", "password": "anything"})
        assert r.status_code == 401, f"unknown account got in: {r.status_code}"
        assert "paused" in r.get_json()["error"].lower(), r.get_json()
    finally:
        os.environ.pop("PORTAL_LOGIN", None)


if __name__ == "__main__":
    test_knob_parsing()
    test_fetch_attendance_makes_no_portal_call()
    test_ensure_user_row_creates_then_preserves()
    test_scope_write_lands_on_a_created_row()
    test_scope_only_rejects_wrong_password()
    test_scope_only_rejects_unknown_account()
    _td.cleanup()
    print("OK — SCOPE-only mode: knob, no portal traffic, row created, SCOPE writes land, "
          "wrong/unknown credentials refused")
