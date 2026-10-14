"""One runnable check for login-rejection classification + sync-quota ordering.

Covers the 2026-09-30 prod incident:
  * a wrong password was reported as "captcha unreadable" and retried 3x per
    request, burning the portal's own 3-attempts-per-NetID lockout;
  * "Sync in progress" rejections consumed the per-netid sync quota, so three
    busy clicks locked an account that had never synced.

Portal wording below is verbatim from live responses captured 2026-09-30
(alert markup + message only — no page markup, no credentials, no PII).
Offline: `_req` is stubbed, so this suite never reaches the SRM portal.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with tempfile.TemporaryDirectory() as td:   # verify76 forbids test DBs in-tree
    os.environ["DATA_DIR"] = td
    from app import app as A
    from app import http_scraper as H

# The login page's own tokens. These are what made the old loose
# "captcha AND invalid" match fire on EVERY rejection — keep them in the
# fixture so a "simplified" classifier fails here, not in prod.
PAGE = ('<div class="invalid-feedback">Enter valid password</div>'
        '<input id="secure_captcha" name="captcha"><label>Captcha</label>')

CRED_ALERT = ("Invalid login credentials The user ID or password entered is "
              "invalid.The login attempt was unsuccessful. You have 2 out of 3 "
              "login attempts remaining.")
CAPTCHA_ALERT = "Invalid captcha. "


def rej(alert):
    return (f"<html>{PAGE}<div class=\"alert-icon-content\">"
            f"<h6 class=\"alert-heading\">Alert</h6>{alert}</div></html>")


calls = {"portal_fail": 0}
helpers = {"portal_fail_once": lambda: calls.__setitem__("portal_fail", calls["portal_fail"] + 1),
           "portal_ok": lambda: None, "save_session": lambda *a: None,
           "load_session": lambda *a: None, "clear_session": lambda *a: None,
           "set_progress": lambda *a: None}


def classify(body, attempt=1):
    """Run the real _post_login classifier over a canned response body."""
    orig = H._req
    H._req = lambda *a, **k: ("https://sp.srmist.edu.in/HRDSystem.jsp" if "HRDSystem" in body
                              else "https://sp.srmist.edu.in/LoginServlet", body.encode())
    try:
        ctx = {"t0": 0, "hp": "ph_db", "dfield": "dom", "cfield": "cptoken",
               "rdelim": "|", "ocr": "ab12cd"}
        return H._post_login(None, ctx, "zz9999", "pw", "https://sp.srmist.edu.in",
                             {}, helpers, None, attempt=attempt)
    finally:
        H._req = orig


# ── 1. classification on the three real portal outcomes ─────────────────────
assert classify(rej(CRED_ALERT)) == ("fail", "invalid credentials — check your NetID/password"), \
    "bad password must be a credentials failure, not a captcha retry"
assert calls["portal_fail"] == 0, "credentials failure is not a portal rate-limit event"

assert classify(rej(CRED_ALERT), attempt=3)[0] == "fail", \
    "credentials failure must never burn captcha retries"
assert classify(rej(CAPTCHA_ALERT), attempt=1) == ("retry", None), "bad captcha retries"
assert classify(rej(CAPTCHA_ALERT), attempt=3) == (
    "fail", "login failed after 3 attempts — captcha unreadable"), "3rd captcha failure gives up"

silent = classify(PAGE)      # page re-rendered with NO alert at all
assert silent[0] == "fail" and "without an error" in silent[1], \
    "the silent-rejection branch must be reachable (it was unreachable before)"
assert calls["portal_fail"] == 1, "silent rejection arms the portal cooldown"
assert classify("<html>HRDSystem.jsp</html>") == ("ok", None), "success path untouched"

# tripwire: the old loose condition still matches the credentials body — this is
# WHY the classifier must key on the portal's alert text, not on page tokens
low = rej(CRED_ALERT).lower()
assert "captcha" in low and "invalid" in low, "fixture lost the tokens that caused the bug"
assert "invalid captcha" not in low, "credentials body must not contain the captcha phrase"

# ── 2. alert extraction (the log line that makes prod debuggable) ────────────
assert H._portal_alert(rej(CRED_ALERT)) == CRED_ALERT.strip()
assert H._portal_alert(rej(CAPTCHA_ALERT)) == CAPTCHA_ALERT.strip()
assert H._portal_alert(PAGE) == ""

# ── 3. sync quota is only consumed by syncs that can actually run ───────────
netid = "zzquota"
A._login_attempts.pop(netid, None)

acquired = A._scrape_lock.acquire(blocking=False)
assert acquired, "scrape lock unexpectedly held before the busy test"
try:
    busy = [A.fetch_attendance(netid, "pw") for _ in range(3)]
finally:
    A._scrape_lock.release()
assert all("Sync in progress" in r["error"] for r in busy), busy
assert netid not in A._login_attempts, "busy rejections must not consume the quota"

A._portal_cooldown_until = time.time() + 60
cd = A.fetch_attendance(netid, "pw")
A._portal_cooldown_until = 0
assert "rate-limiting our server" in cd["error"], cd
assert netid not in A._login_attempts, "cooldown rejections must not consume the quota"

A._portal_attempts[:] = [time.time()] * (A._PORTAL_CAP + 1)
bud = A.fetch_attendance(netid, "pw")
A._portal_attempts.clear()
assert "Too many portal requests" in bud["error"], bud
assert netid not in A._login_attempts, "budget rejections must not consume the quota"

A._login_attempts[netid] = [time.time() - 540] * 3   # window nearly expired
den = A.fetch_attendance(netid, "pw")
assert "Too many sync attempts" in den["error"], den
assert "10 minutes" not in den["error"], \
    f"countdown must reflect the real window, got: {den['error']}"
assert len(A._login_attempts[netid]) == 3, "denied request must not append a 4th timestamp"
cd_txt = A._netid_retry_text(netid)
assert cd_txt.endswith("seconds") and 50 <= int(cd_txt.split()[0]) <= 60, cd_txt
assert A._retry_text(time.time() - 3500, 3600) == "2 minutes"

# ── 4. audit run-1: success-only quota charge + budget floor + per-IP share ──
# admission is check-only: a wrong-password guess can't spend the victim's quota
A._login_attempts.pop("zzvictim", None)
assert A._check_rate("zzvictim") is True, "fresh account must be admitted"
assert "zzvictim" not in A._login_attempts, "admission must not charge (charge = success only)"
for _ in range(3):
    A._charge_rate("zzvictim")
assert A._check_rate("zzvictim") is False, "3 charged syncs must deny the 4th"
A._login_attempts.pop("zzvictim", None)

A._portal_attempts.clear(); A._portal_attempts_auth.clear(); A._portal_ip.clear()
# per-IP share: one rotating source can hold at most _PORTAL_IP_CAP tokens
for _ in range(A._PORTAL_IP_CAP):
    assert A._check_portal_budget("1.2.3.4") is True
assert A._check_portal_budget("1.2.3.4") is False, "per-IP share cap must reject"
assert len(A._portal_attempts) == A._PORTAL_IP_CAP, "rejected attempt must spend no token"
assert A._check_portal_budget("5.6.7.8") is True, "other IPs must still be admitted"
A._portal_attempts.clear(); A._portal_ip.clear()
# auth floor: unauth work can never drain the reserved refresh tokens
n = 0
while len(A._portal_attempts) < A._PORTAL_CAP - A._PORTAL_AUTH_FLOOR:
    assert A._check_portal_budget(f"9.9.9.{n}") is True
    n += 1
assert A._check_portal_budget("2.2.2.2") is False, "unauth must stop at CAP-FLOOR"
assert A._check_portal_budget("3.3.3.3", authorized=True) is True, "refresh floor must stay reachable"
assert A._check_portal_budget("4.4.4.4", authorized=True) is True, "auth draws from full CAP"
A._portal_attempts.clear(); A._portal_attempts_auth.clear(); A._portal_ip.clear()

# ── 5. preflight admission: atomic, bounded, no discriminator (audit run-1 #7/#14)
cl = A.app.test_client()
A._preflight_last.clear(); A._preflight_ip.clear()
# ip cap: 10 hits in-window -> 429, no thread spawned, no token spent
A._preflight_ip["127.0.0.1"] = [time.time()] * 10
r = cl.post("/api/login/preflight", json={"netid": "zzrate"})
assert r.status_code == 429, r.data
assert A._portal_attempts == [] and A._portal_attempts_auth == [], "429 must spend no budget token"
A._preflight_ip.clear()
# cooldown: identical {ok:true} to a fresh start — no cooldown discriminator
A._preflight_last["zzpref"] = time.time()
r = cl.post("/api/login/preflight", json={"netid": "zzpref"})
assert r.status_code == 200 and r.get_json() == {"ok": True}, r.data
assert "cooldown" not in r.get_json(), "per-netid discriminator must not leak"
# busy: scrape lock held -> 503, no thread (all paths here are no-spawn, so
# this offline suite never reaches the portal)
got = A._scrape_lock.acquire(blocking=False)
assert got
try:
    r = cl.post("/api/login/preflight", json={"netid": "zzbusy"})
finally:
    A._scrape_lock.release()
assert r.status_code == 503, r.data
# aggregate eviction: stale buckets die on the next admission sweep
A._preflight_last["zzold"] = time.time() - 700
A._preflight_ip["9.9.9.9"] = [time.time() - 700]
r = cl.post("/api/login/preflight", json={"netid": "zzpref"})  # cooldown path sweeps first
assert "zzold" not in A._preflight_last, "stale netid keys must be evicted"
assert "9.9.9.9" not in A._preflight_ip, "drained ip buckets must be evicted"
A._preflight_last.clear(); A._preflight_ip.clear()

# ── 6. captcha data-src confined to the portal host (audit run-1 #9) ─────
from app import http_scraper as H  # noqa: E402
BASE0 = f"https://{H.PORTAL_HOST}"
assert H._captcha_url("/captcha.jpg", BASE0) == f"https://{H.PORTAL_HOST}/captcha.jpg"
assert H._captcha_url(f"https://{H.PORTAL_HOST}/captcha.jpg", BASE0) == f"https://{H.PORTAL_HOST}/captcha.jpg"
# egress rewrite still works for an absolute portal URL (audit's existing behaviour)
assert H._captcha_url(f"https://{H.PORTAL_HOST}/captcha.jpg", "https://egress.example") \
    == "https://egress.example/captcha.jpg"
assert H._captcha_url("https://egress.example/captcha.jpg", "https://egress.example") \
    == "https://egress.example/captcha.jpg"
for bad in ("file:///etc/passwd", "http://169.254.169.254/x",
            "https://attacker.example/HRDSystem.jsp", "captcha.jpg"):
    try:
        H._captcha_url(bad, BASE0)
        raise AssertionError(f"data-src {bad!r} must be rejected")
    except H.HttpScraperError:
        pass

# ── 7. progress reads are attempt-token bound (audit run-1 #13) ─────────
r = cl.post("/api/login/progress", json={"netid": "zz9999"})
assert r.status_code == 400, f"netid-keyed reads must be gone, got {r.status_code}"
r = cl.post("/api/login/progress", json={"attempt": "abc123"})
assert r.status_code == 200 and r.get_json() == {"step": "", "pct": 0}, r.data
A._set_progress("abc123", "Reading captcha…", 60, netid="zz9999")
r = cl.post("/api/login/progress", json={"attempt": "abc123"})
assert r.get_json().get("step") == "Reading captcha…", r.data
r = cl.post("/api/login/progress", json={"attempt": "abc123<script>"})
assert r.status_code == 400, "attempt must be alnum-only"
A._login_progress.clear()

# ── 8. CF headers gated by edge secret, not client-assertable (#18) ─────
A.CF_EDGE_SECRET = ""
with A.app.test_request_context(headers={"cf-ray": "r1", "CF-Connecting-IP": "6.6.6.6"}):
    assert A._behind_cf() is False, "bare cf-ray must not confer edge trust"
    assert A._client_ip() != "6.6.6.6", "client-asserted IP must be ignored"
    assert A._cookie_secure() is False, "Secure flag must not be client-forgeable"
A.CF_EDGE_SECRET = "edge-s3cret"
with A.app.test_request_context(headers={"X-Edge-Secret": "edge-s3cret",
                                         "CF-Connecting-IP": "6.6.6.6",
                                         "X-Forwarded-Proto": "https"}):
    assert A._behind_cf() is True, "matching edge secret must confer trust"
    assert A._client_ip() == "6.6.6.6"
    assert A._cookie_secure() is True
with A.app.test_request_context(headers={"X-Edge-Secret": "wrong", "cf-ray": "r2"}):
    assert A._behind_cf() is False, "wrong secret must not confer trust"
A.CF_EDGE_SECRET = ""

print("ok  login rejection classifier + sync quota ordering")
