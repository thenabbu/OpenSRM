# Runbook — build, deploy, rollback, restore, rotate, damp

Operator guide for a self-hosted OpenSRM. Every lab/infrastructure claim was
verified live on 2026-10-16 with the command shown next to it; re-run the
command before trusting the claim after any infra change. Code claims are read
from `main` at 4ef16cb (v1.25.0).

## Where things live

| Thing | Where | Verified by |
|---|---|---|
| Repo | `github.com/thenabbu/OpenSRM`, `main` only | `gh pr list` / `git log origin/main` |
| Compose project | `/docker/opensrm/` on the lab host — `docker-compose.yml` + project env file `.env` (the ONLY env file compose interpolates for this project) | `ssh lab 'ls -la /docker/opensrm/'` |
| Container | `opensrm`, bound `127.0.0.1:8083` + `172.31.0.1:8083` (cloudflared gateway) → container 8080; never 0.0.0.0 — CF-only access | `ssh lab 'docker port opensrm'` |
| Data | named volume `opensrm_opensrm-data` → `/app/data` (`srm.db`, `fernet.key`, `opensrm.log`) | `ssh lab 'docker exec opensrm ls /app/data'` |
| Daily snapshots | `/data/ssd120/backups/opensrm/srm.YYYYMMDD.snapshot.db.gz`, taken ~03:0x IST, 7 kept | `ssh lab 'ls -1t /data/ssd120/backups/opensrm/'` |
| Push tick | Hermes-host cron job `opensrm-push-tick` → `/opt/data/scripts/push-tick.sh` → `POST /internal/push/tick`; success log `/opt/data/cron/output/push-tick.log` | see [Push tick](#push-tick-scheduler-alerting-dead-man) |
| Edge | Cloudflare tunnel → `srm.200871.xyz` | `ssh lab 'docker exec opensrm env'` + CF dashboard |

Note the two env files: the lab also keeps a master secret registry at
`/docker/.env`, but **compose never reads it for this project** — a `${VAR}`
that exists only there arrives empty. Every knob below goes into
`/docker/opensrm/.env`.

## Build

CI builds every green `main` push: `lint` + `tests` (unit/docker/e2e) gate the
publish job (`.github/workflows/build.yml`, `needs: [lint, tests]`), which
pushes `ghcr.io/thenabbu/opensrm` as `:latest` + `:<VERSION>` (from the
`VERSION` file) + `:<short-sha>`, with OCI `version`/`revision` labels
(verified: `git show origin/main:.github/workflows/build.yml`; live labels on
the running container: `docker inspect opensrm --format
'{{json .Config.Labels}}'` → `org.opencontainers.image.version: 1.23.0`).
A red suite therefore blocks the image; there is no build step in the image
itself beyond the multi-stage Dockerfile (CDN assets, no frontend bundler).

Deploy is **manual** — no watcher exists, by maintainer decision
(CONTRIBUTING.md "Deploy").

## Deploy

**Sequence: sync the compose file FIRST, then pull.** `docker compose pull`
never touches the compose file, so every compose-level feature the repo
documents (tag pinning, `FERNET_KEYS`, `SYNC_MIN_INTERVAL_S`,
`SQLITE_JOURNAL_MODE`, the `/healthz` healthcheck, container hardening) is a
no-op until the live file matches the repo copy. On 2026-10-16 the live file
predates v1.24.0 (verified: `ssh lab 'grep -n image:
/docker/opensrm/docker-compose.yml'` → hardcoded `:latest`, no `${OPENSRM_TAG}`
— so the documented rollback below did not work until this sync).

```bash
# 0. Snapshot first whenever the release carries migrations (see Restore for
#    the drill). Recipe pinned in SECURITY.md "Key rotation" step 1 — an
#    online .backup through the container (no root needed):
ssh lab 'docker exec opensrm python -c "import sqlite3; s=sqlite3.connect(\"/app/data/srm.db\"); d=sqlite3.connect(\"/app/data/srm.predeploy.snapshot.db\"); s.backup(d); d.close(); s.close(); print(\"snapshot ok\")"'

# 1. Sync the compose file from a repo checkout (backup the old one first —
#    the .bak-<stamp> pattern already used on the lab):
ssh lab 'cp /docker/opensrm/docker-compose.yml /docker/opensrm/docker-compose.yml.bak-$(date +%Y%m%d-%H%M%S)'
scp docker-compose.yml lab:/docker/opensrm/docker-compose.yml

# 2. Make sure the knobs you expect are in the PROJECT env file:
ssh lab 'grep -c "^PUSH_ENABLED=" /docker/opensrm/.env'   # etc.

# 3. Pull + recreate + smoke:
ssh lab 'cd /docker/opensrm && docker compose pull && docker compose up -d'
bash scripts/post_deploy.sh   # from the checkout: prod-image SHA == main,
                              # edge purge + byte-identity, authenticated render
```

Post-deploy sanity (from AGENTS.md "Prod deploy + smoke"):
`GET https://srm.200871.xyz/login` → 200 with HSTS on the `cf-ray` path;
`GET /healthz` → 200 `{"status":"ok"}` (the endpoint the compose healthcheck
polls; its request lines are DEBUG at INFO level, so their absence from
`docker logs` means the log level, not a dead probe — check
`docker inspect opensrm --format '{{.State.Health.Status}}'`).

## Rollback

CI publishes `:<VERSION>` next to `:latest`, so any released version can be
pinned (verified: `git show origin/main:.github/workflows/build.yml` tag
rules; images that exist for the lab: `:1.23.0` = what ran before this
release, `:1.24.0`, `:1.25.0`, plus `:<short-sha>`).

```bash
ssh lab 'echo "OPENSRM_TAG=1.24.0" >> /docker/opensrm/.env'   # PROJECT env file
ssh lab 'cd /docker/opensrm && docker compose pull && docker compose up -d opensrm'
# to ride :latest again: delete the OPENSRM_TAG line, pull, up -d.
```

Prerequisite: the live compose file must carry the
`image: ghcr.io/thenabbu/opensrm:${OPENSRM_TAG:-latest}` line (repo copy does;
the lab copy did not before the first sync — see Deploy step 1). A DB rollback
is separate: if the bad release migrated the schema, pinning the old image
does not un-migrate — restore the pre-deploy snapshot instead (below), and
accept that booting the older image against a newer-schema DB is the failure
mode you are avoiding by restoring.

## Restore from a snapshot

Snapshots: nightly `sqlite3 .backup` (online, WAL-safe) of `/app/data/srm.db`,
gzipped, written by `08-app-state-pre-backup.sh` under `homelab-backup.timer`
(~03:00 IST), 7 kept in `/data/ssd120/backups/opensrm/` (verified:
`ssh lab 'systemctl status homelab-backup.timer'; ssh lab 'cat
/etc/homelab-backup/jobs.d/06-opensrm.job'; ssh lab 'ls -1t
/data/ssd120/backups/opensrm/'`). Backup failures alert on Telegram from the
backup driver itself.

### Restore drill — run it before you ever need a restore

`scripts/restore_drill.sh` proves a snapshot restores cleanly **without
touching prod**: it materialises the snapshot into a temp DB, runs
`PRAGMA integrity_check`, and prints schema version + per-table row counts
next to the live DB's (live side read-only through the container; the temp DB
is deleted on exit; nothing is written into the snapshot dir or the volume).

