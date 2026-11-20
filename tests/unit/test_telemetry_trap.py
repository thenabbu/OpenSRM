"""One runnable check for the login telemetry the portal accepts.

Background (2026-11-19): a genuine browser login, captured over CDP, carried a
telemetry blob the portal ACCEPTED and answered with HRDSystem. That shape is
the contract. A fabricated-looking blob gets the same valid credentials
answered with "Invalid credentials" — indistinguishable from a wrong password,
which is what made this outage take 40 hours to diagnose.

Two invariants cost us that outage and are what this file pins:
  1. the counters must be the plausible browser magnitudes (not 5/32/10/8500),
  2. cptoken's interaction total must equal the same clicks+keystrokes.

Offline: no network, no credentials.
"""
import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

with tempfile.TemporaryDirectory() as td:
    os.environ.setdefault("DATA_DIR", td)
    from app import http_scraper as H


def test_telemetry_is_browser_shaped():
    p = json.loads(base64.b64decode(H._telemetry_b64(time.time() - 3)))
    # the domain key is part of a real payload; dropping it was the earlier
    # (wrong) theory, so guard against "tidying" it away again
    assert p["currentDomain"] == H.PORTAL_HOST
    assert p["platform"] == "Linux x86_64"
    assert (p["screenWidth"], p["screenHeight"]) == (1366, 900)
    assert p["hardwareConcurrency"] == 2 and p["deviceMemory"] == 8
    # interaction magnitudes a real browser produces
    assert p["mouseClicks"] == H._TEL_CLICKS
    assert p["keystrokeCount"] == H._TEL_KEYS
    assert p["typingSpeedMs"] == H._TEL_TYPING_MS
    # a signed/negative canvas hash was part of the rejected blob
    assert p["canvasHash"].isalnum() and not p["canvasHash"].startswith("-")
    # timing must be self-consistent: page time is the submit/start delta
    assert p["timeOnPageMs"] == p["submitTime"] - p["startTime"]
    assert 1200 <= p["timeOnPageMs"] <= 10000


def test_cptoken_interaction_total_matches_telemetry():
    # _post_login encodes clicks+keystrokes as cptoken's third part; if these
    # ever diverge the portal reads the mismatch
    assert H._telemetry_interactions() == H._TEL_CLICKS + H._TEL_KEYS


if __name__ == "__main__":
    test_telemetry_is_browser_shaped()
    test_cptoken_interaction_total_matches_telemetry()
    print("telemetry contract checks OK")
