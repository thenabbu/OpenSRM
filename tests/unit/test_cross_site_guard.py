#!/usr/bin/env python3
"""The cross-site guard must refuse cross-site POSTs and ALLOW same-origin ones
even when the edge forwards a Host WITH a port.

Production incident (v2.9.0, 2026-11-02): every POST on the live site returned
403 "cross-site request refused (Origin)". The guard compared
`urlparse(Origin).netloc` against `request.host` with `!=`. Origin omits the
default port; the Cloudflare tunnel forwards Host as `srm.200871.xyz:443`, so
netlocs differed and every browser POST — /api/refresh, /api/track/tab, login —
was refused. Left unguarded, the lazy "fix" is to delete the Origin check
entirely, which would silently reopen CSRF. This suite pins both directions.
"""
import os
import sys
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import app.app as A  # noqa: E402

fails = []


def check(label, allowed, want):
    mark = "PASS" if allowed == want else "FAIL"
    if allowed != want:
        fails.append(label)
    print(f"  [{mark}] {label} -> allowed={allowed} (want {want})")


print("cross-site guard: origin/host comparison")

# ── must ALLOW (same origin; port may be forwarded, unforwarded, or default) ──
check("same origin, host carries :443 (the prod case)",
      A._origin_matches_host("https://srm.200871.xyz", "srm.200871.xyz:443"), True)
check("same origin, bare host (local dev)",
      A._origin_matches_host("https://srm.200871.xyz", "srm.200871.xyz"), True)
check("same origin, explicit default port on http",
      A._origin_matches_host("http://srm.200871.xyz", "srm.200871.xyz:80"), True)
check("same origin, host has port and origin states the same non-default port",
      A._origin_matches_host("https://srm.200871.xyz:8443", "srm.200871.xyz:8443"), True)
check("case-insensitive host",
      A._origin_matches_host("https://SRM.200871.xyz", "srm.200871.xyz:443"), True)

# ── must REFUSE (this is what the guard exists for; never trade it away) ─────
check("different site", A._origin_matches_host("https://evil.com", "srm.200871.xyz:443"), False)
check("same name, different port",
      A._origin_matches_host("https://srm.200871.xyz:8443", "srm.200871.xyz:443"), False)
check("suffix trick (our host as a subdomain of attacker)",
      A._origin_matches_host("https://srm.200871.xyz.evil.com", "srm.200871.xyz:443"), False)
check("prefix trick (attacker as a subdomain of us)",
      A._origin_matches_host("https://evil.srm.200871.xyz", "srm.200871.xyz:443"), False)
check("localhost vs public host",
      A._origin_matches_host("http://localhost:8083", "srm.200871.xyz:443"), False)
check("null origin (sandboxed iframe / opaque source)",
      A._origin_matches_host("null", "srm.200871.xyz:443"), False)
check("malformed origin", A._origin_matches_host("not a url", "srm.200871.xyz:443"), False)

# ── the guard end to end: Sec-Fetch-Site still leads ──────────────────���─────
with A.app.test_request_context("/api/refresh", method="POST",
                                headers={"Origin": "https://srm.200871.xyz",
                                         "Host": "srm.200871.xyz:443"}):
    check("guard allows the prod request shape", A._cross_site_guard() is None, True)

with A.app.test_request_context("/api/refresh", method="POST",
                                headers={"Origin": "https://evil.com",
                                         "Host": "srm.200871.xyz:443"}):
    check("guard refuses a foreign origin", A._cross_site_guard() is not None, True)

with A.app.test_request_context("/api/refresh", method="POST",
                                headers={"Sec-Fetch-Site": "cross-site",
                                         "Host": "srm.200871.xyz:443"}):
    check("guard refuses Sec-Fetch-Site: cross-site", A._cross_site_guard() is not None, True)

with A.app.test_request_context("/healthz", method="GET",
                                headers={"Origin": "https://evil.com"}):
    check("safe methods are never guarded", A._cross_site_guard() is None, True)


