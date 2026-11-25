"""One runnable check per login-client defect fixed on 2026-11-25.

Covers, offline (`_req` and the pipeline are stubbed — no portal, no NetID):

  1. a WAF/stub page on the login GET is typed `portal_blocked`, told to the
     user truthfully, and does NOT arm the GLOBAL cooldown;
  2. `secureToken` missing/empty is a `markup_changed` hard failure, never a
     POST with "" (which the portal answers "Invalid credentials");
  3. `cptoken`'s elapsed part is SECONDS from a monotonic clock, not an epoch;
  4. `timeOnPageMs` is the real dwell, not the old pinned 10000;
  5. the telemetry platform agrees with the Windows UA;
  6. the success marker is searched in the whole body, not the first 4000 B;
  7. a captcha GET 403 is TERMINAL (one GET, no POST, Retry-After honoured,
     distinct `portal_throttled` kind) and a JSON throttle body never reaches
     ddddocr;
  8. a login that never reaches the portal does not spend the 10/hour per-IP
     budget, while one that does still charges it.

Run: python tests/unit/test_login_hardening.py
"""
import base64
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

TMP = tempfile.mkdtemp(prefix="osrm-login-hardening-")
os.environ["DATA_DIR"] = TMP
os.environ["SYNC_QUEUE_WAIT_S"] = "0"   # a held slot refuses instantly, never waits

from app import app as A  # noqa: E402
from app import errors as E  # noqa: E402
from app import http_scraper as H  # noqa: E402
from app import routes_sync as R  # noqa: E402

A.solve_captcha_b64 = lambda _b64: "ab12"   # _prepare imports it from app.app

BASE = f"https://{H.PORTAL_HOST}"
PAGE_BYTES = 15000          # a healthy page is ~15.6 KB
WAF_STUB = (b'<html><head><title>Request Rejected</title></head><body>'
            b'The requested URL was rejected. Please consult with your administrator.'
            b' Your support ID is: 1234567890.</body></html>')


def _page(secure="sec-abc123", extra=""):
    """A healthy youLogin.jsp body: every token _prepare parses."""
    return ("<html><script>nonce : 'n0nce';</script>"
            "<script>domainFieldName = 'dtoken_1'; captchaFieldName = 'cptoken_1';"
            " randomDelimiter = '313c';</script>"
            '<input type="hidden" name="ph_09e48175" value="">'
            + (f'<input type="hidden" name="secureToken" value="{secure}">'
               if secure is not None else "")
            + '<img id="secure_captcha" data-src="/srmiststudentportal/SCaptchaServlet?ts=1">'
            + extra + "</html>").encode()


def _prepare(page_body, captcha=None, calls=None):
    """Run the real _prepare over a stubbed _req; return (result, calls)."""
    calls = [] if calls is None else calls
    orig = H._req

    def fake(_opener, url, _headers, data=None, timeout=25):
        calls.append(url)
        if "SCaptchaServlet" in url:
            if isinstance(captcha, Exception):
                raise captcha
            return url, (captcha if captcha is not None else b"\x89PNG\r\n\x1a\nfake")
        return url, page_body

    H._req = fake
    try:
        return H._prepare(None, BASE, {}), calls
    finally:
        H._req = orig


def _post(body, ctx_over=None, helpers=None):
    """Run the real _post_login classifier over a canned response body."""
    seen = {}
    orig = H._req

    def fake(_opener, url, _headers, data=None, timeout=25):
        seen["url"] = url
        seen["fields"] = urllib.parse.parse_qs(data.decode()) if data else {}
        return url, body.encode() if isinstance(body, str) else body

    H._req = fake
    ctx = {"t0": time.monotonic() - 22, "hp": "ph_x", "dfield": "dtoken_1",
           "cfield": "cptoken_1", "rdelim": "313c", "ocr": "ab12",
           "page_len": PAGE_BYTES, "secure": "sec"}
    ctx.update(ctx_over or {})
    if helpers is None:
        helpers = {"portal_fail_once": lambda: (_ for _ in ()).throw(
            AssertionError("this branch must not arm the global cooldown"))}
    try:
        return H._post_login(None, ctx, "zzhard", "pw", BASE, {}, helpers, None, attempt=1), seen
    finally:
        H._req = orig


def _reset():
    """Clear every gate that could refuse a sync before calling the pipeline."""
    A._portal_attempts.clear()
    A._portal_attempts_auth.clear()
    A._portal_attempts_pf.clear()
    A._portal_ip.clear()
    A._login_attempts.clear()
    A._ip_attempts.clear()
    A._portal_ok()
    os.environ["SYNC_QUEUE_WAIT_S"] = "0"


def _pipeline_raises(exc):
    """fetch_attendance with H.fetch raising `exc`; returns (res, fails_before)."""
    orig = H.fetch
    H.fetch = lambda *a, **k: (_ for _ in ()).throw(exc)
    A._portal_ok()
    try:
        return A.fetch_attendance("zzhard1", "pw")
    finally:
        H.fetch = orig


