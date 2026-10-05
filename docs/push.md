# Class reminders (Web Push)

Students install OpenSRM as a PWA and get a push notification a few minutes
before each class (default 10): subject, start time, and room when the
timetable has one. Works with the app closed. Zero ongoing cost: no Firebase,
no paid services — only a cron-job.org free account calling one endpoint.

Docs: this file is the feature reference · [push-device-test.md](push-device-test.md)
is the plain-language iOS tester guide.

## How a reminder travels

```
cron-job.org ──POST /internal/push/tick (header X-Push-Tick)──▶ Flask
  tick (stateless, 20 s internal deadline):
    1. load enabled subscriptions ──┐
    2. load current timetable rows  ├─▶ pure due_reminders(now_ist, …)
    3. load sent-log for today      ─┘      start−lead ≤ now < start, unlogged
    4. claim each due block (ON CONFLICT DO NOTHING, at-most-once)
    5. pywebpush → vendor endpoint (FCM / Apple / Mozilla)  [urgency high,
       TTL = seconds until block start — a stale reminder never lands late]
browser (app closed) wakes service worker ──▶ showNotification (tag = block)
test push ──▶ SW also POSTs /api/push/receipt (proof of device arrival)
```

Nothing is precomputed or queued. Every tick recomputes from live data, so a
timetable edit at 11:19 changes what goes out at 11:10-… — the due window
stays open until the class starts.

## Storage (migration 11)

Push tables live behind `app/push_store.py` — plain portable SQL (no
SQLite-only syntax), integer epochs, `ON CONFLICT … DO NOTHING` + rowcount,
one `get_conn()`. Deliberately separate from the rest of the app so the
feature can move to Postgres/libSQL on serverless without a full migration.

- `push_subscriptions` — one row per device endpoint (UNIQUE); a re-subscribe
  from the same endpoint **rebinds the netid** (shared phone never notifies
  the previous user). Holds `lead_minutes`, `enabled`, fail counters, last
  push-service status, short UA label.
- `push_sent_log` — UNIQUE(subscription, local_date, block_start,
  subject_code). Status flow: `claimed → sent | failed (retried ≤3 while the
  window is open) | skipped | orphaned`.
- `push_events` — DB-backed rate limits + test receipts (process-local dicts
  would die on serverless).

### Delivery semantics (the important bit)

- **At-most-once.** A row is *claimed first* (`ON CONFLICT DO NOTHING`,
  only the insert winner sends), then the outcome is recorded. A crash
  between claim and result leaves `claimed` with no outcome; after 120 s the
  next tick marks it `orphaned` and **never retries** it — a lost reminder
  beats a double beep.
- **Retries** only for rows whose send *failed* (5xx/timeouts), only while
  `now < block start`, at most 3 attempts.
- **404/410 from the push service** = dead subscription: row deleted, sent-log
  records `skipped`; the UI tells the user to toggle reminders off/on.
- **Subject change** at the same time = new key = fresh reminder. A room-only
  change does not re-notify.
- Claimed but window already past? Never sent — `due_reminders` re-checks
  `now < start` at send time.

### Block collapsing (one reminder per class block)

Same `subject_code`, adjacent periods, never merged across a break or lunch
divider. The reminder fires at the block's **first** period with the block's
**end** time; the room line prints only when `location` is non-empty (never a
"Room not set" placeholder). Lab vs lecture comes straight from what the
timetable stores: live DB (snapshot 2026-10-05) — labs carry rooms
(`Lab C-4/5`, `Lab C-6/7`, `Lab C-8/9`), lectures have an empty location.

## Environment variables

| Var | Default | Meaning |
|-----|---------|---------|
| `PUSH_ENABLED` | off | Master switch. Off = tick still computes and logs (dry audit), never sends |
| `PUSH_DRY_RUN` | off | Log what would be sent while "enabled"; no claims, no sends |
| `PUSH_ALLOW_NETIDS` | empty | Comma list; when set, only these netids are sent to (others are counted `held`) |
| `PUSH_TICK_SECRET` | — | Header secret for `/internal/push/tick`; missing → every tick 401 |
| `VAPID_PUBLIC_KEY` | — | base64url P-256 public key (safe to display) |
| `VAPID_PRIVATE_KEY` | — | SECRET. Missing → status endpoint says "not configured", feature off |
| `VAPID_SUBJECT` | — | Real `mailto:` — VAPID `sub` claim; Apple rejects anything else |

