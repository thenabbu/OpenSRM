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

### Push notifications (Web Push)
- A subscription's **endpoint is a capability URL** — anyone holding it could
  target that device. It is stored server-side only, never logged in full
  (12-char hash prefix at most) and never rendered to another user; the
  status API exposes only the hash
- `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `PUSH_TICK_SECRET` live in env
  (`/docker/.env`, passed via compose `${VAR}`), never in the repo or
  `DATA_DIR`; the app refuses to run the feature without them (no runtime
  key generation — an ephemeral host would orphan every subscription)
- `POST /internal/push/tick` is authenticated by the `X-Push-Tick` header
  compared with `hmac.compare_digest`; missing/wrong secret → bare 401, no
  session cookie involved, no detail leaked
- Push endpoints use **DB-backed** rate limits (survive serverless): 10
  subscribes, 3 test pushes, 30 receipts per netid per hour
- Reminder payloads contain only timetable facts (subject, time, room) and
  TTL out at class start; the push path never touches the portal

### Content Security Policy
- `default-src 'self'` — everything falls back to same-origin
- `script-src 'self' https://cdn.jsdelivr.net` — no inline scripts; the only external origin is the Tailwind/daisyUI CDN (both pages load it via `partials/theme.html`)
- `style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net` — Tailwind/daisyUI loaded at runtime from jsDelivr
- **Subresource Integrity on both CDN assets** — the Tailwind and daisyUI tags in `partials/theme.html` carry `integrity="sha384-…"` + `crossorigin="anonymous"`, so the browser refuses to execute or apply either file unless its bytes hash exactly to the pinned digest (a changed or tampered CDN response fails closed; the page renders unstyled instead of compromised). The digests were computed from the exact pinned URLs and confirmed against independent fetches; a locally served tampered copy is rejected by the browser while the untampered control loads.
- `img-src 'self' data:` — no remote image hosts
- `connect-src 'self'` — no external API calls from the browser
- `frame-ancestors 'none'` — cannot be embedded in iframes
- `base-uri 'self'`, `form-action 'self'`, `worker-src 'self'`, `manifest-src 'self'`
- Plus `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and HSTS (`max-age=31536000; includeSubDomains`) on `cf-ray` responses only

### Rate limiting
- Per netid: 3 scrapes per 10 minutes — counted only when the sync actually runs; a rejection that never reaches the portal (scrape lock held, portal budget spent, cooldown active) costs nothing, so a busy server can't lock an account out of a sync it never performed
- Per IP: 10 login attempts per hour (counted only after credentials pass format validation)
- Aggregate server→portal budget: 30 requests per 10 minutes
- Portal cooldown: 3 consecutive portal failures arm a cooldown (5 min, doubling, capped at 30 min)
- Memory exhaustion guard: rate-limit dicts are pruned once they pass 10,000 entries (hard clear at 2× as the blowout backstop)

### Input validation
- NetID regex: `[a-z0-9]{2,20}` (after stripping email domain)
- Password max length: 128 characters
- Request body max: 16KB, and login accepts only a real `application/json` body (no form-encoded CSRF vector); no CSRF token — `SameSite=Lax` + the strict JSON requirement cover it

### Infrastructure
- Cloudflare Tunnel for HTTPS termination
- **SQLite backups must be online copies.** `sqlite3 <db> ".backup <dest>"` (the
  method the standing daily snapshot pipeline uses) is safe in every journal
  mode — it reads through the WAL. A raw `cp` of `srm.db` is only equivalent
  while the DB runs the default `delete` journal; with `SQLITE_JOURNAL_MODE=wal`
  recent commits live in `srm.db-wal` and a file-only copy silently misses them
- Only trusted when `cf-ray` header is present (prevents header spoofing)
- Docker container runs with healthcheck and log rotation
- Accepted risk (deliberate): the container runs as root with Chromium
  `--no-sandbox` — required for headless Playwright in-container; the
  container is single-purpose and only reachable through the Cloudflare
  tunnel (compose publishes loopback + the cloudflared bridge gateway only)

### Supply chain
- Every CI action is SHA-pinned to a 40-char commit; the Dockerfile pins its
  base images and the `uv` binary by digest
- `.github/workflows/scans.yml` runs gitleaks (full git history), pip-audit
  (locked python deps) and trivy (built image, HIGH/CRITICAL with a fix
  available) on every PR — **report-only** by design; docs/SCANS.md documents
  what each would block on and how the maintainer can flip one to blocking
- The one git dependency (`blobatar`) is pinned to an exact commit hash
  (`pyproject.toml` + `uv.lock`, enforced by `tests/verify76.py` M22) — a known,
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