# ── 1. WAF stub: typed, honest, and it must not pause every account ─────────
def test_waf_stub_is_typed_blocked():
    try:
        _prepare(WAF_STUB)
        raise AssertionError("a WAF stub must not parse as a login page")
    except H.PortalBlocked as e:
        assert e.kind == "portal_blocked", e.kind
        assert e.arms_breaker is False, "a stub page must never arm the global cooldown"
        assert str(e).startswith("portal_blocked: "), str(e)
    # a short body with no honeypot is a stub even without the WAF's wording
    try:
        _prepare(b"<html>maintenance</html>")
        raise AssertionError("a 26 B body is not the login form")
    except H.PortalBlocked:
        pass
    # a 4.9 KB TSPD JS challenge has no form: it must not read as an outage
    challenge = (b"<html><script>window[\"bobcmn\"]=\"1011111/TSPD/\"</script>" + b" " * 4900 +
                 b"</html>")
    try:
        _prepare(challenge)
        raise AssertionError("a TSPD challenge must not parse as a login page")
    except H.PortalBlocked as e:
        assert e.arms_breaker is False, "a challenge page must never arm the global cooldown"
        assert "challenge" in str(e), str(e)
    # ... and a healthy page is NOT flagged
    ctx, _ = _prepare(_page())
    assert ctx["secure"] == "sec-abc123", ctx


def test_blocked_kind_is_503_and_message_is_honest():
    assert E.KIND_STATUS["portal_blocked"] == 503
    assert E.KIND_STATUS["portal_throttled"] == 503
    _reset()
    res = _pipeline_raises(H.PortalBlocked("portal_blocked: edge filter answered 245B"))
    assert res["kind"] == "portal_blocked", res
    assert "blocked" in res["error"], res
    for wrong in ("not responding", "rate-limiting"):
        assert wrong not in res["error"], f"blocked page must not be sold as {wrong!r}: {res}"
    assert A.portal_health.consecutive_fails == 0, \
        "one WAF stub must not count towards the GLOBAL cooldown"


# ── 2. secureToken is load-bearing: hard-fail, never POST "" ────────────────
def test_secure_token_is_required():
    for page in (_page(secure=None), _page(secure="")):
        try:
            _prepare(page)
            raise AssertionError("a page without secureToken must not reach the POST")
        except H.HttpScraperError as e:
            assert e.kind == "markup_changed", e.kind
            assert e.arms_breaker is False, "markup drift is not a portal outage"
            assert "secureToken" in str(e), str(e)


# ── 3. cptoken: seconds since load, not a 10-digit epoch ────────────────────
def test_cptoken_posts_seconds():
    (_action, err), seen = _post("<html>no marker</html>")
    raw = base64.b64decode(seen["fields"]["cptoken_1"][0]).decode()
    elapsed, count = raw.split("313c")
    assert int(count) == H._telemetry_interactions(), raw
    assert 20 <= int(elapsed) <= 24, f"elapsed must be ~22 s, got {elapsed!r} (epoch bug?)"
    assert err["kind"] == "portal_blocked", err


# ── 4 + 5. telemetry dwell is real, platform matches the UA ─────────────────
def test_telemetry_dwell_and_platform():
    p = json.loads(base64.b64decode(H._telemetry_b64(time.monotonic() - 30)))
    assert 29000 <= p["timeOnPageMs"] <= 31000, p["timeOnPageMs"]
    assert p["timeOnPageMs"] == p["submitTime"] - p["startTime"], p
    floor = json.loads(base64.b64decode(H._telemetry_b64(time.monotonic())))
    assert 1200 <= floor["timeOnPageMs"] <= 1200 + 100, floor["timeOnPageMs"]
    assert p["platform"].startswith("Win"), "platform must agree with the Windows UA"
    assert "Windows" in p["userAgent"], p["userAgent"]


# ── 6. success marker past the old 4000 B window ────────────────────────────
def test_success_marker_beyond_4000_bytes():
    (action, err), _ = _post("<html>" + "x" * 5000 + "HRDSystem.jsp</html>")
    assert (action, err) == ("ok", None), (action, err)


# ── 6b. silent rejection: honest kind, no global cooldown ───────────────────
def test_silent_rejection_does_not_arm():
    box = {"n": 0}
    (_action, err), _ = _post("<html>login page, no error text</html>",
                              helpers={"portal_fail_once": lambda: box.__setitem__("n", box["n"] + 1)})
    assert err["kind"] == "portal_blocked", err
    assert "rate-limiting" not in err["error"] and "not responding" not in err["error"], err
    assert box["n"] == 0, "a discarded login request must not arm the global cooldown"


