> **Identifiers were redacted on 2026-10-14.** Real NetIDs in this archive were replaced with fabricated ones; nothing else changed.

# 2026-10-12 — mid-scrape relogin never persisted the fresh session

**Symptom.** `portal_sessions` rows vanished after a sync whose log showed a
successful mid-scrape relogin; the next sync then started sessionless (extra
full login against the portal — burns the per-IP login budget and the shared
rate limit). Noticed while probing the timetable endpoint with a cached
session: `NO_SESSION: no cached session for zz9999` minutes after a
successful scrape.

**Evidence** (`docker logs opensrm`, 2026-10-12 00:32 IST):

```
DEBUG opensrm.portal session reuse hit netid=zz9999
DEBUG opensrm.portal jsp fetch done netid=zz9999 sizes={'9': 466, '13': 466, '126': 466}
INFO  opensrm.portal session expired mid-scrape netid=zz9999 — relogin
DEBUG opensrm.portal login attempt=1 step=post final=HRDSystem.jsp hrdsystem=True
...   (refetch + full scrape succeed: `http scrape complete ... total_ms=9670`)
```

DB check before/after: row existed at 00:20, `SELECT ... WHERE netid='zz9999'`
returned nothing at 00:34.

**Root cause.** `http_scraper.fetch` has two successful-login sites. The
start-of-fetch one did `portal_ok()` + `save_session()`; the mid-scrape
relogin branch called `clear_session()` then `_login()` and returned without
either — the fresh cookies lived only in the in-process jar, and the row it
had just cleared was never re-written.

**Fix.** Shared `_after_login(netid, jar, helpers)` (portal_ok + save +
`session saved` debug line) called from BOTH sites — the next successful
login of any kind persists and resets the fail counter.

**Verification.** `tests/test_relogin_save.py`: drives `fetch()` into the
relogin branch with a valid cached session (first login skipped, so any save
can only come from the relogin path) and stubbed portal I/O. Pre-fix run:
3/6, `save_session never fired after relogin (0 saves)`. Post-fix: 6/6.
Suites: `test_sessions` 5/5, `test_login_reject` ok, `test_fault_handling`
9/9, `verify76` 71/71, `ruff check app/` clean.

**Standing rule.** Every site that completes a portal login must route
through `_after_login`; a login-success path that skips it recreates this bug.
A `clear_session` in a retry branch must be paired with a save on the success
path that follows it.

**Deliberately not fixed.** The cached-session probe's HRDSystem validity
check can pass on a dead session (youLogin bounce served with HTTP 200 at the
HRDSystem URL) — probe-script level, already documented in
`opensrm-webapp/scripts/probe_with_cached_session.py`.
