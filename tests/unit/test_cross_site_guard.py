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

total = 17
print(f"\n{total - len(fails)}/{total} passed")
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("ok  cross-site guard suite")
