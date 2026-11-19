"""One runnable check for the telemetry bot-trap (prod outage 2026-11-19).

The SRM portal fingerprints `telemetryPayload`. A blob carrying
`currentDomain: "sp.srmist.edu.in"` is silently discarded: LoginServlet answers
200 with the untouched login page and no alert element, which the classifier
reported as "portal rate-limiting". Every other value — another host, empty,
null, or the key omitted — is processed normally and comes back with the portal
alert. Measured 2026-11-19 against the live portal: identical request, one key
flipped, 15597 B no-alert vs 16324 B with `Invalid credentials`.

Offline: no network, no credentials. Fails if the key is reintroduced.
"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

with tempfile.TemporaryDirectory() as td:
    os.environ.setdefault("DATA_DIR", td)
    from app import http_scraper as H


def test_telemetry_payload_omits_the_trapped_domain_key():
    payload = json.loads(base64.b64decode(H._telemetry_b64(0.0)))
    assert "currentDomain" not in payload, (
        "telemetryPayload must not carry currentDomain — the portal silently "
        "bounces the login on that exact value"
    )
    # still shaped like a browser session, not a stripped-down stub
    assert payload["userAgent"] == H.UA
    assert payload["platform"] == "Win32"
    assert isinstance(payload["submitTime"], int) and payload["submitTime"] > 0


if __name__ == "__main__":
    test_telemetry_payload_omits_the_trapped_domain_key()
    print("telemetry trap check OK")
