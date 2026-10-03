# Login-rejection incident — observed 2026-09-30, recorded 2026-10-03

> **Status: FIXED and deployed.** PR #16 (fixes) + PR #18 (v1.5.0 trio), both merged;
> tag `v1.5.0`. Prod verified running the fixed code — inside the container,
> `_scrape_lock.acquire` is line 1014 and the `_check_rate` call is line 1030, i.e.
> the quota is counted *after* the lock, and `_portal_alert` / `_netid_retry_text`
> are both present.
> Verification: `tests/test_login_reject.py` (RED on pre-fix code, GREEN after) ·
> live `guide_server` 4 PASS / 0 FAIL · `verify76` 71/71 · full browser suites green.

## Symptom

Prod logs, container up 39h: 9 × `POST /api/login` → 2 ok, 3 × 401, 2 × 503, 2 × 429,
all inside a 9-minute window (16:44–16:53), plus an unexplained `/api/refresh` 503 at
07:43. Users saw *"login failed after 3 attempts — captcha unreadable"* and
*"Too many sync attempts for this account. Try again in 10 minutes."*

## Findings

### 1. A wrong password was reported as a captcha failure — `http_scraper._post_login`

Portal rejection bodies captured live (fabricated NetIDs, no student account touched):

| Portal response | verbatim alert | old classifier | new classifier |
|---|---|---|---|
| bad password | `Invalid login credentials … You have 2 out of 3 login attempts remaining.` | **captcha retry ×3** | `fail` → `invalid credentials` |
| bad captcha | `Invalid captcha.` | captcha retry | captcha retry (unchanged) |
| no alert | *(none)* | **captcha retry** (silent branch unreachable) | `fail` → silent rejection + cooldown |

The credentials branch matched `"invalid credentials"`, which is *not* in the portal's
message (the word `login` sits in the middle), and the fallback
`"captcha" in low and "invalid" in low` matched the login page's own markup —
`captcha` ×17 and `invalid` from Bootstrap `.invalid-feedback`. So every rejection read
as an invalid captcha, was retried 3× per request, and hit the portal's own
**3-attempts-per-NetID** lockout: **10 portal submissions for one account in 104 s**.

Same bug in the Playwright fallback (`_do_login` matched only `"invalid credentials"`).

### 2. Rejections that never reached the portal consumed the sync quota — `fetch_attendance`

`_check_rate()` ran **above** `_scrape_lock`, so a busy/cooldown/budget rejection still
consumed 1 of the account's 3 syncs per 10 minutes while touching the portal zero times.

Evidence: red run against the old code — 3 × `Sync in progress` → `counted=3` → the 4th
call returned 429 for an account that had **never synced**. Matches prod exactly: busy at
16:45:10, busy at 16:45:38 (during ng2776's sync, 16:45:32–16:45:39), one success at
16:47:12 — all inside the 600 s window → 429 at 16:53:24 after a single real sync.

The 429 also promised a flat "10 minutes" when the sliding window had ~2 minutes left.

### 3. Three silent paths made this undiagnosable

- `/api/refresh` logged no failure reason — prod 07:43 shows only `status=503`.
- Playwright's captcha-image-empty / OCR-empty early returns logged nothing.
- The classifier never logged the portal's message, so "wrong password" and
  "wrong captcha" were indistinguishable after the fact (and still would be).

### 4. A 0-byte captcha crashed the pipeline (07:43)

`SCaptchaServlet` answered `200` with `0 B`; ddddocr raised
`ImageProcessError: cannot identify image file`, which escaped as
`http pipeline crashed` and dropped the request into the Playwright fallback.

## Fixes

- **Classify on the portal's alert text.** New `_portal_alert()` extracts
  `<h6 class="alert-heading">Alert</h6>` and every rejection branch logs it
  (`reject=credentials` / `invalid_captcha … portal_alert=` / `silent_rejection …`).
  Exact phrases only: `invalid login credentials` → fail, `invalid captcha` → retry.
  Clients still get the fixed generic string (Login Flow UX Guide §5 — portal text is
  never relayed, no account-existence wording).
- **Lock → portal budget → cooldown → `_check_rate`.** A request that never ran costs
  nothing. `_netid_retry_text()` names the real remaining window.
- **Logging:** `api_refresh` failures log the same KV line as `api_login`; Playwright's
  silent early returns and its credentials branch now log (with the portal alert line).
- **0-byte / unreadable captcha** raises `HttpScraperError` (retried once) instead of
  crashing the pipeline.

## For future sessions

- **Never classify a portal rejection on the tokens `captcha` / `invalid`** — the login
  page's own markup contains both. `tests/test_login_reject.py` holds the verbatim
  bodies and deliberately still trips the old loose condition; AGENTS.md records it as a
  gotcha.
- The rate-limit docs (README table, SECURITY.md, CONTRIBUTING.md, AGENTS.md) now state
  that the per-netid cap counts only syncs that actually run.

## Not fixed (deliberate)

- The portal-budget message still says a flat "10 minutes" — its window genuinely is
  10 minutes and `guide_server` pins that literal.
- The portal-side account lock on `sg2935` (10 burned submissions) is outside this
  codebase; the student should check access to the real SRM portal.
