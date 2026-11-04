#!/usr/bin/env python3
"""Every non-public route must refuse an unauthenticated request.

A route decorator is one line and one refactor away from being lost: this repo
already shipped v2.9.0 where every POST 403'd, and its sibling failure mode —
`@require_login` following the cut line instead of the function, leaving a route
serving anonymous users — is invisible to every behavioural suite because they
all log in first.

Method: mint an app, walk its real url_map, call every rule anonymously, and
assert each answers like a refusal (302 to /login, 401, 403, 405, or 400 for a
malformed body). Routes that are public by design are allowlisted WITH the
reason, so a new public route is a deliberate edit here rather than a silent
opening.

Run: DATA_DIR=$(mktemp -d) .venv/bin/python tests/unit/test_route_auth.py
"""
import os
import sys

os.environ.setdefault("DATA_DIR", "/tmp/osrm-route-auth")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.app as A  # noqa: E402

# Public by design. Key = the rule string as Flask stores it.
PUBLIC = {
    "/": "redirects to /login when anonymous; the login shell itself",
    "/login": "the login page",
    "/logout": "idempotent; clearing a cookie needs no session",
    "/healthz": "container healthcheck, must answer without a session",
    "/static/<path:filename>": "static assets are public by definition",
    "/avatar": "generated blobatar SVG, no user data",
    "/avatar/<name>": "generated blobatar SVG, no user data",
    "/api/login": "the login endpoint",
    "/api/login/preflight": "admission check, runs before any session",
    "/api/login/progress": "polled by the login page while unauthenticated",
    "/internal/metrics": "token-authenticated (X-Metrics-Token), not session",
    "/internal/push/tick": "secret-authenticated (X-Push-Tick), not session",
    # Deliberately anonymous, and it WRITES NOTHING without a session: the body
    # guards on `if netid:` and returns 204 always, so an anonymous beacon is a
    # no-op (pinned separately in test_product_analytics). Not a regression.
    "/api/track/tab": "204-always beacon; writes only when a session exists",
}

# Methods that cannot be exercised anonymously without a real body.
SKIP_METHODS = {"OPTIONS", "HEAD"}


def main():
    ok = fails = 0
    checks = []

    def chk(desc, cond, ev=""):
        nonlocal ok, fails
        if cond:
            ok += 1
        else:
            fails += 1
            checks.append((desc, ev))

    client = A.app.test_client()
    rules = sorted(A.app.url_map.iter_rules(), key=lambda r: str(r))

    for rule in rules:
        path = str(rule)
        if "<" in path:
            # Fill converters with a plausible value so the route can be reached.
            path = path.replace("<path:filename>", "x.css").replace("<name>", "x")
            path = path.replace("<int:", "<").replace("<", "").replace(">", "")
            if not path.startswith("/"):
                path = "/" + path

        if str(rule) in PUBLIC:
            continue

        for method in sorted(rule.methods - SKIP_METHODS):
            resp = client.open(path, method=method, json={})
            code = resp.status_code
            # A refusal is any of: redirect to login, unauthorised, forbidden,
            # method-not-allowed, or a validation rejection of the empty body.
            anonymous_refused = code in (302, 303, 307, 400, 401, 403, 405, 415, 422)
            redirected_to_login = (
                code in (302, 303, 307) and "/login" in (resp.headers.get("Location") or "")
            )
            chk(f"{method} {rule} refuses anonymous", anonymous_refused,
                f"got {code} (Location={resp.headers.get('Location')!r})")
            if code in (302, 303, 307):
                chk(f"{method} {rule} redirects to /login", redirected_to_login,
                    f"Location={resp.headers.get('Location')!r}")

    # The allowlist itself must not rot: every entry must still be a real rule.
    living = {str(r) for r in rules}
    for path, reason in PUBLIC.items():
        chk(f"PUBLIC entry is a real route: {path}", path in living,
            "not in url_map -- delete the entry or fix the typo")
        chk(f"PUBLIC entry states a reason: {path}", bool(reason.strip()))

    for desc, ev in checks[:25]:
        print(f"  FAIL {desc} -- {ev}")
    print(f"\nroute-auth: {ok + fails} checks, {ok} ok, {fails} failed")
    print("ok   route auth suite" if fails == 0 else "FAIL route auth suite")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
