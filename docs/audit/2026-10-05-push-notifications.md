# 2026-10-05 — Web Push class reminders: build audit

Scope: feature branch `feat/push-notify` (commits 0099cfe..HEAD, PR #23).
Feature reference: [../push.md](../push.md).

## What was checked against real behaviour (not just read)

- **Location-wipe claim (from the brief): CONFIRMED and fixed.**
  `api_save_timetable()` deleted + re-inserted slots without `location`;
  proven with a test on a DB copy (`Test Hall` → `''` after a no-op save).
  Fixed in commit 1 (preserve when day/period/subject unchanged, tested in
  `test_tt_history.py` — 18/18). Live DB (snapshotted before read per
  homelab-backup-management): 1 group / 30 slots; labs carry rooms
  (`Lab C-4/5`, `Lab C-6/7`, `Lab C-8/9`), lectures empty; **zero editor
  saves so far**, so no live data had been wiped yet.
- **Real pywebpush → FCM round trip** (test_push_ui): VAPID-signed,
  RFC 8291-encrypted POST accepted by FCM far enough to classify the
  (nonexistent) token as dead → 410 → subscription cleanup. Proves key
  formats, signing and encryption end to end without a device.
- **Service worker handlers in real Chromium** (test_push_sw): push always
  notifies (incl. malformed payload), block tag applied, receipt POST lands
  in `push_events`, notificationclick resolves.
- **Cloudflare vs cron-job.org**: zone probed with a non-browser POST → 200,
  no challenge; no custom WAF rules; rate limit 5 req/10 s/IP ≫ 1 tick/min.
  Bot Fight Mode is not API-readable (empirical probe only).
- **cron-job.org timeout/jitter: NOT yet observed** — no account access.
  FAQ-documented ~30 s timeout; real numbers to be read from their
  execution log (last 50 runs, ~2 days retention) after the first live runs.

## Tooling limitations hit (documented in tests)

- Playwright's Chromium has **no push service** (built without Google API
  keys) and blocks Push API in incognito contexts → `pushManager.subscribe`
  cannot run in CI; the UI test stubs only the browser-side subscription,
  everything else (server, sender, FCM, SW) is real.
- Two gunicorn processes on one *fresh* SQLite race `schema_version`
  inserts — pre-existing (prod runs a single container); the DUT runner
  staggers boots.

## Surprise for the brief's snapshot (deltas vs 2026-10-04 read)

- `test_tt_history` had 16 checks before this branch (brief implied 76+16;
  now 18 with the location-preservation checks).
- README's architecture diagram pins the SW cache name (verify76 L37/D58) —
  v15 bump required the README edit, not only `test_sw.py`.
