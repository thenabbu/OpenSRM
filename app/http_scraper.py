"""Pure-HTTP SRM portal scraper (no Playwright/Chromium).

Replaces the browser pipeline with 3-request login + parallel JSP fetches.
Proven in egress/test-login-ab.py (Sep 24 2026): direct + CF-worker egress
both reach HRDSystem.

Route: direct by default; set SRM_EGRESS_URL (+ SRM_PROXY_TOKEN) to egress
via the CF Worker byte-pipe (IP diversity vs portal rate-limits).

Login mechanism (from deobfuscated guardlogin.js, committed egress/):
  - captcha = page's OWN data-src image, fetched with X-Domain-Proof:
    btoa(nonce + ":" + hostname) — nonce from SECURE_CONFIG
  - SECURE_CONFIG.captchaText is a DECOY (anti-phishing branch only)
  - dtoken = btoa(reversed hostname); cptoken = btoa(elapsed + delim + interactions)
  - fresh SCaptchaServlet URLs desync the session — never fetch a new one

Deferred imports from .app avoid circularity (app imports this module the
same way inside fetch_attendance).
"""
import base64
import gzip
import http.cookiejar
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from . import captcha_dataset, metrics

log = logging.getLogger("opensrm.portal")

PORTAL_HOST = "sp.srmist.edu.in"
BASE_PATH = "/srmiststudentportal"
LOGIN_PAGE = f"https://{PORTAL_HOST}{BASE_PATH}/students/loginManager/youLogin.jsp"
LOGIN_POST = f"https://{PORTAL_HOST}{BASE_PATH}/LoginServlet"
HRD_URL = f"https://{PORTAL_HOST}{BASE_PATH}/students/template/HRDSystem.jsp"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")

# JSPs scraped after login: formId -> path
JSPS = {
    "1": "/students/transaction/ScribeInner.jsp",
    "9": "/students/report/studentAttendanceDetails.jsp",
    "13": "/students/report/studentInternalMarkDetails.jsp",
    "17": "/students/report/studentPersonalDetails.jsp",
    "7": "/students/report/studentSubjectLists.jsp",
    "32": "/students/courseReg/studentFeedback.jsp",
    "126": "/students/transaction/StudentExamTimeTable.jsp",  # official Exam Time Table (verified live Oct 7 2026)
    "10": "/students/report/studentTimeTableDetails.jsp",  # daily Timetable menu (verified live Oct 12 2026; was a server-side "No Time Table Found" gap before)
}
HOT_FORMIDS = {"9", "13", "10"}  # attendance + marks + daily timetable: every sync
# (no "126": the official exam timetable is fetched PER exam window by
# _official_exam_post — a bare iden=126 POST returns no room allotment and
# only added one wasted portal request per sync/relogin)
# (no "1"/"32": ScribeInner was demoted to the exam probe, and _fb_harvest
# posts iden=32 itself — nothing reads those batch results; both rode along
# on every cold sync for nothing)
COLD_FORMIDS = {"17", "7"}  # personal/courses: re-fetch only when stale > COLD_TTL
COLD_TTL = 24 * 3600  # seconds

MAX_CAPTCHA_RETRIES = 3


class HttpScraperError(Exception):
    """Unexpected transport/code failure — caller falls back to Playwright.

    ``kind`` is the typed sync-failure vocabulary from app/errors.py that the
    caller maps to a status + user message; ``arms_breaker`` says whether this
    failure may count towards the GLOBAL portal cooldown. A definite answer
    from the portal (a 403, a changed login form) is not an outage, so it must
    not pause every account (prod 2026-11-23: a WAF stub on the login page
    armed the 5-min cooldown for all users)."""

    kind = "portal_down"
    arms_breaker = True

    def __init__(self, msg="", *, kind=None, arms_breaker=None, retry_after=None):
        super().__init__(msg)
        if kind is not None:
            self.kind = kind
        if arms_breaker is not None:
            self.arms_breaker = arms_breaker
        self.retry_after = retry_after


class PortalBlocked(HttpScraperError):
    """The portal (or the WAF in front of it) answered with a stub page, not
    the login form. Retrying is pointless within this attempt and it is NOT an
    outage of the portal."""
    kind = "portal_blocked"
    arms_breaker = False


class PortalThrottled(HttpScraperError):
    """The portal is deliberately refusing us (captcha GET 403/429). Distinct
    from bad credentials and from a dead portal; carries Retry-After."""
    kind = "portal_throttled"
    arms_breaker = False


class PortalHttpError(HttpScraperError):
    """The portal answered with an HTTP error status (not a transport fail).

    Keeps the status, Retry-After and the (bounded) response BODY: two very
    different 403s look identical by status alone — `Content-Length: 0` is the
    app rejecting a request with no session, a tiny JSON body is the real IP
    throttle — so callers must classify by shape, not by status."""

    def __init__(self, status, retry_after=None, body=b""):
        super().__init__(f"HTTP {status} from portal",
                         kind="portal_blocked" if 400 <= status < 500 else "portal_down",
                         arms_breaker=status >= 500, retry_after=retry_after)
        self.status = status
        self.body = body


class FeedbackWindowClosed(HttpScraperError):
    """The portal's MidSemFeedback.jsp answers with its service-shut info
    alert — the feedback window itself is closed, not a session or markup
    failure. Observed live wordings: `Service closed` (2026-10-13) and
    `Service period deactivated` (2026-10-20). Raised by _fb_frag_state's
    classification: callers map it to fb_open=0 (archive the CTA) while
    every other harvest failure leaves stored fb_open untouched
    (unknown != closed)."""


def _route():
    """(base_url, extra_headers) — worker egress if configured, else direct."""
    url = os.environ.get("SRM_EGRESS_URL", "").rstrip("/")
    tok = os.environ.get("SRM_PROXY_TOKEN", "")
    if url and tok:
        log.debug("portal route=worker base=%s", url)
        return url, {"x-proxy-token": tok}
    log.debug("portal route=direct")
    return f"https://{PORTAL_HOST}", {}


def _make_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def _hdrs(extra=None, referer=None):
    h = {"User-Agent": UA,
         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
         "Accept-Language": "en-US,en;q=0.9"}
    if referer:
        h["Referer"] = referer
    if extra:
        h.update(extra)
    return h


# audit run-1 (#10): every portal read funnels through _req — bound BOTH
# dimensions here so a bad body fails fast instead of growing RSS while the
# scrape lock is held (32MB/28s drip reproduced under the old unbounded read).
_MAX_BODY = 8 * 1024 * 1024   # portal pages are KB-scale; raise if a real one exceeds
_MAX_READ_SECS = 60           # total wall clock per response — drip-proof on top of timeout=25
_MAX_ERR_BODY = 8 * 1024      # only need enough of a 4xx body to tell JSON from nothing
# urllib sends `Accept-Encoding: identity` by itself, so the portal answers
# uncompressed. The CF egress hop (SRM_EGRESS_URL) can re-compress what it
# proxies, and measured 2026-11-25 a healthy 15,597 B page arrived as 3,522 B
# of gzip: /\x1f\x8b/ magic bytes and no honeypot input, which the parser read
# as a changed login form. Decode on the magic bytes, never on the header.


def _req(opener, url, headers, data=None, timeout=25, hdrs_out=None):
    """GET/POST; returns (final_url, body_bytes). Raises HttpScraperError on transport fail.

    When `hdrs_out` (a dict) is passed it is filled with the RESPONSE headers.
    Only the login GET and the login POST ask for them, because the edge filter
    is identified there by headers, not by body wording.
    """
    t0 = time.monotonic()
    try:
        r = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        for k, v in headers.items():
            r.add_header(k, v)
        resp = opener.open(r, timeout=timeout)
    except urllib.error.HTTPError as e:
        log.warning("portal http_error url=%s status=%s", url[:80], e.code)
        try:
            retry_after = int(str(e.headers.get("Retry-After", "")).strip() or 0) or None
        except (TypeError, ValueError):
            retry_after = None
        # Carry the body: a 403 with no body (app rejects a session-less
        # request) and a 403 with a 54 B JSON throttle are the SAME status.
        # Bounded so a hostile error body cannot grow RSS; unreadable -> b"".
        try:
            body = e.read(_MAX_ERR_BODY) or b""
        except Exception as re_:
            log.debug("portal http_error body unreadable status=%s err=%r", e.code, re_)
            body = b""
        raise PortalHttpError(e.code, retry_after=retry_after, body=body) from e
    except Exception as e:
        log.warning("portal transport_error url=%s err=%r", url[:80], e)
        raise HttpScraperError(f"transport: {e!r}") from e
    clen = resp.headers.get("Content-Length")
    if clen:
        try:
            if int(clen) > _MAX_BODY:
                raise HttpScraperError(f"portal declared oversized body: {clen}B")
        except ValueError:
            pass  # junk header — the read loop still enforces the cap
    deadline = t0 + _MAX_READ_SECS
    parts, got = [], 0
    try:
        while True:
            if time.monotonic() > deadline:
                raise HttpScraperError("portal read deadline exceeded")
            chunk = resp.read(65536)
            if not chunk:
                break
            got += len(chunk)
            if got > _MAX_BODY:
                raise HttpScraperError(f"portal body over size cap ({got}B)")
            parts.append(chunk)
    except HttpScraperError:
        raise
    except Exception as e:
        log.warning("portal transport_error url=%s err=%r", url[:80], e)
        raise HttpScraperError(f"transport: {e!r}") from e
    body = b"".join(parts)
    if hdrs_out is not None:
        hdrs_out.update(resp.headers.items())
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except Exception as e:  # noqa: BLE001 — corrupt stream is a transport fault
            raise HttpScraperError(f"gzip body undecodable: {e!r}") from e
        log.info("portal gunzipped url=%s -> %dB", url[:60], len(body))
    log.debug("portal %s %s -> %s %dB %dms", "POST" if data else "GET",
              url.replace("https://", "")[:60], resp.status, len(body),
              int((time.monotonic() - t0) * 1000))
    return resp.url, body


