# Security Policy

## Reporting vulnerabilities

Report vulnerabilities privately via [GitHub Security Advisories](https://github.com/thenabbu/OpenSRM/security/advisories) (github.com/thenabbu/OpenSRM → Security → Report a vulnerability). Do not open public issues.

## What we protect

### Passwords
- Fernet encryption at rest (AES-128-CBC)
- Key stored at `DATA_DIR/fernet.key` (`/app/data/fernet.key` in the container, mode 600, generated on first boot if absent)
- Never logged or transmitted in plaintext

### Sessions
- HttpOnly cookies (not accessible via JavaScript) with `SameSite=Lax`
- Secure flag enabled only when the request carries a real `cf-ray` and arrived over HTTPS
- 30-day expiry, enforced on every read; expired tokens for an account are pruned when that account logs in again (no background sweeper)

### Content Security Policy
- `default-src 'self'` — everything falls back to same-origin
- `script-src 'self' https://cdn.jsdelivr.net` — no inline scripts; the only external origin is the Tailwind/daisyUI CDN (both pages load it via `partials/theme.html`)
- `style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net` — Tailwind/daisyUI loaded at runtime from jsDelivr
- `img-src 'self' data:` — no remote image hosts
- `connect-src 'self'` — no external API calls from the browser
- `frame-ancestors 'none'` — cannot be embedded in iframes
- `base-uri 'self'`, `form-action 'self'`, `worker-src 'self'`, `manifest-src 'self'`
- Plus `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and HSTS (`max-age=31536000; includeSubDomains`) on `cf-ray` responses only

### Rate limiting
- Per netid: 3 scrapes per 10 minutes
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
- Only trusted when `cf-ray` header is present (prevents header spoofing)
- Docker container runs with healthcheck and log rotation
- Accepted risk (deliberate): the container runs as root with Chromium
  `--no-sandbox` — required for headless Playwright in-container; the
  container is single-purpose and only reachable through the Cloudflare
  tunnel (compose publishes loopback + the cloudflared bridge gateway only)

## Scope

Student-built tool, not production infrastructure. Do not reuse the same password elsewhere.