# ── 7. captcha 403 is terminal; only transport faults retry ─────────────────
def test_captcha_403_is_terminal():
    calls = []
    try:
        _prepare(_page(), captcha=H.PortalHttpError(403, retry_after=60), calls=calls)
        raise AssertionError("a 403 from the captcha endpoint must abort the attempt")
    except H.PortalThrottled as e:
        assert e.kind == "portal_throttled", e.kind
        assert e.retry_after == 60, "Retry-After must be carried through"
        assert e.arms_breaker is False
    assert sum("SCaptchaServlet" in u for u in calls) == 1, \
        f"a 4xx must not be retried (saw {calls})"
    assert not any("LoginServlet" in u for u in calls), "no POST may be built after a 403"


def test_captcha_retry_only_for_transport():
    calls = []
    try:
        _prepare(_page(), captcha=H.HttpScraperError("transport: reset"), calls=calls)
        raise AssertionError("transport errors must still give up after the retry")
    except H.HttpScraperError as e:
        assert e.kind == "portal_down", e.kind
    assert sum("SCaptchaServlet" in u for u in calls) == 2, "transport keeps ONE retry"


def test_captcha_json_body_is_throttle_not_captcha():
    try:
        _prepare(_page(), captcha=b'{"error":"Too many requests. Try later."}')
        raise AssertionError("a JSON throttle body must not reach ddddocr")
    except H.PortalThrottled as e:
        assert e.kind == "portal_throttled", e.kind


def test_throttled_and_markup_kinds_end_to_end():
    _reset()
    res = _pipeline_raises(H.PortalThrottled("captcha endpoint answered 403", retry_after=90))
    assert res["kind"] == "portal_throttled", res
    assert res.get("retry_after") == 90, res
    for wrong in ("invalid credentials", "not responding", "rate-limiting"):
        assert wrong not in res["error"], f"throttle must not read as {wrong!r}: {res}"
    assert A.portal_health.consecutive_fails == 0, "a 403 is not an outage"
    _reset()
    res = _pipeline_raises(H.HttpScraperError("login form missing secureToken",
                                             kind="markup_changed", arms_breaker=False))
    assert res["kind"] == "markup_changed", res
    assert A.portal_health.consecutive_fails == 0


# ── 8. per-IP budget: only attempts that reach the portal spend it ──────────
def test_ip_budget_charge_rules():
    assert R._ip_attempt_counts({"ok": False, "kind": "busy"}) is False
    assert R._ip_attempt_counts({"ok": False, "kind": "portal_cooldown"}) is False
    assert R._ip_attempt_counts({"ok": False, "kind": "rate_limited"}) is False
    assert R._ip_attempt_counts({"ok": False, "kind": "portal_off"}) is False
    assert R._ip_attempt_counts({"ok": False, "kind": "bad_credentials"}) is True
    assert R._ip_attempt_counts({"ok": False, "kind": "portal_throttled"}) is True
    assert R._ip_attempt_counts({"ok": True}) is True

    ip = "203.0.113.9"
    A._ip_attempts.pop(ip, None)
    for _ in range(15):   # consecutive pre-flight rejections never charge
        assert A._admit_ip(ip) is True
    assert not A._ip_attempts.get(ip), "check-only admission must not spend a token"
    for _ in range(10):
        A._charge_ip(ip)
    assert A._admit_ip(ip) is False, "10 real attempts must exhaust the hour"
    assert A._check_ip_rate("198.51.100.7") is not None   # compat API still charges
    A._ip_attempts.clear()


def test_login_route_charges_only_reached_attempts():
    _reset()
    ip = "127.0.0.1"
    A._ip_attempts.pop(ip, None)
    client = A.app.test_client()
    orig = R.fetch_attendance
    try:
        R.fetch_attendance = lambda *a, **k: A.sync_error(
            "busy", "Sync in progress. Try again in about a minute.")
        r = client.post("/api/login", json={"netid": "zzhard2", "password": "pw"})
        assert r.status_code == 503, r.status_code
        assert not A._ip_attempts.get(ip), "a pre-flight rejection must be free"

        R.fetch_attendance = lambda *a, **k: A.sync_error(
            "bad_credentials", "invalid credentials — check your NetID/password")
        r = client.post("/api/login", json={"netid": "zzhard2", "password": "pw"})
        assert r.status_code == 401, r.status_code
        assert len(A._ip_attempts.get(ip, [])) == 1, "a real attempt must charge"
    finally:
        R.fetch_attendance = orig
        A._ip_attempts.pop(ip, None)


if __name__ == "__main__":
    for fn in (test_waf_stub_is_typed_blocked,
               test_blocked_kind_is_503_and_message_is_honest,
               test_secure_token_is_required,
               test_cptoken_posts_seconds,
               test_telemetry_dwell_and_platform,
               test_success_marker_beyond_4000_bytes,
               test_silent_rejection_does_not_arm,
               test_captcha_403_is_terminal,
               test_captcha_retry_only_for_transport,
               test_captcha_json_body_is_throttle_not_captcha,
               test_throttled_and_markup_kinds_end_to_end,
               test_ip_budget_charge_rules,
               test_login_route_charges_only_reached_attempts):
        fn()
        print(f"  ok  {fn.__name__}")
    shutil.rmtree(TMP, ignore_errors=True)
    print("login hardening checks OK")
