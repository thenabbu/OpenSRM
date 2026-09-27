# Security Policy

## Reporting vulnerabilities

Report vulnerabilities privately via [GitHub Security Advisories](https://github.com/thenabbu/OpenSRM/security/advisories) (github.com/thenabbu/OpenSRM → Security → Report a vulnerability). Do not open public issues.

## What we protect

### Passwords
- Fernet encryption at rest (AES-128-CBC)
- Key stored in `/app/data/fernet.key`
- Never logged or transmitted in plaintext

### Sessions
- HTTP-only cookies (not accessible via JavaScript)
- Secure flag enabled behind HTTPS
- 30-day expiry with automatic cleanup of expired tokens

### Content Security Policy
- `script-src 'self' https://cdn.jsdelivr.net` — no inline scripts; the only external origin is the Tailwind/daisyUI CDN (both pages load it via `partials/theme.html`)
- `style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net` — Tailwind/daisyUI loaded at runtime from jsDelivr
- `frame-ancestors 'none'` — cannot be embedded in iframes
- `connect-src 'self'` — no external API calls from the browser

### Rate limiting
- Per netid: 3 scrapes per 10 minutes
- Per IP: 10 login attempts per hour
- Memory exhaustion guard: rate-limit dicts capped at 10,000 entries

### Input validation
- NetID regex: `[a-z0-9]{2,20}` (after stripping email domain)
- Password max length: 128 characters
- Request body max: 16KB

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
