# 2026-11-19 — every login rejected: the telemetry did not look like a browser

## Symptom

Login failed for every account on production. Correct NetID and password, and
the captcha solver read the image correctly. The portal answered:

```
login attempt=1 reject=credentials portal_alert='Invalid credentials'
```

That is the same string the portal returns for a wrong password, so the app told
the user their credentials were wrong — which they were not. All 15 accounts
went stale; the newest successful sync was 2026-11-17T19:20Z.

## Root cause

`LoginServlet` cross-checks the `telemetryPayload` we POST against the request
and discards anything that does not look like a real browser session.
`_telemetry_b64()` fabricated an implausible one:

| field | fabricated (rejected) | real browser (accepted) |
|---|---|---|
| `currentDomain` | absent | `sp.srmist.edu.in` |
| `platform` | `Win32` | `Linux x86_64` |
| `timezoneOffset` | `-330` | `0` |
| screen | 1920x1080 | 1366x900 |
| `hardwareConcurrency` | 8 | 2 |
| `mouseClicks` / `mouseMovements` | 5 / 32 | 4 / 7 |
| `keystrokeCount` | 10 | 22 |
| `typingSpeedMs` | 8500 | 6108 |
| `canvasHash` | `-27fdeb33` (negative) | `563dae46` |
| `cptoken` interactions | `3` | clicks + keystrokes (26) |

Two tells were confirmed against the live portal:

* **`cptoken`'s third part must equal `mouseClicks + keystrokeCount`.** We sent a
  hardcoded `3` against counters claiming 15 interactions.
* **The counter magnitudes must be plausible**, and timing must be consistent
  (`timeOnPageMs == submitTime - startTime`).

Captured evidence: a headless Chromium driving the real page — typing with
keystroke delay, moving the mouse — produced a `LoginServlet` POST that the
portal answered with `HRDSystem.jsp`. Replaying that same request over plain
`urllib`, no browser at all, also returned `HRDSystem.jsp`. The browser
contributes nothing except the telemetry its own JS would compute.

## Correction to the first diagnosis

The first fix removed `currentDomain` entirely, on the theory that the literal
`"sp.srmist.edu.in"` was deny-listed. That theory came from a bisect that
varied one key while the rest of the blob stayed implausible. Corrected: the
real, accepted payload **contains** `currentDomain`; the rejection was the shape
and internal consistency of the whole blob, not that one key. That change
shipped as v2.12.2 and is superseded here.

The bisect table below is kept as the record of how the wrong conclusion was
reached — it is evidence about a *different* question (which payloads get
discarded outright versus evaluated) and not about which key is load-bearing:

| telemetryPayload | POST body | portal verdict |
|---|---|---|
| the blob `_telemetry_b64` produced | 15597 B, no alert | discarded |
| blob minus `currentDomain` | 16324 B, `Invalid credentials` | evaluated, rejected |
| the browser's real blob | 30091 B, `HRDSystem.jsp` | **accepted** |

Reading the middle row as "currentDomain is the trap" is exactly the mistake
this record exists to prevent: *evaluated* is not *accepted*.

## Fix

`app/http_scraper.py`:

* `_telemetry_b64()` emits the accepted shape, counters held as named constants
  (`_TEL_CLICKS`, `_TEL_MOVES`, `_TEL_KEYS`, `_TEL_TYPING_MS`, `_TEL_CANVAS`)
  with self-consistent timing.
* `_post_login()` builds `cptoken` from `_telemetry_interactions()`, so the
  interaction total can never drift from the counters again.
* `_prepare()` captures the page's `secureToken` hidden input; `_post_login()`
  forwards it — the one field a real browser sends that we never did.
* `silent_rejection` logs `untouched_login_page=` by comparing the response
  length against the page this attempt was prepared from.

`tests/unit/test_telemetry_trap.py` pins the shape, the timing consistency and
the `cptoken` = clicks + keystrokes invariant. Wired into the `unit` job.

## Verification

Through the app's own `http_scraper.fetch()` against the live portal, real
account:

```
login attempt=1 step=post final=HRDSystem.jsp hrdsystem=True bytes=30091
PORTAL_OK
ELAPSED 7.6s
OK: True
```

Courses 23, personal 24, marks 6 parsed. Before this change the same call
returned `bad_credentials`.

## Standing rules

* **"Invalid credentials" from this portal does not mean the password is
  wrong.** It is the generic rejection for a request the bot check disliked.
  Never tell a user their credentials are wrong off that string alone.
* **A fabricated fingerprint must be internally consistent.** Anything the page
  computes from real events — interaction counts, timing, canvas hash — must
  agree across every field that carries it, `cptoken` included.
* **Do not "tidy" the telemetry constants.** Their values are the difference
  between a working login and a 40-hour outage.
* **A bisect holding the other fields implausible finds the wrong key.** Vary
  one key from a known-GOOD baseline, not from a known-bad one.
* **A discarding trap answers `200` with the page we just fetched.** Compare
  body lengths before blaming the portal's mood.

## Deliberately not fixed

* The `playwright` fallback is not installed in the production image (no
  package, no browser binaries), so a broken HTTP path has no safety net. Its
  own change; the HTTP path works without it.
* `recaptchaToken` sits inside an HTML comment on the live page, so browsers
  never submit it. Not sending it is correct.
