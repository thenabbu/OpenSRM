# Class reminders (Web Push)

Students install OpenSRM as a PWA and get a push notification a few minutes
before each class (default 10): subject, start time, and room when the
timetable has one. Works with the app closed. Zero ongoing cost: no Firebase,
no paid services — only a scheduled job calling one endpoint every minute.

Docs: this file is the feature reference · [push-device-test.md](push-device-test.md)
is the plain-language iOS tester guide.

## How a reminder travels

```
tick scheduler ──POST /internal/push/tick (header X-Push-Tick)──▶ Flask
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
  the previous user). Holds `lead_minutes`, `enabled`, per-type prefs
  (`notify_reminders`, `notify_exams`), fail counters, last
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

Generate once with `scripts/generate_push_keys.py`; append to the project
env file `/docker/opensrm/.env` (compose interpolates only from it — see the
compose gotcha below; only add if missing — replacing the VAPID pair
invalidates every subscription).

**Compose gotcha (bit us on first deploy):** docker compose interpolates
`${VAR}` from the **project** env file `/docker/opensrm/.env`, *not* from the
master registry `/docker/.env`. A var present only in the master registry
arrives as an empty string — the tick then 401s silently on its own secret.
Keep the seven push vars in **both** files (same pattern as
`SRM_PROXY_TOKEN`). The app
never generates or falls back to generated keys at runtime. **All three
secrets must be copied into Vercel Production env vars unchanged when the
app moves.**

## Tick scheduler (live: cron on oclab)

The tick is fired by a scheduled job that POSTs the endpoint below every
minute. **The scheduler is the oclab host** — the Oracle box that runs
production. `/etc/cron.d/opensrm-push-tick` runs
`/usr/local/bin/opensrm-push-tick.sh` once per minute as root. The script
reads `PUSH_TICK_SECRET` from `/docker/opensrm/.env`, POSTs the endpoint, and
appends one line per attempt to `/var/log/opensrm-push-tick.log`. Both files
are copied from `ops/oclab/` in this repo, so a rebuilt host gets them back.

The box that runs the app also drives it. That removes the two earlier
schedulers and their failure modes: the Hermes cron job whose host could go
away, and the cron-job.org job that stops after 25 consecutive failures.

- The Hermes cron job `opensrm-push-tick` (id `4352c6d4be31`) was removed on
  2026-11-27, together with its script `/opt/data/scripts/push-tick.sh` and
  its log.
- The cron-job.org job `opensrm-push-tick` (id `8744871`) stays, disabled, as
  the fallback for a case where the oclab host is the thing that broke.

Alerting does not depend on the scheduler. The handler stamps
`opensrm_push_tick_last_success_timestamp_seconds` on every successful tick.
The Prometheus rule `OpenSRMPushTickStale` fires when that stamp is more than
300 s old for 5 m. Alertmanager sends the alert to ntfy.

| Field | Value |
|-------|-------|
| Script | `/usr/local/bin/opensrm-push-tick.sh` (repo: `ops/oclab/opensrm-push-tick.sh`) |
| Cron file | `/etc/cron.d/opensrm-push-tick` (repo: `ops/oclab/opensrm-push-tick.cron`) |
| URL | `https://srm.200871.xyz/internal/push/tick` |
| Method | POST (empty body is fine) |
| Custom header | `X-Push-Tick: <value of PUSH_TICK_SECRET from /docker/opensrm/.env — never paste it anywhere else>` |
| Schedule | Every minute |
| Request timeout | 25 s on the client (`curl -m 25`). The server self-limits to 20 s, so overlap is harmless |
| Log | `/var/log/opensrm-push-tick.log`, one line per attempt (`time http_code json`), trimmed to the last 10 000 lines |
| Exit code | 0 only on HTTP 200. Nothing reads the code. The log line is the record |
| Enable | Only **after** `PUSH_TICK_SECRET` is deployed. An unset secret means permanent 401s |

To confirm that the tick runs, read the log on the box:

```bash
ssh oracle 'sudo tail -3 /var/log/opensrm-push-tick.log; systemctl is-active cron'
```

was probed with a non-browser POST against the zone: **no WAF challenge** (no
custom rules, managed ruleset, security level `medium`, rate limit 5 req/10
s/IP — 1 tick/min is far under). If real runs ever get challenged, add the
minimal skip rule for the scheduler's IPs to the Cloudflare WAF and note it
here.

Tick response is JSON counts only:
`{"ok": true, "mode": "off|dry-run|live", "due": N, "claimed": N, "sent": N,
"failed": N, "dead": N, "held": N, "audited": N, "skipped_deadline": N,
"orphaned": N}` — logged through `log_with_kv` as `opensrm.push`. Every send
also logs netid, push-service host, HTTP status. Endpoint URLs are never
logged (only a 12-char hash prefix).

## Rollout (in order)

1. Deploy with `PUSH_ENABLED` unset (off). Snapshot live DB + back up
   `docker-compose.yml` first; follow "Prod deploy + smoke" in AGENTS.md.
   Add the env vars to `/docker/opensrm/.env` (keys generated once).
2. Install `ops/oclab/opensrm-push-tick.sh` and its cron file (see "Tick
   scheduler" above); watch logs — `mode: "off"` ticks should show real
   `audited` counts. Compare logged due-list against the real timetable.
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
- **Scheduler**: the tick job's URL switches to the new deployment URL —
  header/method/schedule unchanged (works for the oclab cron job or any
  hosted scheduler alike).
- **Stateless**: no module-level state, no threads outliving a request, no
  filesystem reads on the push path; the tick's 20 s deadline and at-most-once
  claims make overlapping/cold-started functions harmless.