# Interaction counters. MEASURED 2026-11-25 against the live portal with
# fabricated NetIDs only (portal-p4/REGRESSION.md): these EXACT magnitudes are
# load-bearing. Arms E3/E5/E7 sent 4 clicks / 7 moves / 22 keys / 6108 ms and
# the portal JUDGED the submit (16,455 B + "You have 2 out of 3 login attempts
# remaining"). Arm E4 sent a self-consistent Windows blob with 1/2/5/180/4200
# and was NOT judged (16,324 B, no counter). Do not "tidy" these numbers and do
# not re-derive them: the portal accepts this wire shape and rejects the rest.
_TEL_CLICKS = 4
_TEL_MOVES = 7
_TEL_KEYS = 22
_TEL_TYPING_MS = 6108
_TEL_CANVAS = "563dae46"


def _cptoken_elapsed(t0_monotonic, wall_now, mono_now):
    """The `elapsed` part of `cptoken`, in the shape the portal JUDGES.

    DO NOT "fix" the clock mismatch below. It looks like a bug — `t0` is
    `time.monotonic()` and `wall_now` is `time.time()`, so the subtraction is
    ~1.8e9 and the value posted is a full epoch second, not seconds-on-page.
    It is a bug, and it is LOAD-BEARING: the portal discards every submit that
    carries a plausible small on-page value and judges the epoch one.

    Measured 2026-11-26 with fabricated NetIDs, scores of ~40 interleaved POSTs
    on one IP: the deployed 2.12.4 image posted `17955791525de526` and was
    judged (16,455 B + `N out of 3 login attempts remaining`); the same body
    with `65de526` (elapsed=6) was silently discarded 14/14 (15,597 B, the
    untouched login page, no alert). Equalising the interaction total alone is
    NOT enough. Treat this as a fixed wire constant, not a timer.

    Common mistake: "the portal's JS posts seconds since load". It may, but
    that is not the value it accepts from us. Callers must pass the clocks in
    so a test can pin both without patching time.
    """
    return str(max(5, int(wall_now - t0_monotonic)))


def _telemetry_interactions():
    # Must equal the total the telemetry blob claims. Using mousemove here
    # reads as a runtime interaction count, but the portal JUDGES the blob on
    # the 6b53326 shape (clicks+keystrokes) and DISCARDS every submit that
    # carries the mousemove total. See _cptoken_fragment.
    return _TEL_CLICKS + _TEL_KEYS


def _telemetry_b64(t0):
    """Browser-shaped telemetry, mirroring what a real login sends.

    Shape captured from a genuine browser submit that SUCCEEDED (2026-11-19):
      currentDomain "sp.srmist.edu.in", platform "Linux x86_64",
      timezoneOffset 0, 1366x900, hardwareConcurrency 2, deviceMemory 8,
      mouseClicks 4, mouseMovements 7, keystrokeCount 22, typingSpeedMs 6108,
      canvasHash 563dae46, timeOnPageMs == submitTime - startTime.

    MEASURED 2026-11-25: this blob is load-bearing. An EMPTY `telemetryPayload`
    makes the portal discard the submit without evaluating the password — the
    page looks like a credential rejection (16,324 B, `Invalid credentials`) but
    carries no `N out of 3 login attempts remaining` counter. This exact blob
    (arm E5) gets the submit judged (16,455 B, counter present) even with the
    newer `cptoken`; inventing a different self-consistent blob (arm E4) does
    NOT. `secureToken` also matters; the interaction counters above are the part
    these constants carry. Keep this wire shape unchanged.
    """
    now_ms = int(time.time() * 1000)
    on_page = min(10000, max(1200, int((time.time() - t0) * 1000)))
    return base64.b64encode(json.dumps({
        "startTime": now_ms - on_page, "currentDomain": PORTAL_HOST,
        "timezoneOffset": 0, "screenWidth": 1366, "screenHeight": 900,
        "colorDepth": 24, "devicePixelRatio": 1, "platform": "Linux x86_64",
        "userAgent": UA, "language": "en-US", "hardwareConcurrency": 2,
        "deviceMemory": 8, "touchSupport": False, "webdriver": False,
        "mouseClicks": _TEL_CLICKS, "mouseMovements": _TEL_MOVES,
        "keystrokeCount": _TEL_KEYS, "typingSpeedMs": _TEL_TYPING_MS,
        "canvasHash": _TEL_CANVAS,
        "submitTime": now_ms, "timeOnPageMs": on_page,
    }).encode()).decode()


# ── Login preflight: page fetch + captcha OCR done while the user is
#    still typing their password, so submit skips straight to the POST.
#    keyed by netid; consumed by fetch() on the next login for that netid.
_PREFLIGHT = {}   # netid -> {"opener", "jar", "ctx", "ts"}
_PREFLIGHT_MAX = 32


def _captcha_url(img_path, base):
    """Resolve the page's data-src captcha image (audit run-1 #9).

    The portal controls data-src, so it decides what the server fetches.
    Root-relative is built from the configured host; an absolute URL is only
    accepted when it names the portal host (or the configured egress base).
    file://, internal hosts, anything else -> HttpScraperError BEFORE any
    request is issued (the old code fetched it verbatim: SSRF to any scheme
    urllib would follow)."""
    if img_path.startswith("/"):
        img_url = f"https://{PORTAL_HOST}{img_path}"
    elif img_path.startswith(f"https://{PORTAL_HOST}/") or img_path.startswith(f"{base}/"):
        img_url = img_path
    else:
        raise HttpScraperError("captcha data-src not on the portal host")
    if base != f"https://{PORTAL_HOST}":
        img_url = img_url.replace(f"https://{PORTAL_HOST}", base)
    return img_url


def preflight(netid):
    """Warm the login: GET youLogin.jsp + solve captcha, store for submit."""
    base, xheaders = _route()
    opener, jar = _make_opener()
    ctx = _prepare(opener, base, xheaders)
    if not ctx["ocr"]:
        log.warning("preflight empty ocr netid=%s — not stored", netid)
        metrics.inc("opensrm_preflight_total", outcome="wasted")  # OCR produced nothing usable
        return
    now = time.time()
    if len(_PREFLIGHT) >= _PREFLIGHT_MAX:  # opportunistic prune of stale entries
        for k in [k for k, v in _PREFLIGHT.items() if now - v["ts"] > 180]:
            _PREFLIGHT.pop(k, None)
    _PREFLIGHT[netid] = {"opener": opener, "jar": jar, "ctx": ctx, "ts": now}
    metrics.inc("opensrm_preflight_total", outcome="ready")
    log.info("preflight ready netid=%s ocr=%s age=0ms", netid, ctx["ocr"])


def take_preflight(netid, max_age=150):
    """Pop the warm login for this netid (single-use). None when stale/absent."""
    p = _PREFLIGHT.pop(netid, None)
    if not p:
        return None
    if time.time() - p["ts"] > max_age:
        metrics.inc("opensrm_preflight_total", outcome="wasted")  # stored but never consumed
        return None
    metrics.inc("opensrm_preflight_total", outcome="consumed")
    log.debug("preflight consumed netid=%s age_ms=%d", netid, int((time.time() - p["ts"]) * 1000))
    return p


def _blocked_page(body, html, headers=None):
    """Reason string when the response is NOT the login form.

    The F5 BIG-IP ASM in front of the portal intermittently answers the login
    page with a 245 B "Request Rejected" stub (also a ~5.5 KB variant, and a
    JS challenge). That has no `ph_` input, so the old code raised
    'honeypot field missing' and the caller told the user the portal was down
    while arming the GLOBAL cooldown. Detect it here and say what happened.

    Headers decide it, wording only backs them up: measured 2026-11-25 over 37
    paced GETs, all 8 block pages carried `X-Frame-Options: SAMEORIGIN` and NO
    `Server:` header, all 29 healthy pages carried `DENY` +
    `Server: Apache/2.4.58 (Ubuntu)`. A new stub wording therefore still gets
    named as a filter answer instead of as a changed login form.
    """
    low = html.lower()
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    if h.get("x-frame-options", "").upper() == "SAMEORIGIN" and "server" not in h:
        return (f"edge filter answered {len(body)}B with X-Frame-Options SAMEORIGIN "
                f"and no Server header")
    if ("request rejected" in low or "support id" in low
            or "the requested url was rejected" in low):
        return f"edge filter answered {len(body)}B instead of the login form"
    if "bobcmn" in low:
        # F5 TSPD JS challenge (4,943 B): no form, so the honeypot parse would
        # call it a portal outage and arm the global cooldown.
        return f"edge served a JS challenge ({len(body)}B) instead of the login form"
    if len(body) < 1200 and 'name="ph_' not in low:
        return f"login form absent ({len(body)}B response)"
    return ""


