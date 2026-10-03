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

print("ok  login rejection classifier + sync quota ordering")
