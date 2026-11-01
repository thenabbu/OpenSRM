"""The typed sync-failure result: one error shape for every pipeline.

Extracted from app/app.py (facade pump, phase 1). Pure data + a dict lookup —
imports nothing — so any module in the app (scraper, pipelines, routes) can
build a failure without importing the facade. That is what breaks the
`app.app -> extracted module -> app.app` cycle.

The typed `kind` is the replacement for the old status classifier, which
substring-matched the message text (wrong password vs captcha failure was
told apart by wording). Re-exported from app.app; tests pin every producer's
(kind -> status) mapping against the old classifier.
"""

# 401 auth · 429 rate/cooldown · 503 busy/portal/internal.
# Every status and user-visible string is byte-identical to the old mapping.
KIND_STATUS = {
    "bad_credentials": 401,
    "rate_limited": 429,
    "portal_cooldown": 429,
    "busy": 503,
    "portal_down": 503,
    "markup_changed": 503,
    "internal": 503,
}


def sync_error(kind, user_message, retry_after=None):
    """One failed sync result (the SyncError result type): typed kind, the
    byte-identical user-visible message, optional retry seconds — filled in
    only where the window is already computed (the portal cooldown),
    None otherwise. Routes rebuild the response as {ok, error}, so kind and
    retry_after never reach the client."""
    return {"ok": False, "error": user_message, "kind": kind, "retry_after": retry_after}


def sync_status(res):
    """HTTP status for a failed sync — from its kind, never from message
    text. A failure without a kind (a bare test stub) keeps the old
    fallback: 503."""
    return KIND_STATUS.get(res.get("kind"), 503)
