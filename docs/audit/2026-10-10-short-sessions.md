# 2026-10-10 — sessions die early, users re-login constantly

**Symptom** (user report): "the user sessions dont last long, like even when i am
using the opensrm webapp it is always asking me to re put the login creds" —
forced re-authentication within a single browsing session, repeatedly.

**Ground**: `SESSION_MAX_AGE` is 30 days (`app/app.py`), the cookie carries
`max_age=30d`, and read-time expiry prunes correctly — so TTL was never the
cause. Something was *deleting* sessions while they were young.

## Evidence (all captured from prod logs + read-only DB queries)

Log source: `/app/data/opensrm.log*` (container volume, survives deploys;
Oct 8/9 rotations concatenated with the current file into
`all_http_auth.txt`, 84,150 lines, window 2026-09-22 → 2026-10-10).

| Finding | Number | How |
|---|---|---|
| Logins in window | 78 across 8 accounts | `opensrm.auth login ok` lines |
| Main account (ng2776) logins | 58 from 13 distinct IPs | same, grouped by netid+ip |
| Re-logins preceded by the SAME account's own earlier login | 44 of 70 (36 different IP, 8 same IP) | kill-attribution script: for each login, the prior kill-capable event (own login / `/logout` 302) |
| Re-logins preceded by a real `/logout` 302 | 26 of 70 | same script |
| Session row age at check | ~1.1 days despite 30-day policy | read-only `SELECT` on `cookies` |
| Auth log lines for session deletion | 0 — the DELETE was silent | grepped `opensrm.auth` for any invalidation line: none exist |

## Root causes

1. **Single-session-per-account policy — `make_session_token()` ran
   `DELETE FROM cookies WHERE netid=?` on every login.** Logging in on the
   phone evicted the laptop's session and vice versa; the account ping-ponged
   between devices (13 IPs), each login killing the other device's still-young
   session. Attribution: 44 of 70 re-logins were this account's own earlier
   login. Deploy smoke mints (`make_session_token` inside the container) hit
   the same path with **no log line at all** — an invisible killer.
2. **`GET /logout` was state-changing and unguarded against speculation.**
   26 re-logins followed a real `/logout` 302, and prod sits behind Cloudflare
   Speed Brain's conservative speculation rules (`speculation-rules:
   "/cdn-cgi/speculation"`, prefetch of `/*`) — a touch-start-then-scroll or
   hover on the logout link can fire GET /logout with `Sec-Purpose: prefetch`
   and no navigation ever happens. The hover-reproduction was inconclusive in
   headless Chromium (eager control also didn't fire), so this is fixed as a
   guard, not claimed as the proven trigger of those 26. Real logouts also
   left **no auth log line**, so attribution had to be reconstructed from HTTP
   302s + cookie joins.

**Ruled out** (each with an executable proof, not reading):
- Cloudflare prefetch as the *observed* cause of the logged `/logout` hits:
  all 20 `/logout` events in the Oct 8–10 window were followed within 1.5s by
  login-page asset loads = real navigations; hover test fired no request.
- Frontend JS auto-logout: no `setInterval`/`setTimeout`/401-redirect to
  `/logout` anywhere in `app/static/`.
- Session TTL: `SESSION_MAX_AGE = 60*60*24*30`, enforced at read (audit
  2026-09-27), verified by test.

## Fixes (this PR)

1. `make_session_token()` — dropped the netid-wide DELETE; sessions are now
   concurrent per account, expired rows still pruned at mint and at read.
2. `GET /logout` — requests carrying `Sec-Purpose`/`Purpose` =
   prefetch|prerender get a `302 + Cache-Control: no-store` no-op (no delete,
   no cookie clear); real navigations unchanged.
3. **Logging that would have made this diagnosable**: `logout ok netid=... ip=...`
   and `logout ignored reason=speculation ip=...` auth lines (session
   invalidation previously produced zero auth-log output).
4. `tests/test_sessions.py` — 4/4: multi-device session survives a second
   login (red on old code: `first session died on second login`), expiry
   prunes at read, real logout deletes, prefetch logout is a no-op (red on old
   code: `prefetch killed the session`).

## Verification

- Red → green: `tests/test_sessions.py` 2/4 (both new contracts FAIL on
  unmodified code) → 4/4 after the fix.
- Full matrix: verify76 71/71, test_exams 67/67, test_login_reject,
  test_fault_handling 9/9, test_logging_telemetry 8/8, test_marks_view,
  test_attendance_view, test_feedback 50/50, push suites (32/25/16/19/37),
  test_tt_history, test_exams_view — all green.
- Gates: `uvx ruff check app/` clean, `uv lock --check` clean.

## Standing rules for future sessions

- **A login must never destroy another device's session.** Session eviction
  is only allowed: own logout, own expired token (read-time), own new login's
  expiry-prune of *expired* rows. If a "log out everywhere" feature is ever
  wanted, it must be an explicit action with its own auth-log line.
- **Any state-changing GET on this app must check `Sec-Purpose`/`Purpose`**
  before mutating (Cloudflare Speed Brain is active on the zone).
- **Session mutations must leave an auth-log line** — this incident cost a
  full day of log archaeology because the DELETE was silent.

## Deliberately left unfixed

- The 26 `/logout`-preceded re-logins: fixed at the guard level (prefetch can
  no longer trigger them) and now logged (`logout ok` / `logout ignored`), but
  whether the remaining real navigations were misclicks (logout sits next to
  refresh in the navbar), back-button replays, or deliberate logouts is not
  established — the new logging is what will answer that, post-deploy.
- No per-account session cap: an account could mint unbounded rows over 30
  days; prune-on-expiry bounds it in practice. Add a cap only if the cookies
  table ever grows noticeable.
