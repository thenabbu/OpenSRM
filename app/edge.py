"""Edge/proxy trust: what host did the browser actually address?

The site sits behind two hops that rewrite addressing: a maintenance Worker
that retargets every request at the origin hostname, and a Cloudflare tunnel
that dials the origin by IP. Neither preserves the public name in
`request.host`, so the cross-site guard needs help to know which site it is
serving — and both hops are things a client can lie about, which is why every
value here is gated on the edge secret rather than trusted.

Extracted from app/app.py (the facade should hold routes, not proxy policy).
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
    """Refuse requests addressed to the private origin hostname.

    `srm-origin.200871.xyz` exists only so the maintenance Worker can reach the
    tunnel (a zone route cannot fetch its own hostname). It is a public CNAME,
    so anyone who learns the name reaches the app directly — skipping the
    Worker, and therefore skipping the maintenance page during an outage.

    The legitimate caller is our own Worker, which is the only thing that can
    attach the edge secret. Everything else gets the same 404 a wrong Host
    deserves: no hint that this name is special.

    Inert until ORIGIN_HOSTNAMES is set, and inert entirely when CF_EDGE_SECRET
    is unset (nothing could prove the edge), so this cannot lock out a
    deployment that never configured it.
    """
    names = {h.strip().lower() for h in
             (os.environ.get("ORIGIN_HOSTNAMES") or "").split(",") if h.strip()}
    # Read the secret from app/auth.py, not from this module: CF_EDGE_SECRET is
    # deliberately NOT imported here (see the import block above), so a bare
    # name would be a NameError and a local copy would shadow the proxy.
    from . import auth as _auth
    if not names or not _auth.CF_EDGE_SECRET:
        return None
    host = (request.host or "").split(":")[0].lower()
    if host in names and not _behind_cf():
        return {"error": "not found"}, 404
    return None
