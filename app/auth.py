"""Session identity: who is calling, and the cookie flags that depend on it.

Extracted from app/app.py (facade pump, phase 1). Imports `.db` and `.crypto`
only — never app.app — so it is safe to import from any extracted module.
Every name is re-exported from app.app for existing callers.

get_current_user() is the most-reached-for helper in the app (18 top-level
blocks call it), which is exactly why it lives at the bottom of the import
graph instead of inside the 4.5k-line module.
"""
import hashlib
import os
import secrets
import time

from flask import request

from .db import create_session, delete_cookie, get_cookie

SESSION_MAX_AGE = 60 * 60 * 24 * 30          # 30 days

# audit: Only trust CF headers when request came through Cloudflare (cf-ray present)
# audit run-1 (#18): bare cf-ray presence is client-assertable — anyone
# reaching the origin directly could choose their rate-limit identity and
# forge the cookie Secure / HSTS decisions. Trust is now an edge-injected
# shared secret the client can never see (cloudflared
# originRequest.httpHeaders, or a Worker): X-Edge-Secret must match
# CF_EDGE_SECRET. Unset -> False: peer-only identity (request.remote_addr),
# which is the fail-closed position the audit prescribed. OPS DEP step: set
# CF_EDGE_SECRET in the lab .env AND inject the same value at the tunnel
# together, or per-IP limits collapse onto the tunnel's peer address.
CF_EDGE_SECRET = os.environ.get("CF_EDGE_SECRET", "").strip()


def _edge_secret():
    """Live value of CF_EDGE_SECRET.

    app.app re-exports this constant and tests/ops rebind it on the facade
    (`A.CF_EDGE_SECRET = "..."`). A re-export is a one-time copy, so read the
    facade's current attribute when it exists and fall back to this module's
    import-time value otherwise (e.g. the CLI, no facade loaded)."""
    import sys
    facade = sys.modules.get("app.app")
    if facade is not None and hasattr(facade, "CF_EDGE_SECRET"):
        return facade.CF_EDGE_SECRET
    return CF_EDGE_SECRET


def _behind_cf():
    secret = _edge_secret()
    return bool(secret) and request.headers.get("X-Edge-Secret") == secret


def _cookie_secure():
    return _behind_cf() and request.headers.get("X-Forwarded-Proto") == "https"


def get_current_user():
    token = request.cookies.get("srm_session")
    if not token: return None
    # v1.20.3 (migration 17): rows store sha256(token) — the browser keeps
    # the raw token, the DB never does, so a leaked srm.db cannot be replayed
    # as a live session. Every read/prune/delete path hashes to match.
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = get_cookie(digest)
    if row and time.time() - row["created"] > SESSION_MAX_AGE:
        # audit 2026-09-27: enforce expiry at READ time. Previously pruning
        # happened only inside make_session_token() (i.e. when that same user
        # logged in again), so a leaked srm_session cookie stayed valid
        # server-side indefinitely — the 30-day client cookie was the only cap.
        delete_cookie(digest)
        row = None
    return row["netid"] if row else None


def make_session_token(netid):
    token = secrets.token_hex(32)
    now = int(time.time())
    # incident 2026-10-10: this previously ran `DELETE FROM cookies WHERE
    # netid=?` — one session per account, globally. Every login on any device
    # silently evicted every other device's session: over Sep 22 - Oct 10 the
    # main account logged in 58 times from 13 IPs, and 41 of those 58 re-logins
    # were its OWN earlier login killing the current session (33 from a
    # different IP = cross-device). Sessions are now concurrent per account,
    # each still bounded by SESSION_MAX_AGE at read time.
    # v1.20.3: store sha256(token); the caller/browser keeps the raw token
    # (contract: make_session_token still returns it), so the value at rest
    # is useless to anyone holding the DB but not the cookie.
    create_session(hashlib.sha256(token.encode()).hexdigest(), netid, now,
                   now - SESSION_MAX_AGE)
    return token