def _captcha_refusal(e):
    """(kind, message) for a captcha-endpoint 4xx — classified by BODY SHAPE.

    Measured on the real endpoint: `403 + Content-Length: 0` is the app
    rejecting a request that carried no session (our cookie jar — our bug),
    while the genuine per-IP throttle answers a ~54 B JSON body and usually
    Retry-After. The status is identical, so the body is the only signal. An
    ambiguous body reports BLOCKED: a false "the portal is throttling you" is
    the costlier lie, because it invents a penalty window never sent."""
    raw = (e.body or b"").decode("utf-8", errors="replace").strip()
    throttle = "too many requests" in raw.lower()
    if not throttle and raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        throttle = isinstance(parsed, dict) and "error" in parsed
    if throttle:
        return PortalThrottled, f"captcha endpoint is throttling this server ({e.status})"
    if not raw:
        return PortalBlocked, (f"portal refused the captcha request without a session "
                               f"({e.status}) — cookie jar or token missing")
    return PortalBlocked, (f"portal refused the captcha request ({e.status}, "
                           f"{len(raw)}B unexpected body) — cookie jar or token missing")


def _prepare(opener, base, xheaders, on_step=None, attempt=1):
    """Fetch login page + parse tokens + fetch captcha + OCR.
    Returns ctx dict for _post_login. Raises HttpScraperError."""
    from app.app import solve_captcha_b64  # deferred: same ddddocr solver

    t0 = time.monotonic()
    page_url = f"{base}{BASE_PATH}/students/loginManager/youLogin.jsp"
    hdrs = {}
    _url, body = _req(opener, page_url, _hdrs(xheaders), hdrs_out=hdrs)
    html = body.decode("utf-8", errors="replace")
    log.debug("login attempt=%d step=get_page bytes=%d", attempt, len(html))
    if on_step: on_step("Opening login page…", 15)
    blocked = _blocked_page(body, html, hdrs)
    if blocked:
        log.warning("login attempt=%d blocked_page %s", attempt, blocked)
        raise PortalBlocked(f"portal_blocked: {blocked}")

    def g(p, _html=html):
        m = re.search(p, _html)
        return m.group(1) if m else None

    nonce = g(r"nonce\s*:\s*'([^']+)'")
    dfield = g(r"domainFieldName\s*[=:]\s*['\"]([^'\"]+)['\"]")
    cfield = g(r"captchaFieldName\s*[=:]\s*['\"]([^'\"]+)['\"]")
    rdelim = g(r"randomDelimiter\s*[=:]\s*['\"]([^'\"]+)['\"]")
    hp = re.search(r'name="(ph_[^"]+)"', html)
    if not hp:
        # Reached only for a page that is neither a WAF stub nor a challenge
        # (both caught above): the form itself changed. Never a portal outage,
        # or one reworded form pauses every account.
        raise HttpScraperError("honeypot field missing",
                               kind="markup_changed", arms_breaker=False)
    img = re.search(r'<img[^>]*id="secure_captcha"[^>]*>', html)
    src = re.search(r'data-src="([^"]+)"', img.group(0)) if img else None
    # secureToken: a hidden input the page ships on load, bound to this
    # request's fpNonce + the captcha's own ts. Nothing client-side computes
    # it, so the only correct move is to forward it verbatim. It is LOAD-
    # BEARING: a POST without it answers "Invalid credentials" (2026-11-19
    # bisect), which the classifier would report as a wrong password. Missing
    # here therefore means the form changed — fail loudly, do not POST "".
    sec = re.search(r'<input[^>]*name="secureToken"[^>]*value="([^"]*)"', html) \
        or re.search(r'<input[^>]*value="([^"]*)"[^>]*name="secureToken"', html)
    if not sec or not sec.group(1):
        raise HttpScraperError("login form missing secureToken",
                               kind="markup_changed", arms_breaker=False)
    if not all([nonce, dfield, cfield, rdelim, src]):
        log.warning("login page missing tokens nonce=%s dfield=%s cfield=%s",
                    bool(nonce), bool(dfield), bool(cfield))
        raise HttpScraperError("login page tokens missing",
                               kind="markup_changed", arms_breaker=False)

    # Captcha: the page's OWN image (data-src) with Domain-Proof
    img_path = src.group(1)
    img_url = _captcha_url(img_path, base)
    proof = base64.b64encode(f"{nonce}:{PORTAL_HOST}".encode()).decode()
    img_headers = _hdrs({**xheaders, "X-Domain-Proof": proof,
                         "Accept": "image/png, image/jpeg, image/svg+xml, image/*"},
                        referer=LOGIN_PAGE)
    img_bytes = b""
    for _img_try in range(2):  # worker egress can be slow on cold start
        try:
            _u, img_bytes = _req(opener, img_url, img_headers, timeout=40)
            if not img_bytes:
                # prod 2026-09-30 07:43: SCaptchaServlet answered 200 with 0B,
                # which used to reach ddddocr as "cannot identify image file"
                # and crash the whole http pipeline into the Playwright fallback.
                raise HttpScraperError("captcha image empty (200, 0 bytes)")
            if img_bytes.lstrip()[:1] == b"{":
                # The captcha servlet's own throttle answers a tiny JSON body.
                # Handing that to ddddocr reads as "bad captcha" and spends one
                # of the portal's 3 login attempts for nothing.
                raise PortalThrottled("captcha endpoint returned JSON, not an image")
            break
        except PortalHttpError as e:
            if 400 <= e.status < 500:
                # TERMINAL for this login: retrying the image or POSTing anyway
                # deepens a real throttle, and every user shares this egress IP.
                # The KIND comes from the body (see _captcha_refusal), and the
                # retry window ONLY from the header — never fabricated.
                kind, msg = _captcha_refusal(e)
                log.warning("captcha fetch refused status=%s kind=%s body=%dB retry_after=%s",
                            e.status, kind.kind, len(e.body), e.retry_after)
                if kind is PortalThrottled:
                    raise PortalThrottled(msg, retry_after=e.retry_after) from e
                raise PortalBlocked(msg) from e
            log.warning("captcha fetch try=%d failed (%r)", _img_try + 1, e)
            if _img_try == 1:
                raise
        except PortalThrottled:
            raise
        except HttpScraperError as e:  # transport / empty body only
            log.warning("captcha fetch try=%d failed (%r)", _img_try + 1, e)
            if _img_try == 1:
                raise
    try:
        ocr = solve_captcha_b64(base64.b64encode(img_bytes).decode())
    except Exception as e:  # ddddocr raises ImageProcessError on a non-image body
        raise HttpScraperError(f"captcha OCR rejected the image: {e}") from e
    if on_step: on_step("Reading captcha…", 30)
    log.debug("login attempt=%d step=captcha bytes=%d ocr=%s", attempt,
              len(img_bytes), ocr)
    # Dataset: stage the pair, never act on it here. Overwrites any earlier
    # attempt in this scope; _post_login decides whether it was CORRECT.
    captcha_dataset.offer(img_bytes, ocr)
    return {"t0": t0, "hp": hp.group(1), "dfield": dfield, "cfield": cfield,
            "rdelim": rdelim, "ocr": ocr, "page_len": len(html),
            "secure": sec.group(1) if sec else "",
            # kept so a PREFLIGHT ctx (solved outside the login scope) can be
            # restaged by _login if the portal rejects it. ~1.2 KB, 150s TTL.
            "img_bytes": img_bytes}


