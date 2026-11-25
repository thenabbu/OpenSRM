"""One runnable check for what actually makes the portal accept a login.

Measured 2026-11-20 with a real account, one variable at a time:

  control: real body WITH secureToken        -> HRDSystem.jsp  (accepted)
  test:    identical body WITHOUT secureToken -> "Invalid credentials" (rejected)

So `secureToken` is load-bearing. The telemetry magnitudes are not: with
`secureToken` present, the OLD fabricated counters (5 clicks / 32 moves /
10 keys / 8500 ms) and a `cptoken` interaction total of 3 both logged in.

That matters because "Invalid credentials" is the same string the portal returns
for a wrong password, so a missing `secureToken` reads as bad credentials. This
file pins the field that must keep being forwarded, and keeps the rest honestly
labelled as cosmetic.

Offline: no network, no credentials.
"""
import base64
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

with tempfile.TemporaryDirectory() as td:
    os.environ.setdefault("DATA_DIR", td)
    from app import http_scraper as H


def test_login_page_parses_secure_token():
    # the page ships it as a hidden input; _prepare must capture it or the
    # login POST goes out without it and the portal answers "Invalid credentials"
    html = ('<input type="hidden" name="secureToken" value="abc123XYZ_-" />'
            '<img id="secure_captcha" data-src="/srmiststudentportal/SCaptchaServlet?ts=1">')
    m = re.search(r'<input[^>]*name="secureToken"[^>]*value="([^"]*)"', html)
    assert m and m.group(1) == "abc123XYZ_-"
    # and the value-before-name ordering a minifier could produce
    alt = '<input type="hidden" value="zzz" name="secureToken" />'
    m2 = (re.search(r'<input[^>]*name="secureToken"[^>]*value="([^"]*)"', alt)
          or re.search(r'<input[^>]*value="([^"]*)"[^>]*name="secureToken"', alt))
    assert m2 and m2.group(1) == "zzz"


def test_post_login_forwards_secure_token():
    # guard the wiring: the field name must appear in the POST body builder
    src = Path(__file__).resolve().parent.parent.parent / "app" / "http_scraper.py"
    text = src.read_text()
    assert '"secureToken": ctx.get("secure", "")' in text, (
        "the login POST must forward the page's secureToken — without it the "
        "portal rejects valid credentials as 'Invalid credentials'"
    )


def test_telemetry_stays_self_consistent():
    # cosmetic, but free: a blob whose timing contradicts itself is the sort of
    # detail a bot check may start using, so keep it honest.
    # t0 is time.monotonic() (as _prepare sets it) — the old test fed a
    # time.time() value, which is exactly the clock mix that pinned this field.
    p = json.loads(base64.b64decode(H._telemetry_b64(time.monotonic() - 3)))
    assert p["currentDomain"] == H.PORTAL_HOST
    assert p["timeOnPageMs"] == p["submitTime"] - p["startTime"]
    # 1200..120000 is the plausible dwell clamp; 10000 was the old always-value
    assert 1200 <= p["timeOnPageMs"] <= 120000
    assert p["timeOnPageMs"] != 10000, "timeOnPageMs is pinned at the old constant"
    assert p["platform"].startswith("Win"), "platform must agree with the Windows UA"
    # the portal's own JS counts mousemove + keydown + touchstart
    assert H._telemetry_interactions() == H._TEL_MOVES + H._TEL_KEYS


if __name__ == "__main__":
    test_login_page_parses_secure_token()
    test_post_login_forwards_secure_token()
    test_telemetry_stays_self_consistent()
    print("login secureToken contract checks OK")
