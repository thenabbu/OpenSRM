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


def _prepare(page_body, captcha=None, calls=None, page=None, sentinel=None):
    """Run the real _prepare over a stubbed _req; return (result, calls).

    `page` raises instead of returning the page, so a 4xx on the PAGE GET can
    be exercised. When `sentinel` is given, assert the SAME opener object
    reaches the page GET, the captcha GET and the POST — one cookie jar is
    what keeps JSESSIONID/secureToken in one session."""
    calls = [] if calls is None else calls
    openers = []
    orig = H._req

    def fake(opener, url, _headers, data=None, timeout=25):
        calls.append(url)
        openers.append(opener)
        if "SCaptchaServlet" in url:
            if isinstance(captcha, Exception):
                raise captcha
            return url, (captcha if captcha is not None else b"\x89PNG\r\n\x1a\nfake")
        if isinstance(page, Exception):
            raise page
        return url, page_body

    H._req = fake
    try:
        res = H._prepare(sentinel, BASE, {})
        if sentinel is not None:
            assert openers and all(o is sentinel for o in openers), \
                f"page GET, captcha GET and POST must share one opener/jar: {openers}"
        return res, calls
    finally:
        H._req = orig


def _http_error(status, body=b"", headers=None):
    """A real urllib HTTPError, as the opener raises it — body readable once."""
    import email.message
    import io
    import urllib.error
    hdrs = email.message.Message()
    for k, v in (headers or {}).items():
        hdrs[k] = v
    err = urllib.error.HTTPError(f"{BASE}/x", status, "Forbidden", hdrs,
                                 io.BytesIO(body))
    return err


def _post(body, ctx_over=None, helpers=None, opener=None):
    """Run the real _post_login classifier over a canned response body."""
    seen = {}
    orig = H._req

    def fake(_opener, url, _headers, data=None, timeout=25):
        seen["url"] = url
        seen["opener"] = _opener
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
        return H._post_login(opener, ctx, "zzhard", "pw", BASE, {}, helpers, None, attempt=1), seen
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


# ── 7. captcha 4xx is terminal; only transport faults retry ─────────────────
def test_captcha_403_is_terminal():
    calls = []
    throttle = H.PortalHttpError(403, retry_after=60,
                                 body=b'{"error":"Too many requests. Please try again later."}')
    try:
        _prepare(_page(), captcha=throttle, calls=calls)
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


def test_captcha_4xx_is_classified_by_body_not_status():
    """B1 regression: the 403 body decides the kind, never a fabricated window.

    Measured shapes (w4-captcha-contract): an EMPTY body is the app rejecting
    a request with no session (our bug); a 54 B JSON body is the real IP
    throttle. Both are status 403 — only the body separates them."""
    throttle_body = b'{"error":"Too many requests. Please try again later."}'
    cases = [
        # (captcha error as _req raises it, expected kind, expected retry_after, why)
        (H.PortalHttpError(403, body=b""), "portal_blocked", None,
         "0 B = session rejected, not a throttle"),
        (H.PortalHttpError(403, retry_after=60, body=throttle_body), "portal_throttled", 60,
         "JSON body + header = the real throttle"),
        (H.PortalHttpError(403, body=throttle_body), "portal_throttled", None,
         "no Retry-After = None, never a fabricated 60"),
    ]
    for err, kind, retry_after, why in cases:
        calls = []
        try:
            _prepare(_page(), captcha=err, calls=calls)
            raise AssertionError(f"a captcha 4xx must abort the attempt ({why})")
        except H.PortalThrottled as e:
            assert kind == "portal_throttled", f"{why} — but got throttled: {e}"
            assert e.retry_after == retry_after, \
                f"{why}: retry_after must be {retry_after!r}, got {e.retry_after!r}"
        except H.PortalBlocked as e:
            assert kind == "portal_blocked", f"{why} — but got blocked: {e}"
            assert e.retry_after is None, f"{why}: a blocked response has no window, {e.retry_after!r}"
            assert e.arms_breaker is False
            low = str(e).lower()
            assert "throttl" not in low and "rate" not in low, \
                f"a session rejection must not be sold as a throttle: {e}"
            assert "session" in low and "cookie" in low, \
                f"the message must name the session/cookie cause: {e}"
        assert sum("SCaptchaServlet" in u for u in calls) == 1, f"no retry after a 4xx ({why})"
        assert not any("LoginServlet" in u for u in calls), f"no POST after a 4xx ({why})"


