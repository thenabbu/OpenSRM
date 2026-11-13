"""Edge/proxy trust: what host did the browser actually address?

The site sits behind two hops that rewrite addressing: a maintenance Worker
that retargets every request at the origin hostname, and a Cloudflare tunnel
that dials the origin by IP. Neither preserves the public name in
`request.host`, so the cross-site guard needs help to know which site it is
serving — and both hops are things a client can lie about, which is why every
value here is gated on the edge secret rather than trusted.

Extracted from app/app.py (the facade should hold routes, not proxy policy).
The cross-site request guard and the security response headers live here too:
both are request-trust policy on the response/before-request path, and both
hinge on `_behind_cf()` (HSTS only behind the verified edge).
"""
import os
from urllib.parse import urlparse

from flask import request

from .auth import _behind_cf


def _origin_matches_host(origin, host):
    """Is `Origin` the same site as the Host we were addressed as?

    Compare HOSTNAMES, not netlocs. `Origin` never carries a port for the
    default scheme (https -> 443 implied), while `request.host` is whatever the
    proxy forwarded and DOES carry one (`srm.200871.xyz:443`). A netloc-to-
    netloc `!=` therefore refuses a legitimate same-origin POST — that is the
    "cross-site request refused (Origin)" the tunnel started producing once the
    edge began forwarding Host with the port.

    Port is compared only when the origin actually states one and it is not the
    scheme default, so `:8443` against a bare host still fails closed.
    """
    o = urlparse(origin)
    if not o.hostname:
        return False
    try:
        host_name = urlparse("//" + host).hostname
    except ValueError:
        return False
    if (o.hostname or "").lower() != (host_name or "").lower():
        return False
    default = {"http": 80, "https": 443}.get((o.scheme or "").lower())
    if o.port and default and o.port != default:
        try:
            if o.port != (urlparse("//" + host).port or default):
                return False
        except ValueError:
            return False
    return True


def _public_host():
    """The host the BROWSER addressed, which is not `request.host`.

    Behind the maintenance Worker + Cloudflare tunnel, `request.host` is the
    origin address the edge dialled (`172.31.0.1:8083`, or `srm-origin.…` when
    the Worker rewrites it), never the public name in the URL bar.

    `X-Forwarded-Host` carries the public name, but it is client-assertable
    unless we know our own edge set it — so it is honoured ONLY when
    _behind_cf() proves the edge-injected secret matched. Without that proof we
    fall back to request.host, i.e. fail closed.
    """
    if _behind_cf():
        fwd = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
        if fwd:
            return fwd
    return request.host


def _origin_matches_public(origin):
    """Is `Origin` one of the hostnames this deployment is served under?

    Needed because the Cloudflare tunnel dials the origin by IP: the app sees
    `request.host == 172.31.0.1:8083` (verified in a probe container — Host was
    the internal address, X-Forwarded-Host absent, edge secret unset), so
    comparing Origin against request.host can NEVER succeed for a real browser.
    The ingress address is not the site.

    PUBLIC_HOSTNAMES (comma-separated env) is the deliberate allowlist that
    restores the check's intent: a same-site POST carries OUR hostname, a
    cross-site one carries somebody else's. Unset -> empty set -> this method
    never allows anything, so the guard stays exactly as strict as before until
    an operator names the deployment's public host.
    """
    allowed = {h.strip().lower() for h in
               (os.environ.get("PUBLIC_HOSTNAMES") or "").split(",") if h.strip()}
    if not allowed:
        return False
    return (urlparse(origin).hostname or "").lower() in allowed


def _origin_host_guard():
    """Refuse a DIRECT hit on the private origin hostname.

    `srm-origin.200871.xyz` exists so the maintenance Worker can reach the
    tunnel (a zone route cannot fetch its own hostname). It is a public CNAME
    with no route in front of it, so anyone who learns the name reaches the app
    directly — skipping the Worker, and therefore skipping the maintenance page
    during an outage.

    Host alone cannot make this call: the Worker rewrites EVERY public request
    to this hostname, so both a legitimate visitor and a bypasser arrive as
    `srm-origin`. (That is exactly what took the site down when this guard first
    shipped keyed on host — it 404'd the real site.) (docs: #135)

    The discriminator is X-Forwarded-Host, which only our Worker sets: the
    Worker always attaches it, a direct request never has it. Together with the
    tunnel's own X-Edge-Secret that is a positive signal the request came
    through the edge.

    Inert until ORIGIN_HOSTNAMES is set, and inert when CF_EDGE_SECRET is unset,
    so a deployment that never configures this cannot be locked out.
    """
    names = {h.strip().lower() for h in
             (os.environ.get("ORIGIN_HOSTNAMES") or "").split(",") if h.strip()}
    from . import auth as _auth
    if not names or not _auth.CF_EDGE_SECRET:
        return None
    host = (request.host or "").split(":")[0].lower()
    if host not in names:
        return None
    if _behind_cf() and (request.headers.get("X-Forwarded-Host") or "").strip():
        return None  # came through our Worker
    return {"error": "not found"}, 404


# ── Cross-site request guard ───────────────────────────────────────────────
# v1.20.3: state-changing methods arriving from another site are refused
# (403 + error= on the opensrm.http line) instead of trusting SameSite=Lax
# alone. Sec-Fetch-Site is a forbidden header — a cross-site page can neither
# strip nor forge it — so it leads; Origin covers older browsers. Neither
# header present = non-browser client (curl, cron, tests) -> allowed.
# /internal/push/tick authenticates with its own secret header -> exempt.
_CROSS_SITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
# session-authenticated POSTs served through the tunnel (see above);
# the push tick is secret-header auth, same exemption for the same reason.
_CROSS_SITE_EXEMPT = ("/internal/push/tick", "/marks/tag")


def _cross_site_guard():
    if request.method not in _CROSS_SITE_METHODS:
        return None
    # exempt: POSTs that authenticate with the session cookie and are served
    # through the Cloudflare tunnel — the tunnel rewrites the browser's
    # same-origin fetch metadata (Sec-Fetch-Site/Origin no longer match the
    # origin host once cloudflared fronts the POST), so a same-site user form
    # would false-403 behind the tunnel while passing locally.
    if request.path in _CROSS_SITE_EXEMPT:
        return None
    sfs = request.headers.get("Sec-Fetch-Site")
    if sfs is not None and sfs.lower() not in ("same-origin", "none"):
        return {"error": "cross-site request refused (Sec-Fetch-Site)"}, 403
    origin = request.headers.get("Origin")
    if origin is not None and not (
            _origin_matches_host(origin, _public_host())
            or _origin_matches_public(origin)):
        return {"error": "cross-site request refused (Origin)"}, 403
    return None


# ── Response headers ───────────────────────────────────────────────────────
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; worker-src 'self'; manifest-src 'self'")
    resp.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    # audit: HSTS only when the request came through the VERIFIED CF edge
    # (audit run-1 #18: bare cf-ray is client-assertable) — plain-HTTP local
    # dev and direct-origin requests must never receive it
    if _behind_cf():
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp
