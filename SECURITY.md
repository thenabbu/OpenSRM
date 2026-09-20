# Security Policy

## Reporting

Report vulnerabilities via GitHub DM or email. Do not open public issues.

## What We Protect

- **Passwords** — Fernet encryption at rest (AES-128-CBC), key in /app/data/fernet.key
- **Sessions** — HTTP-only, Secure-flagged (behind HTTPS), 30-day expiry
- **CSP** — script-src 'self' https://cdn.jsdelivr.net (Tailwind/daisyUI CDN), worker-src 'self', manifest-src 'self'
- **Rate limiting** — per-netid (3/10min) + per-IP (10/hr)
- **Input validation** — Net ID regex [a-zA-Z0-9]{2,20}, max lengths enforced
- **Cache** — no-store on HTML, max-age=3600 on JS/JSON/icons (for PWA service worker)

## Scope

Student-built tool, not production infrastructure. Do not reuse the same password elsewhere.
