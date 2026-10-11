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
}
HOT_FORMIDS = {"9", "13", "126"}  # attendance + marks + official exam timetable: every sync
# (no "1"/"32": ScribeInner was demoted to the exam probe, and _fb_harvest
# posts iden=32 itself — nothing reads those batch results; both rode along
# on every cold sync for nothing)
COLD_FORMIDS = {"17", "7"}  # personal/courses: re-fetch only when stale > COLD_TTL
COLD_TTL = 24 * 3600  # seconds

MAX_CAPTCHA_RETRIES = 3


class HttpScraperError(Exception):
    """Unexpected transport/code failure — caller falls back to Playwright."""


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


def _req(opener, url, headers, data=None, timeout=25):
    """GET/POST; returns (final_url, body_bytes). Raises HttpScraperError on transport fail."""
    t0 = time.monotonic()
    try:
        r = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        for k, v in headers.items():
            r.add_header(k, v)
        resp = opener.open(r, timeout=timeout)
        body = resp.read()
        log.debug("portal %s %s -> %s %dB %dms", "POST" if data else "GET",
                  url.replace("https://", "")[:60], resp.status, len(body),
                  int((time.monotonic() - t0) * 1000))
        return resp.url, body
    except urllib.error.HTTPError as e:
        log.warning("portal http_error url=%s status=%s", url[:80], e.code)
        raise HttpScraperError(f"HTTP {e.code} from portal") from e
    except Exception as e:
        log.warning("portal transport_error url=%s err=%r", url[:80], e)
        raise HttpScraperError(f"transport: {e!r}") from e


def _telemetry_b64(t0):
    return base64.b64encode(json.dumps({
        "startTime": int(time.time() * 1000 - 10000), "currentDomain": PORTAL_HOST,
        "timezoneOffset": -330, "screenWidth": 1920, "screenHeight": 1080,
        "colorDepth": 24, "devicePixelRatio": 1, "platform": "Win32",
        "userAgent": UA, "language": "en-US", "hardwareConcurrency": 8,
        "deviceMemory": 8, "touchSupport": False, "webdriver": False,
        "mouseClicks": 5, "mouseMovements": 32, "keystrokeCount": 10,
        "typingSpeedMs": 8500, "canvasHash": "-27fdeb33",
        "submitTime": int(time.time() * 1000), "timeOnPageMs": 10000,
    }).encode()).decode()


# ── Login preflight: page fetch + captcha OCR done while the user is
#    still typing their password, so submit skips straight to the POST.
#    keyed by netid; consumed by fetch() on the next login for that netid.
_PREFLIGHT = {}   # netid -> {"opener", "jar", "ctx", "ts"}
_PREFLIGHT_MAX = 32


def preflight(netid):
    """Warm the login: GET youLogin.jsp + solve captcha, store for submit."""
    base, xheaders = _route()
    opener, jar = _make_opener()
    ctx = _prepare(opener, base, xheaders)
    if not ctx["ocr"]:
        log.warning("preflight empty ocr netid=%s — not stored", netid)
        return
    now = time.time()
    if len(_PREFLIGHT) >= _PREFLIGHT_MAX:  # opportunistic prune of stale entries
        for k in [k for k, v in _PREFLIGHT.items() if now - v["ts"] > 180]:
            _PREFLIGHT.pop(k, None)
    _PREFLIGHT[netid] = {"opener": opener, "jar": jar, "ctx": ctx, "ts": now}
    log.info("preflight ready netid=%s ocr=%s age=0ms", netid, ctx["ocr"])


def take_preflight(netid, max_age=150):
    """Pop the warm login for this netid (single-use). None when stale/absent."""
    p = _PREFLIGHT.pop(netid, None)
    if not p or time.time() - p["ts"] > max_age:
        return None
    log.debug("preflight consumed netid=%s age_ms=%d", netid, int((time.time() - p["ts"]) * 1000))
    return p


