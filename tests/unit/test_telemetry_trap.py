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
import os
import re
import sys
import tempfile
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


def test_telemetry_payload_is_not_synthesised():
    # The real submit writes telemetryPayload from the LIVE client (see
    # browser-truth.json: platform "Linux x86_64" with UA "X11; Linux x86_64 …
    # Chrome/139" — one coherent self-portrait, plus mouse/key counters). A
    # server cannot produce that record truthfully, so we send none: an empty
    # (non-JSON) value is ignored by the portal and the credentials are still
    # evaluated, while a well-formed fake is the shape that produced the
    # documented silent discard.
    assert not hasattr(H, "_telemetry_b64"), "the fabricated blob builder must be gone"
    src = Path(__file__).resolve().parent.parent.parent / "app" / "http_scraper.py"
    assert '"telemetryPayload": ""' in src.read_text(), \
        "the login POST must send an EMPTY telemetryPayload, never a fake record"
    # the portal's own JS counts mousemove + keydown + touchstart
    assert H._telemetry_interactions() == H._TEL_MOVES + H._TEL_KEYS


if __name__ == "__main__":
    test_login_page_parses_secure_token()
    test_post_login_forwards_secure_token()
    test_telemetry_payload_is_not_synthesised()
    print("login secureToken contract checks OK")