def _portal_alert(rhtml):
    """The portal's own rejection message, rendered as
    `<h6 class="alert-heading">Alert</h6> … </div>` in the response.
    Logged for diagnosis ONLY — clients get fixed generic strings
    (Login Flow UX Guide §5: portal text is never relayed, and no
    account-existence wording may leak)."""
    m = re.search(r'alert-heading">Alert</h6>(.*?)</div>', rhtml, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()


def _post_login(opener, ctx, netid, password, base, xheaders, helpers, on_step=None, attempt=1):
    """POST LoginServlet with a prepared ctx. Returns (action, err):
    action: "ok" | "retry" (fresh captcha needed) | "fail" (fatal — err is a
    sync_error() result: typed kind + byte-identical message)."""
    from app.app import sync_error  # deferred: app.app imports this module lazily
    # POST login
    dtoken = base64.b64encode(PORTAL_HOST[::-1].encode()).decode()
    elapsed = _cptoken_elapsed(ctx["t0"], time.time(), time.monotonic())
    # cptoken's third part must be the same interaction total the telemetry
    # claims. Sending a hardcoded 3 against fabricated counters is a mismatch
    # the portal reads.
    cptoken = base64.b64encode(
        f"{elapsed}{ctx['rdelim']}{_telemetry_interactions()}".encode()).decode()
    fields = {ctx["hp"]: "", "username": netid, "password": password,
              "captcha": ctx["ocr"],
              # fpPayload/fpToken are filled in at runtime by the portal's own
              # fingerprint JS; nothing on the page carries a value to scrape,
              # so they stay empty (browser-filled, unmodelled).
              "fpPayload": "", "fpToken": "",
              # Server-minted on page load and bound to this attempt's fpNonce
              # and the captcha ts; a real browser posts it and we did not.
              "secureToken": ctx.get("secure", ""),
              # The interaction counters this field carries are load-bearing:
              # an EMPTY value makes the portal discard the submit before it
              # checks the password (16,324 B page that looks like a credential
              # rejection but has no attempts-remaining counter), and a
              # different self-consistent blob is rejected too. See
              # _telemetry_b64 and portal-p4/REGRESSION.md arms E1/E4/E5.
              "telemetryPayload": _telemetry_b64(ctx["t0"]),
              ctx["dfield"]: dtoken, ctx["cfield"]: cptoken}
    post_url = f"{base}{BASE_PATH}/LoginServlet"
    data = urllib.parse.urlencode(fields).encode()
    headers = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded",
                     "Origin": f"https://{PORTAL_HOST}"}, referer=LOGIN_PAGE)
    hdrs = {}
    final_url, body = _req(opener, post_url, headers, data=data, hdrs_out=hdrs)
    rhtml = body.decode("utf-8", errors="replace")
    # Whole body: a JS-redirect success can put the marker past 4000 B, and
    # reading that as a silent rejection used to arm the global cooldown.
    ok = "HRDSystem" in final_url or "HRDSystem" in rhtml
    if on_step: on_step("Verifying credentials…", 55)
    log.debug("login attempt=%d step=post final=%s hrdsystem=%s bytes=%d",
              attempt, final_url.split("/")[-1][:40], ok, len(rhtml))
    if ok:
        # The captcha was accepted (the POST succeeded) — this is the pair the
        # solver got RIGHT. Scoped: nothing is staged outside a scrape scope.
        captcha_dataset.commit()
        return "ok", None
    # The same edge filter can answer the SUBMIT. Named AFTER the portal's own
    # alert phrases: a real rejection page is the re-rendered login form and can
    # be short, while a filter stub carries neither phrase — checking here keeps
    # a genuine "invalid credentials" a credentials verdict and still stops a
    # stub from reading as a silent rejection (or, before this branch, an outage).
    low = rhtml.lower()
    alert = _portal_alert(rhtml)
    # Classify on the portal's OWN alert text, captured live 2026-09-30:
    #   bad password -> "Invalid login credentials The user ID or password …
    #                   You have N out of 3 login attempts remaining."
    #   bad captcha  -> "Invalid captcha."
    # Both come back inside the same re-rendered login page, whose markup
    # already contains 'captcha' (x17) and 'invalid' (Bootstrap
    # .invalid-feedback) — so the old loose "captcha AND invalid" match fired
    # on EVERY rejection, reported a wrong password as "captcha unreadable"
    # and retried it 3x, burning the portal's own 3-attempts-per-NetID
    # lockout. Exact alert phrases only; anything else is a silent rejection.
    if ("invalid login credentials" in low or "invalid credentials" in low
            or "invalid username" in low or "invalid password" in low):
        log.warning("login attempt=%d reject=credentials portal_alert=%r", attempt, alert)
        return "fail", sync_error("bad_credentials", "invalid credentials — check your NetID/password")
    if "invalid captcha" in low:
        log.info("login attempt=%d invalid_captcha ocr=%s portal_alert=%r",
                 attempt, ctx["ocr"], alert)
        # The portal judged this read WRONG — that is a real negative sample.
        captcha_dataset.reject()
        if attempt < MAX_CAPTCHA_RETRIES:
            return "retry", None
        return "fail", sync_error("bad_credentials", "login failed after 3 attempts — captcha unreadable")
    # An edge-filter stub instead of the login page: name it, so a filter answer
    # is never logged (or sold) as a discarded payload or an outage. Checked
    # after the portal's own alert phrases, because a real rejection page is the
    # re-rendered form and can be short, while a stub carries neither phrase.
    blocked = _blocked_page(body, rhtml, hdrs)
    if blocked:
        log.warning("login attempt=%d post blocked_page %s", attempt, blocked)
        return "fail", sync_error("portal_blocked",
                                  "SRM portal did not accept the login request — try again "
                                  "in a few minutes.")
    # Silent rejection: login page again, no error text. Record whether the
    # body is the UNTOUCHED login page (same byte length as the page this ctx
    # was prepared from): that means LoginServlet discarded the request as a
    # bot instead of evaluating the credentials, which is a payload problem,
    # not the portal rate-limiting us. It is NOT a portal outage either, so it
    # must not touch the GLOBAL cooldown (one bad body must not pause everyone).
    same_page = bool(ctx.get("page_len")) and len(rhtml) == ctx["page_len"]
    log.warning("login attempt=%d silent_rejection (no HRDSystem, no error text) "
                "portal_alert=%r bytes=%d untouched_login_page=%s",
                attempt, alert, len(rhtml), same_page)
    return "fail", sync_error("portal_blocked",
                              "SRM portal did not accept the login request — try again "
                              "in a few minutes.")


def _login_done(ok, err, attempts):
    """Record captcha attempts-per-login for the HTTP pipeline, return the
    (ok, err) passthrough. One attempt == one prepared submit (OCR+POST)."""
    metrics.observe("opensrm_captcha_attempts_per_login", attempts, pipeline="http")
    return ok, err


def _login(opener, netid, password, base, xheaders, helpers, on_step=None, prepared=None):
    """Pure-HTTP login. Returns (ok, fail) — fail is a sync_error() result or
    None. Raises HttpScraperError on transport fail."""
    from app.app import sync_error  # deferred: app.app imports this module lazily
    extra = 1 if prepared else 0   # a pre-solved captcha counts as one attempt
    # CAPTCHA dataset scope for THIS login. Must open here, not in _prepare:
    # _prepare is shared with preflight() (a captcha solved while the visitor is
    # still typing, which must NOT be stored), and a scope opened per-attempt
    # inside the loop would drop each attempt's staging before _post_login could
    # judge it. Only the login path reaches _post_login, so scoping here is what
    # makes "staged pair -> portal verdict" reliable.
    captcha_dataset.begin()
    # Preflight path: warm session + solved captcha from the typing phase.
    if prepared:
        try:
            if on_step: on_step("Using pre-solved captcha…", 40)
            # That image was solved outside this scope — restage it so a
            # rejection of it is still recorded (its bytes are in the ctx).
            if prepared["ctx"].get("img_bytes"):
                captcha_dataset.offer(prepared["ctx"]["img_bytes"],
                                      prepared["ctx"].get("ocr"))
            action, err = _post_login(prepared["opener"], prepared["ctx"], netid,
                                      password, base, xheaders, helpers, on_step, attempt=1)
            if action == "ok":
                return _login_done(True, None, 1)
            if action == "fail":
                return _login_done(False, err, 1)
            log.info("preflight captcha rejected netid=%s — fetching fresh captcha", netid)
        except HttpScraperError as e:
            log.warning("preflight post failed (%r) — fresh login", e)

    for attempt in range(1, MAX_CAPTCHA_RETRIES + 1):
        ctx = _prepare(opener, base, xheaders, on_step, attempt)
        if not ctx["ocr"]:
            log.warning("login attempt=%d ocr_empty", attempt)
            if attempt < MAX_CAPTCHA_RETRIES:
                time.sleep(2)
                continue
            return _login_done(False, sync_error("internal", "captcha OCR failed — try again"), extra + attempt)
        action, err = _post_login(opener, ctx, netid, password, base, xheaders,
                                  helpers, on_step, attempt)
        if action == "ok":
            return _login_done(True, None, extra + attempt)
        if action == "retry":
            time.sleep(2)
            continue
        return _login_done(False, err, extra + attempt)
    return _login_done(False, sync_error("bad_credentials", "login failed — captcha retries exhausted"), extra + MAX_CAPTCHA_RETRIES)


def _jsp_post(opener, base, xheaders, path, form_id):
    """POST one report JSP. Returns (form_id, html)."""
    url = f"{base}{BASE_PATH}{path}"
    data = urllib.parse.urlencode({"iden": form_id, "filter": "",
                                   "hdnFormDetails": "1", "csrfPreventionSalt": ""}).encode()
    headers = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded",
                     "X-Requested-With": "XMLHttpRequest"}, referer=HRD_URL)
    try:
        _u, body = _req(opener, url, headers, data=data)
        return form_id, body.decode("utf-8", errors="replace")
    except HttpScraperError:
        return form_id, ""


# End-sem schedule probe: ScribeInner.jsp (iden=1) accepts ANY hdnExamMonth/
# hdnExamYear — the portal never validates against the official dropdown, so
# un-released end-sem dates leak for sessions that AREN'T offered in the UI
# (verified live Sep 27 2026: 11_2026 returned 4 subjects; the two official
# options returned 'No subject found'). Candidates = exam windows that are
# imminent or in progress.
EXAM_PROBE_MONTHS = (4, 5, 6, 11, 12)  # even-sem Apr-Jun, odd-sem Nov-Dec