def _prepare(opener, base, xheaders, on_step=None, attempt=1):
    """Fetch login page + parse tokens + fetch captcha + OCR.
    Returns ctx dict for _post_login. Raises HttpScraperError."""
    from app.app import solve_captcha_b64  # deferred: same ddddocr solver

    t0 = time.monotonic()
    page_url = f"{base}{BASE_PATH}/students/loginManager/youLogin.jsp"
    _url, body = _req(opener, page_url, _hdrs(xheaders))
    html = body.decode("utf-8", errors="replace")
    log.debug("login attempt=%d step=get_page bytes=%d", attempt, len(html))
    if on_step: on_step("Opening login page…", 15)

    def g(p, _html=html):
        m = re.search(p, _html)
        return m.group(1) if m else None

    nonce = g(r"nonce\s*:\s*'([^']+)'")
    dfield = g(r"domainFieldName\s*[=:]\s*['\"]([^'\"]+)['\"]")
    cfield = g(r"captchaFieldName\s*[=:]\s*['\"]([^'\"]+)['\"]")
    rdelim = g(r"randomDelimiter\s*[=:]\s*['\"]([^'\"]+)['\"]")
    hp = re.search(r'name=\"(ph_[^\"]+)\"', html)
    if not hp:
        raise HttpScraperError("honeypot field missing")
    img = re.search(r'<img[^>]*id=\"secure_captcha\"[^>]*>', html)
    src = re.search(r'data-src=\"([^\"]+)\"', img.group(0)) if img else None
    if not all([nonce, dfield, cfield, rdelim, src]):
        log.warning("login page missing tokens nonce=%s dfield=%s cfield=%s",
                    bool(nonce), bool(dfield), bool(cfield))
        raise HttpScraperError("login page tokens missing")

    # Captcha: the page's OWN image (data-src) with Domain-Proof
    img_path = src.group(1)
    img_url = f"https://{PORTAL_HOST}{img_path}" if img_path.startswith("/") else img_path
    if base != f"https://{PORTAL_HOST}":
        img_url = img_url.replace(f"https://{PORTAL_HOST}", base)
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
            break
        except HttpScraperError as e:
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
    return {"t0": t0, "hp": hp.group(1), "dfield": dfield, "cfield": cfield,
            "rdelim": rdelim, "ocr": ocr}


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
    action: "ok" | "retry" (fresh captcha needed) | "fail" (fatal)."""
    # POST login
    dtoken = base64.b64encode(PORTAL_HOST[::-1].encode()).decode()
    elapsed = str(max(5, int(time.time() - ctx["t0"])))
    cptoken = base64.b64encode(f"{elapsed}{ctx['rdelim']}3".encode()).decode()
    fields = {ctx["hp"]: "", "username": netid, "password": password,
              "captcha": ctx["ocr"], "fpPayload": "", "fpToken": "",
              "telemetryPayload": _telemetry_b64(ctx["t0"]),
              ctx["dfield"]: dtoken, ctx["cfield"]: cptoken}
    post_url = f"{base}{BASE_PATH}/LoginServlet"
    data = urllib.parse.urlencode(fields).encode()
    headers = _hdrs({**xheaders, "Content-Type": "application/x-www-form-urlencoded",
                     "Origin": f"https://{PORTAL_HOST}"}, referer=LOGIN_PAGE)
    final_url, body = _req(opener, post_url, headers, data=data)
    rhtml = body.decode("utf-8", errors="replace")
    ok = "HRDSystem" in final_url or "HRDSystem" in rhtml[:4000]
    if on_step: on_step("Verifying credentials…", 55)
    log.debug("login attempt=%d step=post final=%s hrdsystem=%s bytes=%d",
              attempt, final_url.split("/")[-1][:40], ok, len(rhtml))
    if ok:
        return "ok", None
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
        return "fail", "invalid credentials — check your NetID/password"
    if "invalid captcha" in low:
        log.info("login attempt=%d invalid_captcha ocr=%s portal_alert=%r",
                 attempt, ctx["ocr"], alert)
        if attempt < MAX_CAPTCHA_RETRIES:
            return "retry", None
        return "fail", "login failed after 3 attempts — captcha unreadable"
    # Silent rejection: login page again, no error text → portal rate-limiting
    log.warning("login attempt=%d silent_rejection (no HRDSystem, no error text) "
                "portal_alert=%r bytes=%d", attempt, alert, len(rhtml))
    helpers["portal_fail_once"]()
    return "fail", ("SRM portal rejected the login without an error (likely "
                    "rate-limiting). Try again in a few minutes.")


def _login(opener, netid, password, base, xheaders, helpers, on_step=None, prepared=None):
    """Pure-HTTP login. Returns (ok, err). Raises HttpScraperError on transport fail."""
    # Preflight path: warm session + solved captcha from the typing phase.
    if prepared:
        try:
            if on_step: on_step("Using pre-solved captcha…", 40)
            action, err = _post_login(prepared["opener"], prepared["ctx"], netid,
                                      password, base, xheaders, helpers, on_step, attempt=1)
            if action == "ok":
                return True, None
            if action == "fail":
                return False, err
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
            return False, "captcha OCR failed — try again"
        action, err = _post_login(opener, ctx, netid, password, base, xheaders,
                                  helpers, on_step, attempt)
        if action == "ok":
            return True, None
        if action == "retry":
            time.sleep(2)
            continue
        return False, err
    return False, "login failed — captcha retries exhausted"


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
    if "youLogin" in frag or "txtCourseTitle" not in frag:
        raise HttpScraperError("feedback form did not load (session dead or window closed)")

    subjects = _fb_subjects(frag)
    if not subjects:
        raise HttpScraperError("feedback form parsed but lists no subjects — "
                               "portal markup changed, aborting")

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
    if "youLogin" in frag or "txtCourseTitle" not in frag:
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
        _u, inner = _fb_post(opener, base, xheaders, q)
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
        _u, resp = _fb_post(opener, base, xheaders, sub)
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


def _merge_exam_results(results, official_html=None):
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
    Parse state: rows = merge them; [] = official publishes nothing yet
    (scribe fallback rules apply); None = table present but unparseable
    (label/column drift) — preserve stored rows, never wipe."""
    from app.app import parse_exam_schedule, parse_exam_timetable  # deferred: avoid circularity
    official = []
    if official_html:
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


