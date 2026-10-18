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
| Observability stack (optional, not yet deployed) | repo `ops/observability/` → deploy at `/docker/opensrm-obs/`; loopback-only 9092/9093, Grafana 3100 on the LAN (password-gated) | see [Observability stack](#observability-stack-optional) |
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
`curl -H "X-Metrics-Token: <value>" …/internal/metrics`. The optional stack
below is the only intended consumer.

## Observability stack (optional)

`ops/observability/` in the repo is a self-contained metrics stack —
**Prometheus + Grafana + Alertmanager** — that runs NEXT TO the app
(`ops/` is in `.dockerignore`; nothing here ships inside the app image).
Design rules, all verified live on the lab daemon 2026-10-18:

- **No existing stack to extend**: the lab had no Prometheus/Grafana/Loki/
  ntfy containers (`docker ps`), and the classic ports are taken — 9090 is
  Cockpit (served its login page), 3000 is dockhand. So the stack binds
  `127.0.0.1:9092` (Prometheus) and `127.0.0.1:9093` (Alertmanager) —
  **loopback only** — and Grafana on `0.0.0.0:3100` so it opens from any
  LAN device at `http://<lab-ip>:3100` (password-gated: sign-up and
  anonymous access are off, admin is the 32-hex secret file). The
  Cloudflare tunnel is never touched — LAN exposure does not imply
  internet exposure; home NAT has no 3100 forward.
- Images pinned by tag AND digest (resolved from the registry): prometheus
  v3.13.4, alertmanager v0.34.1, grafana 13.2.4. Non-root users, `cap_drop:
  ALL`, `no-new-privileges`, `mem_limit`/`pids_limit` from a measured run
  (see the compose comments for the numbers), named volumes, retention 30d
  + 2GB size cap (the root fs had 15GiB free at design time).
- The scrape target is the app's real container-reachable bind
  `172.31.0.1:8083` (verified from a throwaway container: `wget -O-
  http://172.31.0.1:8083/healthz` → `{"status":"ok"}`); `metrics_path:
  /internal/metrics` and the `X-Metrics-Token` value comes from a mounted
  **secret file**, never inline (Prometheus `http_headers: … files:` —
  verified live: correct token scrapes `up == 1`, a deliberately-wrong
  token file makes the job go `up == 0` with the app logging its bare 401).
- Grafana: sign-up off, anonymous off, analytics + update checks off, admin
  password from a secret file, dashboard provisioned **read-only**
  (`allowUiUpdates: false` — panel edits in the UI are never saved; edit
  the JSON in the repo and restart).
- Alert delivery (verified end-to-end against a throwaway ntfy topic):
  Alertmanager's own `webhook_configs` posts to an ntfy URL carrying
  `?template=yes&title={{.commonLabels.alertname}}&message={{.commonAnnotations.summary}}`
  — ntfy's URL templating renders a proper notification, so **no bridge
  container and no Grafana-side contact point is needed**. The topic URL
  lives in a mode-600 `url_file` (the ntfy topic name is a secret by ntfy's
  design). The two rejected alternatives: a third-party alertmanager→ntfy
  bridge image (extra unpinnable-trust container) and a Grafana contact
  point (would need Grafana-managed alert rules duplicating the
  promtool-tested ones — the rules live in git, so Prometheus is the source
  of truth).

### Bring-up (exact lab steps)

The stack is a sibling compose project. One-time, on the lab host:

```bash
# 1. enable the app's metrics endpoint (project env file, NOT the master registry)
echo 'METRICS_SECRET=<long-random-value>' >> /docker/opensrm/.env
cd /docker/opensrm && docker compose up -d --force-recreate opensrm   # env is baked at create: a plain up -d leaves the old container Running with the OLD env
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Metrics-Token: <value>' \
  http://127.0.0.1:8083/internal/metrics                    # expect 200

# 2. deploy the stack (copy ops/observability/ from the repo)
mkdir -p /docker/opensrm-obs && cd /docker/opensrm-obs
#    ... copy ops/observability/* here (docker-compose.yml, prometheus/, ...)

# 3. create the secret files NEXT TO the compose file (never commit them —
#    secrets/ is gitignored). ORDER MATTERS: the files must exist AND be
#    readable by each container's uid BEFORE the first `up`, because
#    Grafana seeds the admin password into its volume on FIRST boot only.
printf '<the METRICS_SECRET value>'  > secrets/metrics_token     # no newline
printf '<grafana admin password>'    > secrets/grafana_admin
printf '<the ntfy topic URL incl. the template=... params from the compose file header>' > secrets/ntfy_url
chmod 600 secrets/*

# 4. bind mounts keep host ownership: the containers run as uid 65534
#    (prometheus/alertmanager) and 472 (grafana) and CANNOT read a 600 file
#    owned by your user. Hand the files over with a one-shot container
#    (docker group membership is all that is needed, no sudo):
docker run --rm -v "$PWD/secrets:/s" alpine:3.20 \
  sh -c 'chown 65534:65534 /s/metrics_token /s/ntfy_url; chown 472:472 /s/grafana_admin'

# 5. up
docker compose up -d
docker compose ps
```

Re-ordering gotchas burned into the steps above: if Grafana's first boot
cannot read its password file, it seeds the DB with the fallback and the
volume remembers it forever (fix = `docker compose down grafana && docker
volume rm <project>_grafana-data && up` again, in the right order).

### Access

```bash
# Grafana — primary: any LAN device
#   http://<lab-ip>:3100   (e.g. http://192.168.29.7:3100)
#   admin password: docker exec -u 472:472 opensrm-grafana \
#                     cat /run/secrets/grafana_admin
ssh -L 3100:127.0.0.1:3100 lab    # Grafana — fallback (remote/VPN), same URL
ssh -L 9092:127.0.0.1:9092 lab    # Prometheus (loopback-only)
ssh -L 9093:127.0.0.1:9093 lab    # Alertmanager (loopback-only)
```

### What each panel means

The dashboard (`opensrm-observability` uid, folder OpenSRM) has 10 panels:

- **Scrape up** — `up{job="opensrm"}`: 1 = the endpoint answered the last
  scrape. 0 = app down, restarting, or the token file stopped matching
  `METRICS_SECRET` (e.g. the secret rotated on one side only).
- **Push tick age** — seconds since the last successful
  `POST /internal/push/tick`; the dead-man switch. Healthy ≈ 0–120s; the
  alert trips past 300s.
- **Portal cooldown** — live cooldown the app arms after 3 consecutive
  portal failures (5min doubling, capped 30min). 0 = armed off; sustained
  >0 = retries keep failing.
- **Syncs per minute by pipeline and outcome** — `rate()` of
  `opensrm_sync_total` (counters reset on every deploy — that's why every
  panel uses rate/increase, never raw counter reads).
- **Error classes (1h)** — failing syncs grouped by the typed `error=`
  label; one class dominating names the cause without reading logs.
- **Sync duration p50/p95** — from the histogram buckets (app buckets top
  at 150s = the pipeline deadline).
- **Cache hits vs joined vs real syncs** — how refreshes resolved: served
  from the last sync's cache, joined an in-flight sync, or ran a real
  portal sync. Cache+joined high = quota-friendly.
- **Scrape-lock rejections** — syncs refused because the lock was held;
  a burst = one long portal call is blocking everyone.
- **Parse-empty by page (24h)** — pages that parsed to zero rows = portal
  markup drift, the thing this stack exists to catch first.
- **Captcha attempts per login (average)** — OCR health: ~1 = first-try
  captcha reads; creeping up = the portal changed its captcha.

### What each alert means (thresholds are STARTING POINTS)

Every threshold was picked at design time with no production history —
**retune from real data after a few weeks**; each rule's comment in
`ops/observability/prometheus/rules/opensrm.yml` says what firing means:

| Alert | Fires when | First action |
|---|---|---|
| OpenSRMAppDown | scrape down 5m | `docker ps` + `docker logs opensrm` |
| OpenSRMPushTickStale | no tick >5m, 5m sustained | check the Hermes cron job + push-tick.log |
| OpenSRMSyncFailureRatioHigh | >20% failing, ≥10 syncs/h | read the error= breakdown |
| OpenSRMParseEmpty | any parse-empty in 1h | compare a capture vs `app/portal/parsers/` |
| OpenSRMSyncP95TooSlow | p95 >90s for 1h | correlate lock rejections |
| OpenSRMScrapeLockRejectionsBurst | >10 in 15m, 5m sustained | check p95 + app logs |
| OpenSRMPortalCooldownActive | cooldown >0 for 10m | portal health / cooldown section above |

The rule unit tests (`opensrm.test.yml`, run by the CI promtool step) prove
each rule BOTH fires on crafted bad series and stays quiet on the matching
good one.

### Tuning

- Edit `ops/observability/prometheus/rules/opensrm.yml` (or the dashboard
  JSON) in a PR — the running stack picks changes up only via
  `docker compose up -d --force-recreate` (the lifecycle/reload endpoint is
  deliberately OFF: `--no-web.enable-lifecycle`).
- Grafana UI panel edits are never saved (read-only provisioning) — edit
  `grafana/dashboards/opensrm.json`.
- Retention: `--storage.tsdb.retention.time=30d` + `.size=2GB` in the
  compose file.

### Restore / teardown

The stack holds NO authoritative data — deleting everything loses only
metrics history: `docker compose down -v` removes the three named volumes;
`ops/observability/` + the secrets files in `/docker/opensrm-obs/` recreate
it. The app runs with or without it (endpoint returns 401 to nothing).

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

### Dead-man (implemented — Prometheus alert on the app's own gauge)

Both alert chains used to be generated **inside the Hermes host**: if that
host (or the cron job) died or the job got disabled, ticks stopped and
**nothing alerted** — no monitor watched a missing tick anywhere (verified
at design time: the job's `monitor_url`/`monitor_script` were null in
`jobs.json`; Uptime Kuma had 29 monitors, zero matching
OpenSRM/push/cron/heartbeat; Kuma's `hermes Docker` monitor only saw the
container being down, not a stopped job). A missing tick was also silent for
up to ~2 min by design (the 3-failure rule).

**Implemented fix — the app itself is now the heartbeat (v1.25.x):** every
successful `POST /internal/push/tick` increments
`opensrm_push_tick_total{outcome="ok"|"error"}` and stamps the
`opensrm_push_tick_last_success_timestamp_seconds` gauge (same `app/metrics.py`
module, no PII in labels; auth-failed ticks deliberately move nothing — an
outside prober must not be able to fake scheduler liveness). The
observability stack's `OpenSRMPushTickStale` rule fires when the stamp goes
>5 min stale for 5m sustained, and Alertmanager delivers it to ntfy — so the
alarm lives OUTSIDE the process that fails, which was the whole point.
Both the counter and the gauge are pinned by `tests/test_push_tick.py`
(27/27) and the rule is promtool-tested both ways.

Not yet deployed on the lab: it needs the optional observability stack
brought up (see [Observability stack](#observability-stack-optional)) —
the metrics are in the app image, but until `METRICS_SECRET` + the stack
go live, the dead-man watches nothing. The earlier proposal — a Uptime Kuma
push monitor fed by `push-tick.sh` — stays a valid stack-free alternative
(needs the Hermes-side script edit, outside this repo); the Prometheus
route shipped instead because the rules are in git, promtool-tested, and
the delivery path was verified end-to-end.

## Upgrade notes (accumulated)

- **Observability stack (2026-10-18)** — first bring-up on the lab follows
  the exact steps in [Observability stack](#observability-stack-optional):
  set `METRICS_SECRET` in `/docker/opensrm/.env` and `docker compose up -d
  --force-recreate opensrm` (the compose file passes the key through its
  `environment:` list — without that line a .env key is never injected; and
  a plain `up -d` does not recreate, so the env stays old), copy `ops/observability/` to `/docker/opensrm-obs/`,
  create the three 600-mode secret files there (`metrics_token` =
  the METRICS_SECRET value, `grafana_admin`, `ntfy_url` with the template
  params — exact strings in the compose file header), hand them to the
  container uids with the one-shot `docker run … chown` line, then
  `docker compose up -d`. ORDER MATTERS: Grafana seeds its admin password
  from the secret file on first boot only.
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