def exam_candidates(now=None):
    """(month, year) windows worth probing: end within past 45d, start within next 210d.
    ponytail: 45d/210d bounds are a heuristic — widen if SRM seeds sessions >7 months out."""
    now = now or datetime.now()
    out = []
    for y in (now.year - 1, now.year, now.year + 1):
        for m in EXAM_PROBE_MONTHS:
            start = datetime(y, m, 1)
            end = datetime(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
            if end >= now - timedelta(days=45) and start <= now + timedelta(days=210):
                out.append((m, y))
    return out


def _exam_post(opener, base, xheaders, month, year):
    """POST ScribeInner.jsp for one exam window. Returns ((month, year), html) or None."""
    url = f"{base}{BASE_PATH}/students/certificateRequest/ScribeInner.jsp"
    data = urllib.parse.urlencode({"iden": "1", "hdnExamMonth": month,
                                   "hdnExamYear": year}).encode()
    headers = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded",
                     "X-Requested-With": "XMLHttpRequest"}, referer=HRD_URL)
    try:
        _u, body = _req(opener, url, headers, data=data)
        return (month, year), body.decode("utf-8", errors="replace")
    except HttpScraperError:
        return None


def _official_exam_post(opener, base, xheaders, month, year):
    """POST StudentExamTimeTable.jsp (iden=126) for one exam window.
    Returns ((month, year), html) or None. The official timetable needs the
    month/year pair; without it the portal returns no hall/seat allotment.
    """
    url = f"{base}{BASE_PATH}/students/transaction/StudentExamTimeTable.jsp"
    data = urllib.parse.urlencode({"iden": "126", "hdnExamMonth": month,
                                   "hdnExamYear": year}).encode()
    headers = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded",
                     "X-Requested-With": "XMLHttpRequest"}, referer=HRD_URL)
    try:
        _u, body = _req(opener, url, headers, data=data)
        return (month, year), body.decode("utf-8", errors="replace")
    except HttpScraperError:
        return None


def _merge_official_rows(results):
    """Parse iden=126 bodies from several exam windows into one de-duplicated row list."""
    from app.app import parse_exam_timetable  # deferred: avoid circularity
    rows, seen = [], set()
    for res in results:
        if not res:
            continue
        for r in parse_exam_timetable(res[1]) or []:
            key = (r["code"], r["date"])
            if key not in seen:
                seen.add(key)
                rows.append(r)
    return rows


def _official_exam_rows(opener, base, xheaders, exam_results):
    """Official iden=126 rows for the windows the scribe probe actually listed.

    The official page only carries the term that is published, so there is no
    point POSTing every candidate window twice (scribe + official). Fetch it
    only for windows that returned scribe rows — normally one term.
    """
    from app.app import parse_exam_schedule  # deferred: avoid circularity
    wanted = []
    for entry in exam_results or []:
        if not entry:
            continue
        for r in parse_exam_schedule(entry[1]):
            key = (int(r["date"][3:5]), int(r["date"][6:]))
            if key not in wanted:
                wanted.append(key)
    if not wanted:
        return []
    with ThreadPoolExecutor(max_workers=min(4, len(wanted))) as ex:
        futs = [ex.submit(_official_exam_post, opener, base, xheaders, m, y)
                for m, y in wanted]
        return _merge_official_rows([f.result() for f in futs])


# fallback question ids when the live form fragment carries no
# hiddenQuestionId field (see _fb_question_ids)
DEFAULT_FB_QIDS = ",".join(str(x) for x in range(23, 37)) + ","


def _fb_post(opener, base, xheaders, query):
    """GET MidSemFeedbackInner.jsp with the form's own query contract.
    Returns (final_url, text); raises HttpScraperError on transport fail."""
    url = f"{base}{BASE_PATH}/students/Feedback/MidSemFeedbackInner.jsp?{query}"
    headers = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "X-Requested-With": "XMLHttpRequest"}, referer=HRD_URL)
    _u, body = _req(opener, url, headers)
    return _u, body.decode("utf-8", errors="replace")


def _fb_common(frag):
    """Hidden-field values from the MidSemFeedback fragment (attribute order
    varies — value-before-id on most tags, so extract independently)."""
    def _val(_id):
        m = re.search(r'<input[^>]*id="%s"[^>]*>' % _id, frag, re.I)
        if m:
            vm = re.search(r'value="([^"]*)"', m.group(0))
            if vm:
                return vm.group(1)
        return ""
    return {
        "programme": _val("hdntxtProgramme"),
        "section": _val("hdntxtSection"),
        "classstrenth": _val("hdnStudentCount"),
        "studenId": _val("hdnStudentId"),
        "academicyearid": _val("hdnAcademicYearId"),
        "courseid": _val("hdnCourseId"),
        "hdnPgsecid": _val("hdnPgsecid"),
        "semesterId": _val("hdntxtSem") or _val("txtSem"),
        "totalFeedBack": _val("hdnTotalFeedBack"),
        "feedbacktypeId": _val("hdnFeedbackTypeId") or "2",
        "previousSemester": _val("previousSemester") or _val("txtSem"),
        "subjectTypeId": "1",
    }


def _fb_subjects(frag):
    """[(subject_id, name)] from the form's txtCourseTitle select."""
    m = re.search(r'<select[^>]*id="txtCourseTitle".*?</select>', frag, re.S | re.I)
    return re.findall(r'<option[^>]*value="(\d+)"[^>]*>\s*([^<]+?)\s*</option>', m.group(0)) if m else []


def _fb_staff_options(frag):
    """[(staff_id, 'Name-Kind')] from the response's txtCourseStaff select."""
    m = re.search(r'<select[^>]*id="txtCourseStaff".*?</select>', frag, re.S | re.I)
    return re.findall(r'<option[^>]*value="(\d+)"[^>]*>\s*([^<]+?)\s*</option>', m.group(0)) if m else []


def _fb_question_ids(frag):
    """Comma-joined question ids the LIVE form expects (hiddenQuestionId field),
    or None when the fragment doesn't render them. The submit used to post a
    hardcoded 23..36 set with zero validation — a portal question change would
    record ratings against wrong/nonexistent questions while still 'succeeding'.
    (value may precede the name/id attribute, same trap as _fb_common.)"""
    m = re.search(r'<input[^>]*(?:name|id)="hiddenQuestionId"[^>]*>', frag, re.I)
    if not m:
        return None
    vm = re.search(r'value="([^"]*)"', m.group(0))
    val = vm.group(1).strip() if vm else ""
    return val or None


def _fb_registered(frag):
    """True when the response says this subject is already registered — the
    ONLY trustworthy done-signal ('SAVED SUCCESSFULLY' never re-renders).
    Attr order varies (value-before-id on the saved response), so extract
    the tag first, then the value."""
    if "ALREADY REGISTERED" in frag.upper():
        return True
    m = re.search(r'<input[^>]*id="hdnRegisterFeedBack"[^>]*>', frag, re.I)
    if m:
        vm = re.search(r'value="([^"]*)"', m.group(0))
        if vm:
            return vm.group(1) == "1"
    return False


# The portal's shut-the-window alert, observed live: `Service closed`
# (2026-10-13 capture) and `Service period deactivated` (2026-10-20 capture).
# Matched case-insensitively; a drifted wording still archives through the
# zero-subjects fallback in _fb_frag_state, so a text change can never
# re-show a dead CTA.
_FB_CLOSED_MARKERS = ("service closed", "service period deactivated")


def _fb_frag_state(frag):
    """Classify a MidSemFeedback iden=32 fragment: "dead" (login bounce),
    "closed" (the portal shut the window), "broken" (unexpected fragment), or
    "open" (subject list present). ONE classifier shared by the cold harvest,
    the hot-sync probe and fill_feedback's refusal check, so every path reads
    the same live fragment the same way."""
    if "youLogin" in frag:
        return "dead"
    if any(m in frag.lower() for m in _FB_CLOSED_MARKERS):
        return "closed"
    if "txtCourseTitle" not in frag:
        return "broken"
    if not _fb_subjects(frag):
        # Shell renders but no subject rows. Observed live 2026-10-20 (with
        # the "Service period deactivated" alert); also what ANY drifted
        # shut-wording looks like. Treat as closed — a genuine subject-list
        # markup change leaves the fill equally unusable, so archived is the
        # honest state either way, and the next open window harvests fresh
        # and unarchives automatically.
        return "closed"
    return "open"


