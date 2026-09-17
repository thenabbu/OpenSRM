# Security Policy

## Reporting Vulnerabilities

If you find a security issue, **do not open a public GitHub issue**. Instead, contact the maintainer directly via GitHub DM or email.

## What We Protect

- **Passwords** — encrypted at rest using Fernet (AES-128-CBC). Key stored in `/app/data/fernet.key`.
- **Sessions** — HTTP-only, Secure-flagged (when behind HTTPS), 30-day expiry.
- **CSP** — `script-src 'self'`, no inline JS, no `unsafe-eval`.
- **Rate limiting** — per-netid and per-IP to prevent abuse.
- **Input validation** — Net ID validated via regex, max lengths enforced.

## Scope

This is a student-built tool, not production infrastructure. Treat credentials stored here as you would any shared secret — don't reuse the same password for other services.
