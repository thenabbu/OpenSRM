# Contributing to OpenSRM

Thanks for considering a contribution.

## Guidelines

1. **Branch** — create a feature branch from `main` (`git checkout -b feature/your-thing`)
2. **Test** — verify changes work against the live SRM portal (use `scripts/srm_attendance.py` for standalone testing)
3. **Commit** — write clear, descriptive commit messages. One logical change per commit.
4. **PR** — open a PR against `main` with a description of what changed and why.

## Code Style

- Python: PEP 8 where reasonable, no linter enforced
- CSS: hand-written, IBM Carbon aesthetic, no preprocessor
- No new dependencies unless strictly necessary (check the ladder in skill)

## Architecture Constraints

- **gunicorn: exactly 1 worker** — the persistent browser singleton and ddddocr pre-warm are process-local. More workers = more Chromium instances = OOM.
- **No inline JS** — CSP blocks it (`script-src 'self'`). All event handlers go in `static/*.js` via `addEventListener`.
- **No new frameworks** — the frontend is vanilla JS + CSS. No React, no build step.
- **SQLite** — single-file database. No migrations framework; use idempotent `ALTER TABLE` with `try/except`.

## Testing Against the Portal

The app scrapes a live external portal. Rate limits apply:
- Per-netid: 3 scrapes per 10 minutes
- Per-IP: 10 login attempts per hour

Don't hammer the portal during testing. Use `scripts/srm_attendance.py` for quick standalone checks.

## Reporting Bugs

Use the GitHub issue templates. Include:
- What you expected to happen
- What actually happened
- Browser/device (if frontend issue)
- Steps to reproduce