def _fb_harvest(opener, base, xheaders, netid):
    """Read-only harvest of the subject->staff map. Returns
    {name: {"subject_id", "staff": [[id, name], ...]}} — no submissions.

    Sync only ever runs this; submitting is opt-in via fill_feedback() (the
    student must preview + confirm). per-GET pacing 0.7s keeps portal load
    at human scale.
    """
    t0 = time.monotonic()

    # 1. main fragment (POST iden=32, the funSetFormId contract)
    url = f"{base}{BASE_PATH}/students/Feedback/MidSemFeedback.jsp"
    data = urllib.parse.urlencode({"iden": "32", "filter": "", "hdnFormDetails": "1",
                                   "csrfPreventionSalt": ""}).encode()
    headers = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "X-Requested-With": "XMLHttpRequest"}, referer=HRD_URL)
    _u, body = _req(opener, url, headers, data=data)
    frag = body.decode("utf-8", errors="replace")
    state = _fb_frag_state(frag)
    if state == "dead":
        raise HttpScraperError("feedback form did not load (session dead)")
    if state == "closed":
        # the portal's own availability marker — see _FB_CLOSED_MARKERS for
        # the observed live wordings; the zero-subjects shell is in here too.
        raise FeedbackWindowClosed("feedback window closed on the portal")
    if state == "broken":
        raise HttpScraperError("feedback form did not load (unexpected fragment)")

    subjects = _fb_subjects(frag)

    # 2. per subject: staff list (read-only)
    faculty_map = {}
    for sid, name in subjects:
        name = name.strip()
        q = "&" + urllib.parse.urlencode(dict(subjectId=sid, forWhat="1", functionId="1",
                                              staffid="0", **_fb_common(frag)))
        _u, inner = _fb_post(opener, base, xheaders, q)
        staff = _fb_staff_options(inner)
        if not staff:
            log.warning("feedback probe netid=%s subject=%s staff=EMPTY (marking unknown)", netid, name[:40])
            faculty_map[name] = {"subject_id": sid, "staff": [["0", "Unknown"]]}
        else:
            faculty_map[name] = {"subject_id": sid,
                                 "staff": [[v, t.strip()] for v, t in staff]}
        time.sleep(0.7)

    log.info("feedback harvest done netid=%s subjects=%d total_ms=%d",
             netid, len(faculty_map), int((time.monotonic() - t0) * 1000))
    if faculty_map and all(all(str(s[1]).strip() == "Unknown" for s in e["staff"])
                           for e in faculty_map.values()):
        # every subject came back teacherless = one failed staff-list render,
        # not a genuinely empty map. Storing it would hide the Teachers card
        # and the autofill CTA until the next clean harvest; None omits the
        # key upstream and preserves the stored map (README: only a fresh
        # SUCCESSFUL harvest overwrites).
        log.warning("feedback harvest netid=%s all subjects teacherless — "
                    "treating as failed, preserving stored map", netid)
        return None
    return faculty_map


def _fb_cold(opener, base, xheaders, netid):
    """One cold-sync harvest, classified for availability.

    Returns (fb, fb_open): fb is the faculty map (None = preserve stored) and
    fb_open is 1 only after a real map came back, 0 only when the portal
    itself said `Service closed`, None = unknown (session/markup/other
    failure) -> the caller preserves stored fb_open. ponytail: one function so
    the exception->flag mapping is unit-testable without running fetch()."""
    fb_open = None
    try:
        fb = _fb_harvest(opener, base, xheaders, netid)
        fb_open = 1
    except FeedbackWindowClosed as e:
        fb = None
        fb_open = 0
        log.info("feedback window closed netid=%s err=%r", netid, e)
    except HttpScraperError as e:
        fb = None
        log.info("feedback harvest skipped netid=%s err=%r", netid, e)
    except Exception as e:
        fb = None
        log.warning("feedback harvest crashed netid=%s err=%r", netid, e)
    return fb, fb_open


def _fb_probe(opener, base, xheaders, netid):
    """Hot-sync availability probe: ONE fragment fetch, no per-subject
    posts. Returns fb_open 1/0; None on transport failure or an unreadable
    fragment (caller preserves stored). Keeps the CTA archive/unarchive
    fresh on EVERY sync instead of only the daily cold one (2026-10-20: a
    closed form must archive itself without waiting for the next cold
    sync; an open one must come back the same way)."""
    url = f"{base}{BASE_PATH}/students/Feedback/MidSemFeedback.jsp"
    data = urllib.parse.urlencode({"iden": "32", "filter": "", "hdnFormDetails": "1",
                                   "csrfPreventionSalt": ""}).encode()
    headers = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "X-Requested-With": "XMLHttpRequest"}, referer=HRD_URL)
    try:
        _u, body = _req(opener, url, headers, data=data)
    except HttpScraperError as e:
        log.info("feedback probe skipped netid=%s err=%r", netid, e)
        return None
    state = _fb_frag_state(body.decode("utf-8", errors="replace"))
    if state == "closed":
        log.info("feedback window closed (probe) netid=%s", netid)
        return 0
    if state == "open":
        return 1
    # dead/broken: availability unknown -> preserve stored
    log.info("feedback probe netid=%s state=%s (unknown -> preserve)", netid, state)
    return None


def fill_feedback(netid, plan, cookies_json):
    """Opt-in submit: restore the cached portal session, re-verify the live form,
    then submit all-5 ratings + the comment for each planned subject.

    plan comes from app._fb_plan() — the SAME builder the modal preview
    renders, so what the student saw IS what gets sent. Rows are PER TEACHER
    (one portal form per teacher within a subject). Returns
    {"filled": [labels], "already": [labels], "failed": [[label, reason]]}
    where label = "subject · teacher".

    Expected portal-state refusals (session expired, window closed) return
    {"error": <user-facing literal>} instead of raising, so the caller can put
    the message straight in front of the student: exception text is never safe
    to echo into an HTTP response (CWE-209 / CodeQL py/stack-trace-exposure —
    a message can embed nested exception reprs). Transport and unexpected
    failures still raise HttpScraperError and are logged server-side by the
    caller.
    """
    t0 = time.monotonic()
    base, xheaders = _route()
    opener, jar = _make_opener()
    try:
        for ck in json.loads(cookies_json):
            jar.set_cookie(http.cookiejar.Cookie(
                version=0, name=ck["name"], value=ck.get("value", ""),
                port=None, port_specified=False,
                domain=ck.get("domain", PORTAL_HOST), domain_specified=True,
                domain_initial_dot=False, path=ck.get("path", "/"), path_specified=True,
                secure=ck.get("secure", True), expires=ck.get("expires"),
                discard=False, comment=None, comment_url=None, rest={}))
    except Exception as e:
        raise HttpScraperError(f"bad cached session: {e!r}") from e

    _u, body = _req(opener, f"{base}{BASE_PATH}/students/template/HRDSystem.jsp", _hdrs(xheaders))
    if "HRDSystem" not in _u and b"HRDSystem" not in body[:4000]:
        # refusal, not a fault: plain literal the caller may show verbatim
        return {"error": "portal session expired — sync first"}

    # fresh main fragment: common hidden fields + the CURRENT subject list
    url = f"{base}{BASE_PATH}/students/Feedback/MidSemFeedback.jsp"
    data = urllib.parse.urlencode({"iden": "32", "filter": "", "hdnFormDetails": "1",
                                   "csrfPreventionSalt": ""}).encode()
    headers = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "X-Requested-With": "XMLHttpRequest"}, referer=HRD_URL)
    _u, body = _req(opener, url, headers, data=data)
    frag = body.decode("utf-8", errors="replace")
    state = _fb_frag_state(frag)
    if state == "dead":
        # refusal, not a fault: plain literal the caller may show verbatim
        return {"error": "portal session expired — sync first"}
    if state == "closed":
        # refusal + confirmed-closed flag: the caller archives the CTA
        # (fb_open=0) so the stale button can never be clicked again.
        return {"error": "the mid-sem feedback window is closed on the portal — nothing submitted",
                "closed": True}
    if state != "open":
        # refusal, not a fault: plain literal the caller may show verbatim
        return {"error": "feedback window closed or session dead — nothing submitted"}
    common = _fb_common(frag)
    live = {" ".join(n.split()).upper(): sid for sid, n in _fb_subjects(frag)}

    res = {"filled": [], "already": [], "failed": []}
    for item in plan:
        name, staff_id, comment = item["subject"], item["staff_id"], item["comment"]
        label = f"{name} · {item['teacher']}"
        sid = live.get(" ".join(name.split()).upper())
        if not sid:
            res["failed"].append([label, "not on the live form — re-sync"])
            log.warning("feedback fill netid=%s subject=%s no-live-match", netid, name[:40])
            time.sleep(0.7)
            continue
        q = "&" + urllib.parse.urlencode(dict(subjectId=sid, forWhat="1", functionId="1",
                                              staffid="0", **common))
        try:
            _u, inner = _fb_post(opener, base, xheaders, q)
        except HttpScraperError as e:
            # audit run-1 (#17): rows already submitted must survive a later
            # row's transport failure — record + STOP so the caller reports
            # the true end state instead of "nothing was submitted"
            log.warning("feedback fill mid-loop abort netid=%s row=%s err=%s",
                        netid, label[:40], str(e)[:80])
            res["failed"].append([label, "portal error after earlier rows were submitted — re-run to see what is already registered"])
            break
        if _fb_registered(inner):
            res["already"].append(label)
            time.sleep(0.7)
            continue
        if staff_id not in [v for v, _t in _fb_staff_options(inner)]:
            res["failed"].append([label, "teacher not on the live form — re-sync"])
            time.sleep(0.7)
            continue
        # question ids: the LIVE set when the form renders it, else the
        # known 23..36 default; answers must match the id count
        qids = _fb_question_ids(inner) or DEFAULT_FB_QIDS
        n_q = len([x for x in qids.split(",") if x.strip()])
        ans = ",".join(["5"] * n_q) + ","
        sub = "&" + urllib.parse.urlencode(dict(
            subjectId=sid, forWhat="2", staffid=staff_id,
            hiddenQuestionId=qids, hiddenAnswerId=ans,
            commentTextArea=comment[:250], **common))
        try:
            _u, resp = _fb_post(opener, base, xheaders, sub)
        except HttpScraperError as e:
            log.warning("feedback fill mid-loop abort netid=%s row=%s err=%s",
                        netid, label[:40], str(e)[:80])
            res["failed"].append([label, "portal error after earlier rows were submitted — re-run to see what is already registered"])
            break
        if _fb_registered(resp):
            res["filled"].append(label)
            log.info("feedback submitted netid=%s subject=%s staff=%s", netid, name[:40], staff_id)
        else:
            res["failed"].append([label, f"no success marker ({len(resp)}B)"])
            log.warning("feedback submit no-success-marker netid=%s subject=%s resp=%dB",
                        netid, name[:40], len(resp))
        time.sleep(0.7)

    log.info("feedback fill done netid=%s filled=%d already=%d failed=%d total_ms=%d",
             netid, len(res["filled"]), len(res["already"]), len(res["failed"]),
             int((time.monotonic() - t0) * 1000))
    return res


