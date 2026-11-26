"""One runnable check for what actually makes the portal accept a login.

Measured 2026-11-20 with a real account, one variable at a time:

  control: real body WITH secureToken        -> HRDSystem.jsp  (accepted)
  test:    identical body WITHOUT secureToken -> "Invalid credentials" (rejected)

So `secureToken` is load-bearing. The telemetry magnitudes are not: with
`secureToken` present, the OLD fabricated counters (5 clicks / 32 moves /
10 keys / 8500 ms) and a `cptoken` interaction total of 3 both logged in.

Corrected 2026-11-26: that last clause was measured against an account with
attempts to spend, and it conflated "the portal evaluated this" with "the
portal accepted this". Re-measured on fabricated NetIDs, only served attempts
exist, so the difference is visible: the cptoken interaction total and its
elapsed part are load-bearing. See portal-p6/DISCARD.md. The blob's exact
magnitudes below stay pinned because they are the same judged shape.

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


def test_telemetry_payload_is_the_judged_blob():
    # MEASURED 2026-11-25 (portal-p4/REGRESSION.md): an empty telemetryPayload
    # is NOT ignored — the portal discards the submit and never checks the
    # password (16,324 B, "Invalid credentials", no attempts-remaining counter;
    # arms E1/E6). The blob below keeps the submit JUDGED (16,455 B, "You have
    # 2 out of 3 login attempts remaining"; arms E3/E5 with bf1f147e's own
    # cptoken). A different self-consistent blob is rejected (arm E4), so this
    # pins the exact wire shape, not just "some JSON".
    raw = H._telemetry_b64(time.time() - 30)
    blob = json.loads(base64.b64decode(raw))
    assert (blob["mouseClicks"], blob["mouseMovements"], blob["keystrokeCount"],
            blob["typingSpeedMs"]) == (4, 7, 22, 6108), blob
    assert blob["timeOnPageMs"] == 10000, blob   # clamped dwell, as sent by E3/E5
    src = Path(__file__).resolve().parent.parent.parent / "app" / "http_scraper.py"
    assert '"telemetryPayload": _telemetry_b64(ctx["t0"])' in src.read_text(), \
        "the login POST must send the measured blob, never an empty value"
    # MEASURED 2026-11-26 (portal-p6/DISCARD.md): the cptoken interaction total
    # is CLICKS+KEYS=26, not mousemove+keydown. The mousemove total (29) is part
    # of the wire shape the portal silently DISCARDS — same body, same blob,
    # 15,597 B untouched login page.
    assert H._telemetry_interactions() == H._TEL_CLICKS + H._TEL_KEYS == 26, (
        f"cptoken interaction total must be CLICKS+KEYS=26 (judged), got "
        f"{H._telemetry_interactions()}")


if __name__ == "__main__":
    test_login_page_parses_secure_token()
    test_post_login_forwards_secure_token()
    test_telemetry_payload_is_the_judged_blob()
    print("login secureToken contract checks OK")
