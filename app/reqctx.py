"""Request identity: which client is calling, and is it behind our edge.

Extracted from app/app.py (facade pump, phase 1). Depends on app.auth
(_behind_cf) and flask only — never app.app — so rate limiters, the portal
budget and extracted routes can identify a caller without the facade.
Re-exported from app.app.
"""
from flask import has_request_context, request

from .auth import _behind_cf


def _client_ip():
    # Only trust CF-Connecting-IP when request came through Cloudflare.
    # Direct access spoofing the header would bypass rate limiting otherwise.
    # audit run-1: background/test callers (no active request) must not crash —
    # no request means no asserted identity.
    if not has_request_context():
        return "?"
    if _behind_cf():
        return request.headers.get("CF-Connecting-IP") or request.remote_addr or "?"
    return request.remote_addr or "?"