```bash
# on the lab host (reads only):
ssh lab 'bash -s' < scripts/restore_drill.sh              # newest snapshot
ssh lab 'bash -s' < scripts/restore_drill.sh /data/ssd120/backups/opensrm/srm.20261016.snapshot.db.gz
# verdict: FAIL on integrity error or missing table; row-count deltas vs live
# are printed as INFO (the snapshot is up to a day old — deltas are expected).
```

Drilled live 2026-10-16 (`ssh lab 'bash -s' < scripts/restore_drill.sh` →
`DRILL PASS`, RC=0): `srm.20261016.snapshot.db.gz` (03:02 IST) → integrity
`ok`, all 13 tables present, drill schema 16 vs live 17 (+1 row in
`schema_version`) — migration 17 landed after the snapshot was cut, and
the drill passes because restoring an older snapshot re-runs forward
migrations on boot; the FAIL arm is only the downgrade direction
(drill schema > live). Row deltas were the day's churn: cookies +1,
`push_sent_log` +15, `usage_events` +42, every stable table +0.

### Full prod restore (only after a drill passed)

1. `ssh lab 'docker compose stop opensrm'` (writes must stop).
2. As root, copy the drill-verified file over the volume DB:
   `ssh lab 'sudo cp <drill.db> /var/lib/docker/volumes/opensrm_opensrm-data/_data/srm.db'`
   — keep a copy of the file you are replacing (that DB is the thing you are
   restoring *from* a disaster; don't destroy the last witness).
3. `docker compose start opensrm`; the entrypoint re-chowns `/app/data`.
4. Re-verify: `GET /healthz` 200, then
   `docker exec opensrm python -c "…select max(version),count(*) from schema_version…"`
   matches the drill output.

## Key rotation

Full procedure: [SECURITY.md "Key rotation"](../SECURITY.md#key-rotation)
(generate keys in-container, `FERNET_KEYS=<new>,<old>` in
`/docker/opensrm/.env`, recreate, `scripts/rotate_fernet_key.py` dry-run →
`--apply`, drop the old key later). Two runbook-level notes:

- `FERNET_KEYS` only takes effect once the live compose file carries the
  `FERNET_KEYS=${FERNET_KEYS:-}` environment line (repo copy has it; the lab
  copy did not before the compose sync). Until then the env entry is silently
  ignored and the file key `DATA_DIR/fernet.key` stays active (verified:
  `ssh lab 'docker exec opensrm env | grep FERNET'` → empty while
  `docker exec opensrm ls -la /app/data/fernet.key` → active).
- Env is baked at container create — every key change needs
  `docker compose up -d opensrm`, not just a file edit.

## Disabling sync — no switch exists

There is **no env var or flag that disables portal sync** (verified at main:
the full env surface is
`git grep -hoE 'os\.environ\.get\("[A-Z_0-9]+' origin/main -- app/` — no
`SYNC_DISABLED`/maintenance mode; no doc claims one). When you need to damp or
stop portal contact, these are the real levers, in order of blast radius:

1. **Do nothing / wait** — the portal cooldown and the aggregate portal budget
   already damp contact automatically after failures (below).
2. **Widen the cache window** — `SYNC_MIN_INTERVAL_S` (default 300 s; inside
   the window a refresh is answered from stored data with zero portal
   requests). Requires the compose-synced env line; read per-request, so
   editing the env + `docker compose up -d opensrm` applies it.
3. **Block at the edge** — Cloudflare (tunnel/WAF) in front of :8083; the app
   never binds a LAN address, so the edge is the only door.
4. **`docker compose stop opensrm`** — takes the whole app down, not just
   sync. Students see downtime; the portal sees nothing.

A code-level sync-disable knob is out of scope here; if ops wants one, it is a
feature PR, not a runbook entry.

## Portal cooldown handling

After **3 consecutive portal failures** the app arms a global cooldown:
5 min, doubling per further failure, capped at 30 min (1800 s); one success
resets it. While armed, syncs and logins are rejected immediately with HTTP
429 `portal_cooldown` and a "Try again in N minutes" message, and a cooldown
rejection costs no per-account quota and no portal request (code:
`app/state.py` `PortalHealth` + `app/app.py` `_portal_cooldown_remaining`,
rejections at `app/app.py` login/refresh gates; `git grep -n cooldown
origin/main -- app/state.py app/app.py`).

Operator guidance:

- The log line `portal cooldown N min after M consecutive fails` is the
  alarm — it means the portal itself is failing, not OpenSRM. Check the
  portal in a browser before touching anything.
- Do **not** restart the container to "clear" it: the state is in-memory so a
  restart clears it, but you then immediately re-arm it while the portal is
  still down, and you lose the counter that tells you how bad it is. The max
  wait is 30 min by design.
- To see cooldown without grepping logs, enable `/internal/metrics`
  (below — the `opensrm_portal_cooldown_seconds` gauge).

## Observability: canary and metrics

**`scripts/canary_sync.sh <netid>`** — a manual health probe that performs
**exactly one real portal sync** against a running deployment: mints a session
cookie, `POST /api/refresh` once, asserts `ok` + non-empty attendance and
marks, deletes the cookie (trap-guaranteed), exits non-zero with the reason on
any failure. It fails loudly if the answer came from the `SYNC_MIN_INTERVAL_S`
cache window, because a canary must really touch the portal. It is **not
scheduled anywhere** — run it by hand after deploys or when users report sync
failures; fabricated netids only. (`bash scripts/canary_sync.sh` reads its own
defaults; `CANARY_BASE`/`CANARY_MINT`/`CANARY_CHECK`/`CANARY_DROP` override
each leg — that is also how its unit test runs offline.)

**`GET /internal/metrics`** — Prometheus text of sync outcomes/durations by
pipeline and error class, cache hits / single-flight joins, captcha attempts,
preflight fates, scrape-lock rejections, portal-cooldown seconds, parse-empty
counts; no PII in labels. Guarded by the `X-Metrics-Token` header matching
`METRICS_SECRET`; **unset = endpoint off** (bare 401). On the lab today it is
off (verified: `curl -s -o /dev/null -w '%{http_code}'
http://127.0.0.1:8083/internal/metrics` → 401; `METRICS_SECRET` absent from
container env and project `.env`). To enable: add `METRICS_SECRET=<value>` to
`/docker/opensrm/.env`, `docker compose up -d opensrm`, then
`curl -H "X-Metrics-Token: <value>" …/internal/metrics`. It is on-demand only
— nothing scrapes it yet.

## Push tick (scheduler, alerting, dead-man)

**Scheduler: a Hermes cron job, not cron-job.org.** The job
`opensrm-push-tick` (id `4352c6d4be31`, `* * * * *`, no-agent, enabled) runs
`/opt/data/scripts/push-tick.sh` on the Hermes host, which POSTs
`https://srm.200871.xyz/internal/push/tick` with `X-Push-Tick` (secret at
`/opt/data/secrets/push_tick_secret`, 25 s timeout). Verified:
`python3` read of `/opt/data/cron/jobs.json` → schedule/state above; one
caller only, ~1/min (recon counted 725 `push/tick` 200s in ~776 min:
`ssh lab 'grep -a -c "push/tick" /app/data/opensrm.log'`). cron-job.org is
kept in [push.md](push.md) as an alternative scheduler only — the same
URL/header/schedule can be entered there if the Hermes host ever goes away.

The script is **silent on HTTP 200**, appends one JSON line per success to
`/opt/data/cron/output/push-tick.log` (only successes write), and exits 1 only
at **≥3 consecutive failures** (1st/2nd are silent by design — deploys
routinely drop a tick or two). Failures alert through two independent chains:

1. **Tick chain** — exit 1 → Hermes records a `cron_incidents` row and
   delivers to chat + ntfy (38 incidents in the job's history, 36 alerted —
   e.g. the Oct 8 20:11–21:47 deploy outage; evidence:
   `python3` over `/opt/data/cron/executions.db`).
2. **App chain** — `NTFY_ALERT_URL` set in the project env file → the app
   POSTs its own ERROR-level (5xx/unhandled — **not** WARNING) log records to
   ntfy, rate-limited 1/min (`app/logging_setup.py` `NtfyHandler`; on the lab:
   `grep -cE "^NTFY_ALERT_URL=.+" /docker/opensrm/.env` → 1).

### Dead-man gap (PROPOSED — not installed)

Both alert chains are generated **inside the Hermes host**. If that host (or
the cron job) dies or the job gets disabled, ticks stop and **nothing alerts**
— no monitor watches a missing tick anywhere (verified: the job's
`monitor_url`/`monitor_script` are null in `jobs.json`; Uptime Kuma has 29
monitors, zero matching OpenSRM/push/cron/heartbeat:
`sqlite3 kuma.db "select id,name,type from monitor where name like '%SRM%'
or type in ('push','cron')"` → empty; Kuma's `hermes Docker` monitor only
sees container down, not a stopped job). A missing tick is also silent for up
to ~2 min by design (the 3-failure rule).

**Proposed fix — a Kuma push (heartbeat) monitor, alarm outside Hermes:**

1. In Uptime Kuma add a *Push* monitor, e.g. name `opensrm-push-tick`,
   heartbeat interval **5 min** (tolerates the designed 2-min silence plus a
   deploy), "Alert after 1 missed heartbeat".
2. Copy its push URL into `/opt/data/secrets/kuma_push_url` (600) and have
   `push-tick.sh` POST to it on each **successful** tick (one extra
   `curl -fsS -m 5 -o /dev/null "$(cat …/kuma_push_url)"` line; failure to
   ping must never fail the tick).
3. The freshness signal is then the heartbeat itself: Hermes-dead,
   job-disabled and script-hang all stop the pings, and the **alarm lives in
   Kuma**, which is a different process on a different host than the failure
   it detects — closing the same-process gap.

Not installed: it needs a Kuma monitor + an edit to the Hermes-side script,
both outside this repo. Flip this section from PROPOSED to a procedure when
done.

## Upgrade notes (accumulated)

- **Snapshot before any release that carries migrations** — pinned recipe in
  Deploy step 0; ad-hoc pre-deploy snapshots on the lab have inconsistent
  names (`srm.db.predeploy-<unixts>`, `srm.db.bak-pre-<ver>-<stamp>`) and no
  generating script — use the pinned recipe so the drill covers what you made.
- **Dead env cleanup** — `OPENROUTER_API_KEY` was removed from the repo (A5;
  `git grep -n OPENROUTER origin/main` → no matches) but the lab still carries
  it in the project env and the pre-sync compose: delete the line from both
  during the first compose sync.
- **`FERNET_KEYS` stays inert** until the compose sync lands the env line
  (Key rotation above).