Generate once with `scripts/generate_push_keys.py`; append to lab
`/docker/.env` (only if missing — replacing the VAPID pair invalidates every
subscription) and pass through `docker-compose.yml` as `${VAR}`. The app
never generates or falls back to generated keys at runtime. **All three
secrets must be copied into Vercel Production env vars unchanged when the
app moves.**

## cron-job.org job (enter by hand — secret value lives in `/docker/.env`)

| Field | Value |
|-------|-------|
| Name | `opensrm-push-tick` |
| URL | `https://srm.200871.xyz/internal/push/tick` |
| Method | POST (empty body is fine) |
| Custom header | `X-Push-Tick: <value of PUSH_TICK_SECRET from lab /docker/.env — never paste it anywhere else>` |
| Schedule | Every 1 minute |
| Request timeout | 30 s (server self-limits to 20 s; overlap is harmless) |
| Failure notification | ON — e-mail after ~3 consecutive failures |
| Enable | Only **after** `PUSH_TICK_SECRET` is deployed — an unset secret = permanent 401s |

Observed/constraints (FAQ + live probes, 2026-10-05): jobs run at most once
per minute; the last 50 executions (with duration) are kept ~2 days — use
that log to read the *real* timeout and jitter after the first live runs
(numbers not yet observed; report them after deploy). Cloudflare was probed
with a non-browser POST against the zone: **no WAF challenge** (no custom
rules, managed ruleset, security level `medium`, rate limit 5 req/10 s/IP —
1 tick/min is far under). If real runs ever get challenged, add the minimal
skip rule for cron-job.org's IPs to the Cloudflare WAF and note it here.

Tick response is JSON counts only:
`{"ok": true, "mode": "off|dry-run|live", "due": N, "claimed": N, "sent": N,
"failed": N, "dead": N, "held": N, "audited": N, "skipped_deadline": N,
"orphaned": N}` — logged through `log_with_kv` as `opensrm.push`. Every send
also logs netid, push-service host, HTTP status. Endpoint URLs are never
logged (only a 12-char hash prefix).

## Rollout (in order)

1. Deploy with `PUSH_ENABLED` unset (off). Snapshot live DB + back up
   `docker-compose.yml` first; follow "Prod deploy + smoke" in AGENTS.md.
   Add the env vars to compose + `/docker/.env` (keys generated once).
2. Point cron-job.org at the tick; watch logs — `mode: "off"` ticks should
   show real `audited` counts. Compare logged due-list against the real
   timetable.
3. `PUSH_ENABLED=1` + `PUSH_DRY_RUN=1` → same audit, claims still not made.
4. `PUSH_ALLOW_NETIDS=<yours>` only, dry-run off → your devices first.
5. Android broadly, then iOS once `push-device-test.md` comes back green.
   Do not touch `flights.200871.xyz`.

## Known limitations (documented, deliberately not solved)

- **Holidays/cancellations are not modelled anywhere** — reminders fire on
  holidays. No calendar invented.
- **The shared timetable is editable by any student in the section** — a bad
  edit produces bad reminders for everyone; every change is in the section's
  Edit history (`timetable_edit_log`). A "timetable changed" notification is
  a possible later feature, out of scope.
- **Delivery timing is best effort** and OEM battery managers (Xiaomi, Oppo,
  Vivo, some Samsung) can delay it — the UI shows a short tip; TTL caps
  lateness at class start.
- **No resolvable `group_key` or timetable** → the card shows a
  "no timetable found" style state and no reminders are produced.
- Push reads only local tables — **never the portal** (no scrape cost).
- iOS web push needs iOS/iPadOS 16.4+ *and* Home-Screen install; iOS is
  **unverified** until the friend test in push-device-test.md passes.

## Moving to Vercel (when the app goes serverless)

The push feature was built to survive the move unchanged:

- **Env vars**: copy `PUSH_ENABLED`, `PUSH_DRY_RUN`, `PUSH_ALLOW_NETIDS`,
  `PUSH_TICK_SECRET`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
  `VAPID_SUBJECT` into Vercel Production — values must stay identical.
- **Database**: push tables already sit behind `app/push_store.py` — point
  `get_conn()` at Postgres/libSQL; plain SQL, no SQLite-only features (a test
  enforces this).
- **Scheduler**: cron-job.org job URL switches to the new deployment URL —
  header/method/schedule unchanged.
- **Stateless**: no module-level state, no threads outliving a request, no
  filesystem reads on the push path; the tick's 20 s deadline and at-most-once
  claims make overlapping/cold-started functions harmless.