def test_captcha_403_body_is_carried_by_req():
    """The discriminator must survive _req: the body is read and carried."""
    class _Opener:
        def __init__(self, err):
            self.err = err

        def open(self, _req, timeout=None):
            raise self.err

    throttle = b'{"error":"Too many requests."}'
    for body in (b"", throttle):
        try:
            H._req(_Opener(_http_error(403, body)), f"{BASE}/x", {})
            raise AssertionError("a 403 must raise")
        except H.PortalHttpError as e:
            assert e.status == 403, e.status
            assert e.body == body, f"body discarded: {e.body!r} != {body!r}"


def test_http_error_body_read_failure_is_tolerated():
    """A body we cannot read must not crash the error path — it becomes empty."""
    class _Opener:
        def open(self, _req, timeout=None):
            e = _http_error(403, b"x")

            def _boom(n=-1):
                raise OSError("connection reset while reading the error body")

            e.read = _boom   # HTTPError.read is the tempfile's, so patch the instance
            raise e

    try:
        H._req(_Opener(), f"{BASE}/x", {})
        raise AssertionError("a 403 must raise")
    except H.PortalHttpError as e:
        assert e.status == 403 and e.body == b"", (e.status, e.body)


def test_page_get_4xx_does_not_arm_breaker():
    """B2: the case this PR exists for — a WAF answers the PAGE GET with 4xx.

    Never counted as a portal outage (that armed the 5-min cooldown for every
    account), and never sold as a throttle."""
    _reset()
    try:
        _prepare(_page(), page=H.PortalHttpError(403))
        raise AssertionError("a 4xx on the page GET must abort the attempt")
    except H.PortalHttpError as e:
        assert e.kind == "portal_blocked", e.kind
        assert e.arms_breaker is False
    res = _pipeline_raises(H.PortalHttpError(403))
    assert res["kind"] == "portal_blocked", res
    for wrong in ("throttl", "not responding", "rate-limiting"):
        assert wrong not in res["error"], f"a page-GET 403 must not read as {wrong!r}: {res}"
    assert A.portal_health.consecutive_fails == 0, \
        "a 4xx on the page GET must not count towards the GLOBAL cooldown"
    # a 5xx still IS an outage: the breaker must not be dead code
    assert H.PortalHttpError(503).arms_breaker is True


def test_one_opener_across_page_captcha_and_post():
    """The shared-cookie-jar contract: one opener, so one JSESSIONID/secureToken.

    page GET -> captcha GET -> POST must all see the SAME opener object; a
    second opener would carry a different cookie jar and a different session."""
    sentinel = object()
    page, calls = _prepare(_page(), sentinel=sentinel)   # asserts page+captcha share it
    assert page["secure"] == "sec-abc123", page
    assert any("youLogin.jsp" in u for u in calls), calls
    assert any("SCaptchaServlet" in u for u in calls), calls
    (_action, _err), seen = _post("ok", opener=sentinel,
                                  helpers={"portal_fail_once": lambda: None})
    assert seen["opener"] is sentinel, "the POST must reuse the login's opener/jar"


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
               test_captcha_4xx_is_classified_by_body_not_status,
               test_captcha_403_body_is_carried_by_req,
               test_http_error_body_read_failure_is_tolerated,
               test_page_get_4xx_does_not_arm_breaker,
               test_one_opener_across_page_captcha_and_post,
               test_throttled_and_markup_kinds_end_to_end,
               test_ip_budget_charge_rules,
               test_login_route_charges_only_reached_attempts):
        fn()
        print(f"  ok  {fn.__name__}")
    shutil.rmtree(TMP, ignore_errors=True)
    print("login hardening checks OK")