def fetch(netid, password, helpers, cold=True, prepared=None):
    """Full scrape via pure HTTP. Same contract as _fetch_rich_optimized.

    helpers: {portal_fail_once, portal_ok, save_session, load_session,
              clear_session} — injected to avoid circular imports.
    cold=True fetches slow-changing JSPs (personal/courses) too;
    cold=False fetches only hot data (attendance 9 + marks 13).
    prepared: warm login from preflight() (page+captcha done while the
              user typed their password) — skips the prepare phase.
    Raises HttpScraperError on transport-level failure (caller may fall back
    to the Playwright pipeline).
    """
    t_start = time.monotonic()
    base, xheaders = _route()
    on_step = helpers.get("set_progress")
    def _prog(step, pct):
        try: on_step(netid, step, pct)
        except Exception: pass
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

    if not logged_in:
        if prepared:
            # preflight's opener holds the warm JSESSIONID + solved captcha
            opener, jar = prepared["opener"], prepared["jar"]
            log.debug("using preflight session netid=%s", netid)
        ok, err = _login(opener, netid, password, base, xheaders, helpers,
                         on_step=lambda st, pc: _prog(st, pc), prepared=prepared)
        if not ok:
            return {"ok": False, "error": err}
        helpers["portal_ok"]()
        try:
            helpers["save_session"](netid, json.dumps(
                [{"name": c.name, "value": c.value, "domain": c.domain,
                  "path": c.path, "secure": c.secure, "httpOnly": "HttpOnly" in (c.get_nonstandard_attr("HttpOnly") or "") or c.has_nonstandard_attr("HttpOnly"),
                  "expires": c.expires} for c in jar]))
        except Exception as e:
            log.debug("session save failed err=%r", e)
    log.debug("login phase done netid=%s total_ms=%d", netid,
              int((time.monotonic() - t_start) * 1000))

    # Parallel JSP fetch — hot always, cold only when requested
    fids = HOT_FORMIDS | (COLD_FORMIDS if cold else set())
    log.debug("jsp batch netid=%s formids=%s", netid, sorted(fids))
    _prog("Fetching attendance & marks…", 65)
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
    log.debug("jsp fetch done netid=%s sizes=%s", netid,
              {k: len(v) for k, v in parallel_html.items()})

    from app.app import MONTHS, _cells, _parse_component_inner, parse_attendance, parse_marks, parse_personal_details  # deferred
    content_html = parallel_html.get("9", "")
    if "youLogin" in content_html or ("captcha" in content_html.lower() and "Login" in content_html[:2000]):
        # Session died mid-scrape → relogin once
        log.info("session expired mid-scrape netid=%s — relogin", netid)
        helpers["clear_session"](netid)
        jar.clear()
        ok, err = _login(opener, netid, password, base, xheaders, helpers)
        if not ok:
            return {"ok": False, "error": err}
        fids = HOT_FORMIDS | (COLD_FORMIDS if cold else set())  # refetch with same plan
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(_jsp_post, opener, base, xheaders, path, fid)
                       for fid, path in JSPS.items() if fid in fids]
            exam_futs = [ex.submit(_exam_post, opener, base, xheaders, m, y)
                         for m, y in cands]
            parallel_html = {fid: html for fid, html in
                             (f.result() for f in futures)}
            exam_results = [f.result() for f in exam_futs]
        # audit S25: re-derive from the REFETCHED body — content_html still
        # held the dead session's page, so a legitimate refetch parsed a
        # 466-byte corpse and reported 'Attendance page did not load'
        # (3 prod 503s on 2026-10-07 with the fresh 19KB body in the log)
        content_html = parallel_html.get("9", "")

    data = parse_attendance(content_html)
    if not data.get("courses"):
        if "ABC ID" in content_html or "Aadhaar" in content_html:
            return {"ok": False, "error": "Portal requires ABC ID Generation first — "
                                           "log in at sp.srmist.edu.in and complete the "
                                           "Aadhaar/ABC ID form, then try again."}
        return {"ok": False, "error": "Attendance page did not load (portal returned no "
                                      "course table). The portal may be slow or your "
                                      "account may be restricted."}

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
                daily[mstr] = rows
        log.debug("daily drilldown months=%s", [t["mstr"] for t in targets])
    data["daily_absent"] = daily

    # End-sem schedule: official 126 table wins; scribe rows fill the rest.
    # None (both unreliable) -> key omitted -> stored value preserved upstream.
    exams = _merge_exam_results(exam_results, official_html=parallel_html.get("126", ""))
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

    # Faculty map: read-only harvest rides the same logged-in session after the
    # JSP batch (MidSemFeedback.jsp is a portal window — when closed, the whole
    # harvest raises and the sync still ships attendance/marks). Submitting is
    # OPT-IN from the dashboard (fill_feedback) — sync never writes to the portal.
    fb = None
    if cold:
        try:
            _prog("Checking mid-sem feedback…", 85)
            fb = _fb_harvest(opener, base, xheaders, netid)
        except HttpScraperError as e:
            log.info("feedback harvest skipped netid=%s err=%r", netid, e)
        except Exception as e:
            log.warning("feedback harvest crashed netid=%s err=%r", netid, e)

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
    return out