# ── the tunnel case: request.host is the ORIGIN IP, not the public name ──────
# Verified in a probe container against the real tunnel: the app receives
# host='172.31.0.1:8083', X-Forwarded-Host absent, edge secret unset — so no
# host-comparison alone can ever match a browser's Origin in prod.
print("\ncross-site guard: public-hostname allowlist (the tunnel case)")

import importlib  # noqa: E402

os.environ.pop("PUBLIC_HOSTNAMES", None)
importlib.reload(A)
check("allowlist unset -> public match never fires (stays strict)",
      A._origin_matches_public("https://srm.200871.xyz"), False)

os.environ["PUBLIC_HOSTNAMES"] = "srm.200871.xyz, alt.example.com"
importlib.reload(A)
check("allowlist: our public host matches",
      A._origin_matches_public("https://srm.200871.xyz"), True)
check("allowlist: second listed host matches",
      A._origin_matches_public("https://alt.example.com"), True)
check("allowlist: foreign host refused",
      A._origin_matches_public("https://evil.com"), False)
check("allowlist: suffix trick refused",
      A._origin_matches_public("https://srm.200871.xyz.evil.com"), False)

# end to end through the guard, with the host the tunnel actually delivers
with A.app.test_request_context("/api/refresh", method="POST",
                                headers={"Origin": "https://srm.200871.xyz",
                                         "Host": "172.31.0.1:8083"}):
    check("guard allows the REAL tunnel shape", A._cross_site_guard() is None, True)

with A.app.test_request_context("/api/refresh", method="POST",
                                headers={"Origin": "https://evil.com",
                                         "Host": "172.31.0.1:8083"}):
    check("guard still refuses a foreign origin via the tunnel shape",
          A._cross_site_guard() is not None, True)

os.environ.pop("PUBLIC_HOSTNAMES", None)
importlib.reload(A)


# ── the Worker's X-Forwarded-Host: honoured ONLY with the edge secret ────────
# The maintenance Worker retargets the request at the origin hostname, so the
# app must read the public host from X-Forwarded-Host. That header is
# client-assertable, so it is trusted only when _behind_cf() proves our edge
# set the secret. These three cases are the whole security argument.
print("\ncross-site guard: X-Forwarded-Host trust boundary")

_SECRET = "unit-test-edge-secret"
os.environ["CF_EDGE_SECRET"] = _SECRET
# CF_EDGE_SECRET is read at import into app/auth.py (app.py deliberately keeps no
# copy — a copy would shadow the facade proxy), so auth must be reloaded too.
import app.auth as _auth  # noqa: E402
importlib.reload(_auth)
importlib.reload(A)


def _guard(origin, host, xfh=None, secret=None):
    h = {"Origin": origin, "Host": host}
    if xfh:
        h["X-Forwarded-Host"] = xfh
    if secret:
        h["X-Edge-Secret"] = secret
    with A.app.test_request_context("/api/refresh", method="POST", headers=h):
        return A._cross_site_guard()


check("XFH honoured from our edge (real tunnel shape)",
      _guard("https://srm.200871.xyz", "172.31.0.1:8083", "srm.200871.xyz", _SECRET) is None, True)
check("spoofed XFH with NO secret is refused",
      _guard("https://evil.com", "172.31.0.1:8083", "srm.200871.xyz") is not None, True)
check("spoofed XFH with WRONG secret is refused",
      _guard("https://evil.com", "172.31.0.1:8083", "srm.200871.xyz", "wrong") is not None, True)
check("our edge but foreign Origin is still refused",
      _guard("https://evil.com", "172.31.0.1:8083", "srm.200871.xyz", _SECRET) is not None, True)

os.environ.pop("CF_EDGE_SECRET", None)
importlib.reload(_auth)
importlib.reload(A)


total = 29
print(f"\n{total - len(fails)}/{total} passed")
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("ok  cross-site guard suite")
