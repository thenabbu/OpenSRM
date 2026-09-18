# Security Policy

## Reporting

Report vulnerabilities via GitHub DM or email. Do not open public issues.

## What We Protect

- **Passwords** — Fernet encryption at rest (AES-128-CBC), key in `/app/data/fernet.key`
- **Sessions** — HTTP-only, Secure-flagged (behind HTTPS), 30-day expiry
- **CSP** — `script-src 'self'`, no inline JS, `worker-src 'self'`, `manifest-src 'self'`
- **Rate limiting** — per-netid (3/10min) + per-IP (10/hr)
- **Input validation** — Net ID regex `[a-zA-Z0-9]{2,20}`, max lengths enforced
- **Cache** — `no-store` on HTML, `no-store` on CSS, selective caching for PWA assets

## Scope

Student-built tool, not production infrastructure. Don't reuse the same password elsewhere.
