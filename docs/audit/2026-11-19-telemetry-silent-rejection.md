# 2026-11-19 — every login silently discarded by the portal

## Symptom

Login failed for every account on production, with no usable error. The user
supplied a correct NetID and password, and the captcha solver read the image.
The app reported:

```
silent_rejection (no HRDSystem, no error text) portal_alert='' bytes=15596
refresh failed netid=… error=SRM portal rejected the login without an error
```

That message says "rate-limiting". It was wrong. All 15 accounts were stale:
the newest successful sync was 2026-11-17T19:20Z, roughly 40 hours earlier.

## Evidence

The pod log showed the POST answering with a byte-identical copy of the login
page:

```
GET  youLogin.jsp      -> 200 15597B
GET  SCaptchaServlet   -> 200 1089B   (real PNG, OCR produced 6 characters)
POST LoginServlet      -> 200 15597B  <-- same size as the page we just fetched
```

A plain `urllib` POST of the same field set, from the same host and IP, got a
proper answer instead: 16324 B with `<h6 class="alert-heading">Alert</h6>` and
`Invalid credentials`. So the network, the source IP, the URL, the method, the
headers and the captcha fetch were all fine. One field differed:
`telemetryPayload`.

Bisecting that blob against the live portal, one key at a time, with everything
else held identical:

| telemetryPayload | POST body | portal verdict |
|---|---|---|
| the blob `_telemetry_b64` produced | 15597 B, no alert | discarded |
| empty | 16324 B, `Invalid credentials` | processed |
| `"x"` | 16324 B, `Invalid credentials` | processed |
| blob minus `currentDomain` | 16324 B, `Invalid credentials` | processed |
| `{"currentDomain": "sp.srmist.edu.in"}` | 15597 B, no alert | discarded |
| `{"currentDomain": "srmist.edu.in"}` | 16324 B, `Invalid credentials` | processed |
| `{"currentDomain": ""}` | 16324 B, `Invalid credentials` | processed |
| `{"currentDomain": null}` | 16324 B, `Invalid credentials` | processed |

`canvasHash`, `webdriver`, `startTime`, `userAgent`, `mouseClicks` and the rest
of the blob were each removed in turn and none of them changed the outcome.

## Root cause

The portal now fingerprints `telemetryPayload`, and the literal value
`currentDomain: "sp.srmist.edu.in"` is on a deny-list. When it sees that value
it answers `200 OK` with the unmodified login page, no alert element, and no
session — instead of evaluating the credentials.

Because a discarded request and a rate-limited request look the same to
`_post_login` (no `HRDSystem`, no alert text), the classifier read every one of
these as `portal_cooldown`. That fed `PortalHealth`, which is global: three
discards armed a 5-minute pause that refused every other account too, and the
user was told the portal was throttling our server.

Two traps made this expensive:

1. `silent_rejection` claimed "rate-limiting" without checking whether the
   portal had answered at all.
2. Nothing recorded that the response was the untouched login page, which is the
   one fact that separates "the portal judged you" from "the portal ignored
   you".

## Fix

`app/http_scraper.py`:

* `_telemetry_b64()` no longer emits `currentDomain`. Every other key stays, so
  the payload is still shaped like a browser session.
* The `silent_rejection` log line now carries `untouched_login_page=`, computed
  by comparing the response length against the login page this attempt was
  prepared from.

`tests/unit/test_telemetry_trap.py` fails if the key comes back, and is wired
into the `unit` job in `tests.yml`.

## Verification

In the container, through the app's own `http_scraper.fetch()` with a
fabricated NetID:

| | before | after |
|---|---|---|
| log line | `silent_rejection … bytes=15596` | `reject=credentials portal_alert='Invalid credentials'` |
| typed kind | `portal_cooldown` | `bad_credentials` |

`bad_credentials` is the correct answer for a NetID that does not exist. The
pipeline once again sends a request the portal evaluates.

## Standing rules

* **A discarding trap answers `200` with the page we just fetched.** Compare
  body lengths before believing any diagnosis that blames the portal's mood.
* **Do not re-add a fabricated field to a bot-defended form.** Every key we
  invent is a signature the other side can blocklist. Send only what the flow
  needs.
* **`silent_rejection` is not a rate limit.** It means the portal said nothing,
  which needs its own explanation every time.

## Deliberately not fixed

* `secureToken` and `recaptchaToken` exist on the live form and our POST does
  not send them. Tested 2026-11-19: sending them empty, and omitting them, both
  produce a normal processed response. No action until the flow needs them.
* The captcha-value read still has no independent verification before submit.
  That is a separate change.
