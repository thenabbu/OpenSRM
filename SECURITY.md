# Security Policy

## Reporting vulnerabilities

Report vulnerabilities privately via [GitHub Security Advisories](https://github.com/thenabbu/OpenSRM/security/advisories) (github.com/thenabbu/OpenSRM → Security → Report a vulnerability). Do not open public issues.

## What we protect

### Passwords
- Fernet encryption at rest (AES-128-CBC); when `FERNET_KEYS` is set, reads go through `MultiFernet`, so every listed key decrypts while only the **first** key encrypts (old ciphertext stays readable through a rotation)
- Key location, in precedence order:
  - `FERNET_KEYS` env — comma-separated base64 keys, first key = the encrypting key. It belongs in `/docker/opensrm/.env` (the compose project env, interpolated into the container's `environment:`), **not `/docker/.env`** (the lab master registry — compose never reads it for this project) and never inside `DATA_DIR`
  - default (unset or empty): `DATA_DIR/fernet.key` (`/app/data/fernet.key` in the container, mode 600, generated on first boot if absent)
- Never logged or transmitted in plaintext — `scripts/rotate_fernet_key.py` prints counts only, never key material, ciphertext, plaintext or netids
- A decrypt failure keeps today's behaviour: the credentials read as unreadable and the user is asked to log in again (no crash)
- How to replace the key without losing stored passwords: see [Key rotation](#key-rotation)

### Sessions
- HttpOnly cookies (not accessible via JavaScript) with `SameSite=Lax`
- Secure flag enabled only when the request carries a real `cf-ray` and arrived over HTTPS
- 30-day expiry, enforced on every read; expired tokens for an account are pruned when that account logs in again (no background sweeper)
- **Tokens are stored as a sha256 hex digest** (migration 17): the browser holds the raw token, the database never does, so a leaked `srm.db` cannot be replayed as a live session. Existing rows are hashed inside the migration, so every current session survives the upgrade; the digest is computed over the presented cookie on every read, prune and delete
- **Cross-site state-changing requests are refused with 403** (`POST`/`PUT`/`PATCH`/`DELETE`): when `Sec-Fetch-Site` is present it must be `same-origin` or `none` (forbidden header — a cross-site page can neither strip nor forge it); otherwise a present `Origin` must match the request host (including `Origin: null`, which fails closed); a client that sends neither header (curl, cron, tests) is not a browser and is allowed. `POST /internal/push/tick` is exempt — it authenticates with its own secret header. Every refusal logs `status=403` with its `error=` on the `opensrm.http` line

### Push notifications (Web Push)
- A subscription's **endpoint is a capability URL** — anyone holding it could
  target that device. It is stored server-side only, never logged in full
  (12-char hash prefix at most) and never rendered to another user; the
  status API exposes only the hash
- `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `PUSH_TICK_SECRET` live in env
  (`/docker/opensrm/.env`, the project env file compose interpolates from —
  never the master `/docker/.env`), never in the repo or
  `DATA_DIR`; the app refuses to run the feature without them (no runtime
  key generation — an ephemeral host would orphan every subscription)
- `POST /internal/push/tick` is authenticated by the `X-Push-Tick` header
  compared with `hmac.compare_digest`; missing/wrong secret → bare 401, no
  session cookie involved, no detail leaked

### Observability (`GET /internal/metrics`)
- Same auth contract as the push tick: `METRICS_SECRET` lives in env, the
  `X-Metrics-Token` header is compared with `hmac.compare_digest` over
  UTF-8 bytes (non-ASCII fails closed), unset env means the endpoint is
  off, and any failure returns a bare 401 with an empty body; every failure
  logs a WARNING (reason only, never the secret)
- The rendered Prometheus text carries only counters/timers/gauges with
  low-cardinality labels (pipeline, error class, page, outcome) — no
  netids, no portal payloads, no PII
- **The scrape itself is secret-gated twice over** when the optional
  observability stack (ops/observability/) is up: the stack's Prometheus
  reads its `X-Metrics-Token` value from a mounted secret file
  (mode 600, owned by the container's uid, created on the deploy host —
  never in the repo), Prometheus and Alertmanager bind 127.0.0.1 only
  (reachable solely via `ssh -L`), and Grafana binds all LAN interfaces
  behind a generated 32-hex admin password — sign-up, anonymous access
  and self-registration are all off, so reaching the port still requires
  authenticating. The Cloudflare tunnel is untouched and neither service
  is exposed publicly (home NAT forwards no port; LAN is not internet).
  The alertmanager's ntfy topic URL is likewise a mode-600 `url_file`
  mount — the topic name is a secret by ntfy's own design
- Push endpoints use **DB-backed** rate limits (survive serverless): 10
  subscribes, 3 test pushes, 30 receipts per netid per hour
- Reminder payloads contain only timetable facts (subject, time, room) and
  TTL out at class start; the push path never touches the portal

### Content Security Policy
- `default-src 'self'` — everything falls back to same-origin
- `script-src 'self'` — no inline scripts and no external script origins (the Tailwind/daisyUI CDN was removed when the CSS moved to a pre-compiled `app.css`; both pages now load only same-origin files)
- `style-src 'self' 'unsafe-inline'` — the pre-compiled `app.css` plus inline style attributes; no stylesheet is fetched from any third-party host
- **No third-party payload to integrity-check** — Tailwind and daisyUI are compiled ahead of time from a version-pinned, sha256-verified toolchain (`scripts/build-css.sh`) into the committed `app/static/app.css`, so the browser never fetches third-party CSS or JS. The old SRI-on-CDN defence became unnecessary once the CDN itself was removed; the supply-chain surface it guarded no longer exists.
- `img-src 'self' data:` — no remote image hosts
- `connect-src 'self'` — no external API calls from the browser
- `frame-ancestors 'none'` — cannot be embedded in iframes
- `base-uri 'self'`, `form-action 'self'`, `worker-src 'self'`, `manifest-src 'self'`
- Plus `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and HSTS (`max-age=31536000; includeSubDomains`) on `cf-ray` responses only

### Rate limiting
- Per netid: 3 scrapes per 10 minutes — counted only when the sync actually runs; a rejection that never reaches the portal (sync queue wait exhausted, portal budget spent, cooldown active) costs nothing, so a busy server can't lock an account out of a sync it never performed; a refresh served from the last completed sync (`SYNC_MIN_INTERVAL_S`, default 300s) or shared from an already-running sync likewise never reaches the portal
- Per IP: 10 login attempts per hour (counted only after credentials pass format validation)
- Aggregate server→portal budget: 30 requests per 10 minutes, split into three buckets — full logins and preflights share 20 (preflight additionally capped at its own 10 so warm-logins can't drain the login pool), refreshes hold a reserved floor of 10 that unauthenticated work can never spend; one source IP holds at most 6 unauth tokens
- Sync serialization: one portal pipeline at a time (`SYNC_MAX_CONCURRENCY`, default 1); a second sync waits up to `SYNC_QUEUE_WAIT_S` (default 45s, `0` = refuse immediately) with logins queued ahead of refreshes, then gets the busy 503 — the wait is free, never charged against the account quota. The Playwright fallback stays serialized on one browser at any concurrency setting — and is archived off by default (`PLAYWRIGHT_FALLBACK` unset), so the shipped image carries no browser at all unless built with `--build-arg WITH_PLAYWRIGHT=1`
- Portal cooldown: 3 consecutive portal failures arm a cooldown (5 min, doubling, capped at 30 min)
- Memory bound: every rate-limit structure (per-netid and per-IP attempt windows, preflight admission state, the login-progress map and its per-IP read cap) is a dict in `app/state.py` behind one lock, pruned of expired keys on every access; when a map still passes 10,000 entries only its stale keys are dropped, with a hard clear at 2× as the blowout backstop for that one map. Worst case per map: ~20,000 keys × at most 10 timestamps each (10-minute or 1-hour window). The progress map additionally prunes on every write, so a login flow that never polls holds memory for at most its 10-minute TTL; the portal cooldown/failure counter is two scalars and cannot accumulate.

### Input validation
- NetID regex: `[a-z0-9]{2,20}` (after stripping email domain)
- Password max length: 128 characters
- Request body max: 16KB, and login accepts only a real `application/json` body (no form-encoded CSRF vector); no CSRF token — the cross-site 403 guard (Sec-Fetch-Site/Origin, see Sessions) + `SameSite=Lax` + the strict JSON requirement cover it

### Infrastructure
- Cloudflare Tunnel for HTTPS termination
- **SQLite backups must be online copies.** `sqlite3 <db> ".backup <dest>"` (the
  method the standing daily snapshot pipeline uses) is safe in every journal
  mode — it reads through the WAL. A raw `cp` of `srm.db` is only equivalent
  while the DB runs the default `delete` journal; with `SQLITE_JOURNAL_MODE=wal`
  recent commits live in `srm.db-wal` and a file-only copy silently misses them
- Only trusted when `cf-ray` header is present (prevents header spoofing)
- Docker container runs with healthcheck and log rotation; the healthcheck
  polls `GET /healthz` (`SELECT 1`, no session, no portal contact, a 16-byte
  body) and `_log_request` demotes that path to DEBUG, so a 30s poll cannot
  fill `opensrm.log` — a 5xx from the probe still logs ERROR so ntfy pages
- The container does **not** run as root. `entrypoint.sh` starts root for
  exactly two lines — `chown -R opensrm /app/data` (every existing volume
  predates the change and is root-owned) and the `setpriv` drop that follows
  — then `exec`s CMD in place, so PID 1 is the app as `opensrm` (uid 10001)
  with `CapPrm`/`CapEff` zeroed and `NoNewPrivs` set. Compose adds
  `cap_drop: ALL` with only `CHOWN`/`SETUID`/`SETGID` back, `read_only`
  rootfs + `/tmp` tmpfs, `no-new-privileges`, and `mem_limit`/`pids_limit`
  sized from measured RSS and task counts
- Chromium keeps `--no-sandbox` (headless Playwright in-container; only
  present in images built with `--build-arg WITH_PLAYWRIGHT=1`) — it no
  longer needs root for it; the container is single-purpose and only
  reachable through the Cloudflare tunnel (compose publishes loopback +
  the cloudflared bridge gateway only)

### Supply chain
- Every CI action is SHA-pinned to a 40-char commit; the Dockerfile pins its
  base images and the `uv` binary by digest
- `.github/workflows/scans.yml` runs gitleaks (full git history), pip-audit
  (locked python deps) and trivy (built image, HIGH/CRITICAL with a fix
  available) on every PR — **report-only** by design; docs/SCANS.md documents
  what each would block on and how the maintainer can flip one to blocking
- The one git dependency (`blobatar`) is pinned to an exact commit hash
  (`pyproject.toml` + `uv.lock`, enforced by `tests/unit/test_audit_findings.py` M22) — a known,
  documented supply-chain gap (see docs/SCANS.md) reported rather than fixed

## Key rotation

The encryption key can be replaced without losing stored passwords, and kept off the data volume: `FERNET_KEYS` in `/docker/opensrm/.env` holds comma-separated keys, **the first key encrypts** and every key decrypts. `DATA_DIR/fernet.key` stays the zero-config default. All commands below run on the lab host; the env is read at process start, so every key change needs a container recreate, and `scripts/rotate_fernet_key.py` ships in the image at `/app/scripts/`.

1. **Snapshot first** — an online `.backup`, the same WAL-safe method the daily snapshot pipeline uses (the image has no `sqlite3` CLI, so use its python):
   ```bash
   docker exec opensrm python -c 'import sqlite3; s=sqlite3.connect("/app/data/srm.db"); d=sqlite3.connect("/app/data/srm.pre-rotation.snapshot.db"); s.backup(d); d.close(); s.close(); print("snapshot ok")'
   docker cp opensrm:/app/data/srm.pre-rotation.snapshot.db ./srm.pre-rotation.snapshot.db
   ```
   Keep the copy until step 4's dry run is green. To restore: stop the container, `docker cp ./srm.pre-rotation.snapshot.db opensrm:/app/data/srm.db`, start it again.
2. **Generate the new key** on the lab host — it never passes through chat, logs or the repo:
   ```bash
   docker exec opensrm python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
   ```
3. **Edit `/docker/opensrm/.env`** (only ever this file — compose does not read `/docker/.env` for this project): set one line `FERNET_KEYS=<new-key>,<current-key>`. The current key is `docker exec opensrm cat /app/data/fernet.key` while you still run file mode; if `FERNET_KEYS` is already in use, keep its keys after the new one. **When first moving off the file key it must appear in the list — a key left out makes its rows unreadable.**
4. **Recreate, then re-encrypt history** (dry run is the default and prints counts only, never key material):
   ```bash
   cd /docker/opensrm && docker compose up -d opensrm
   docker exec opensrm python /app/scripts/rotate_fernet_key.py          # dry run: expect "to re-encrypt: N", "unreadable: 0"
   docker exec opensrm python /app/scripts/rotate_fernet_key.py --apply  # one transaction; verifies by decrypting every row; rolls back if any fails
   ```
   Any unreadable row stops the run **before a single write** with the count printed (fix the key list — usually a missing old key); `--skip-unreadable` continues and leaves exactly those rows untouched. Safe against the running app: one short transaction on a small DB, both sides wait up to 10s for the lock. Re-running is a no-op (`to re-encrypt: 0`).
5. **Drop the old key** once the dry run reports `to re-encrypt: 0` and logins look healthy: remove it from `FERNET_KEYS` (new key stays first), recreate again, dry-run once more. Rows still on a dropped key surface as the existing "stored credentials unreadable — log in again" path; portal-session rows have a 4h TTL, so they just force one fresh login. The app's own decrypt-failure behaviour is unchanged throughout.

## Scope

Student-built tool, not production infrastructure. Do not reuse the same password elsewhere.