def _merge_exam_results(results, official_html=None, official_rows=None):
    """[(month, year), html] | None entries -> sorted rows, or None when the
    probe is unreliable — None means 'preserve stored value' upstream.

    Unreliable = every transport failed, a silent-rejection page (no empty
    marker, no table), OR a subject table with zero dated rows: the portal
    blanked Date/Session for a window it still lists (seen Oct 4 2026 — an
    empty result there wiped stored schedules; it is not proof the stored
    rows are wrong).

    official_html: the iden=126 Exam Time Table body. Official rows win per
    subject code (they carry exact clock slots); scribe rows fill subjects the
    official page leaves pending — pre-release fallback for future sems.
    official_rows: pre-parsed iden=126 rows gathered across several exam
    windows. When given, official_html is ignored.
    Parse state: rows = merge them; [] = official publishes nothing yet
    (scribe fallback rules apply); None = table present but unparseable
    (label/column drift) — preserve stored rows, never wipe."""
    from app.app import parse_exam_schedule, parse_exam_timetable  # deferred: avoid circularity
    official = []
    if official_rows is not None:
        official = official_rows
    elif official_html:
        official = parse_exam_timetable(official_html)
    ok = [r for r in results if r is not None]
    if official is None:
        # official table present but unparseable (header drift): degrade to the
        # scribe rows instead of freezing exam updates forever — the guards
        # below still preserve stored rows when scribe is empty/unreliable.
        log.warning("exam timetable: unparseable official table shape — falling back to scribe rows")
        official = []
    if not ok and not official:
        return None
    rows, blanked = [], False
    for _wy, html in ok:
        if "No subject found" in html:
            continue  # clean empty window
        wrows = parse_exam_schedule(html)
        if wrows:
            rows.extend(wrows)
        else:
            blanked = True
    if official:
        # per-code merge: official replaces scribe rows with real slots;
        # scribe rows fill subjects the official page leaves pending ("- -")
        codes = {o["code"] for o in official}
        rows = official + [r for r in rows if r["code"] not in codes]
    if not rows and blanked:
        log.debug("exam probe: subject table(s) with no dated rows — "
                  "unreliable, preserving stored value")
        return None
    seen, out = set(), []
    for r in rows:  # a window can repeat across candidate overlap
        k = (r["code"], r["date"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    out.sort(key=lambda r: (r["date"][6:], r["date"][3:5], r["date"][:2]))  # dd-mm-yyyy -> ymd
    return out


def _after_login(netid, jar, helpers):
    """Post-login bookkeeping, shared by EVERY successful-login site: reset the
    portal fail/cooldown counter and persist the fresh cookie jar. The mid-scrape
    relogin path used to skip both — its clear_session() then left the DB with no
    row, so the fresh cookies died with the process and the next sync started
    sessionless (prod evidence 2026-10-12: 'session reuse hit' ->
    'session expired mid-scrape — relogin' -> portal_sessions row gone)."""
    helpers["portal_ok"]()
    try:
        helpers["save_session"](netid, json.dumps(
            [{"name": c.name, "value": c.value, "domain": c.domain,
              "path": c.path, "secure": c.secure, "httpOnly": "HttpOnly" in (c.get_nonstandard_attr("HttpOnly") or "") or c.has_nonstandard_attr("HttpOnly"),
              "expires": c.expires} for c in jar]))
        log.debug("session saved netid=%s cookies=%d", netid, len(jar))
    except Exception as e:
        log.debug("session save failed err=%r", e)


def fetch(netid, password, helpers, cold=True, prepared=None, deadline=None):
    """Full scrape via pure HTTP. Same contract as _fetch_rich_optimized.

    helpers: {portal_fail_once, portal_ok, save_session, load_session,
              clear_session} — injected to avoid circular imports.
    cold=True fetches slow-changing JSPs (personal/courses) too;
    cold=False fetches only hot data (attendance 9 + marks 13).
    prepared: warm login from preflight() (page+captcha done while the
              user typed their password) — skips the prepare phase.
    deadline: time.monotonic() budget for the whole critical section
              (audit run-1 #8) — checked between phases; aborting raises the
              HttpScraperError the caller already handles. None = unbounded
              (tests/tools).
    Raises HttpScraperError on transport-level failure (caller may fall back
    to the Playwright pipeline).
    """
    t_start = time.monotonic()
    base, xheaders = _route()
    on_step = helpers.get("set_progress")
    def _prog(step, pct):
        try: on_step(netid, step, pct)
        except Exception: pass
    def _chk(phase):
        if deadline is not None and time.monotonic() > deadline:
            raise HttpScraperError(f"pipeline deadline exceeded at {phase}")
    opener, jar = _make_opener()

    # Session reuse: cached cookies still valid → skip login entirely
    logged_in = False
    cached = helpers["load_session"](netid)
    if cached:
        try:
            for ck in json.loads(cached):
                jar.set_cookie(http.cookiejar.Cookie(
                    version=0, name=ck["name"], value=ck.get("value", ""),
                    port=None, port_specified=False,
                    domain=ck.get("domain", PORTAL_HOST),
                    domain_specified=True, domain_initial_dot=False,
                    path=ck.get("path", "/"), path_specified=True,
                    secure=ck.get("secure", True), expires=ck.get("expires"),
                    discard=False, comment=None, comment_url=None,
                    rest={}))
            _u, body = _req(opener, f"{base}{BASE_PATH}/students/template/HRDSystem.jsp", _hdrs(xheaders))
            if "HRDSystem" in _u or b"HRDSystem" in body[:4000]:
                logged_in = True
                _prog("Restoring your session…", 50)  # NOT raw on_step: it takes (netid, step, pct) and a raise here used to wipe the jar while logged_in stayed True
                log.debug("session reuse hit netid=%s", netid)
        except Exception as e:
            log.debug("session reuse miss err=%r", e)
            jar.clear()
            helpers["clear_session"](netid)

    _chk("login")
    if not logged_in:
        if prepared:
            # preflight's opener holds the warm JSESSIONID + solved captcha
            opener, jar = prepared["opener"], prepared["jar"]
            log.debug("using preflight session netid=%s", netid)
        ok, fail = _login(opener, netid, password, base, xheaders, helpers,
                          on_step=lambda st, pc: _prog(st, pc), prepared=prepared)
        if not ok:
            return fail
        _after_login(netid, jar, helpers)
    log.debug("login phase done netid=%s total_ms=%d", netid,
              int((time.monotonic() - t_start) * 1000))

    # Parallel JSP fetch — hot always, cold only when requested
    fids = HOT_FORMIDS | (COLD_FORMIDS if cold else set())
    log.debug("jsp batch netid=%s formids=%s", netid, sorted(fids))
    _prog("Fetching attendance & marks…", 65)
    _chk("jsp-batch")
    cands = exam_candidates()
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(_jsp_post, opener, base, xheaders, path, fid)
                   for fid, path in JSPS.items() if fid in fids]
        # end-sem schedule probe rides the same batch: same session, +~1.6KB
        # responses, no wall-time cost (plan: hot cadence, catches early seeding)
        exam_futs = [ex.submit(_exam_post, opener, base, xheaders, m, y)
                     for m, y in cands]
        parallel_html = {fid: html for fid, html in
                         (f.result() for f in futures)}
        exam_results = [f.result() for f in exam_futs]
    # official timetable (iden=126) for the windows the scribe listed — the
    # portal only returns hall/seat for the requested month/year
    official_rows = _official_exam_rows(opener, base, xheaders, exam_results)
    log.debug("jsp fetch done netid=%s sizes=%s", netid,
              {k: len(v) for k, v in parallel_html.items()})

    from app.app import MONTHS, _cells, _parse_component_inner, parse_attendance, parse_marks, parse_personal_details, parse_timetable, sync_error  # deferred
    content_html = parallel_html.get("9", "")
    if "youLogin" in content_html or ("captcha" in content_html.lower() and "Login" in content_html[:2000]):
        # Session died mid-scrape → relogin once
        log.info("session expired mid-scrape netid=%s — relogin", netid)
        helpers["clear_session"](netid)
        jar.clear()
        ok, fail = _login(opener, netid, password, base, xheaders, helpers)
        if not ok:
            return fail
        _after_login(netid, jar, helpers)  # persist the relogin too — see _after_login docstring
        fids = HOT_FORMIDS | (COLD_FORMIDS if cold else set())  # refetch with same plan
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(_jsp_post, opener, base, xheaders, path, fid)
                       for fid, path in JSPS.items() if fid in fids]
            exam_futs = [ex.submit(_exam_post, opener, base, xheaders, m, y)
                         for m, y in cands]
            parallel_html = {fid: html for fid, html in
                             (f.result() for f in futures)}
            exam_results = [f.result() for f in exam_futs]
        official_rows = _official_exam_rows(opener, base, xheaders, exam_results)
        # audit S25: re-derive from the REFETCHED body — content_html still
        # held the dead session's page, so a legitimate refetch parsed a
        # 466-byte corpse and reported 'Attendance page did not load'
        # (3 prod 503s on 2026-10-07 with the fresh 19KB body in the log)
        content_html = parallel_html.get("9", "")

    data = parse_attendance(content_html)
    if not data.get("courses"):
        metrics.inc("opensrm_parse_empty_total", page="attendance", pipeline="http")
        if "ABC ID" in content_html or "Aadhaar" in content_html:
            return sync_error("markup_changed", "Portal requires ABC ID Generation first — "
                                                "log in at sp.srmist.edu.in and complete the "
                                                "Aadhaar/ABC ID form, then try again.")
        return sync_error("portal_down", "Attendance page did not load (portal returned no "
                                         "course table). The portal may be slow or your "
                                         "account may be restricted.")

    # Photo: removed Sep 25 2026 — portal photo unused in any workflow (blobatar avatars instead)

    # Daily absence drilldowns (parallel)
    targets = []
    for mo in data.get("monthly", []):
        mm = re.search(r"([A-Z]+)\s*/\s*(\d{4})", mo["month"])
        if not mm:
            continue
        absent_val = mo["absent"].replace("\xa0", " ").strip()
        if not absent_val or int(absent_val) <= 0:
            continue
        if mm.group(1).upper() not in MONTHS:
            continue
        targets.append({"mstr": mo["month"], "mon": MONTHS[mm.group(1).upper()],
                        "year": mm.group(2)})

    _chk("drills")
    daily = {}
    if targets:
        def drill(t):
            url = f"{base}{BASE_PATH}/students/report/studentAttendanceDetailsInner.jsp"
            d = urllib.parse.urlencode({"ids": "1", "attendanceMonth": t["mon"],
                                        "attendanceYear": t["year"]}).encode()
            h = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                       "X-Requested-With": "XMLHttpRequest"}, referer=HRD_URL)
            try:
                _u, b = _req(opener, url, h, data=d)
                return t["mstr"], b.decode("utf-8", errors="replace")
            except HttpScraperError:
                return t["mstr"], ""
        with ThreadPoolExecutor(max_workers=min(6, len(targets))) as ex:
            for mstr, inner in ex.map(drill, targets):
                rows = []
                for row in re.findall(r"<tr[^>]*>(.*?)</tr>", inner, re.S):
                    cells = [re.sub(r"<[^>]+>", "", c).replace("\xa0", " ").strip()
                             for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
                    if len(cells) >= 2 and re.match(r"\d{2}-\d{2}-\d{4}", cells[0]):
                        rows.append({"date": cells[0], "hours": cells[1]})
                # audit run-1: failed/empty drilldown months are OMITTED, not
                # stored as [] — the merge then keeps stored rows for that month
                if rows:
                    daily[mstr] = rows
        log.debug("daily drilldown months=%s", [t["mstr"] for t in targets])
    data["daily_absent"] = daily

    # End-sem schedule: official 126 table wins; scribe rows fill the rest.
    # None (both unreliable) -> key omitted -> stored value preserved upstream.
    exams = _merge_exam_results(exam_results, official_rows=official_rows)
    if not exams:   # [] = clean empty window, None = unreliable — both worth counting
        metrics.inc("opensrm_parse_empty_total", page="exams", pipeline="http")
    log.debug("exam probe netid=%s candidates=%s rows=%s", netid, cands,
              len(exams) if exams is not None else None)

    # Personal details + courses
    personal = {}
    try:
        ph = parallel_html.get("17", "")
        if ph:
            personal = parse_personal_details(ph)
    except Exception as e:
        log.debug("personal parse err=%r", e)
    if cold and not personal:
        metrics.inc("opensrm_parse_empty_total", page="personal", pipeline="http")

    # Faculty map: read-only harvest rides the same logged-in session after the
    # JSP batch (MidSemFeedback.jsp is a portal window — when closed, the whole
    # harvest raises and the sync still ships attendance/marks). Submitting is
    # OPT-IN from the dashboard (fill_feedback) — sync never writes to the portal.
    # _fb_cold classifies availability on the daily cold sync; _fb_probe keeps
    # it fresh on every hot sync too (one fragment POST, see its docstring).
    _chk("harvest")
    fb, fb_open = None, None
    _prog("Checking mid-sem feedback…", 85)
    if cold:
        fb, fb_open = _fb_cold(opener, base, xheaders, netid)
    else:
        fb_open = _fb_probe(opener, base, xheaders, netid)

    courses = []
    try:
        ch = parallel_html.get("7", "")
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", ch, re.S):
            cells = _cells(row)
            if len(cells) >= 3 and cells[0] and not cells[0].lower().startswith("total"):
                try:
                    courses.append({"code": cells[0], "name": cells[1],
                                    "credits": int(cells[2] or 0)})
                except ValueError:
                    pass
    except Exception as e:
        log.debug("courses parse err=%r", e)
    if cold and not courses:
        metrics.inc("opensrm_parse_empty_total", page="courses", pipeline="http")

    # Marks + parallel component drilldowns
    marks, subject_map = [], {}
    try:
        mh = parallel_html.get("13", "")
        if mh:
            marks, subject_map = parse_marks(mh)
            drill_subjects = [{"sid": v["id"], "st": v["status"], "code": k}
                              for k, v in subject_map.items() if v.get("id")]
            if drill_subjects:
                def mdrill(s):
                    url = f"{base}{BASE_PATH}/students/report/studentInternalMarkDetailsInner.jsp"
                    d = urllib.parse.urlencode({"iden": "1", "hdnSubjectId": s["sid"],
                                                "status": s["st"]}).encode()
                    h = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded",
                               "X-Requested-With": "XMLHttpRequest"}, referer=HRD_URL)
                    try:
                        _u, b = _req(opener, url, h, data=d)
                        return s["code"], b.decode("utf-8", errors="replace")
                    except HttpScraperError:
                        return s["code"], ""
                with ThreadPoolExecutor(max_workers=min(6, len(drill_subjects))) as ex:
                    for code, html in ex.map(mdrill, drill_subjects):
                        comps = _parse_component_inner(html)
                        if comps:
                            for m in marks:
                                if m["code"] == code:
                                    m["components"] = comps
                                    m["scored_total"] = round(sum(x["scored"] for x in comps), 2)
                                    m["max_total"] = round(sum(x["max"] for x in comps), 2)
                                    break
            log.debug("marks drilldown subjects=%d", len(drill_subjects))
            _prog("Reading personal details & timetable…", 80)
    except Exception as e:
        log.warning("marks parse err — marks return empty (stored marks now preserved by caller): %r", e)
    if not marks:
        metrics.inc("opensrm_parse_empty_total", page="marks", pipeline="http")

    _prog("Preparing your dashboard…", 92)
    log.info("http scrape complete netid=%s courses=%d marks=%d personal=%d "
             "cold=%s total_ms=%d", netid, len(data["courses"]), len(marks),
             len(personal), cold, int((time.monotonic() - t_start) * 1000))
    out = {"ok": True, "data": data, "personal": personal,
           "courses": courses, "marks": marks, "subjects": subject_map,
           "fetched": int(time.time())}
    if exams is not None:  # absent key = preserve stored exam_schedule_json
        out["exams"] = exams
    if fb is not None:  # absent key = feedback window closed / harvest failed
        out["faculty"] = fb
    if fb_open is not None:  # absent key = availability unknown -> preserve stored
        out["fb_open"] = fb_open
    # Official daily timetable (formId 10): a real grid ships; [] (section
    # never published) and None (drift/session/dead JSP) omit the key so the
    # caller preserves stored rows — same absent==preserve contract as exams.
    try:
        tt = parse_timetable(parallel_html.get("10", ""))
        if tt:  # dict only
            out["timetable"] = tt
        else:
            metrics.inc("opensrm_parse_empty_total", page="timetable", pipeline="http")
    except Exception as e:
        log.debug("timetable parse err=%r", e)
        metrics.inc("opensrm_parse_empty_total", page="timetable", pipeline="http")
    return out
